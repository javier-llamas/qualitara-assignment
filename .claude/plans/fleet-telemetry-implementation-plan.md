# Fleet Telemetry Monitoring Service — Implementation Plan

## Context

The repo is currently documentation-only: two locked ADRs (`arch/ADR-001`, `arch/ADR-002`), authoritative SVG diagrams for the local and AWS topologies, the original assignment prompt, and a `CLAUDE.md` enumerating 11 non-negotiable constraints. No code, no `package.json`, no `pyproject.toml`, no compose file.

The goal of this work is to **scaffold the system the ADRs already designed** — a FastAPI + Postgres + Redis backend with a React/TS dashboard, demonstrating safe concurrent telemetry ingest, a transactional fault transition, derived zone counts, derived fleet aggregates, and live SSE-pushed updates — and to do so test-first using the practicing-tdd skill for the concurrency-critical paths.

Budget: 5–6 hours. Partial-but-tested beats complete-but-undocumented. The deliverables explicitly include the AI interaction log and the ADRs (already written), so implementation effort should be biased toward correctness of the load-bearing paths (telemetry ingest, fault transition, zone counters, SSE fanout) and high test coverage on those paths.

### User-confirmed choices

| Question | Decision |
|---|---|
| Auth | **Skip.** Stub a static dev session cookie; wire Redis session module per ADR-001 §6.4 but don't gate routes. |
| Vehicle simulator | **Makefile target** (`make simulate`), not a compose service. Standalone script POSTs telemetry for 50 fake vehicles at 1 Hz. |
| Concurrency tests | **testcontainers-python.** Each integration test spins up an ephemeral Postgres + Redis container. No mocked DB. |
| Frontend scope | **3 widgets + fault-injection panel.** Vehicle list, zone counts, fleet aggregate, plus a small panel to POST a fault status to a chosen vehicle for live demo. |

---

## Tech stack

**Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async), asyncpg, Alembic, redis-py asyncio, Pydantic v2, uv, pytest, pytest-asyncio, testcontainers, mypy, ruff (with black profile + isort).

**Frontend:** React 18, TypeScript, Vite, Tailwind (light) for styling, Jest + React Testing Library, ESLint (Airbnb base) + Prettier. Native `EventSource` for SSE.

**Infra:** Docker Compose with bind mounts for live reload — services: `frontend` (Vite dev), `nginx` (reverse proxy + LB), `api` (FastAPI under Uvicorn ×N replicas), `postgres`, `redis`. All on a shared bridge network — endpoint shapes match the AWS diagram (ADR-001 D4).

---

## Repo layout

```
qualitara-assignment/
├── backend/
│   ├── pyproject.toml             # uv-managed
│   ├── app/
│   │   ├── main.py                # FastAPI app, lifespan starts Redis subscriber
│   │   ├── config.py              # pydantic-settings (env vars)
│   │   ├── db.py                  # async engine, session factory
│   │   ├── realtime.py            # per-worker client registry + run_subscriber (ADR-001 §6.1)
│   │   ├── pubsub.py              # publish helper (post-commit)
│   │   ├── sessions.py            # Redis session helpers (ADR-001 §6.4)
│   │   ├── zones.py               # ZONES constant
│   │   ├── models.py              # SQLAlchemy models per ADR-002
│   │   ├── schemas.py             # Pydantic request/response models
│   │   ├── anomalies.py           # 5 detectors (ADR-002 D5)
│   │   ├── services/
│   │   │   ├── telemetry.py       # ingest transaction: insert + detect + maybe-fault-transition
│   │   │   ├── faults.py          # transactional fault transition (ADR-002 D4)
│   │   │   ├── fleet.py           # aggregate queries (latest-per-vehicle, status counts)
│   │   │   └── zones.py           # GROUP BY zone_entered query
│   │   ├── routes/
│   │   │   ├── telemetry.py       # POST /telemetry
│   │   │   ├── vehicles.py        # GET /vehicles, PATCH /vehicles/{id}/status
│   │   │   ├── anomalies.py       # GET /anomalies
│   │   │   ├── zones.py           # GET /zones/counts
│   │   │   ├── fleet.py           # GET /fleet/state
│   │   │   └── stream.py          # GET /stream (SSE, ADR-001 §6.2)
│   ├── alembic/                   # owns enum types (create_type=False in models)
│   ├── tests/
│   │   ├── conftest.py            # testcontainers fixtures (pg, redis), session factory, alembic upgrade
│   │   ├── unit/                  # anomaly detectors, schema validation
│   │   └── integration/           # ingest, fault transition concurrency, zone count concurrency, SSE fanout
│   └── scripts/simulate.py        # 50-vehicle simulator (asyncio + httpx)
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/client.ts          # fetch wrapper
│   │   ├── hooks/
│   │   │   ├── useEventStream.ts  # EventSource hook (ADR-001 §6.5)
│   │   │   └── useFleetState.ts   # resync + apply SSE events
│   │   ├── components/
│   │   │   ├── VehicleList.tsx
│   │   │   ├── ZoneCounts.tsx
│   │   │   ├── FleetAggregate.tsx
│   │   │   └── FaultInjector.tsx
│   │   └── types.ts               # shared TS types matching backend schemas
│   └── tests/                     # Jest + RTL
├── nginx/nginx.conf               # reverse proxy; SSE-safe (proxy_buffering off)
├── docker-compose.yml             # frontend, nginx, api (×3), postgres, redis
├── Makefile                       # setup, fmt, lint, type, test, up, down, simulate, migrate
├── .env.example
└── README.md
```

