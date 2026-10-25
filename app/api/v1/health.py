"""Health check and readiness endpoints."""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def health_liveness() -> dict[str, str]:
    """Basic liveness check verifying the HTTP server is alive."""
    return {"status": "ok"}


@router.get(
    "/health/ready",
    summary="Readiness probe checking database and cache connectivity",
)
async def health_readiness(
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis[str] = Depends(get_redis),
) -> dict[str, Any]:
    """Readiness probe checking PostgreSQL and Redis connectivity."""
    db_ok = False
    redis_ok = False

    try:
        res = await db.execute(text("SELECT 1"))
        db_ok = res.scalar() == 1
    except Exception:
        db_ok = False

    try:
        redis_ok = await redis.ping()
    except Exception:
        redis_ok = False

    overall_ready = db_ok and redis_ok

    if not overall_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if overall_ready else "degraded",
        "database": "connected" if db_ok else "unavailable",
        "redis": "connected" if redis_ok else "unavailable",
    }
