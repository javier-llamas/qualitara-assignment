"""Fleet aggregate queries — derived from telemetry_events (ADR-002 D2)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..models import (
    Incident,
    MaintenanceReport,
    Mission,
    MissionStatus,
    TelemetryEvent,
    VehicleStatus,
)
from ..schemas import (
    FleetState,
    IncidentOut,
    MaintenanceOut,
    MissionOut,
    VehicleDetail,
    VehicleSummary,
)


async def list_vehicles_with_latest(session: AsyncSession) -> list[VehicleSummary]:
    """One row per vehicle with its latest telemetry + latest incident."""
    latest_tel = select(
        TelemetryEvent,
        func.row_number()
        .over(
            partition_by=TelemetryEvent.vehicle_id,
            order_by=TelemetryEvent.timestamp.desc(),
        )
        .label("rn"),
    ).subquery()
    tel_alias = aliased(TelemetryEvent, latest_tel)

    latest_inc = select(
        Incident,
        func.row_number()
        .over(partition_by=Incident.vehicle_id, order_by=Incident.timestamp.desc())
        .label("rn"),
    ).subquery()
    inc_alias = aliased(Incident, latest_inc)

    stmt = (
        select(tel_alias, inc_alias)
        .where(latest_tel.c.rn == 1)
        .join(
            latest_inc,
            (latest_inc.c.vehicle_id == latest_tel.c.vehicle_id)
            & (latest_inc.c.rn == 1),
            isouter=True,
        )
        .order_by(tel_alias.vehicle_id)
    )

    rows = (await session.execute(stmt)).all()
    out: list[VehicleSummary] = []
    for t, i in rows:
        latest_incident = (
            IncidentOut.model_validate(i, from_attributes=True)
            if i is not None
            else None
        )
        out.append(
            VehicleSummary(
                vehicle_id=t.vehicle_id,
                status=t.status,
                battery_pct=t.battery_pct,
                speed_mps=t.speed_mps,
                lat=t.lat,
                lon=t.lon,
                last_seen_at=t.timestamp,
                latest_incident=latest_incident,
            )
        )
    return out


async def get_vehicle_detail(
    session: AsyncSession, vehicle_id: str, maintenance_limit: int = 50
) -> VehicleDetail:
    """Current mission + recent maintenance reports for a single vehicle.

    Missions and maintenance reports are real tables (not derived from
    telemetry), so they are queried directly. Incidents are intentionally not
    bundled here — the dashboard fetches them via /anomalies so the vehicle +
    time-range filtering can be exercised independently.
    """
    mission_row = (
        await session.execute(
            select(Mission)
            .where(
                Mission.vehicle_id == vehicle_id,
                Mission.status == MissionStatus.CURRENT,
            )
            .order_by(Mission.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    maint_rows = (
        (
            await session.execute(
                select(MaintenanceReport)
                .where(MaintenanceReport.vehicle_id == vehicle_id)
                .order_by(MaintenanceReport.timestamp.desc())
                .limit(maintenance_limit)
            )
        )
        .scalars()
        .all()
    )

    return VehicleDetail(
        vehicle_id=vehicle_id,
        current_mission=(
            MissionOut.model_validate(mission_row, from_attributes=True)
            if mission_row is not None
            else None
        ),
        maintenance_reports=[
            MaintenanceOut.model_validate(m, from_attributes=True) for m in maint_rows
        ],
    )


async def get_fleet_state(session: AsyncSession) -> FleetState:
    """Per-status counts across the fleet, derived from latest telemetry."""
    latest_tel = select(
        TelemetryEvent.vehicle_id,
        TelemetryEvent.status,
        func.row_number()
        .over(
            partition_by=TelemetryEvent.vehicle_id,
            order_by=TelemetryEvent.timestamp.desc(),
        )
        .label("rn"),
    ).subquery()
    stmt = (
        select(latest_tel.c.status, func.count().label("count"))
        .where(latest_tel.c.rn == 1)
        .group_by(latest_tel.c.status)
    )
    rows = (await session.execute(stmt)).all()
    state = FleetState()
    for status, count in rows:
        s = VehicleStatus(status)
        setattr(state, s.value, count)
        state.total += count
    return state
