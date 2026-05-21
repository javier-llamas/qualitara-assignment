# AI Interaction Log — Real-Time Dashboard Architecture Discussion

**Date:** 2026-05-21
**Participants:** User (engineer), Claude (assistant)
**Topic:** Architecting a real-time dashboard backed by FastAPI, Postgres, and React; producing a deployable local topology, an AWS production topology, and an ADR to feed downstream implementation planning.

---

## 1. Key Prompts (in order)

| # | Prompt (paraphrased) | Intent |
|---|---|---|
| P1 | What other information should we know to decide between polling and websockets for a React dashboard backed by FastAPI + Postgres? How hard is it to implement? Performance considerations? | Frame the decision space before choosing. |
| P2 | Assume 10 users and a single FastAPI writer. The plan should also include a clear path for when scale grows. Considering Lambda + SNS + Cognito for that path — what am I missing? | Get a reality-check on a proposed serverless scaling plan. |
| P3 | Who is the connection pooler — FastAPI or Redis? | Clarify a confusing piece of the previous answer. |
| P4 | If I have dozens of FastAPI instances, is the `DATABASE_URL` pointing at PgBouncer or at RDS? | Nail down the concrete wiring. |
| P5 | Can AWS handle that for me as a managed service? | Confirm the managed-service path. |
| P6 | Walk me through how a state update from a FastAPI writer reaches the browser via Redis Pub/Sub. | Get an end-to-end trace of the realtime path. |
| P7 | If this is real-time via SSE with fresh notifications, why do I want caching? | Push back on a default recommendation that didn't fit. |
| P8 | Give me an architecture diagram of a Docker Compose stack (backend, Nginx, Postgres, Redis), and a second diagram replacing those with ALB, Route 53, RDS Proxy, ElastiCache, RDS, and a memory-based autoscaling policy. | Convert the discussion into concrete diagrams. |
| P9 | We forgot the React frontend in both diagrams. Add it: compiled in Docker Compose locally, served from S3 in AWS, with its own Route 53 subdomain. | Fix a scope omission. |
| P10 | Two issues in the production diagram: Route 53 and CloudFront belong in the account but outside the region; and the arrows from FastAPI to ElastiCache Redis didn't reach the block. | Correct factual and visual errors. |
| P11 | Produce an ADR to serve as input for downstream planning by Claude Code. Include key code snippets (SSE endpoint, queue, sub, publish, Redis sessions, React subscription). Make no assumptions on business logic, URLs, or payloads. Be explicit that Postgres is in the architecture but its usage is out of scope. Key HOWs, more detail on WHYs. Assume diagrams will be provided. | Convert the entire discussion into a structured, handoff-ready document. |
| P12 | Create an AI interaction log: key prompts, response summaries, corrections and redirections. | (This document.) |

---

## 2. Response Summaries

### R1 — Framing polling vs. websockets (response to P1)
Identified the decisive questions before recommending anything: *who writes to the DB*, *required freshness*, *concurrent user count*, *update pattern* (steady vs. bursty), *infrastructure constraints*, *auth model*, *one-way vs. bidirectional*. Introduced Server-Sent Events as an often-overlooked third option suited to dashboards. Sketched implementation difficulty (polling = trivial with React Query; websockets = days of work plus cross-worker fanout via Redis; SSE = in between). Covered performance considerations on both sides (polling load scales as users × frequency; websockets shift cost to memory and connection limits). Default recommendation: start with polling unless hard real-time is required.

### R2 — Scaling plan reality-check (response to P2)
Pushed back on the premise that "10 users" needs serverless planning at all — polling scales much further than expected. Identified concrete problems with the proposed serverless sketch: FastAPI on Lambda via Mangum is an awkward fit; "unlimited Lambda concurrency" against Postgres exhausts connection limits without RDS Proxy; SNS doesn't push to browsers directly (would need API Gateway WebSockets or IoT Core); Cognito is one option among many. Flagged additional missing concerns: cost model flip at sustained load, cold starts, local dev story, observability, database as ongoing bottleneck, vendor lock-in. Proposed a more pragmatic migration path: container → autoscaled container service + connection pooler → Redis pub/sub + SSE if real-time needed → serverless only for specific high-volume endpoints if ever.

### R3 — Connection pooler clarification (response to P3)
Clarified that the pooler is *neither* FastAPI nor Redis — it's a separate piece of infrastructure (PgBouncer or RDS Proxy) sitting between FastAPI and Postgres. Distinguished two levels of pooling that are easy to conflate: app-level pool inside FastAPI (free, automatic) and infrastructure-level pool outside the app (added when scaling horizontally). Explained Redis's actual roles in the architecture (caching, pub/sub) — unrelated to DB connections.

