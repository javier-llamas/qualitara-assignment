"""Per-worker SSE client registry + Redis subscriber.

Module-level state. NOT shared across workers — fanout uses Redis Pub/Sub
(see app.pubsub). One subscriber task per worker (ADR-001 §6.1, §7.8).
"""

import asyncio
import logging

import redis.asyncio as redis

from .config import settings

log = logging.getLogger(__name__)

_clients: set[asyncio.Queue[str]] = set()


def register() -> asyncio.Queue[str]:
    """Register a new SSE client and return its bounded queue."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.sse_queue_maxsize)
    _clients.add(queue)
    return queue


def unregister(queue: asyncio.Queue[str]) -> None:
    _clients.discard(queue)


def client_count() -> int:
    return len(_clients)


async def run_subscriber(redis_url: str, channel: str) -> None:
    """Fan messages from `channel` to every locally-connected SSE client.

    Bounded queues + drop-newest on overflow (ADR-001 §7.1). A slow client
    must never grow memory unboundedly; clients resync on reconnect.
    """
    client = redis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    log.info("realtime subscriber listening on %s", channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            payload = message["data"]
            for q in list(_clients):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    # drop-newest; client will resync on next reconnect
                    pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await client.aclose()
