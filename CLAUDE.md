# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is currently **documentation-only**. There is no application code, no `package.json`, no `pyproject.toml`, no `docker-compose.yml`, and no test suite. The deliverable is a fleet telemetry monitoring service (the assignment in `ai-log/db-design-main-prompt.md`); the architectural decisions are locked in via the ADRs in `arch/`, but the implementation has not been started.

When asked to "build the thing," start by scaffolding from the ADRs — do not invent an architecture.

## What's in the repo

- `arch/ADR-001-realtime-dashboard-architecture.md` — push transport (SSE), cross-worker fanout (Redis Pub/Sub), session storage (Redis), and the local-mirrors-prod stance. Contains canonical code snippets (§6) that the implementation must replicate in shape.
- `arch/ADR-002-database-and-concurrency.md` — Postgres choice, schema (DDL + SQLAlchemy models), and the fault-transition concurrency strategy. The recommended DDL and the two partial unique indexes are **load-bearing**, not suggestions.
- `arch/aws_production_architecture_with_frontend_v2.svg`, `arch/docker_compose_local_architecture_with_frontend.svg` — authoritative component diagrams (Diagram A = local, Diagram B = AWS).
- `ai-log/` — original assignment prompt (`db-design-main-prompt.md`) and the AI interaction log deliverables. The prompt defines the functional requirements (50 vehicles, 1 Hz telemetry, fault → cancel-mission + create-maintenance, zone counts, etc.) and the hardcoded `ZONES` list.

## Non-negotiable constraints (do not re-litigate without a new ADR)

These come from the ADRs and would break the design if violated:

1. **SSE, not WebSockets, not polling** for server→client updates (ADR-001 D1).
2. **Redis Pub/Sub for cross-worker fanout.** Each FastAPI worker keeps a per-process in-memory `Set[asyncio.Queue]` of SSE clients and runs **exactly one** subscriber task (ADR-001 D2, D5, §7.8). Do not share the client registry across workers; do not use Postgres `LISTEN/NOTIFY`.
3. **Publish to Redis *after* DB transaction commit** (ADR-001 §7.4 / ADR-002 by implication). Publishing inside the transaction can broadcast rolled-back state.
4. **Bounded per-client queues** with an explicit drop policy; default is drop-newest and rely on client resync (ADR-001 §7.1).
5. **SSE response headers**: `Cache-Control: no-cache` and `X-Accel-Buffering: no`; keep-alive comments every ~20 s; ALB/Nginx idle timeout ≥ 2× the keep-alive interval; sticky sessions at the LB (ADR-001 §7.2, §7.3, §7.6, §7.7).
6. **Telemetry is the single source of truth.** Do **not** create a `vehicles` table with denormalized `current_status`/`current_battery_pct`/`last_seen_at`. Derive per-vehicle state from `telemetry_events` via `ORDER BY timestamp DESC LIMIT 1` (ADR-002 D2). Same applies to zone counts: no `zone_counters` table — `GROUP BY zone_entered` against the event log (ADR-002 D3).
7. **Fault transition** runs in one transaction at `READ COMMITTED`, uses `SELECT ... FOR UPDATE` on the active mission row, and relies on two partial unique indexes (`missions_one_active_per_vehicle_idx`, `maintenance_one_open_per_vehicle_idx`) as the real correctness guarantee. The `IntegrityError` on concurrent fault is swallowed as a no-op (ADR-002 D4).
8. **Anomaly detection runs synchronously in the telemetry ingest transaction** with a `NOT NULL` FK from `incidents` to `telemetry_events` (ADR-002 D5). Don't move it to a worker/queue.
9. **Enum types are owned by Alembic migrations**, not per-table `CREATE TYPE`. SQLAlchemy models must declare `PgEnum(..., create_type=False)` (ADR-002 §Notes).
10. **Sessions live in Redis**, keyed by session ID, with TTL; invalidation = `DEL session:<id>` (ADR-001 D3).
11. **Local mirrors production at the component level.** Same component shapes in Docker Compose and AWS; only endpoints differ via env vars. No environment branching in application code (ADR-001 D4).

When a question arises that the ADRs left open (URL paths, channel naming, payload schemas, auth mechanism — see ADR-001 §10), make a choice consistent with §4–§7 of ADR-001 and §Decisions of ADR-002. If a choice would contradict an operational constraint, it requires a follow-up ADR rather than a silent deviation.

## Functional spec quick-reference

From `ai-log/db-design-main-prompt.md`:

- 50 vehicles, telemetry at 1 Hz, ~50 writes/sec sustained with bursts.
- Required endpoints: `POST /telemetry`, `GET /zones/counts`, fleet-state aggregate (per-status counts across all vehicles), recent-anomalies query filtered by vehicle and time range, and a vehicle status-update path that handles the fault transition.
- 20 hardcoded zones — keep them as a Python constant; do not seed a table.
- Incident types implemented per ADR-002 D5: `OVER_SPEED_LIMIT`, `LOW_BATTERY`, `MOVEMENT_UNDER_FAULT`, `ERROR_CODE_PRESENT`, `RAPID_BATTERY_DRAIN`. Timer-based incidents (e.g. `STALE_TELEMETRY`) are deliberately out of scope.

## Deliverables expected by the assignment

1. Python backend (FastAPI per ADR-001).
2. React + TypeScript dashboard (live vehicle list, latest anomaly per vehicle, live zone counts).
3. The two ADRs in `arch/` — already written; update or supersede rather than rewriting.
4. The AI interaction log in `ai-log/` — append meaningful prompts and a short reflection rather than fabricating history.

Budget for the assignment is 5–6 hours total; partial-but-documented beats complete-but-undocumented.

## When you start writing code

There is no existing convention to follow yet, so the first scaffold sets it. Suggested starting layout (derived from ADR-001 §6 module names):

- `backend/app/main.py` (FastAPI app + lifespan that starts the Redis subscriber)
- `backend/app/realtime.py` (per-worker registry + `run_subscriber`)
- `backend/app/routes_stream.py` (SSE endpoint)
- `backend/app/sessions.py` (Redis-backed sessions)
- `backend/app/models.py` (SQLAlchemy models from ADR-002)
- `backend/alembic/` (migrations — own the enum types here)
- `frontend/src/hooks/useEventStream.ts` (the `EventSource` hook from ADR-001 §6.5)
- `docker-compose.yml` at the repo root (frontend, nginx, fastapi, postgres, redis on a shared network — Diagram A)

Once scaffolded, replace this section with the real "how to run, how to test, how to add a migration" commands.
