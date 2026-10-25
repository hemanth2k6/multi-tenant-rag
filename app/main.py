"""Main FastAPI application entry point with lifespan and exception handlers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1 import api_v1_router, health_router
from app.core.config import settings
from app.core.dependencies import RateLimitHTTPException
from app.core.logging import get_logger
from app.core.redis import close_redis, get_redis_client
from app.db.session import engine
from app.middleware.rate_limit import RateLimitExceeded

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    env_name = "production" if not settings.DEBUG else "debug"
    logger.info("Starting Multi-Tenant RAG API", extra={"environment": env_name})

    # Warm up Redis client connection pool
    try:
        redis = get_redis_client()
        await redis.ping()
        logger.info("Redis connection initialized successfully")
    except Exception as exc:
        logger.warning(f"Initial Redis ping warning (will retry on requests): {exc}")

    yield

    logger.info("Shutting down Multi-Tenant RAG API")
    await close_redis()
    await engine.dispose()
    logger.info("Database and Redis connections closed")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    application = FastAPI(
        title="Multi-Tenant RAG API",
        description=(
            "Isolated multi-tenant Retrieval-Augmented Generation API "
            "powered by pgvector and Gemini."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Register custom exception handlers for rate limiting to match contract
    @application.exception_handler(RateLimitHTTPException)
    async def rate_limit_http_handler(
        request: Request,
        exc: RateLimitHTTPException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "plan": exc.plan,
                "limit": exc.limit,
            },
        )

    @application.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(
        request: Request,
        exc: RateLimitExceeded,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "plan": exc.plan,
                "limit": exc.limit,
            },
        )

    # Mount routers
    application.include_router(health_router)
    application.include_router(api_v1_router)

    return application


app = create_application()
