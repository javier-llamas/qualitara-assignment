"""SSE endpoint per ADR-001 §6.2."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..realtime import register, unregister

router = APIRouter()


@router.get("")
async def stream(request: Request) -> StreamingResponse:
    queue = register()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_keepalive_seconds
                    )
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    # Keep-alive comment; ignored by EventSource.
                    yield ": keep-alive\n\n"
        finally:
            unregister(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
