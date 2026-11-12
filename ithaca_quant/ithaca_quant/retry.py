"""Bounded retries for unreliable public market-data services.

Each operation is tried once, with at most 2 more attempts after failures.
Requests denied for authorization or rate limits should not be retried.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar
from .config import MAX_RETRIES

T = TypeVar("T")


class EmptyResponseError(ValueError):
    """A provider returned no usable data."""


def retry_call(
    operation: Callable[[], T], *,
    usable: Callable[[T], bool] | None = None,
    retryable: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    pause_seconds: float = 0.5,
) -> T:
    """Run 1 + MAX_RETRIES attempts; never loop indefinitely."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            value = operation()
            if usable is not None and not usable(value):
                raise EmptyResponseError("Provider returned no usable data")
            return value
        except Exception as exc:
            if attempt >= MAX_RETRIES or (retryable is not None and not retryable(exc)):
                raise
            sleep(pause_seconds * (attempt + 1))
    raise AssertionError("unreachable")
