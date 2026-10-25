"""Distributed rate limiting tests: sliding-window Lua enforcement."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_free_tier_sliding_window_rate_limiting(
    async_client: httpx.AsyncClient,
    test_headers: dict[str, str],
) -> None:
    """Verify free tier allows exactly 10 requests / 60s and blocks the 11th with 429."""
    # First 10 requests must succeed with 200 OK
    for i in range(10):
        response = await async_client.get("/api/v1/documents", headers=test_headers)
        assert (
            response.status_code == 200
        ), f"Request {i + 1} expected 200, got {response.status_code}: {response.text}"

    # 11th request within same window must be rejected with 429 Too Many Requests
    blocked_response = await async_client.get("/api/v1/documents", headers=test_headers)
    assert blocked_response.status_code == 429

    error_data = blocked_response.json()
    assert error_data == {
        "error": "rate_limit_exceeded",
        "plan": "free",
        "limit": 10,
    }
