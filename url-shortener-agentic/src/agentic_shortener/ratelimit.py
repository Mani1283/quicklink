"""Bounded, process-local sliding-window rate limiter."""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int = 60, window_seconds: int = 60, max_keys: int = 10000):
        if limit < 1 or window_seconds < 1 or max_keys < 1:
            raise ValueError("rate limit, window, and max_keys must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._requests = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        instant = time.monotonic() if now is None else now
        cutoff = instant - self.window_seconds
        with self._lock:
            self._evict_idle(cutoff)
            events = self._requests[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - instant + 0.999))
                return False, retry_after
            events.append(instant)
            return True, 0

    def _evict_idle(self, cutoff: float) -> None:
        if len(self._requests) < self.max_keys:
            return
        idle = [key for key, events in self._requests.items() if not events or events[-1] <= cutoff]
        for key in idle:
            self._requests.pop(key, None)

        # If all buckets are active, forget the oldest bucket to keep memory bounded.
        while len(self._requests) >= self.max_keys:
            oldest = min(self._requests, key=lambda key: self._requests[key][-1] if self._requests[key] else 0)
            self._requests.pop(oldest, None)
