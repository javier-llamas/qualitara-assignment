# ADR-002: Database, Schema, and Write-Path Concurrency

**Status:** Accepted
**Scope:** Persistence layer and write-path concurrency for the fleet telemetry monitoring service.
**Audience:** Downstream planning agent (Claude Code) implementing the backend.

---

## Context

50 autonomous vehicles emit telemetry at 1 Hz (~50 writes/sec sustained, with bursts when many vehicles cross zone boundaries or transition state simultaneously). The service must:

- Ingest bursts of concurrent telemetry writes.
- Atomically cancel an active mission and create a maintenance record when a vehicle enters `fault`.
- Guarantee every `zone_entered` is counted, even when multiple vehicles cross into the same zone in the same instant.
- Serve a consistent aggregate fleet-state count under concurrent writes.
- Serve recent-anomaly queries filtered by vehicle and time range.

---

## Decision 1 — PostgreSQL over SQLite

**Decision:** Use PostgreSQL.

**Why:** At 50 writes/sec SQLite (WAL mode) would handle raw throughput fine; the "single-writer serialization" argument is weak at this scale. The real reasons are *correctness primitives* this spec needs:

- **Row-level locking (`SELECT ... FOR UPDATE`)** for the fault → cancel-mission → create-maintenance-record transaction. SQLite locks the whole database; Postgres locks just the mission row, so unrelated writes (telemetry from other vehicles) proceed.
- **Tunable isolation per transaction.** `READ COMMITTED` for telemetry inserts (cheap, no contention between vehicles), explicit row locks for the fault path. SQLite is effectively serializable for everything, which over-pays for the common case.
- **Native `TEXT[]`** for `error_codes` (vs. JSON-in-TEXT in SQLite) — preserves array operators for incident detection.
- **Partial unique indexes** to enforce "at most one active mission per vehicle" at the DB level (see Decision 2).
- **Answers the ADR's "what changes at scale" question honestly** — nothing on the DB axis until ~10k vehicles.

**Trade-off accepted:** Reviewer setup cost. Mitigated with `docker-compose.yml` and a one-command `README`.

---

## Decision 2 — Telemetry is the single source of truth; no `vehicles` table

**Decision:** Do not maintain a denormalized `vehicles(current_status, current_battery_pct, last_seen_at)` table. Derive all per-vehicle current state from `telemetry_events`.

**Why:** A denormalized vehicles row was the first instinct (fast aggregate reads), but at this scale the read is cheap and the denormalization introduces a hazard that outweighs the savings.

- **The aggregate query is already fast.** With an index on `(vehicle_id, timestamp DESC)`, the per-vehicle "latest event" lookup executes as a loose index scan — effectively 50 index seeks. Sub-millisecond. This only starts to hurt above ~10k vehicles, at which point a materialized view or cache beats a hand-maintained column anyway.
- **Out-of-order events become a correctness hazard.** A naive `UPDATE vehicles SET current_status = $new` clobbers newer state with older when a delayed/retried event lands. To do it correctly you need `WHERE last_seen_at < $incoming_ts` on every update — one more thing to get wrong. With telemetry as the source of truth, `ORDER BY timestamp DESC LIMIT 1` is correct by construction.
- **Zero setup to start receiving events.** No preseed step, no FK that rejects unknown `vehicle_id`s. The edge sends opaque IDs and the ingest endpoint never 500s on a typo'd ID — a better failure mode than rejecting the write.
- **Same logic applies to stateful incident detection** (e.g., `RAPID_BATTERY_DRAIN`): the "previous reading" lookup uses the same index and is equally cheap.

**Trade-off accepted:** No FK integrity on `vehicle_id`. Acceptable for this spec; called out under "Deliberately Left Out."

---

## Decision 3 — Zone counts are derived from the telemetry event log

**Decision:** No separate `zone_counters` table. The `GET /zones/counts` endpoint reads:

