"""Correlation ID middleware for distributed request tracing and context binding."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_context_var


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns or preserves X-Request-ID for every incoming request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        header_request_id = request.headers.get("X-Request-ID")
        request_id = header_request_id.strip() if header_request_id else f"req_{uuid.uuid4().hex[:16]}"

        token = request_id_context_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context_var.reset(token)

