"""Distributed sliding-window rate limiter backed by Redis and atomic Lua."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.core.security import hash_api_key

logger = get_logger(__name__)

_LUA_PATH = Path(__file__).parent / "rate_limit.lua"
_LUA_SCRIPT: str = _LUA_PATH.read_text(encoding="utf-8")

# Plan limits: requests allowed per 60s sliding window
PLAN_LIMITS: dict[str, int] = {
    "free": 10,
    "premium": 100,
}
WINDOW_MS: int = 60_000  # 60-second window in milliseconds

# Paths exempt from rate limiting (health checks and API documentation)
EXEMPT_PATHS: set[str] = {
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class RateLimitExceeded(Exception):
    """Raised when a tenant or client exceeds their plan request limit."""

    def __init__(self, plan: str, limit: int, current: int) -> None:
        self.plan = plan
        self.limit = limit
        self.current = current
        super().__init__(f"Rate limit exceeded: {current}/{limit} for plan '{plan}'")


async def check_rate_limit(
    redis: Any,
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
    eval_result = await redis.eval(
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Production ASGI middleware enforcing sliding-window rate limits via Redis.

    Features:
    - Path exemption for probes (/health, /health/ready) and docs.
    - Dual client identification: Bearer key hash for authenticated calls, IP for unauthenticated calls.
    - Tier determination: 'free' (10 req/min) or 'premium' (100 req/min).
    - RFC-compliant rate limit response headers (X-RateLimit-Limit, X-RateLimit-Remaining).
    - Fail-open resilience: If Redis is unavailable, requests pass with a logged warning.
    - De-duplication: Flags request.state to prevent double-charging inside dependency handlers.
    """

    def __init__(
        self,
        app: Any,
        redis_client: Any = None,
        default_plan: str = "free",
    ) -> None:
        super().__init__(app)
        self._redis_client = redis_client
        self.default_plan = default_plan

    async def _get_redis(self, request: Request) -> Any:
        """Resolve Redis client from constructor, app state, or singleton."""
        if self._redis_client is not None:
            return self._redis_client
        if hasattr(request.app.state, "redis"):
            return request.app.state.redis
        return get_redis_client()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # 1. Skip exempt endpoints (health checks, API docs)
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # 2. Check if request has an Authorization header
        auth_header = request.headers.get("Authorization", "")
        plan = request.headers.get("X-Plan", self.default_plan).lower()
        if plan not in PLAN_LIMITS:
            plan = self.default_plan

        # For requests that will be authenticated and rate-limited by rate_limited_tenant dependency,
        # pass through to allow the dependency to resolve the exact tenant plan from the database.
        if auth_header.startswith("Bearer "):
            return await call_next(request)

        # 3. For unauthenticated requests, enforce IP-based rate limiting
        client_ip = request.client.host if request.client else "unknown_ip"
        client_id = f"ip_{client_ip}"
        limit = PLAN_LIMITS[plan]

        try:
            redis = await self._get_redis(request)
            current, effective_limit = await check_rate_limit(
                redis=redis,
                tenant_id=client_id,
                plan=plan,
            )
            request.state.rate_limit_checked = True

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(effective_limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, effective_limit - current))
            return response

        except RateLimitExceeded as exc:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "plan": exc.plan,
                    "limit": exc.limit,
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(exc.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        except Exception as exc:
            # Fail-open: Never drop traffic if cache has transient connectivity issues
            logger.warning(
                f"Rate limiter fail-open: Redis connection issue ({exc})",
                extra={"client_id": client_id},
            )
            return await call_next(request)
