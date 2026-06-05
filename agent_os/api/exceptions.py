"""Custom API exception classes (Phase 12.3).

Typed exceptions that map to specific HTTP status codes. Registered as
exception handlers in app.py so routes can raise them instead of raw HTTPException.
"""
from __future__ import annotations


class PipelineConflictError(Exception):
    """409 Conflict — action cannot be performed in the current pipeline state."""

    def __init__(self, detail: str = "Pipeline state conflict"):
        self.detail = detail
        super().__init__(detail)


class InvalidStateError(Exception):
    """422 Unprocessable Entity — the request is valid but the state is invalid."""

    def __init__(self, detail: str = "Invalid pipeline state"):
        self.detail = detail
        super().__init__(detail)


class ValidationError(Exception):
    """400 Bad Request — request body or parameters failed validation."""

    def __init__(self, detail: str = "Validation error"):
        self.detail = detail
        super().__init__(detail)