```sql
SELECT zone_entered AS zone, COUNT(*) AS entry_count
FROM telemetry_events
WHERE zone_entered IS NOT NULL
GROUP BY zone_entered;
```

Zones with zero entries are filled in from the hardcoded `ZONES` constant in the application layer.

**Why:**

- **"Guarantee every entry is counted" reduces to insert atomicity.** Each telemetry event is a single row insert; Postgres guarantees it either commits or doesn't. No counter to keep in sync, no `UPDATE ... SET count = count + 1` row contention when many vehicles converge on the same charging bay at shift change.
- **No write contention on hot zones.** A counter row would serialize all writes to the same zone; the event-log approach has zero cross-vehicle contention.
- **Read cost is trivial** with a partial index on `zone_entered`. ~50 vehicles × shift duration = small cardinality.

**Trade-off accepted:** `GET /zones/counts` scans more rows than a counter read. At this scale (and with the partial index) it's well under 10 ms. If reads become hot, materialize.

---

## Decision 4 — Fault transition: `READ COMMITTED` + row lock + DB-enforced invariant

**Decision:** Handle fault transitions in a single transaction at `READ COMMITTED` isolation, using `SELECT ... FOR UPDATE` to serialize concurrent transitions for the *same vehicle*, with a partial unique index enforcing the "at most one active mission" invariant.

**Why:** Two telemetry events for the same vehicle can race (network reorder, retry). The naive flow — read active mission, update it, insert maintenance — has a TOCTOU window where both transactions see an active mission, both cancel it, both insert maintenance.

- **`FOR UPDATE` serializes only same-vehicle transitions**, leaving all other writes unaffected. `READ COMMITTED` (PG default) is sufficient — no need to escalate to `SERIALIZABLE` and deal with retry loops.
- **The partial unique index** (`UNIQUE (vehicle_id) WHERE status = 'CURRENT'`) is the belt to the lock's suspenders: even if application logic regresses, the DB will reject any second active mission. This is the *real* guarantee; the lock is for performance and avoiding spurious constraint errors.
- **A second partial unique index on `maintenance_report`** (`UNIQUE (vehicle_id) WHERE status IN ('QUEUED','ONGOING')`) means a double-fault event gets a constraint violation we can swallow as a no-op, rather than creating duplicate maintenance work.

Key snippet (the planner should replicate this shape):

```python
async with db.begin():  # READ COMMITTED
    mission = await db.execute(
        select(Mission)
        .where(Mission.vehicle_id == vid, Mission.status == "CURRENT")
        .with_for_update()
    )
    if mission:
        mission.status = "CANCELED"
        mission.ended_at = now
    try:
        db.add(MaintenanceReport(vehicle_id=vid, status="QUEUED", ...))
        await db.flush()
    except IntegrityError:
        pass  # concurrent fault already created the record; no-op
```

---

## Decision 5 — Anomaly detection scope (in-process, on the write path)

**Decision:** Run anomaly detection synchronously inside the telemetry ingest handler, in the same transaction as the telemetry insert. Implement the following incident types:

| Incident | Type | Detection |
|---|---|---|
| `OVER_SPEED_LIMIT` | stateless | `speed_mps > THRESHOLD` |
| `LOW_BATTERY` | stateless | `battery_pct < THRESHOLD` |
| `MOVEMENT_UNDER_FAULT` | stateless | `status='fault' AND speed_mps > 0` |
| `ERROR_CODE_PRESENT` | stateless | `array_length(error_codes, 1) > 0` |
| `RAPID_BATTERY_DRAIN` | stateful | drop > N% vs. previous event for same vehicle |

**Why:**

- **Synchronous keeps the write path simple** and gives "real-time" semantics for free — by the time `POST /telemetry` returns 201, any incidents are persisted and queryable.
- **In-transaction means incident-and-event are atomic** — no "phantom incident" pointing at a telemetry row that rolled back, and the `telemetry_event_id` FK can be `NOT NULL`.
- **A mix of stateless and stateful** demonstrates the pattern without sprawling scope. Timer-based incidents (`STALE_TELEMETRY`) are deferred — see "Deliberately Left Out."

