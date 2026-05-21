from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import (
    Incident,
    IncidentType,
    MaintenanceReport,
    MaintenanceStatus,
    TelemetryEvent,
    VehicleStatus,
)
from app.schemas import TelemetryIn
from app.services.faults import transition_to_fault
from app.services.telemetry import ingest
from app.services.zones import get_zone_counts

NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def make_event(
    vehicle_id: str = "v-1",
    offset_s: int = 0,
    **overrides,
) -> TelemetryIn:
    base = dict(
        vehicle_id=vehicle_id,
        timestamp=NOW + timedelta(seconds=offset_s),
        lat=37.41,
        lon=-122.08,
        battery_pct=80,
        speed_mps=1.0,
        status=VehicleStatus.MOVING,
        error_codes=[],
        zone_entered=None,
    )
    base.update(overrides)
    return TelemetryIn(**base)


@pytest.mark.asyncio
async def test_single_ingest_inserts_telemetry_and_no_incident(
    db_session: AsyncSession,
) -> None:
    factory = get_session_factory()
    async with factory() as s:
        outcome = await ingest(s, make_event())
    assert outcome.telemetry_id > 0
    assert outcome.incident_ids == []
    assert outcome.triggered_fault_transition is False


@pytest.mark.asyncio
async def test_ingest_detects_over_speed(db_session: AsyncSession) -> None:
    factory = get_session_factory()
    async with factory() as s:
        outcome = await ingest(s, make_event(speed_mps=10.0))
    assert len(outcome.incident_ids) == 1
    async with factory() as s:
        inc = (await s.execute(select(Incident))).scalars().all()
    assert inc[0].incident_type == IncidentType.OVER_SPEED_LIMIT
    assert inc[0].telemetry_event_id == outcome.telemetry_id


@pytest.mark.asyncio
async def test_concurrent_ingest_200_events(db_session: AsyncSession) -> None:
    """200 events for 20 vehicles via asyncio.gather. Every row must be present
    and every incident FK must point at an existing telemetry row."""
    factory = get_session_factory()

    async def one(vid: int, offset: int) -> None:
        async with factory() as s:
            await ingest(
                s,
                make_event(
                    vehicle_id=f"v-{vid}",
                    offset_s=offset,
                    # Trigger LOW_BATTERY every other event so we exercise incident inserts.
                    battery_pct=5 if offset % 2 == 0 else 90,
                ),
            )

    tasks = [one(vid, i) for vid in range(20) for i in range(10)]
    await asyncio.gather(*tasks)

    async with factory() as s:
        tel_count = (await s.execute(select(TelemetryEvent))).scalars().all()
        inc_rows = (await s.execute(select(Incident))).scalars().all()
    assert len(tel_count) == 200
    tel_ids = {t.id for t in tel_count}
    for inc in inc_rows:
        assert inc.telemetry_event_id in tel_ids
    # At least 100 LOW_BATTERY incidents (every other event has battery=5);
    # RAPID_BATTERY_DRAIN may also fire on transitions, so cap is loose.
    assert len(inc_rows) >= 100


@pytest.mark.asyncio
async def test_zone_counts_under_concurrent_writes(db_session: AsyncSession) -> None:
    """50 simultaneous zone_entered events for the same zone all count."""
    factory = get_session_factory()

    async def one(vid: int) -> None:
        async with factory() as s:
            await ingest(
                s,
                make_event(
                    vehicle_id=f"v-{vid}",
                    offset_s=vid,
                    zone_entered="charging_bay_1",
                ),
            )

    await asyncio.gather(*(one(i) for i in range(50)))

    async with factory() as s:
        counts = await get_zone_counts(s)
    by_zone = {c.zone: c.entry_count for c in counts}
    assert by_zone["charging_bay_1"] == 50
    # Untouched zones zero-filled
    assert by_zone["maintenance_bay"] == 0


