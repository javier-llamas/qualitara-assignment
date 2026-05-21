from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Incident
from ..schemas import IncidentOut

router = APIRouter()


@router.get("", response_model=list[IncidentOut])
async def get_anomalies(
    vehicle_id: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[IncidentOut]:
    stmt = select(Incident).order_by(Incident.timestamp.desc()).limit(limit)
    if vehicle_id is not None:
        stmt = stmt.where(Incident.vehicle_id == vehicle_id)
    if since is not None:
        stmt = stmt.where(Incident.timestamp >= since)
    if until is not None:
        stmt = stmt.where(Incident.timestamp <= until)
    rows = (await session.execute(stmt)).scalars().all()
    return [IncidentOut.model_validate(r, from_attributes=True) for r in rows]
