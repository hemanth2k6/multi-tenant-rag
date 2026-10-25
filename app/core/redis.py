"""Redis async client connection management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

RedisClient = Any

_redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    """Return or initialize the singleton Redis async client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


async def get_redis() -> AsyncGenerator[RedisClient, None]:
    """FastAPI dependency yielding the async Redis client."""
    client = get_redis_client()
    yield client