@pytest.mark.asyncio
async def test_telemetry_contradicts_open_maintenance_report(
    db_session: AsyncSession,
) -> None:
    """A vehicle with an open (QUEUED/ONGOING) maintenance report that reports
    a non-fault status should produce a TELEMETRY_CONTRADICTS_MAINTENANCE
    incident. Mirrors the manual-fault-then-simulator-keeps-moving scenario."""
    factory = get_session_factory()
    # Operator manually faults the vehicle (no telemetry row written).
    async with factory() as s:
        async with s.begin():
            await transition_to_fault(s, "v-contradict", diagnostics="test")

    # Now a telemetry event arrives claiming status=moving — should fire the new incident.
    async with factory() as s:
        outcome = await ingest(
            s,
            make_event(
                vehicle_id="v-contradict", status=VehicleStatus.MOVING, speed_mps=1.0
            ),
        )
    assert outcome.incident_ids, "expected at least one incident"

    async with factory() as s:
        rows = (await s.execute(select(Incident))).scalars().all()
    types = {r.incident_type for r in rows}
    assert IncidentType.TELEMETRY_CONTRADICTS_MAINTENANCE in types

    # And NOT firing when the same vehicle reports fault.
    async with factory() as s:
        await ingest(
            s,
            make_event(
                vehicle_id="v-contradict",
                offset_s=2,
                status=VehicleStatus.FAULT,
                speed_mps=0.0,
            ),
        )
    async with factory() as s:
        rows = (await s.execute(select(Incident))).scalars().all()
        contradictions = [
            r
            for r in rows
            if r.incident_type == IncidentType.TELEMETRY_CONTRADICTS_MAINTENANCE
        ]
    # Only the first event should have produced one.
    assert len(contradictions) == 1

    # And NOT firing for a vehicle with no open maintenance report.
    async with factory() as s:
        outcome2 = await ingest(
            s,
            make_event(
                vehicle_id="v-clean", status=VehicleStatus.MOVING, speed_mps=1.0
            ),
        )
    async with factory() as s:
        rows = (
            (await s.execute(select(Incident).where(Incident.vehicle_id == "v-clean")))
            .scalars()
            .all()
        )
    assert not any(
        r.incident_type == IncidentType.TELEMETRY_CONTRADICTS_MAINTENANCE for r in rows
    )
    # Silence unused warnings
    _ = outcome2

    # Closing the maintenance report stops further contradictions.
    async with factory() as s:
        async with s.begin():
            report = (
                await s.execute(
                    select(MaintenanceReport).where(
                        MaintenanceReport.vehicle_id == "v-contradict"
                    )
                )
            ).scalar_one()
            report.status = MaintenanceStatus.COMPLETE
    async with factory() as s:
        await ingest(
            s,
            make_event(
                vehicle_id="v-contradict",
                offset_s=10,
                status=VehicleStatus.MOVING,
                speed_mps=1.0,
            ),
        )
    async with factory() as s:
        rows = (
            (
                await s.execute(
                    select(Incident).where(Incident.vehicle_id == "v-contradict")
                )
            )
            .scalars()
            .all()
        )
        contradictions = [
            r
            for r in rows
            if r.incident_type == IncidentType.TELEMETRY_CONTRADICTS_MAINTENANCE
        ]
    assert len(contradictions) == 1, "no new contradiction after report COMPLETE"


@pytest.mark.asyncio
async def test_rapid_battery_drain_uses_previous_event(
    db_session: AsyncSession,
) -> None:
    factory = get_session_factory()
    async with factory() as s:
        await ingest(s, make_event(vehicle_id="v-rapid", battery_pct=80, offset_s=0))
    async with factory() as s:
        outcome = await ingest(
            s, make_event(vehicle_id="v-rapid", battery_pct=50, offset_s=1)
        )
    async with factory() as s:
        rows = (await s.execute(select(Incident))).scalars().all()
    types = {r.incident_type for r in rows}
    assert IncidentType.RAPID_BATTERY_DRAIN in types
    assert outcome.incident_ids  # at least one