### R4 — Wiring of `DATABASE_URL` (response to P4)
Confirmed that all FastAPI instances point `DATABASE_URL` at the pooler, not Postgres directly. Showed the connection-string shape and standard ports (PgBouncer on 6432, Postgres on 5432, RDS Proxy on 5432 with its own endpoint hostname). Explained that the pooler is wire-compatible with Postgres so app code is unchanged. Flagged operational gotchas: pool mode (transaction mode is the win but breaks session-level state), app-level pool sizing (keep it small), and single-point-of-failure considerations.

### R5 — Managed pooler on AWS (response to P5)
Confirmed RDS Proxy is exactly the managed pooling service. Listed what it provides out of the box (pooling, multi-AZ HA, faster failover, IAM auth, Secrets Manager integration, CloudWatch metrics). Gave honest tradeoffs vs. self-hosted PgBouncer (cost per vCPU, fewer configuration knobs, session-pinning behaviour, small latency overhead). Updated the recommended migration path: single container today → RDS Proxy + multiple containers when scaling → Redis pub/sub + SSE for realtime later.

### R6 — End-to-end Redis Pub/Sub trace (response to P6)
Walked through the full path for one update: setup phase (each worker spawns a Redis subscriber task on boot and keeps a per-worker registry of connected SSE clients as `asyncio.Queue` instances); browser connect (load balancer routes to one specific worker, which creates a queue and returns a streaming response); write event (a different worker handles the POST, commits to Postgres, then publishes to Redis); fanout (Redis pushes to every subscribed worker; each iterates its local registry); browser receive (the SSE generator yields the data chunk). Highlighted key properties: DB isn't touched during fanout, pub/sub is fire-and-forget, channel design tradeoffs, slow-client failure modes, automatic `EventSource` reconnect. Noted that the same architecture works for websockets with only the transport layer changed.

### R7 — Cache pushback acknowledged (response to P7)
Conceded the point. In a pure SSE + pub/sub world, browsers don't poll, so reads collapse to initial page load and reconnects — well within Postgres's capacity. Cache layer was a reflexive suggestion that didn't fit the architecture we ended up with. Identified the narrow cases where caching legitimately earns its place (expensive aggregations on initial load, fan-in reads on shared data, ephemeral key-value lookups like rate limiting and session validation, or just adding a read replica instead). Updated the stack: Redis stays for pub/sub fanout only; cache is added per-query if and when a specific hot read justifies it.

### R8 — Two architecture diagrams (response to P8)
Produced Diagram A (Docker Compose: browser → Nginx → FastAPI instances → Postgres + Redis on a shared Docker network) and Diagram B (AWS: Route 53 → ALB in public subnets → FastAPI tasks on Fargate in private app subnets → RDS Proxy → RDS Postgres and ElastiCache Redis in private data subnets, with a memory-based target-tracking autoscaling policy). Explained the migration mechanics: only environment variables change between local and prod. Covered Nginx → ALB nuances (sticky sessions and idle timeout for SSE), ECS Fargate as the boring-correct compute choice, VPC tier discipline, and ElastiCache Valkey as an option. Honest "is this overkill?" check: yes for 10 users, but the shape is right and stretches without breaking.

### R9 — Frontend added (response to P9)
Updated both diagrams. Local: a frontend container with two reasonable modes (Vite dev server with hot reload, or multi-stage build into `nginx:alpine` for prod-mirror). Production: split subdomains — `app.example.com` → CloudFront → S3 for the static SPA; `api.example.com` → ALB → FastAPI for the API. Explained why two subdomains beats one (independent deploys, different caching policies, different scaling characteristics), the CORS tradeoff that comes with the split, ACM certificate management, why CloudFront + S3 beats S3 alone, and what the CI deploy looks like (`npm run build`, `aws s3 sync`, `cloudfront create-invalidation`). Closed on the asymmetry: dynamic backend, static frontend, zero runtime to babysit on the frontend.

### R10 — Production diagram corrected (response to P10)
Acknowledged both errors and produced a v2 diagram. Route 53 and CloudFront moved into the account boundary but above the region boundary, reflecting their status as AWS global services. Added a small but useful aside on ACM certificate region requirements (CloudFront requires `us-east-1`; ALB requires the same region as the ALB). Repositioned the FastAPI → ElastiCache Redis arrows so they actually land on the box.

