from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import pubsub
from ..db import get_session
from ..models import VehicleStatus
from ..schemas import StatusUpdate, VehicleDetail, VehicleSummary
from ..services.faults import transition_to_fault
from ..services.fleet import get_vehicle_detail, list_vehicles_with_latest

router = APIRouter()


@router.get("", response_model=list[VehicleSummary])
async def get_vehicles(
    session: AsyncSession = Depends(get_session),
) -> list[VehicleSummary]:
    return await list_vehicles_with_latest(session)


@router.get("/{vehicle_id}/detail", response_model=VehicleDetail)
async def get_detail(
    vehicle_id: str,
    session: AsyncSession = Depends(get_session),
) -> VehicleDetail:
    return await get_vehicle_detail(session, vehicle_id)


@router.patch("/{vehicle_id}/status")
async def patch_vehicle_status(
    vehicle_id: str,
    body: StatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if body.status != VehicleStatus.FAULT:
        # For non-fault explicit status changes there is no transactional side
        # effect — the next telemetry event will carry the new status. We do
        # not write a synthetic telemetry row.
        return {
            "status": body.status.value,
            "applied": False,
            "reason": "no-op (status flows via telemetry)",
        }

    async with session.begin():
        result = await transition_to_fault(
            session, vehicle_id, diagnostics="manual: status patch"
        )

    await pubsub.publish(
        "fault",
        vehicle_id,
        {
            "cancelled_mission_id": result.cancelled_mission_id,
            "maintenance_report_id": result.maintenance_report_id,
            "already_open": result.already_open,
        },
    )
    return {
        "status": "fault",
        "applied": True,
        "cancelled_mission_id": result.cancelled_mission_id,
        "maintenance_report_id": result.maintenance_report_id,
        "already_open": result.already_open,
    }
