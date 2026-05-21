"""Post-commit publish helper.

Callers MUST invoke `publish` after their DB transaction has committed
(ADR-001 §7.4 / ADR-002 by implication). Publishing inside a transaction
risks broadcasting state that was subsequently rolled back.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from .config import settings
from .schemas import StreamEvent, StreamEventType

log = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def reset_client_for_tests(url: str) -> None:
    global _client
    _client = redis.from_url(url, decode_responses=True)


async def publish(
    event_type: StreamEventType,
    vehicle_id: str,
    data: dict[str, Any],
) -> None:
    payload = StreamEvent(
        type=event_type,
        vehicle_id=vehicle_id,
        data=data,
        ts=datetime.now(UTC),
    )
    try:
        await get_client().publish(settings.fleet_channel, payload.model_dump_json())
    except Exception:  # noqa: BLE001
        # Publish-after-commit failing must not roll back already-committed state.
        log.exception("redis publish failed for %s/%s", event_type, vehicle_id)
