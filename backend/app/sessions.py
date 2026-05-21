"""Redis-backed sessions per ADR-001 §6.4.

For this assignment auth is stubbed: requests without a `session_id` cookie
get a deterministic `dev-session` value. Routes are NOT gated.
"""

from __future__ import annotations

import redis.asyncio as redis
from fastapi import Cookie, Response

from .config import settings

SESSION_PREFIX = "session:"
DEV_SESSION_ID = "dev-session"
DEV_SESSION_VALUE = '{"user":"dev"}'


def _key(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


async def put(client: redis.Redis, session_id: str, value: str) -> None:
    await client.set(_key(session_id), value, ex=settings.session_ttl_seconds)


async def get(client: redis.Redis, session_id: str) -> str | None:
    value = await client.get(_key(session_id))
    return value if value is None else str(value)


async def invalidate(client: redis.Redis, session_id: str) -> None:
    await client.delete(_key(session_id))


async def touch(client: redis.Redis, session_id: str) -> None:
    await client.expire(_key(session_id), settings.session_ttl_seconds)


async def ensure_dev_session(
    response: Response,
    session_id: str | None = Cookie(default=None),
) -> str:
    """Dependency that ensures a session cookie is present. Stub — never gates."""
    if session_id:
        return session_id
    response.set_cookie(
        "session_id",
        DEV_SESSION_ID,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return DEV_SESSION_ID
