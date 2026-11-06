"""FastAPI dependencies for tenant authentication, vector store injection, and rate limiting."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger, tenant_id_context_var
from app.core.redis import RedisClient, get_redis
from app.core.security import hash_api_key
from app.db.models.api_key import ApiKey
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.middleware.rate_limit import RateLimitExceeded, check_rate_limit
from app.services.vector_store.base import VectorStore
from app.services.vector_store.pgvector_client import PgVectorClient
from app.services.vector_store.pinecone_client import PineconeClient

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

    Security Invariants:
    1. Tenant identity is NEVER accepted from request body, headers, or query parameters.
    2. The raw key is hashed using constant-time SHA-256 before database lookup.
    3. Revoked keys are rejected immediately.
    4. Current tenant_id is bound to ContextVar for structured log tracing.
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


# Aliases for user-centric nomenclature
get_current_user = get_current_tenant
authenticate_api_key = get_current_tenant


async def rate_limited_tenant(
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    redis: RedisClient = Depends(get_redis),
) -> Tenant:
    """Enforce distributed sliding-window rate limit after tenant authentication.

    Free plan: 10 requests / 60s
    Premium plan: 100 requests / 60s
    """
    # Prevent duplicate rate-limit evaluation if already checked in middleware
    if getattr(request.state, "rate_limit_checked", False):
        return tenant

    try:
        await check_rate_limit(redis, str(tenant.id), tenant.plan)
        request.state.rate_limit_checked = True
    except RateLimitExceeded as exc:
        raise RateLimitHTTPException(plan=exc.plan, limit=exc.limit) from exc

    return tenant


async def get_vector_store(
    db: AsyncSession = Depends(get_db),
) -> VectorStore:
    """Inject configured vector store backend (PgVector or Pinecone)."""
    if settings.VECTOR_BACKEND == "pinecone" and settings.PINECONE_API_KEY:
        return PineconeClient(
            api_key=settings.PINECONE_API_KEY,
            index_name=settings.PINECONE_INDEX_NAME,
        )
    return PgVectorClient(session=db)
