"""API v1 router configuration."""

from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.query import router as query_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(documents_router)
api_v1_router.include_router(query_router)

__all__ = ["api_v1_router", "health_router"]