---

## Recommended DDL

```sql
-- Enums ----------------------------------------------------------------------
CREATE TYPE vehicle_status AS ENUM ('idle', 'moving', 'charging', 'fault');
CREATE TYPE mission_status AS ENUM ('current', 'finished', 'canceled');
CREATE TYPE maintenance_status AS ENUM ('queued', 'ongoing', 'complete');
CREATE TYPE incident_type AS ENUM (
    'movement_under_fault',
    'over_speed_limit',
    'low_battery',
    'error_code_present',
    'rapid_battery_drain'
);

-- Telemetry events (the source of truth) -------------------------------------
CREATE TABLE telemetry_events (
    id            BIGSERIAL PRIMARY KEY,
    vehicle_id    TEXT          NOT NULL,
    timestamp     TIMESTAMPTZ   NOT NULL,
    lat           DOUBLE PRECISION NOT NULL,
    lon           DOUBLE PRECISION NOT NULL,
    battery_pct   SMALLINT      NOT NULL CHECK (battery_pct BETWEEN 0 AND 100),
    speed_mps     REAL          NOT NULL CHECK (speed_mps >= 0),
    status        vehicle_status NOT NULL,
    error_codes   TEXT[]        NOT NULL DEFAULT '{}',
    zone_entered  TEXT          NULL,
    received_at   TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- Powers: latest-per-vehicle, fleet aggregate, anomaly-by-vehicle queries.
CREATE INDEX telemetry_vehicle_time_idx
    ON telemetry_events (vehicle_id, timestamp DESC);

-- Powers: GET /zones/counts. Partial — most rows have NULL.
CREATE INDEX telemetry_zone_idx
    ON telemetry_events (zone_entered)
    WHERE zone_entered IS NOT NULL;

-- Missions -------------------------------------------------------------------
CREATE TABLE missions (
    id           BIGSERIAL PRIMARY KEY,
    vehicle_id   TEXT          NOT NULL,
    status       mission_status NOT NULL,
    description  TEXT          NULL,
    started_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    ended_at     TIMESTAMPTZ   NULL
);

-- Enforces "at most one active mission per vehicle" at the DB level.
-- This is the invariant that protects the fault-transition path.
CREATE UNIQUE INDEX missions_one_active_per_vehicle_idx
    ON missions (vehicle_id)
    WHERE status = 'current';

-- Incidents ------------------------------------------------------------------
CREATE TABLE incidents (
    id                  BIGSERIAL PRIMARY KEY,
    vehicle_id          TEXT          NOT NULL,
    incident_type       incident_type NOT NULL,
    timestamp           TIMESTAMPTZ   NOT NULL,
    telemetry_event_id  BIGINT        NOT NULL REFERENCES telemetry_events(id),
    details             JSONB         NOT NULL DEFAULT '{}'::jsonb
);

-- Powers: GET /anomalies?vehicle_id=...&since=...&until=...
CREATE INDEX incidents_vehicle_time_idx
    ON incidents (vehicle_id, timestamp DESC);

-- Maintenance reports --------------------------------------------------------
CREATE TABLE maintenance_reports (
    id                    BIGSERIAL PRIMARY KEY,
    vehicle_id            TEXT               NOT NULL,
    timestamp             TIMESTAMPTZ        NOT NULL DEFAULT now(),
    status                maintenance_status NOT NULL,
    diagnostics           TEXT               NULL,
    cancelled_mission_id  BIGINT             NULL REFERENCES missions(id)
);

-- Prevents duplicate open maintenance records under concurrent fault events.
-- Lets the application swallow the IntegrityError as an idempotent no-op.
CREATE UNIQUE INDEX maintenance_one_open_per_vehicle_idx
    ON maintenance_reports (vehicle_id)
    WHERE status IN ('queued', 'ongoing');
```

