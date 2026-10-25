"""Authentication tests: API key validation and tenant resolution."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import InMemorySession


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify missing Authorization header produces 401 Unauthorized."""
    response = await async_client.get("/api/v1/documents")
    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(
    async_client: httpx.AsyncClient,
    in_memory_db: InMemorySession,
) -> None:
    """Verify invalid API key produces 401 Unauthorized."""
    # Empty out api_keys in DB to simulate non-matching key hash
    in_memory_db.api_keys.clear()

    headers = {"Authorization": "Bearer rag_completely_bogus_key_xyz"}
    response = await async_client.get("/api/v1/documents", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or revoked API key"


@pytest.mark.asyncio
async def test_valid_api_key_accepted(
    async_client: httpx.AsyncClient,
    test_headers: dict[str, str],
) -> None:
    """Verify valid Bearer token resolves tenant and yields 200 OK."""
    response = await async_client.get("/api/v1/documents", headers=test_headers)
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "total" in data
