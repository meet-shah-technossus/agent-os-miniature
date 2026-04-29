"""Retry with exponential backoff — configurable retry utility for Agent OS."""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"All {attempts} attempts exhausted. Last error: {last_error}")


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 2,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    retryable_errors: tuple[type[Exception], ...] = (Exception,),
    label: str = "operation",
) -> T:
    """Execute *fn* with exponential backoff on failure.

    Args:
        fn: Zero-arg callable to attempt.
        max_retries: Maximum number of retries (0 = no retries, try once).
        backoff_base: Base delay in seconds (doubles each retry).
        backoff_max: Maximum delay cap in seconds.
        retryable_errors: Exception types that trigger a retry.
        label: Human-readable label for log messages.

    Returns:
        The return value of *fn* on success.

    Raises:
        RetryExhaustedError: When all attempts fail.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):
        try:
            return fn()
        except retryable_errors as exc:
            last_error = exc
            if attempt > max_retries:
                break
            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
            logger.warning(
                "%s attempt %d/%d failed (%s). Retrying in %.1fs...",
                label, attempt, max_retries + 1, exc, delay,
            )
            time.sleep(delay)

    raise RetryExhaustedError(max_retries + 1, last_error)  # type: ignore[arg-type]
