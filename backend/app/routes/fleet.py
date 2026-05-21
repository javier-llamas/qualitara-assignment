from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import FleetState
from ..services.fleet import get_fleet_state

router = APIRouter()


@router.get("/state", response_model=FleetState)
async def fleet_state(session: AsyncSession = Depends(get_session)) -> FleetState:
    return await get_fleet_state(session)
