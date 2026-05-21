from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TelemetryEvent
from ..schemas import ZoneCount
from ..zones import ZONES


async def get_zone_counts(session: AsyncSession) -> list[ZoneCount]:
    """GROUP BY zone_entered against the event log. Zero-fill from ZONES constant
    (ADR-002 D3)."""
    stmt = (
        select(TelemetryEvent.zone_entered, func.count().label("entry_count"))
        .where(TelemetryEvent.zone_entered.is_not(None))
        .group_by(TelemetryEvent.zone_entered)
    )
    rows = {row[0]: row[1] for row in (await session.execute(stmt)).all()}
    return [ZoneCount(zone=z, entry_count=rows.get(z, 0)) for z in ZONES]
