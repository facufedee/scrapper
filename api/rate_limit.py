"""Per-client sliding-window rate limiting.

State is in process memory: it is correct for a single API process. Running several
workers or instances requires a shared store (e.g. Redis) instead.
"""

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60, clock: Callable[[], float] = time.monotonic):
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    def hit(self, key: str) -> RateLimitDecision:
        with self._lock:
            now = self._clock()
            hits = self._hits[key]
            while hits and hits[0] <= now - self._window:
                hits.popleft()

            if len(hits) < self._limit:
                hits.append(now)
                return RateLimitDecision(True, self._limit, self._limit - len(hits), 0)

            retry_after = max(1, math.ceil(hits[0] + self._window - now))
            return RateLimitDecision(False, self._limit, 0, retry_after)
