"""Retry utilities with exponential backoff and jitter.

Usage::

    from agent_os.utils.retry import retry_with_backoff

    result = retry_with_backoff(
        fn=lambda: call_api(),
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        on_retry=lambda attempt, exc: logger.warning("Retry %d: %s", attempt, exc),
    )
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


def compute_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 30.0) -> float:
    """Compute delay with exponential backoff + jitter.

    Args:
        attempt: Zero-based attempt number (0 = first retry).
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.

    Returns:
        Delay in seconds with added jitter.
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> T:
    """Execute ``fn()`` with retries and exponential backoff.

    Args:
        fn: Zero-argument callable to execute.
        max_retries: Maximum number of retries (total attempts = max_retries + 1).
        base_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff cap in seconds.
        retryable_exceptions: Tuple of exception types that trigger a retry.
        on_retry: Optional callback invoked before each retry sleep.

    Returns:
        The return value of ``fn()`` on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            if on_retry:
                on_retry(attempt + 1, exc)
            delay = compute_backoff(attempt, base_delay, max_delay)
            time.sleep(delay)
    # Should never reach here, but satisfies type checker
    raise last_exc  # type: ignore[misc]
