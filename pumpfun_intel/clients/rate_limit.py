"""Simple token-bucket rate limiter with retry helpers."""

from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


class RateLimitError(Exception):
    """Raised when an upstream API returns HTTP 429."""


class TransientAPIError(Exception):
    """Raised for retryable 5xx / network failures."""


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float | None = None) -> None:
        self.rate = max(rate_per_sec, 0.1)
        self.capacity = capacity if capacity is not None else max(self.rate, 1.0)
        self.tokens = self.capacity
        self.updated_at = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                need = tokens - self.tokens
                wait_s = need / self.rate
            time.sleep(wait_s)


def with_retries(fn: Callable[[], T]) -> T:
    """Run callable with exponential backoff on transient / rate-limit errors."""

    @retry(
        reraise=True,
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=20),
        retry=retry_if_exception_type((RateLimitError, TransientAPIError)),
    )
    def _inner() -> T:
        return fn()

    return _inner()