---

## Backend — TDD-first implementation order

Each step is **write failing tests → minimal implementation → refactor**, invoked via the `practicing-tdd` skill. Order is chosen so dependencies flow downward.

### Step 1 — Project scaffolding (no tests)
- `uv init backend`, add deps, `pyproject.toml` with `[tool.ruff]` (black profile, isort, line-length 100) and `[tool.mypy]` (strict-ish: `disallow_untyped_defs = true`).
- Alembic init + base revision creating the four enum types **and** the four tables with all DDL from ADR-002 verbatim, including the two partial unique indexes (`missions_one_active_per_vehicle_idx`, `maintenance_one_open_per_vehicle_idx`) and the partial `telemetry_zone_idx`.
- `models.py` mirrors the ADR-002 §SQLAlchemy section literally, with `PgEnum(..., create_type=False)`.
- `conftest.py` brings up Postgres + Redis via testcontainers once per session, runs `alembic upgrade head` against the container, hands out scoped `AsyncSession` to tests, truncates between tests.

### Step 2 — Anomaly detectors (pure unit tests)
- `anomalies.py` exposes `detect(event, prev_event_or_none) -> list[IncidentDraft]`.
- Implements the five rules from ADR-002 D5: `OVER_SPEED_LIMIT` (>5 m/s default), `LOW_BATTERY` (<15%), `MOVEMENT_UNDER_FAULT` (`status==fault and speed_mps>0`), `ERROR_CODE_PRESENT` (`len(error_codes)>0`), `RAPID_BATTERY_DRAIN` (drop >10% vs. previous event for that vehicle).
- Thresholds are module constants, documented in code with a one-line comment justifying the choice.
- Tests parameterize each rule's boundary; no DB needed.

### Step 3 — Telemetry ingest (integration tests, concurrency-critical)
- `services/telemetry.py::ingest(event)` runs **one transaction** at default isolation that:
  1. Inserts the `TelemetryEvent` row, flushes to get `id`.
  2. Loads the previous event for `vehicle_id` (`ORDER BY timestamp DESC LIMIT 1, exclude current`).
  3. Calls `anomalies.detect(...)` and inserts incident rows with the NOT NULL FK to `telemetry_events.id`.
  4. Commits.
