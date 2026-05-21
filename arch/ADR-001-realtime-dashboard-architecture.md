# ADR-001: Real-Time Dashboard Architecture

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** Backend + Frontend engineering
- **Supersedes:** —
- **Superseded by:** —

---

## 1. Context

We need a web dashboard whose data updates in near real-time as the underlying state changes in the system. The dashboard is backed by:

- A **FastAPI** service that owns all writes to the database.
- A **PostgreSQL** database as the system of record.
- A **React + TypeScript** single-page application as the client.

Expected concurrent usage at launch is small (single-digit to low-double-digit users), but the architecture must offer a *clear, low-friction path* to grow without rewrites. Operationally, the system runs locally via **Docker Compose** during development and on **AWS managed services** in production.

This ADR records the cross-cutting architectural decisions that govern *how the dashboard stays up to date* and *how state is shared across backend instances*. Implementation details that depend on product specifics are deliberately deferred.

## 2. Scope

**In scope**
- Transport choice for delivering updates from backend to browser.
- Cross-instance fanout mechanism on the backend.
- Session storage strategy.
- Local development topology and its production analogue.
- Key code patterns that downstream implementation must follow.

**Out of scope**
- Postgres schema, query design, migrations, or any data-modelling concern. Postgres appears in the architecture diagrams as a component, but its *usage* (what tables exist, what is read or written, when) is to be defined elsewhere.
- Business logic of the dashboard.
- URL/route structure for HTTP and SSE endpoints.
- Payload shapes published to or consumed from Redis, or sent over SSE.
- Authentication mechanism (the *storage* of session state is decided here; the *issuance* of sessions is not).
- IaC, CI/CD pipelines, observability stack.

These omissions are intentional. Downstream planning (e.g., by Claude Code) is expected to define them consistently with the patterns in §6.

## 3. Reference Architecture

Two diagrams are authoritative and referenced throughout this ADR:

- **Diagram A — Local (Docker Compose):** frontend container, Nginx reverse proxy, FastAPI service(s), Postgres container, Redis container, on a shared Docker network.
- **Diagram B — Production (AWS):** Route 53 + CloudFront (global) → S3 static site for the frontend; Route 53 → ALB → autoscaled FastAPI tasks on ECS Fargate (private subnets) → RDS Proxy → RDS Postgres and ElastiCache Redis (private data subnets), inside a VPC.

The diagrams define *what runs where*. This ADR defines *how the pieces talk to each other and why*.

## 4. Decisions

### D1. Push transport — Server-Sent Events (SSE)

The backend pushes updates to the browser over **SSE**, not WebSockets and not client polling.

### D2. Cross-worker fanout — Redis Pub/Sub

When a FastAPI worker performs a write, it **publishes a notification to Redis**. All FastAPI workers maintain a subscription and forward received messages to their locally-connected SSE clients.

### D3. Session storage — Redis

User session state (whatever the auth layer ends up storing per session) lives in **Redis**, keyed by session ID. Invalidation is performed by deleting the key.

### D4. Local mirrors production at the component level

The Docker Compose stack (Diagram A) uses the *same* component shapes as the AWS stack (Diagram B). Only endpoints change between environments; application code does not branch on environment.

### D5. Per-worker in-memory client registry

Each FastAPI worker process owns an in-process registry of its currently-connected SSE clients (as `asyncio.Queue` instances). The registry is **never shared across workers**; cross-worker delivery is exclusively via Redis Pub/Sub (D2).

### D6. At-most-once delivery is acceptable

Redis Pub/Sub is fire-and-forget. We accept that a client which is mid-reconnect at the moment of a publish may miss that message, and that the client is responsible for resynchronizing state on (re)connect by performing a regular HTTP fetch before resuming the stream.

## 5. Rationale (the WHYs)

### Why SSE over WebSockets

- **One-way is sufficient.** A dashboard is a server-push problem. The browser sends data through normal HTTP requests; the SSE channel is exclusively server → client. WebSockets' bidirectional capability would be unused complexity.
- **Built on plain HTTP.** SSE is a long-lived HTTP response with `Content-Type: text/event-stream`. It traverses every proxy, load balancer, and CORS configuration that already handles HTTP. WebSockets require a protocol upgrade that some intermediaries handle imperfectly.
- **Native browser reconnect.** `EventSource` automatically reconnects on disconnect and supports `Last-Event-ID` resume semantics. With WebSockets, reconnect, backoff, and jitter are the application's problem.
- **Standard auth.** SSE requests carry headers like any other HTTP request, so existing auth flows apply unchanged. WebSocket auth typically requires bespoke handshake handling.
- **Simpler server code.** A streaming HTTP response with an async generator is a smaller surface than a stateful WebSocket lifecycle.

