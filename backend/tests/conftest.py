"""Session-scoped testcontainers fixtures for integration tests.

One Postgres + one Redis container per pytest session. Schema is created once
via `alembic upgrade head`. Tests get a per-test AsyncSession; tables are
truncated between tests to keep order independence cheap.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app import config as config_mod
from app import db as db_mod
from app import pubsub as pubsub_mod
from app.db import get_session_factory

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    # Bump max_connections so the 200-concurrent-event test doesn't trip the
    # default 100-connection cap when NullPool is in use.
    pg = PostgresContainer("postgres:16-alpine")
    pg = pg.with_command("postgres -c max_connections=500")
    with pg as started:
        yield started


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest.fixture(scope="session", autouse=True)
def configure_env(
    postgres_container: PostgresContainer, redis_container: RedisContainer
) -> Iterator[None]:
    """Bind app config + db + pubsub clients to the running containers."""
    raw = postgres_container.get_connection_url()
    # testcontainers default URL uses psycopg2 driver; swap to asyncpg.
    async_url = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    # Strip query params (e.g. ?sslmode=...) that asyncpg doesn't accept verbatim.
    async_url = async_url.split("?")[0]

    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    redis_url = f"redis://{redis_host}:{redis_port}/0"

    os.environ["DATABASE_URL"] = async_url
    os.environ["REDIS_URL"] = redis_url

    # `app.config.settings` was instantiated at import time with whatever env
    # existed then; mutate it now to match the running containers.
    config_mod.settings.database_url = async_url
    config_mod.settings.redis_url = redis_url
    db_mod.reset_engine_for_tests(async_url)
    pubsub_mod.reset_client_for_tests(redis_url)

    # Run alembic upgrade head against this container.
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={**os.environ},
        check=True,
    )
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_pubsub_client() -> AsyncIterator[None]:
    """Re-create the module-level pubsub redis client per test so it's bound to
    the current event loop (function-scoped). Otherwise the client carries
    connections from the previous test's closed loop."""
    pubsub_mod.reset_client_for_tests(config_mod.settings.redis_url)
    yield
    # Close the client cleanly before the loop closes.
    if pubsub_mod._client is not None:
        try:
            await pubsub_mod._client.aclose()
        except Exception:  # noqa: BLE001
            pass
        pubsub_mod._client = None


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Per-test session. Truncates all tables after each test."""
    factory = get_session_factory()
    async with factory() as session:
        yield session

    # Truncate between tests.
    async with factory() as cleanup:
        await cleanup.execute(_truncate_all_sql())
        await cleanup.commit()


def _truncate_all_sql() -> object:
    return text(
        "TRUNCATE TABLE incidents, maintenance_reports, missions, telemetry_events "
        "RESTART IDENTITY CASCADE"
    )


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[redis.Redis]:
    """Fresh redis client per test, scoped to the test container."""
    client = redis.from_url(config_mod.settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