- **After commit**, publishes a `telemetry` event to the Redis channel via `pubsub.publish()` — never inside the transaction (ADR-001 §7.4).
- POST `/telemetry` accepts a single event (and optionally a batch).
- **Concurrency tests (TDD focus):**
  - 200 events for 20 vehicles fired via `asyncio.gather` → assert all rows present, every incident points at an existing telemetry id, no exceptions.
  - 50 simultaneous `zone_entered` events for the same zone → assert `GET /zones/counts` returns the right number (the partial index makes this trivial since we're just inserting; no contention).

### Step 4 — Fault transition (integration tests, hardest concurrency case)
- `services/faults.py::transition_to_fault(vehicle_id)` opens a transaction at `READ COMMITTED`, does `SELECT ... FOR UPDATE` on the active mission row, sets it to `CANCELED`, inserts a `MaintenanceReport(status=QUEUED, cancelled_mission_id=…)`, commits. Wraps the insert in try/except `IntegrityError` and swallows it (idempotent under concurrent faults — ADR-002 D4).
- Called from two places: (a) PATCH `/vehicles/{id}/status` to `fault`, (b) inside `services/telemetry.py` when an incoming telemetry event has `status == fault` and the previous event did not.
- **Concurrency tests:**
  - Pre-seed one active mission. Fire 20 concurrent fault transitions via `asyncio.gather`. Assert: exactly one mission canceled, exactly one maintenance report created, zero exceptions surfaced to caller.
  - Fire fault transitions for 50 different vehicles concurrently. Assert: all 50 missions canceled, 50 maintenance reports.
  - Verify the partial unique indexes are doing the work by dropping them temporarily in a test variant and asserting the test would fail without them — documents *why* they're load-bearing.

### Step 5 — Read endpoints
- `GET /vehicles` → `services/fleet.py::list_vehicles_with_latest()` uses `DISTINCT ON (vehicle_id) ... ORDER BY vehicle_id, timestamp DESC` to produce latest telemetry per vehicle; left-joined with latest incident per vehicle.
- `GET /fleet/state` → `SELECT status, COUNT(*) FROM (DISTINCT ON …) GROUP BY status` — derived, never cached server-side. Tests assert correctness mid-burst.
- `GET /zones/counts` → `SELECT zone_entered, COUNT(*) FROM telemetry_events WHERE zone_entered IS NOT NULL GROUP BY zone_entered`, then zero-fill from `ZONES` constant.
- `GET /anomalies?vehicle_id=&since=&until=` → indexed query on `(vehicle_id, timestamp DESC)`.
- Unit tests for query correctness; integration tests assert behavior under in-flight writes.

### Step 6 — SSE + Redis Pub/Sub fanout (integration tests for fanout)
- `realtime.py`: per-worker `Set[asyncio.Queue]`, `register`/`unregister`, `run_subscriber(redis_url, channel)` exactly as ADR-001 §6.1. Bounded queue (`maxsize=100`), drop-newest on full.
- `main.py` lifespan starts one subscriber task per worker.
- `routes/stream.py`: SSE generator with 20s keep-alive, `Cache-Control: no-cache`, `X-Accel-Buffering: no` headers; checks `request.is_disconnected()` (ADR-001 §6.2).
- Channel name: single global `fleet:events`. Payload schema: `{"type": "telemetry"|"incident"|"fault"|"zone_entered", "vehicle_id": ..., "data": {...}, "ts": iso8601}`. Versioned via a top-level `"v": 1`.
- Publisher is called from `services/*` post-commit only.
- **Integration tests:**
  - Spin up two API workers (two processes via subprocess or two app instances sharing redis). Connect an `EventSource`-equivalent (httpx-sse client) to each. POST a telemetry event to worker A. Assert both worker A and worker B's clients receive the message.
  - Fire 1000 publishes against a single bounded queue (maxsize=100). Assert no exception, queue depth never exceeds 100, drops are silent.

### Step 7 — Sessions & simulator
- `sessions.py` per ADR-001 §6.4 (set/get/touch/invalidate with TTL). Wired into a dependency that, if no `session_id` cookie is present, sets a static `dev-session` value. No login flow.
- `scripts/simulate.py`: 50 asyncio tasks, each sleeps `~1.0s` and POSTs telemetry; ~5% of vehicles drift into `fault`; `zone_entered` set on ~10% of events drawn from `ZONES`; battery drains over time and recharges in `charging_bay_*`. Invoked via `make simulate`.

### Step 8 — Lint/type/coverage gates
- `make lint` runs `ruff check` and `ruff format --check`.
- `make type` runs `mypy backend/app`.
- `make test` runs `pytest --cov=app --cov-fail-under=90`.

---

## Frontend implementation

### Step 1 — Scaffolding
- `npm create vite@latest frontend -- --template react-ts`. Add ESLint (airbnb + airbnb-typescript) + Prettier + Tailwind. Path aliases.

### Step 2 — SSE hook & resync pattern
- `useEventStream(url, onMessage)` per ADR-001 §6.5 — does **not** call `source.close()` on error (auto-reconnect).
- `useFleetState()`: on mount, fetch `/vehicles`, `/zones/counts`, `/fleet/state` to seed; then subscribe to `/stream` and apply incoming deltas. On `EventSource` `error` → re-run resync after reconnect.

### Step 3 — Components
- `VehicleList` — 50 rows, each shows id, status pill, battery bar, latest anomaly type+time. Sorted by vehicle id.
- `ZoneCounts` — grid of 20 zones from the `ZONES` constant (mirrored in TS), each with a count badge that animates on increment.
- `FleetAggregate` — four big counters (idle/moving/charging/fault).
- `FaultInjector` — dropdown of vehicle ids + button → `PATCH /vehicles/{id}/status` with body `{"status":"fault"}`. Shows toast on success.

### Step 4 — Tests
- Jest + RTL: render each component with mocked props, assert correct visuals; mock `EventSource` for the hook tests and assert resync triggers on error.
- 90% coverage gate via `jest --coverage --coverageThreshold`.

---

## Docker & Nginx

- `docker-compose.yml` services: `frontend` (vite dev, bind-mount `./frontend`), `nginx` (config bind-mounted), `api` (built from `backend/Dockerfile`, bind-mounts `./backend/app`, `--reload`, **scaled via `deploy.replicas: 3`** so all replicas share the `api` service name), `postgres:16`, `redis:7`. Shared `fleet-net` bridge. Note: `api` must **not** publish a host port (replicas can't bind the same port); only `nginx` publishes `:8080`.
- `nginx/nginx.conf`: uses Docker's embedded DNS for round-robin across replicas — at the `http` level declare `resolver 127.0.0.11 valid=10s ipv6=off;` and in each `location` set `set $api_upstream http://api:8000; proxy_pass $api_upstream;` so Nginx re-resolves on every request instead of caching one replica IP at startup. Two `location` blocks: `/api/` proxies normally; `/stream` adds `proxy_buffering off; proxy_read_timeout 1h; proxy_http_version 1.1;` so SSE survives — matches ADR-001 §7.2/§7.7. Sticky sessions are intentionally not used: ADR-001 D6 specifies at-most-once delivery + client resync on (re)connect, so an SSE reconnect landing on a different worker is by design; an open SSE connection stays pinned to its initial worker for its lifetime regardless.
- Multi-stage Dockerfiles: backend builder installs deps into `/opt/venv` with uv → slim runtime image copies `/opt/venv` and `app/`. Frontend production build is multi-stage but dev uses Vite directly via bind mount.
- `.env.example` lists `DATABASE_URL`, `REDIS_URL`, `SESSION_TTL_SECONDS`, anomaly thresholds. `python-dotenv` loads `.env` for local non-docker runs; in Docker, compose's `environment:` block is the source.

---

## Makefile targets

```
make setup           # uv sync + npm install
make fmt             # ruff format + prettier write
make lint            # ruff check + eslint
make type            # mypy + tsc --noEmit
make test            # pytest (with testcontainers) + jest
make test-backend
make test-frontend
make up              # docker compose up --build
make down
make migrate         # alembic upgrade head against running compose pg
make simulate        # python backend/scripts/simulate.py against localhost
make clean
```

---

## Reused / non-negotiable references

- All SQLAlchemy models, DDL, partial indexes, and the fault-transition transaction pattern come **verbatim** from `arch/ADR-002-database-and-concurrency.md`. Do not paraphrase.
- The SSE registry, subscriber task, SSE generator, session helpers, and React `useEventStream` hook come **verbatim** from `arch/ADR-001-realtime-dashboard-architecture.md` §6.1–§6.5.
- `ZONES` constant from `ai-log/db-design-main-prompt.md` (and CLAUDE.md). Lives in `backend/app/zones.py` and is mirrored in `frontend/src/types.ts` as a `readonly` array of literal types.

---

## Verification

End-to-end manual:
1. `make up` → docker compose brings up all five services.
2. `make migrate` → enum types + tables created.
3. `make simulate` → 50 vehicles start POSTing at 1 Hz.
4. Open `http://localhost:3000` → dashboard shows 50 rows filling in, zone counts ticking up, status counters changing. Verify no `EventSource` reconnect storms in devtools.
5. In the dashboard, use the fault-injection panel on `v-12` → that row turns red, fleet aggregate `fault` increments by 1, a `MOVEMENT_UNDER_FAULT` incident appears within ~1s when the next telemetry arrives with `status=fault, speed_mps>0`.
6. Query `psql` directly: `SELECT vehicle_id, COUNT(*) FROM missions WHERE status='canceled' GROUP BY 1` → matches the count of vehicles injected.

Automated:
- `make test` → both suites green, ≥90% coverage on both sides.
- `make lint && make type` → clean.
- The concurrency tests in `backend/tests/integration/test_fault_transition.py` and `test_telemetry_burst.py` are the must-pass set — they exercise the load-bearing partial unique indexes and the row lock.

Out of scope (documented in README's "Deliberately left out" section, echoing ADR-002):
- Auth / login UI (stubbed session).
- Telemetry partitioning, retention, dead-letter queue.
- Timer-based anomalies (`STALE_TELEMETRY`).
- AWS deployment — the production diagram is authoritative documentation, but no Terraform/CDK is delivered.
- Per-vehicle drill-down view.
