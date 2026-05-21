from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .config import settings
from .realtime import run_subscriber
from .routes import anomalies, fleet, stream, telemetry, vehicles, zones
from .sessions import ensure_dev_session

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fleet")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(
        run_subscriber(settings.redis_url, settings.fleet_channel)
    )
    log.info("started redis subscriber task")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="Fleet Telemetry Monitoring", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Routes — all gated by the dev-session stub (does not actually enforce).
app.include_router(
    telemetry.router, prefix="/telemetry", dependencies=[Depends(ensure_dev_session)]
)
app.include_router(
    vehicles.router, prefix="/vehicles", dependencies=[Depends(ensure_dev_session)]
)
app.include_router(
    anomalies.router, prefix="/anomalies", dependencies=[Depends(ensure_dev_session)]
)
app.include_router(
    zones.router, prefix="/zones", dependencies=[Depends(ensure_dev_session)]
)
app.include_router(
    fleet.router, prefix="/fleet", dependencies=[Depends(ensure_dev_session)]
)
app.include_router(
    stream.router, prefix="/stream", dependencies=[Depends(ensure_dev_session)]
)
