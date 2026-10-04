"""Minimal in-memory sliding-window rate limiter, keyed by client address.

Good enough for a single-process deployment. Behind multiple workers or a proxy, swap for a
shared store (e.g. Redis) and trust the proxy's forwarded address instead.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:
                self._evict_idle(now)
            return True

    def _evict_idle(self, now: float) -> None:
        idle = [k for k, h in self._hits.items() if not h or now - h[-1] >= self._window]
        for key in idle:
            del self._hits[key]
