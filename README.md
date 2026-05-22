# Fleet Telemetry Monitoring Service

Vertical-slice implementation of the assignment in `ai-log/db-design-main-prompt.md`. Start with the one-page summary ADR — [`ADR.md`](ADR.md) — which answers the four required ADR questions and embeds both architecture diagrams. The full reasoning is split across two detailed records: [ADR-001-realtime-dashboard-architecture.md](arch/ADR-001-realtime-dashboard-architecture.md) and [`ADR-002-database-and-concurrency.md`](arch/ADR-002-database-and-concurrency.md). Implementation plan in [fleet-telemetry-implementation-plan.md](.claude/plans/fleet-telemetry-implementation-plan.md).

## Quick start

Prerequisites: Docker + Docker Compose, plus `make`. Local dev outside of docker also needs `uv` (Python) and Node 24+.

```bash
make up         # build + start postgres, redis, 3× api replicas, nginx, vite dev
make migrate    # alembic upgrade head against the running pg
make simulate   # 50 vehicles posting at 1 Hz; runs from the host
open http://localhost:8080
```

Stop with `make down`.

## What's where

- `backend/app/` — FastAPI service
  - `models.py` — SQLAlchemy models (verbatim from ADR-002 with `values_callable` for PgEnum)
  - `services/telemetry.py` — ingest transaction (insert + detect + fault-transition + post-commit publish)
  - `services/faults.py` — `SELECT FOR UPDATE` + savepoint + `IntegrityError` swallow
  - `services/fleet.py`, `services/zones.py` — derived read queries
  - `realtime.py` — per-worker SSE client registry + Redis subscriber (ADR-001 §6.1)
  - `pubsub.py` — post-commit publish helper
  - `routes/stream.py` — SSE generator with 20s keep-alive (ADR-001 §6.2)
- `backend/alembic/versions/0001_initial.py` — schema + the two load-bearing partial unique indexes
- `backend/tests/` — pytest with `testcontainers` for integration tests
- `frontend/src/` — React + TS + Tailwind dashboard
  - `hooks/useEventStream.ts` — `EventSource` hook (ADR-001 §6.5)
  - `hooks/useFleetState.ts` — REST resync + SSE delta application
  - `components/` — VehicleList, ZoneCounts, FleetAggregate, FaultInjector
- `nginx/nginx.conf` — proxy with SSE-safe headers; re-resolves `api` via Docker DNS to round-robin replicas
- `docker-compose.yml` — five services on `fleet-net`

## Tests

```bash
make test           # backend (pytest + testcontainers) + frontend (jest + RTL)
make test-backend   # just python; spins up ephemeral pg/redis containers per session
make test-frontend  # just jest
```

Concurrency-critical paths have integration tests that actually exercise concurrency:

- `tests/integration/test_telemetry_ingest.py::test_concurrent_ingest_200_events` — 200 events for 20 vehicles via `asyncio.gather`; asserts row count + FK integrity.
- `tests/integration/test_telemetry_ingest.py::test_zone_counts_under_concurrent_writes` — 50 concurrent `zone_entered` events for the same zone; asserts every count was captured.
- `tests/integration/test_fault_transition.py::test_concurrent_faults_same_vehicle_idempotent` — 20 concurrent faults for one vehicle; asserts exactly one mission canceled + exactly one maintenance report (the partial unique index does the work).
- `tests/integration/test_pubsub_fanout.py` — proves a worker's subscriber forwards Redis messages to local clients.

## Lint / typecheck

```bash
make check    # ruff + mypy — wired into the Claude Code Stop hook
make lint     # also runs frontend ESLint
make type     # also runs `tsc --noEmit`
```

## How the design holds together

- **Telemetry is the source of truth.** No `vehicles` table; per-vehicle state is `ORDER BY timestamp DESC LIMIT 1` on `telemetry_events` (ADR-002 D2).
- **Zone counts are derived**, not maintained. `GROUP BY zone_entered`; zero-fill from the `ZONES` constant (D3).
- **Fault transitions** use one transaction at `READ COMMITTED` + `SELECT FOR UPDATE` + a SAVEPOINT around the maintenance insert, so a concurrent fault hits the partial unique index and is swallowed as a no-op (D4).
- **Anomalies are synchronous on ingest**, in the same transaction, with a `NOT NULL` FK back to the telemetry row (D5).
- **Updates are pushed via SSE**, fanned across worker processes by Redis Pub/Sub. Each worker keeps an in-process bounded-queue client registry; messages are published only *after* the DB transaction commits (ADR-001 D1/D2/D5, §7.4).
- **Clients resync on (re)connect** by fetching `/vehicles`, `/zones/counts`, `/fleet/state` before subscribing. At-most-once delivery is accepted (ADR-001 D6).

## Deliberately left out

Matches the "Deliberately Left Out" section of ADR-002 plus a few additions for budget:

- Auth / login UI. A stub `dev-session` cookie is set; routes are not gated. Session helpers exist in `app/sessions.py` per ADR-001 §6.4.
- Telemetry partitioning, retention, dead-letter queue.
- Timer-based anomalies (`STALE_TELEMETRY`).
- AWS deployment / Terraform / CDK. The production diagram in `arch/aws_production_architecture_with_frontend_v2.svg` is documentation only.
- Per-vehicle drill-down view.

See ADR-002 § "What Changes at Significant Scale" for the layered scale-up plan.