---

## Recommended SQLAlchemy Models

```python
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, SmallInteger, String, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PgEnum, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class VehicleStatus(str, Enum):
    IDLE = "idle"; MOVING = "moving"; CHARGING = "charging"; FAULT = "fault"

class MissionStatus(str, Enum):
    CURRENT = "current"; FINISHED = "finished"; CANCELED = "canceled"

class MaintenanceStatus(str, Enum):
    QUEUED = "queued"; ONGOING = "ongoing"; COMPLETE = "complete"

class IncidentType(str, Enum):
    MOVEMENT_UNDER_FAULT = "movement_under_fault"
    OVER_SPEED_LIMIT     = "over_speed_limit"
    LOW_BATTERY          = "low_battery"
    ERROR_CODE_PRESENT   = "error_code_present"
    RAPID_BATTERY_DRAIN  = "rapid_battery_drain"


# create_type=False everywhere: types are owned by Alembic migrations,
# not by per-table CREATEs, to avoid "type already exists" errors.
vehicle_status_pg     = PgEnum(VehicleStatus,     name="vehicle_status",     create_type=False)
mission_status_pg     = PgEnum(MissionStatus,     name="mission_status",     create_type=False)
maintenance_status_pg = PgEnum(MaintenanceStatus, name="maintenance_status", create_type=False)
incident_type_pg      = PgEnum(IncidentType,      name="incident_type",      create_type=False)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id:           Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    vehicle_id:   Mapped[str]      = mapped_column(Text, nullable=False)
    timestamp:    Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat:          Mapped[float]    = mapped_column(Float, nullable=False)
    lon:          Mapped[float]    = mapped_column(Float, nullable=False)
    battery_pct:  Mapped[int]      = mapped_column(SmallInteger, nullable=False)
    speed_mps:    Mapped[float]    = mapped_column(Float, nullable=False)
    status:       Mapped[VehicleStatus] = mapped_column(vehicle_status_pg, nullable=False)
    error_codes:  Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    zone_entered: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("battery_pct BETWEEN 0 AND 100", name="battery_pct_range"),
        CheckConstraint("speed_mps >= 0",                name="speed_mps_nonneg"),
        Index("telemetry_vehicle_time_idx", "vehicle_id", "timestamp", postgresql_using="btree"),
        Index(
            "telemetry_zone_idx", "zone_entered",
            postgresql_where=(mapped_column("zone_entered").isnot(None)),
        ),
    )


class Mission(Base):
    __tablename__ = "missions"

    id:          Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    vehicle_id:  Mapped[str]      = mapped_column(Text, nullable=False)
    status:      Mapped[MissionStatus] = mapped_column(mission_status_pg, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The invariant. Implementation MUST rely on this, not just on app logic.
        Index(
            "missions_one_active_per_vehicle_idx", "vehicle_id",
            unique=True,
            postgresql_where=(mapped_column("status") == "current"),
        ),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id:                 Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    vehicle_id:         Mapped[str]      = mapped_column(Text, nullable=False)
    incident_type:      Mapped[IncidentType] = mapped_column(incident_type_pg, nullable=False)
    timestamp:          Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    telemetry_event_id: Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("telemetry_events.id"), nullable=False
    )
    details:            Mapped[dict]     = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        Index("incidents_vehicle_time_idx", "vehicle_id", "timestamp"),
    )


class MaintenanceReport(Base):
    __tablename__ = "maintenance_reports"

    id:                   Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    vehicle_id:           Mapped[str]      = mapped_column(Text, nullable=False)
    timestamp:            Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status:               Mapped[MaintenanceStatus] = mapped_column(maintenance_status_pg, nullable=False)
    diagnostics:          Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_mission_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("missions.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "maintenance_one_open_per_vehicle_idx", "vehicle_id",
            unique=True,
            postgresql_where=(mapped_column("status").in_(["queued", "ongoing"])),
        ),
    )
```