### R11 — ADR produced (response to P11)
Wrote `ADR-001-realtime-dashboard-architecture.md`. Structured as one ADR covering coupled decisions (transport, fanout, sessions, topology) rather than splitting into four cross-referencing documents. Explicit scope section listing what is in scope and what isn't (Postgres usage, business logic, URLs, payloads, auth issuance). Six numbered decisions with detailed rationale (WHYs given more space than HOWs, per request). Code snippets are framework-vanilla and use placeholder names — no SQLAlchemy, Pydantic, auth library, or React state library committed. Operational Constraints section (§7) captures the things that aren't full decisions but that an implementation could subtly get wrong (bounded queues, keep-alives, publish-after-commit, sticky sessions). Open Items section (§10) enumerates what downstream planning still has to decide. Flagged that D6 (at-most-once delivery) is the decision most likely to need revisiting if safety-critical use cases ever appear.

### R12 — This log (response to P12)
The current document.

---

## 3. Corrections and Redirections Issued by the User

These are the moments where the user pushed back, narrowed scope, or fixed errors. They materially shaped the final outputs.

| # | Correction / Redirection | Effect on the conversation |
|---|---|---|
| C1 | **Constrained the scaling assumption.** "Let's say I assume 10 expected users with a single FastAPI writer" (P2). | Cut off premature serverless architecture talk; forced the conversation onto the right scale and surfaced that polling is more than adequate today. |
| C2 | **Demanded a concrete scaling path** rather than abstract advice (P2: "a clear path for when scale grew significantly"). | Produced a staged migration plan (container → managed pooler → realtime layer → selective serverless) instead of a vague "scale later" hand-wave. |
| C3 | **Asked who the connection pooler actually is** (P3). | Exposed that the prior explanation was muddled; forced a clean explanation distinguishing app-level from infrastructure-level pooling and Redis's actual role. |
| C4 | **Made an explicit scope decision: skip PgBouncer locally** ("if we ever need a connection pooler we can just get it from AWS as a managed service", P8). | Kept the local Compose stack minimal; deferred a complication to the moment it's actually needed. |
| C5 | **Rejected caching as a default** (P7: "why do I want to cache if I'm using SSE with fresh notifications?"). | Caused a concession and the removal of a Redis-cache box that was being drawn out of habit. Updated the stated role of Redis in the architecture to pub/sub + sessions only. |
| C6 | **Caught the missing frontend** in both diagrams (P9). | Required updates to both diagrams and prompted the split-subdomain architecture for production, plus the dual-mode frontend container for local. |
| C7 | **Flagged that Route 53 and CloudFront were drawn inside the region** (P10, issue 1). | Corrected an AWS-topology accuracy issue. Route 53 and CloudFront are global services; the diagram was rebuilt with them at the account level, above the region. |
| C8 | **Flagged that the arrows to ElastiCache Redis didn't visually reach the block** (P10, issue 2). | Caused a layout fix so the diagram actually communicated what it claimed to. |
| C9 | **Set explicit scope boundaries for the ADR** (P11: no assumptions on business logic, URLs, or payloads; Postgres in the architecture but its usage out of scope; key HOWs only, more detail on WHYs). | Shaped the ADR's structure: explicit Scope section, framework-vanilla code snippets with placeholder names, WHY sections given more room than HOW sections, an Open Items section enumerating what was deliberately deferred. |
| C10 | **Specified that diagrams would be referenced, not recreated** (P11). | Kept the ADR text-focused and avoided duplicating effort; the ADR points at the existing diagrams as authoritative for the topology. |

---

## 4. Patterns Worth Noting

A few meta-observations about how the conversation went, since they may be useful for similar future work:

- **The most productive prompts were the corrective ones.** P3, P7, and P10 in particular each made the next answer materially better. Defaulting to "let me push back on that" produced cleaner architecture than accepting the first answer.
- **Scope-narrowing prompts outperformed scope-expanding ones.** P2's "assume 10 users" and P11's explicit out-of-scope list both forced sharper outputs than open-ended framing would have.
- **Diagram errors surfaced quickly because the diagrams were specific.** Generic boxes-and-arrows would have hidden the Route 53/CloudFront placement issue; the labelled region boundary made it visible immediately.
- **The ADR's value is largely in §7 (Operational Constraints) and §10 (Open Items)** — the parts that constrain downstream work without over-deciding it. These sections only exist because the conversation produced enough tacit knowledge to fill them.
