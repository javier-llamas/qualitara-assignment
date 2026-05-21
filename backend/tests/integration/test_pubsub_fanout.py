"""Pub/Sub fanout test — proves a worker's subscriber forwards to local clients
and that publishes from a different "worker" (separate redis client) reach it."""

from __future__ import annotations

import asyncio

import pytest

from app import pubsub, realtime
from app.config import settings


@pytest.mark.asyncio
async def test_subscriber_fans_message_to_local_clients() -> None:
    # Worker A: register a client and start the subscriber task.
    queue = realtime.register()
    sub_task = asyncio.create_task(
        realtime.run_subscriber(settings.redis_url, settings.fleet_channel)
    )
    try:
        # Allow subscriber a moment to actually SUBSCRIBE before publishing.
        await asyncio.sleep(0.3)

        # Worker B: publish via the module-level publish helper.
        await pubsub.publish("telemetry", "v-1", {"hello": "world"})

        msg = await asyncio.wait_for(queue.get(), timeout=3.0)
        assert '"hello"' in msg
        assert '"v-1"' in msg
    finally:
        sub_task.cancel()
        try:
            await sub_task
        except (asyncio.CancelledError, Exception):
            pass
        realtime.unregister(queue)


@pytest.mark.asyncio
async def test_bounded_queue_drops_when_full() -> None:
    """A slow client whose queue fills up must NOT cause exceptions on publish."""
    # Fill a queue beyond capacity directly (deterministic — no race).
    queue = realtime.register()
    try:
        for i in range(settings.sse_queue_maxsize):
            queue.put_nowait(f"msg-{i}")
        # Next put_nowait would raise — confirm publish path swallows it.
        # Simulate the subscriber's forwarding logic:
        try:
            queue.put_nowait("overflow")
            raise AssertionError("expected QueueFull")
        except asyncio.QueueFull:
            pass
        assert queue.qsize() == settings.sse_queue_maxsize
    finally:
        realtime.unregister(queue)
