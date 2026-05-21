"""Telemetry ingest — one transaction at READ COMMITTED:
  1. insert TelemetryEvent
  2. look up previous event for vehicle
  3. run anomaly detectors and insert incident rows (NOT NULL FK)
  4. if status transitioned to fault, call transition_to_fault inline
  5. commit

After commit, publish a `telemetry` event to Redis (ADR-001 §7.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import pubsub
from ..anomalies import TelemetrySample, detect, detect_maintenance_contradiction
from ..models import Incident, TelemetryEvent, VehicleStatus
from ..schemas import TelemetryIn
from .faults import transition_to_fault


@dataclass
class IngestOutcome:
    telemetry_id: int
    incident_ids: list[int]
    triggered_fault_transition: bool
    cancelled_mission_id: int | None
    maintenance_report_id: int | None


async def ingest(session: AsyncSession, event: TelemetryIn) -> IngestOutcome:
    """Insert telemetry + incidents in one transaction. Caller must NOT have an
    outer transaction open; this function uses `session.begin()` itself."""

    async with session.begin():
        # 1. Look up previous event for this vehicle BEFORE inserting the new one,
        #    so the "previous" sample is unambiguous regardless of timestamp ordering.
        previous_row = (
            await session.execute(
                select(TelemetryEvent)
                .where(TelemetryEvent.vehicle_id == event.vehicle_id)
                .order_by(TelemetryEvent.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        previous_status: VehicleStatus | None = (
            previous_row.status if previous_row is not None else None
        )

        # 2. Insert the new telemetry event.
        row = TelemetryEvent(
            vehicle_id=event.vehicle_id,
            timestamp=event.timestamp,
            lat=event.lat,
            lon=event.lon,
            battery_pct=event.battery_pct,
            speed_mps=event.speed_mps,
            status=event.status,
            error_codes=event.error_codes,
            zone_entered=event.zone_entered,
        )
        session.add(row)
        await session.flush()  # row.id assigned

        # 3. Detect anomalies and persist them with the FK to the telemetry row.
        prev_sample = (
            TelemetrySample(
                vehicle_id=previous_row.vehicle_id,
                timestamp=previous_row.timestamp,
                battery_pct=previous_row.battery_pct,
                speed_mps=previous_row.speed_mps,
                status=previous_row.status,
                error_codes=previous_row.error_codes,
            )
            if previous_row is not None
            else None
        )
        curr_sample = TelemetrySample(
            vehicle_id=event.vehicle_id,
            timestamp=event.timestamp,
            battery_pct=event.battery_pct,
            speed_mps=event.speed_mps,
            status=event.status,
            error_codes=event.error_codes,
        )
        drafts = detect(curr_sample, prev_sample)
        # Stateful detector that needs a DB lookup against maintenance_reports.
        contradiction = await detect_maintenance_contradiction(session, curr_sample)
        if contradiction is not None:
            drafts.append(contradiction)
        incident_rows = [
            Incident(
                vehicle_id=event.vehicle_id,
                incident_type=draft.incident_type,
                timestamp=draft.timestamp,
                telemetry_event_id=row.id,
                details=draft.details,
            )
            for draft in drafts
        ]
        for ir in incident_rows:
            session.add(ir)
        if incident_rows:
            await session.flush()

        # 4. If this event is a transition INTO fault, run the cancel-mission +
        #    create-maintenance step in the same transaction.
        triggered_fault = (
            event.status == VehicleStatus.FAULT
            and previous_status != VehicleStatus.FAULT
        )
        cancelled_mission_id: int | None = None
        maintenance_report_id: int | None = None
        if triggered_fault:
            result = await transition_to_fault(
                session,
                event.vehicle_id,
                diagnostics=f"auto: telemetry event {row.id}",
            )
            cancelled_mission_id = result.cancelled_mission_id
            maintenance_report_id = result.maintenance_report_id

        outcome = IngestOutcome(
            telemetry_id=row.id,
            incident_ids=[ir.id for ir in incident_rows],
            triggered_fault_transition=triggered_fault,
            cancelled_mission_id=cancelled_mission_id,
            maintenance_report_id=maintenance_report_id,
        )

    # 5. After commit: publish stream events. Publish failures must not propagate
    #    (already-committed state is final).
    await pubsub.publish(
        "telemetry",
        event.vehicle_id,
        {
            "telemetry_id": outcome.telemetry_id,
            "battery_pct": event.battery_pct,
            "speed_mps": event.speed_mps,
            "status": event.status.value,
            "lat": event.lat,
            "lon": event.lon,
            "timestamp": event.timestamp.isoformat(),
        },
    )
    if event.zone_entered is not None:
        await pubsub.publish(
            "zone_entered",
            event.vehicle_id,
            {"zone": event.zone_entered, "telemetry_id": outcome.telemetry_id},
        )
    for ir in incident_rows:
        await pubsub.publish(
            "incident",
            event.vehicle_id,
            {
                "incident_id": ir.id,
                "incident_type": ir.incident_type.value,
                "telemetry_id": outcome.telemetry_id,
            },
        )
    if outcome.triggered_fault_transition:
        await pubsub.publish(
            "fault",
            event.vehicle_id,
            {
                "cancelled_mission_id": outcome.cancelled_mission_id,
                "maintenance_report_id": outcome.maintenance_report_id,
            },
        )

    return outcome