**Notes for the planner:**

- The two partial unique indexes (`missions_one_active_per_vehicle_idx`, `maintenance_one_open_per_vehicle_idx`) are load-bearing. Do not drop them in favor of "the application checks it" — they are the only guarantee under concurrent writes.
- Enum types must be created once in an Alembic migration (`create_type=False` on the model prevents SQLAlchemy from re-emitting `CREATE TYPE` per table).
- All timestamps are `TIMESTAMPTZ`. Application code must send timezone-aware datetimes.

---

## Open Assumptions

- **Vehicle IDs are opaque strings from the edge.** No registration step.
- **`timestamp` on telemetry is wall-clock from the vehicle** (may be out-of-order on arrival). Indexes are designed for `ORDER BY timestamp DESC` regardless of insert order.
- **Mission lifecycle is created out-of-band** (no spec on how missions start). For the demo, seed a few `current` missions at startup so the fault path has something to cancel.

## Deliberately Left Out

- **`vehicles` table.** Not needed; see Decision 2. Loses FK integrity on `vehicle_id` — acceptable.
- **Planned-route deviation incidents.** Would require modeling planned zone sequences per mission, deviation tolerance, debounce/cooldown to prevent flooding on first-zone misses, and an alerting policy. Significant business logic for marginal value in this slice.
- **Timer-based incidents (`STALE_TELEMETRY`).** Would need a background scheduler. Out of scope; the synchronous-on-ingest model covers the spec.
- **Telemetry partitioning / retention.** At 50 writes/sec a single table is fine for months. Range-partition by `timestamp` when retention or query latency demands it.

## What Changes at Significant Scale (~10k+ vehicles, ~10k writes/sec)

These are not alternatives — they are layers, each triggered by a different pressure. They can be adopted independently as that pressure shows up:

- **Read latency on aggregates becomes the bottleneck** → Redis counters updated post-commit (the same Redis already used for SSE fan-out to the dashboard). `GET /fleet/state` reads `HGETALL fleet:status` in sub-millisecond. Replaces the on-demand SQL query. Simpler than a materialized view at this scale and reuses infrastructure already in the architecture for the live dashboard.
- **Ingest spikes overwhelm DB write capacity** → Kafka (or Redis Streams) in front of the API; the endpoint publishes to the queue and returns 202, a worker pool consumes into Postgres at a controlled rate. Decouples burst absorption from durable-write throughput.
- **Telemetry table query/storage degrades** → range-partition by month with `pg_partman` for auto-creation. The real value isn't query speed — it's that it *enables* cheap retention via `DROP TABLE partition_xyz` (instant, releases disk) instead of `DELETE FROM ... WHERE timestamp < ...` (locks, WAL bloat, requires `VACUUM FULL`). Worth adopting before a retention policy exists, so it's in place when one is defined.
- **Windowed analytics requirement appears** (e.g., "avg battery per zone per 5-min tumbling window," "p95 speed per aisle per hour") → introduce a stream processor. Flink SQL is the 2026 default for new projects; ksqlDB's long-term trajectory is uncertain given Confluent's strategic pivot to Flink (Immerok acquisition, 2023). **Not needed for the per-status counts in this spec** — those are point-in-time lookups, not windowed aggregations, and the Redis-counter pattern above handles them with far less operational overhead.

None of this is needed at 50 vehicles.

**Note:** The above measures are deliberately *not* present in the production-scaled architecture for this submission. There is not enough information in the spec to predict which (if any) of these will become necessary — the choice depends on actual traffic shape, retention requirements, dashboard latency SLOs, and what windowed analytics (if any) the business eventually asks for. Pre-adopting any of them would be guessing. The architecture as designed scales linearly with vehicle count until one of the four pressures above actually shows up, at which point the corresponding layer can be added without restructuring the rest of the system.
