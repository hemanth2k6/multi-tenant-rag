"""Integration tests for health probes."""

from __future__ import annotations

import httpx
import pytest

from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_health_liveness(async_client: httpx.AsyncClient) -> None:
    """Verify /health returns 200 OK without dependencies."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_readiness_healthy(async_client: httpx.AsyncClient) -> None:
    """Verify /health/ready returns 200 when DB and Redis are operational."""
    response = await async_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["redis"] == "connected"


@pytest.mark.asyncio
async def test_health_readiness_db_failure(async_client: httpx.AsyncClient) -> None:
    """Verify /health/ready returns 503 when Database query fails."""
    from collections.abc import AsyncGenerator
    from typing import Any

    class FailingDbSession:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("DB connection refused")

    async def override_failing_db() -> AsyncGenerator[FailingDbSession, None]:
        yield FailingDbSession()

    app.dependency_overrides[get_db] = override_failing_db
    try:
        response = await async_client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unavailable"
    finally:
        del app.dependency_overrides[get_db]
