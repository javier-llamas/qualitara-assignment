from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import ZoneCount
from ..services.zones import get_zone_counts

router = APIRouter()


@router.get("/counts", response_model=list[ZoneCount])
async def zone_counts(session: AsyncSession = Depends(get_session)) -> list[ZoneCount]:
    return await get_zone_counts(session)
