"""FastAPI dependencies for tenant authentication and rate limiting."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger, tenant_id_context_var
from app.core.redis import RedisClient, get_redis
from app.core.security import hash_api_key
from app.db.models.api_key import ApiKey
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.middleware.rate_limit import RateLimitExceeded, check_rate_limit

logger = get_logger(__name__)

security_scheme = HTTPBearer(auto_error=False)


class RateLimitHTTPException(HTTPException):
    """Custom 429 exception preserving plan and limit metadata."""

    def __init__(self, plan: str, limit: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limit_exceeded", "plan": plan, "limit": limit},
        )
        self.plan = plan
        self.limit = limit


async def get_current_tenant(
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Resolve and authenticate a tenant solely from the Bearer API key.

    Never accepts tenant identity from request body or query parameters.
    Hashes the raw key with SHA-256 and queries the database.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = credentials.credentials.strip()
    key_hash = hash_api_key(raw_key)

    stmt = (
        select(ApiKey)
        .options(selectinload(ApiKey.tenant))
        .where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked.is_(False),
        )
    )
    result = await db.execute(stmt)
    api_key_record = result.scalar_one_or_none()

    if api_key_record is None or api_key_record.tenant is None:
        logger.warning(
            "Authentication failed: invalid or revoked API key",
            extra={"key_prefix": raw_key[:8] if len(raw_key) >= 8 else "invalid"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant = api_key_record.tenant

    # Bind tenant_id to context variable for structured logging
    tenant_id_context_var.set(str(tenant.id))

    return tenant


async def rate_limited_tenant(
    tenant: Tenant = Depends(get_current_tenant),
    redis: RedisClient = Depends(get_redis),
) -> Tenant:
    """Enforce distributed sliding-window rate limit after tenant authentication.

    Free plan: 10 requests / 60s
    Premium plan: 100 requests / 60s
    """
    try:
        await check_rate_limit(redis, str(tenant.id), tenant.plan)
    except RateLimitExceeded as exc:
        raise RateLimitHTTPException(plan=exc.plan, limit=exc.limit) from exc

    return tenant
