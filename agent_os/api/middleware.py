"""FastAPI middleware for request correlation and timing.

Adds:
- X-Request-ID header (correlation ID for tracing)
- Request duration logging
"""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ..logging_config import correlation_id_var, new_correlation_id

logger = logging.getLogger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Assigns a unique correlation ID to each request and logs request metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use incoming X-Request-ID if present, otherwise generate one
        incoming_id = request.headers.get("x-request-id", "")
        if incoming_id:
            correlation_id_var.set(incoming_id)
            cid = incoming_id
        else:
            cid = new_correlation_id()

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        # Attach correlation ID to response
        response.headers["X-Request-ID"] = cid

        # Suppress high-frequency health-check polling noise: skip logging
        # GET /api/orchestrator/status 304 responses unless the response was
        # unexpectedly slow (> 500 ms), which is worth knowing about regardless.
        _is_noisy_status_poll = (
            request.method == "GET"
            and request.url.path == "/api/orchestrator/status"
            and response.status_code == 304
            and duration_ms < 500
        )

        # Log request summary
        if not _is_noisy_status_poll:
            logger.info(
                "%s %s %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        return response
