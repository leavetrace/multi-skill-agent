"""Async sliding-window rate limiter for free-tier RPM quotas.

A sliding window (not a token bucket) matches how providers count "requests per minute",
so we never burst past the quota at a window edge. Clock and sleep are injectable so tests
run instantly and deterministically.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

__all__ = ["SlidingWindowRateLimiter"]


class SlidingWindowRateLimiter:
    """Allow at most `max_requests` acquisitions per `window_s` seconds; `max_requests <= 0`
    disables limiting. Waiters are served in FIFO order (the lock is held while waiting)."""

    def __init__(
        self,
        max_requests: int,
        window_s: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.max_requests = max_requests
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.max_requests <= 0:
            return
        async with self._lock:
            while True:
                now = self._clock()
                while self._sent and self._sent[0] <= now - self.window_s:
                    self._sent.popleft()
                if len(self._sent) < self.max_requests:
                    self._sent.append(now)
                    return
                await self._sleep(self._sent[0] + self.window_s - now)
