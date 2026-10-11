"""Per-key sliding-window rate limiter (thread-safe)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Allows at most `limit` events per `window` seconds for each key."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float) -> bool:
        """Record an event and return True if it is within the limit, else False."""
        if limit <= 0:
            return False
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True
