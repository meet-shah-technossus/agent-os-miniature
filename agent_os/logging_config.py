"""Structured logging configuration for Agent OS.

Supports two output formats controlled by the ``LOG_FORMAT`` env var:
- ``json``  — machine-parseable JSON lines (production default)
- ``text``  — human-readable colored output (development)

Log level is controlled by ``LOG_LEVEL`` env var (default: ``INFO``).

Usage::

    from agent_os.logging_config import configure_logging
    configure_logging()  # call once at process startup
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ── Correlation ID ───────────────────────────────────────────────────────────

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the current request/pipeline correlation ID (or empty string)."""
    return correlation_id_var.get()


def new_correlation_id() -> str:
    """Generate and set a new correlation ID, returning it."""
    cid = uuid.uuid4().hex[:12]
    correlation_id_var.set(cid)
    return cid


# ── JSON Formatter ───────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add correlation ID if present
        cid = correlation_id_var.get()
        if cid:
            log_entry["correlation_id"] = cid

        # Add extra fields bound via `extra=`
        for key in ("duration_ms", "step", "status_code", "method", "path",
                    "iteration", "pipeline_status", "agent"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        # Add exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


# ── Text Formatter ───────────────────────────────────────────────────────────

class TextFormatter(logging.Formatter):
    """Human-readable colored formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        cid = correlation_id_var.get()
        cid_str = f" [{cid}]" if cid else ""
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%H:%M:%S.%f"
        )[:-3]
        msg = record.getMessage()
        base = f"{color}{timestamp} {record.levelname:<8}{self.RESET}{cid_str} {record.name}: {msg}"
        if record.exc_info and record.exc_info[0] is not None:
            base += "\n" + self.formatException(record.exc_info)
        return base


# ── Timer utility ────────────────────────────────────────────────────────────

class StepTimer:
    """Context manager that measures elapsed time for a pipeline step.

    Usage::

        with StepTimer("code_generation") as timer:
            do_work()
        logger.info("Step done", extra={"duration_ms": timer.duration_ms, "step": timer.step})
    """

    def __init__(self, step: str) -> None:
        self.step = step
        self.duration_ms: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> StepTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.duration_ms = round((time.perf_counter() - self._start) * 1000, 1)


# ── Configuration entrypoint ─────────────────────────────────────────────────

def configure_logging() -> None:
    """Configure the root logger based on environment variables.

    Environment variables:
        LOG_FORMAT: ``json`` (default) or ``text``
        LOG_LEVEL:  Any standard level name (default: ``INFO``)
    """
    log_format = os.environ.get("LOG_FORMAT", "text").lower()
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Validate level
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    # Remove existing handlers from root logger
    root = logging.getLogger()
    root.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)

    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Suppress noisy third-party loggers
    for noisy in ("uvicorn.access", "httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