The cost is that the client cannot push messages over the same channel — which is precisely what we don't need.

### Why SSE over polling

Polling would also work and was the leading candidate at small scale. SSE is chosen because:

- **Update latency is bounded by the publish, not the poll interval.** Sub-second freshness without paying a per-second request tax.
- **Idle is free.** No requests flow when nothing changes. Polling pays for silence; SSE does not.
- **Connection cost scales with active users, not with users × frequency.** This shifts the resource bottleneck from request throughput to concurrent connection count, which is easier to reason about and to provision.

### Why Redis Pub/Sub for fanout

The moment more than one FastAPI worker exists (and in production there are many), each worker only knows about its own SSE clients. Writes can arrive at any worker, but the user whose dashboard must update may be connected to a different worker entirely. A shared message bus is non-negotiable.

Redis Pub/Sub is chosen over alternatives because:

- **It is already in the stack** for session storage (D3); reusing it avoids a second piece of infrastructure.
- **Latency is sub-millisecond** in the same VPC/network.
- **Fire-and-forget semantics match the use case.** A missed message during a reconnect is recoverable via state resync (D6); we do not need durable queueing.
- **Operationally trivial.** ElastiCache Redis (Diagram B) provides multi-AZ replication and automatic failover; no broker to administer.

Alternatives considered and rejected:
- **Postgres `LISTEN`/`NOTIFY`** — couples fanout to the DB connection pool, consumes pooled connections, and ties real-time scaling to database scaling.
- **A managed broker (SNS, Kafka, NATS)** — overkill for in-process broadcast; introduces ops surface area we don't need.
- **In-process only (no broker)** — works for a single worker; breaks the moment we scale horizontally, which is the explicit growth path.

### Why Redis for sessions

- **Shared across workers by definition** — any worker can validate any session without sticky routing.
- **Fast.** Session lookups happen on essentially every authenticated request, including the initial SSE handshake; sub-millisecond lookups matter.
- **Trivially invalidatable.** `DEL session:<id>` is the entire logout/revoke story.
- **TTL is a first-class primitive** — sessions expire on their own without a sweeper job.
- **No second store needed.** Already provisioned for D2.

### Why per-worker in-memory client registry (and not a shared one)

- **Connections are inherently worker-local.** The TCP socket terminates on one specific process; another worker cannot write to it. Trying to make the registry "shared" would not actually let another worker send bytes to the client — it would only duplicate metadata.
- **The fanout layer already exists.** Redis Pub/Sub fans messages to all workers; each worker then iterates its local registry. This is the simplest design that works correctly.
- **Failure is contained.** A crashing worker drops only its own connections; surviving workers and their clients are unaffected. Clients auto-reconnect (via `EventSource`) and the load balancer routes them to a healthy worker.

### Why local mirrors production

Configuration differences (endpoints, credentials, TLS) are injected via environment variables; application code is identical across environments. This means "works on my machine" actually predicts production behaviour for the cases this ADR covers (fanout correctness, reconnect behaviour, session sharing). It also makes the production migration a configuration exercise, not a code change.

### Why at-most-once is acceptable

The dashboard's correctness model is *eventual consistency from a known-good baseline*. On connect, the client fetches current state via a normal HTTP request, then subscribes to the stream for deltas. If a message is lost, the next message (or the next reconnect-and-refetch cycle) will still bring the client to the correct state. Stronger delivery guarantees would force us to either persist messages (Redis Streams, a broker) or implement per-client acknowledgement, both of which are disproportionate to the requirement.

## 6. Implementation Patterns (the key HOWs)

The following snippets are **canonical patterns**, not complete implementations. They fix the *shape* of the solution. Names of routes, channel names, payload schemas, and auth specifics are intentionally placeholders; downstream planning will define them.

### 6.1 Per-worker client registry and Redis subscriber

Each worker, on startup, opens one Redis subscription and runs a single background task that forwards every received message to every locally-connected client.

