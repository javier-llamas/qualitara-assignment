from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import TelemetryIn
from ..services.telemetry import ingest

router = APIRouter()


@router.post("", status_code=201)
async def post_telemetry(
    event: TelemetryIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    outcome = await ingest(session, event)
    return {
        "telemetry_id": outcome.telemetry_id,
        "incident_ids": outcome.incident_ids,
        "triggered_fault_transition": outcome.triggered_fault_transition,
        "cancelled_mission_id": outcome.cancelled_mission_id,
        "maintenance_report_id": outcome.maintenance_report_id,
    }
