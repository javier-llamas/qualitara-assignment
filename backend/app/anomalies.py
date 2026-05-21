"""Anomaly detectors per ADR-002 Decision 5.

Run synchronously inside the telemetry ingest transaction so the incident
rows share atomicity with their telemetry_event_id FK target.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import IncidentType, MaintenanceReport, MaintenanceStatus, VehicleStatus


@dataclass(frozen=True)
class IncidentDraft:
    incident_type: IncidentType
    timestamp: datetime
    details: dict[str, Any]


@dataclass(frozen=True)
class TelemetrySample:
    vehicle_id: str
    timestamp: datetime
    battery_pct: int
    speed_mps: float
    status: VehicleStatus
    error_codes: list[str]


def detect(
    event: TelemetrySample, previous: TelemetrySample | None
) -> list[IncidentDraft]:
    """Return drafts for every anomaly rule that fires on this event.

    `previous` is the most recent telemetry for this vehicle (or None on first sighting).
    """
    drafts: list[IncidentDraft] = []

    if event.speed_mps > settings.speed_limit_mps:
        drafts.append(
            IncidentDraft(
                incident_type=IncidentType.OVER_SPEED_LIMIT,
                timestamp=event.timestamp,
                details={
                    "speed_mps": event.speed_mps,
                    "limit": settings.speed_limit_mps,
                },
            )
        )

    if event.battery_pct < settings.low_battery_pct:
        drafts.append(
            IncidentDraft(
                incident_type=IncidentType.LOW_BATTERY,
                timestamp=event.timestamp,
                details={
                    "battery_pct": event.battery_pct,
                    "threshold": settings.low_battery_pct,
                },
            )
        )

    if event.status == VehicleStatus.FAULT and event.speed_mps > 0:
        drafts.append(
            IncidentDraft(
                incident_type=IncidentType.MOVEMENT_UNDER_FAULT,
                timestamp=event.timestamp,
                details={"speed_mps": event.speed_mps},
            )
        )

    if len(event.error_codes) > 0:
        drafts.append(
            IncidentDraft(
                incident_type=IncidentType.ERROR_CODE_PRESENT,
                timestamp=event.timestamp,
                details={"error_codes": list(event.error_codes)},
            )
        )

    if previous is not None:
        drop = previous.battery_pct - event.battery_pct
        if drop > settings.rapid_battery_drop_pct:
            drafts.append(
                IncidentDraft(
                    incident_type=IncidentType.RAPID_BATTERY_DRAIN,
                    timestamp=event.timestamp,
                    details={
                        "from_pct": previous.battery_pct,
                        "to_pct": event.battery_pct,
                        "drop": drop,
                    },
                )
            )

    return drafts


async def detect_maintenance_contradiction(
    session: AsyncSession, event: TelemetrySample
) -> IncidentDraft | None:
    """Fires when the vehicle has an open maintenance report but reports a
    non-fault status. The check requires a DB lookup so it lives outside the
    pure `detect()` function. Called from the ingest transaction so the
    resulting Incident row is atomic with the telemetry insert.
    """
    if event.status == VehicleStatus.FAULT:
        return None
    open_report_id = (
        await session.execute(
            select(MaintenanceReport.id)
            .where(
                MaintenanceReport.vehicle_id == event.vehicle_id,
                MaintenanceReport.status.in_(
                    [MaintenanceStatus.QUEUED, MaintenanceStatus.ONGOING]
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_report_id is None:
        return None
    return IncidentDraft(
        incident_type=IncidentType.TELEMETRY_CONTRADICTS_MAINTENANCE,
        timestamp=event.timestamp,
        details={
            "maintenance_report_id": open_report_id,
            "reported_status": event.status.value,
        },
    )