```python
# app/realtime.py
import asyncio
from typing import Set
import redis.asyncio as redis

# Module-level, per-worker state. Not shared across processes.
_clients: Set[asyncio.Queue] = set()

def register() -> asyncio.Queue:
    # Bounded queue prevents a slow client from leaking memory.
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _clients.add(queue)
    return queue

def unregister(queue: asyncio.Queue) -> None:
    _clients.discard(queue)

async def run_subscriber(redis_url: str, channel: str) -> None:
    client = redis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = message["data"]
        for q in list(_clients):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop policy is a deliberate choice; see §7.
                pass
```

Wire it into the app lifecycle (channel name is a placeholder):

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .realtime import run_subscriber

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_subscriber(REDIS_URL, CHANNEL_NAME))
    try:
        yield
    finally:
        task.cancel()

app = FastAPI(lifespan=lifespan)
```

### 6.2 SSE endpoint

The endpoint path and any query/path parameters are out of scope. The pattern is:

```python
# app/routes_stream.py
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from .realtime import register, unregister

router = APIRouter()

@router.get("")  # path is a placeholder
async def stream(request: Request):
    queue = register()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive comment prevents intermediaries from closing the
                    # idle connection. Comment lines are ignored by EventSource.
                    yield ": keep-alive\n\n"
        finally:
            unregister(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### 6.3 Publishing from a write path

Any write handler publishes after a successful commit. The channel name and payload shape are out of scope; the *position* of the publish is not:

```python
# app/some_write_handler.py
# Pseudocode for the pattern; route, request model, and payload are placeholders.

async def handle_write(...):
    async with db.transaction():
        # ... perform writes ...
        pass  # commit happens on context exit

    # Publish only after the transaction has committed, so subscribers never
    # see a notification about state that was rolled back.
    await redis_client.publish(CHANNEL_NAME, serialized_payload)

    return response
```

### 6.4 Sessions in Redis

Storage, lookup, and invalidation use the standard Redis primitives. The session ID generation scheme and the contents of the session are out of scope.

```python
# app/sessions.py
import redis.asyncio as redis

SESSION_PREFIX = "session:"
SESSION_TTL_SECONDS = 60 * 60 * 8  # placeholder

async def put(client: redis.Redis, session_id: str, value: str) -> None:
    await client.set(f"{SESSION_PREFIX}{session_id}", value, ex=SESSION_TTL_SECONDS)

async def get(client: redis.Redis, session_id: str) -> str | None:
    return await client.get(f"{SESSION_PREFIX}{session_id}")

async def invalidate(client: redis.Redis, session_id: str) -> None:
    await client.delete(f"{SESSION_PREFIX}{session_id}")

async def touch(client: redis.Redis, session_id: str) -> None:
    # Sliding expiry: extend TTL on activity.
    await client.expire(f"{SESSION_PREFIX}{session_id}", SESSION_TTL_SECONDS)
```

### 6.5 React subscription

The client opens an `EventSource` and dispatches each message to wherever component state lives. State management library, payload parsing, and error UX are out of scope.

```tsx
// src/hooks/useEventStream.ts
import { useEffect } from "react";

type Handler = (raw: string) => void;

export function useEventStream(url: string, onMessage: Handler): void {
  useEffect(() => {
    const source = new EventSource(url, { withCredentials: true });

    source.onmessage = (event) => {
      onMessage(event.data);
    };

    source.onerror = () => {
      // EventSource reconnects automatically. We intentionally do not
      // close() here on transient errors. Application-level resync on
      // reconnect (re-fetching baseline state) is the responsibility
      // of the caller and is out of scope for this hook.
    };

    return () => {
      source.close();
    };
  }, [url, onMessage]);
}
```

Usage shape (illustrative — payload parsing and state shape are not decided here):

```tsx
// src/components/SomeView.tsx
import { useCallback } from "react";
import { useEventStream } from "../hooks/useEventStream";

export function SomeView({ streamUrl }: { streamUrl: string }) {
  const handle = useCallback((raw: string) => {
    // Parse and dispatch. Payload contract defined elsewhere.
  }, []);

  useEventStream(streamUrl, handle);

  return null; // render the view
}
```

## 7. Operational Constraints (binding on implementation)

These items are not full decisions but are tight enough to constrain downstream planning:

1. **Bounded queues.** Per-client queues must be bounded (see 6.1). The drop policy on overflow must be explicit; a slow client must never be allowed to grow memory without limit. The default is *drop the newest message and rely on resync*; alternatives must be justified.
2. **Keep-alives.** The SSE generator must emit a keep-alive comment at an interval shorter than the most aggressive idle timeout in the path (Nginx in local; ALB in production). 20 seconds is the starting value.
3. **Headers.** `Cache-Control: no-cache` and `X-Accel-Buffering: no` are required on the SSE response to prevent proxy buffering.
4. **Publish-after-commit.** Notifications must be published *after* the DB transaction has committed. Publishing inside the transaction risks broadcasting state that is subsequently rolled back.
5. **Resync on (re)connect.** Clients must fetch baseline state via a regular HTTP request before (or immediately after) subscribing, on every connect and every reconnect. This is the recovery mechanism for D6.
6. **Sticky sessions at the load balancer.** Diagram B requires ALB target-group stickiness enabled, because each SSE connection is bound to one specific task for its lifetime. Local Nginx must mirror this behaviour.
7. **Idle timeout.** ALB and Nginx idle timeouts must exceed the keep-alive interval with comfortable margin (≥ 2×).
8. **One subscriber task per worker.** Exactly one Redis subscription per worker process. Multiple subscriptions waste connections; zero subscriptions silently breaks fanout.
9. **No business logic in this layer.** The realtime module is a transport. It does not inspect payloads, filter, or authorize. Anything content-aware lives upstream of the publish or downstream of the SSE message handler.

## 8. Consequences

**Positive**
- Latency from write to UI is bounded by network + Redis, not by a poll interval.
- Backend scales horizontally without changing the realtime layer.
- Local and production share a single mental model; debugging at the laptop predicts production behaviour.
- Redis serves two needs (fanout + sessions) with one piece of infrastructure.

**Negative**
- Two long-lived connection paths now exist per user (the SPA's HTTP requests and its SSE stream). Connection-count capacity planning matters.
- At-most-once fanout requires correct client-side resync. A bug in resync manifests as silently stale data.
- Sticky sessions at the load balancer are required, which complicates rolling deploys (in-flight SSE connections drop when a task is replaced; clients reconnect, which is fine but visible).
- Redis is now load-bearing for both real-time and auth. Its availability SLO becomes the dashboard's availability SLO.

**Neutral**
- Future migration to WebSockets, if ever needed, replaces only §6.2 and §6.5; the Redis fanout layer (§6.1, §6.3) is unchanged. The transport is genuinely swappable.

## 9. Alternatives Considered

| Option | Why rejected |
|---|---|
| HTTP polling | Higher latency floor; pays a per-interval request cost forever; bursty updates handled poorly. Acceptable at very small scale but does not meet the "clear path to grow" requirement without later rework. |
| WebSockets | Bidirectionality unused; reconnect, auth, and proxy interactions are all more complex than SSE for no benefit here. Reconsider only if the client gains a need to *send* over the channel. |
| Postgres `LISTEN`/`NOTIFY` | Couples real-time fanout to DB connection budget; scaling realtime forces scaling DB connections; complicates the move to RDS Proxy (which does not support `LISTEN`/`NOTIFY` in transaction pooling mode). |
| Managed broker (SNS / Kafka / NATS) | Solves a problem we do not have (durability, ordering, multi-consumer-group semantics). Adds an additional service to operate. |
| In-memory fanout only (no Redis) | Works for a single worker. Silently breaks the moment a second worker exists. |
| Cookies / JWT-only sessions (no server store) | Cannot be invalidated server-side without additional machinery. Forces compromises on revocation latency that we do not need to make. |

## 10. Open Items for Downstream Planning

Items deliberately left for the implementation plan:

- Concrete URL/route definitions for HTTP and SSE endpoints.
- Channel naming scheme (single global channel vs. per-resource vs. per-user; pattern subscriptions).
- Payload schema and versioning strategy for messages published to Redis and forwarded over SSE.
- Authentication mechanism and how it populates the Redis-stored session.
- Authorization model: which clients are entitled to which messages, and whether filtering happens at publish, at subscribe, or in the SSE generator.
- Resync endpoint(s) and the contract between resync and stream.
- Postgres schema, query patterns, and write paths.
- Observability: metrics on connected clients, queue depth, publish rate, drop rate.
- Deployment, IaC, CI/CD.

These should be elaborated consistently with §4–§7. Anything that contradicts the operational constraints in §7 requires a follow-up ADR.
