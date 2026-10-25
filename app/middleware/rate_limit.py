"""Distributed sliding-window rate limiter backed by Redis and Lua."""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

import redis.asyncio as aioredis

from app.core.logging import get_logger

logger = get_logger(__name__)

_LUA_PATH = Path(__file__).parent / "rate_limit.lua"
_LUA_SCRIPT: str = _LUA_PATH.read_text(encoding="utf-8")

# Plan limits: requests allowed per 60s sliding window
PLAN_LIMITS: dict[str, int] = {
    "free": 10,
    "premium": 100,
}
WINDOW_MS: int = 60_000  # 60-second window in milliseconds


class RateLimitExceeded(Exception):
    """Raised when a tenant exceeds their plan request limit."""

    def __init__(self, plan: str, limit: int, current: int) -> None:
        self.plan = plan
        self.limit = limit
        self.current = current
        super().__init__(f"Rate limit exceeded: {current}/{limit} for plan '{plan}'")


async def check_rate_limit(
    redis: aioredis.Redis[str],
    tenant_id: str,
    plan: str,
) -> tuple[int, int]:
    """Execute the atomic sliding-window Lua script against Redis.

    Returns:
        tuple of (current_count, limit) on success.

    Raises:
        RateLimitExceeded: if the tenant has exceeded their plan's request quota.
    """
    limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    key = f"rl:{tenant_id}"
    now_ms = int(time.time() * 1000)

    # eval returns a list of integers [allowed, current_count, limit]
    eval_result = await redis.eval(  # type: ignore[no-untyped-call]
        _LUA_SCRIPT,
        1,
        key,
        str(now_ms),
        str(WINDOW_MS),
        str(limit),
    )

    result = cast(list[int], eval_result)
    allowed = int(result[0])
    current = int(result[1])
    effective_limit = int(result[2])

    if not allowed:
        logger.warning(
            "Rate limit exceeded",
            extra={
                "tenant_id": tenant_id,
                "plan": plan,
                "count": current,
                "limit": effective_limit,
            },
        )
        raise RateLimitExceeded(plan=plan, limit=effective_limit, current=current)

    return current, effective_limit
