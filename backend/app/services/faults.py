"""Fault transition — ADR-002 Decision 4.

One transaction at READ COMMITTED, SELECT ... FOR UPDATE on the active mission,
mark canceled, insert maintenance report. The maintenance insert runs inside
a SAVEPOINT so an IntegrityError (from the partial unique index) can be
swallowed as an idempotent no-op without poisoning the outer transaction.

The partial unique indexes are the real guarantee — the lock is for
performance and avoiding spurious constraint errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MaintenanceReport, MaintenanceStatus, Mission, MissionStatus


@dataclass(frozen=True)
class FaultTransitionResult:
    cancelled_mission_id: int | None
    maintenance_report_id: int | None
    already_open: bool  # True if a maintenance report was already open for this vehicle


async def transition_to_fault(
    session: AsyncSession,
    vehicle_id: str,
    diagnostics: str | None = None,
) -> FaultTransitionResult:
    """Idempotent under concurrency.

    Must be called inside an outer transaction (caller commits). The maintenance
    insert is wrapped in a SAVEPOINT so a duplicate-fault IntegrityError can be
    swallowed without rolling back work that already happened in the outer txn
    (e.g. the telemetry event insert in the ingest path).
    """

    now = datetime.now(UTC)

    active = (
        await session.execute(
            select(Mission)
            .where(
                Mission.vehicle_id == vehicle_id,
                Mission.status == MissionStatus.CURRENT,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    cancelled_mission_id: int | None = None
    if active is not None:
        active.status = MissionStatus.CANCELED
        active.ended_at = now
        cancelled_mission_id = active.id
        # Flush the mission update before the savepoint so it's part of the outer txn,
        # not subject to savepoint rollback.
        await session.flush()

    report = MaintenanceReport(
        vehicle_id=vehicle_id,
        status=MaintenanceStatus.QUEUED,
        diagnostics=diagnostics,
        cancelled_mission_id=cancelled_mission_id,
    )

    try:
        async with session.begin_nested():
            session.add(report)
            # savepoint commit triggers the INSERT
    except IntegrityError:
        # Concurrent fault already opened a maintenance report; partial unique
        # index rejected the duplicate. Idempotent no-op.
        return FaultTransitionResult(
            cancelled_mission_id=cancelled_mission_id,
            maintenance_report_id=None,
            already_open=True,
        )

    return FaultTransitionResult(
        cancelled_mission_id=cancelled_mission_id,
        maintenance_report_id=report.id,
        already_open=False,
    )
