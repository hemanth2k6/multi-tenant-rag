"""Main FastAPI application entry point with lifespan, middlewares, and exception handlers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1 import api_v1_router, health_router
from app.core.config import settings
from app.core.dependencies import RateLimitHTTPException
from app.core.exceptions import (
    AppException,
    CorruptedPDFError,
    DuplicateDocumentError,
    EmbeddingServiceError,
    EmbeddingTimeoutError,
    EmptyDocumentError,
)
from app.core.logging import get_logger, setup_logging
from app.core.redis import close_redis, get_redis_client
from app.db.session import engine
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.rate_limit import RateLimitExceeded, RateLimitMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    setup_logging(settings.LOG_LEVEL)
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
            "Production-ready, isolated multi-tenant Retrieval-Augmented Generation API "
            "powered by pgvector and Gemini with distributed rate limiting."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 1. Mount Middlewares
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(RateLimitMiddleware)

    # 2. Register Rate Limit Exception Handlers
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
            headers={"Retry-After": "60"},
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
            headers={"Retry-After": "60"},
        )

    # 3. Register Domain Exception Handlers
    @application.exception_handler(DuplicateDocumentError)
    async def duplicate_doc_handler(request: Request, exc: DuplicateDocumentError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": "duplicate_document", "detail": exc.message},
        )

    @application.exception_handler(CorruptedPDFError)
    async def corrupted_pdf_handler(request: Request, exc: CorruptedPDFError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "corrupted_pdf", "detail": exc.message},
        )

    @application.exception_handler(EmptyDocumentError)
    async def empty_doc_handler(request: Request, exc: EmptyDocumentError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "empty_document", "detail": exc.message},
        )

    @application.exception_handler(EmbeddingTimeoutError)
    async def embedding_timeout_handler(request: Request, exc: EmbeddingTimeoutError) -> JSONResponse:
        return JSONResponse(
            status_code=504,
            content={"error": "embedding_timeout", "detail": exc.message},
        )

    @application.exception_handler(EmbeddingServiceError)
    async def embedding_service_handler(request: Request, exc: EmbeddingServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": "embedding_service_error", "detail": exc.message},
        )

    @application.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "detail": exc.message},
        )

    # 4. Mount API Routers
    application.include_router(health_router)
    application.include_router(api_v1_router)

    return application


app = create_application()
