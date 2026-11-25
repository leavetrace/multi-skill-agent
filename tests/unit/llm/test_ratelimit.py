from __future__ import annotations

import asyncio

from skillagent.llm.ratelimit import SlidingWindowRateLimiter


class FakeClock:
    """Virtual time: `sleep` advances `now` instantly, so window tests never sleep for real."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_allows_up_to_limit_without_waiting() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(3, 60, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        await limiter.acquire()
    assert clock.sleeps == []


async def test_waits_until_oldest_request_leaves_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(2, 60, clock=clock, sleep=clock.sleep)
    await limiter.acquire()  # t=1000
    clock.now += 10
    await limiter.acquire()  # t=1010
    await limiter.acquire()  # must wait until t=1060
    assert clock.sleeps == [50]
    assert clock.now == 1060


async def test_never_exceeds_rate_in_any_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(5, 60, clock=clock, sleep=clock.sleep)
    stamps = []
    for _ in range(23):
        await limiter.acquire()
        stamps.append(clock.now)
    for start in stamps:
        assert sum(start <= t < start + 60 for t in stamps) <= 5


async def test_concurrent_waiters_are_serialized() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(1, 60, clock=clock, sleep=clock.sleep)
    await asyncio.gather(*(limiter.acquire() for _ in range(3)))
    assert clock.now == 1120  # 2 extra requests → 2 full windows


async def test_zero_disables_limiter() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(0, 60, clock=clock, sleep=clock.sleep)
    for _ in range(100):
        await limiter.acquire()
    assert clock.sleeps == []
