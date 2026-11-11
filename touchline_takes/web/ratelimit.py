"""A small in-process sliding-window rate limiter (no external service needed).

Limits are per worker process: with gunicorn ``-w 2`` the effective limit doubles.
That is fine for slowing abuse of ``/ask`` and admin password guessing on a small
site; put a CDN/WAF limit in front for anything bigger.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_limit(spec: str) -> tuple[int, int]:
    """``"10/minute"`` -> ``(10, 60)``."""
    count, _, unit = spec.partition("/")
    unit = unit.strip().rstrip("s") or "minute"
    if unit not in UNITS or not count.strip().isdigit():
        raise ValueError(f"bad rate limit {spec!r}; use e.g. '10/minute'")
    return int(count), UNITS[unit]


class RateLimiter:
    """Allows ``limit`` hits per ``window`` seconds per key."""

    def __init__(self, spec: str, clock=time.monotonic) -> None:
        self.limit, self.window = parse_limit(spec)
        self.clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque:
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        """True if ``key`` has used up its allowance (does not record a hit)."""
        with self._lock:
            return len(self._trim(key, self.clock())) >= self.limit

    def hit(self, key: str) -> bool:
        """Record a hit; returns False if it was over the limit."""
        with self._lock:
            now = self.clock()
            hits = self._trim(key, now)
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # forget idle clients
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return True
