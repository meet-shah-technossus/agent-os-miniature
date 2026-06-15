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

        # ── Log-noise reduction for high-frequency GET polling endpoints ──────
        # These paths are polled every ~3 s by the frontend and carry no signal
        # during normal operation. Rules (applied in priority order):
        #
        #   1. Errors (status >= 400)         → always INFO
        #   2. Slow responses (>= 500 ms)     → always INFO
        #   3. status == 304 on status path   → suppress entirely (zero info)
        #   4. GET poll path + status 200     → DEBUG only
        #   5. Everything else                → INFO (default)
        #
        _POLL_PATHS = {
            "/api/orchestrator/status",
            "/api/orchestrator/current-prompt",
            "/api/orchestrator/current-review",
            "/api/orchestrator/story-queue",
        }
        _path = request.url.path
        _status = response.status_code
        _is_error = _status >= 400
        _is_slow = duration_ms >= 500

        if _is_error or _is_slow:
            # Always surface errors and slow responses at INFO regardless of path
            log_fn = logger.info
        elif (
            request.method == "GET"
            and _path == "/api/orchestrator/status"
            and _status == 304
        ):
            # 304 on the status poll: zero information content — skip entirely
            return response
        elif request.method == "GET" and _path in _POLL_PATHS and _status == 200:
            # Normal poll response: move to DEBUG to keep INFO stream clean
            log_fn = logger.debug
        else:
            log_fn = logger.info

        log_fn(
            "%s %s %d (%.1fms)",
            request.method,
            _path,
            _status,
            duration_ms,
            extra={
                "method": request.method,
                "path": _path,
                "status_code": _status,
                "duration_ms": duration_ms,
            },
        )

        return response
