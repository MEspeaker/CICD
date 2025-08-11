import os
import time
import threading
from collections import deque
from typing import Deque, Optional


class SlidingWindowRateLimiter:
    def __init__(self, per_second: int, per_two_minutes: int) -> None:
        self.per_second = per_second
        self.per_two_minutes = per_two_minutes
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._win1s: Deque[float] = deque()
        self._win120s: Deque[float] = deque()

    def _purge(self, now: float) -> None:
        one_sec_ago = now - 1.0
        two_min_ago = now - 120.0
        while self._win1s and self._win1s[0] <= one_sec_ago:
            self._win1s.popleft()
        while self._win120s and self._win120s[0] <= two_min_ago:
            self._win120s.popleft()

    def acquire(self, max_wait_seconds: Optional[float] = None) -> None:
        start_wait = time.monotonic()
        with self._cond:
            while True:
                now = time.monotonic()
                self._purge(now)
                if len(self._win1s) < self.per_second and len(self._win120s) < self.per_two_minutes:
                    # grant
                    self._win1s.append(now)
                    self._win120s.append(now)
                    return
                # compute sleep needed until next slot opens
                wait1 = float("inf")
                if self._win1s:
                    wait1 = max(0.0, 1.0 - (now - self._win1s[0]))
                wait2 = float("inf")
                if self._win120s:
                    wait2 = max(0.0, 120.0 - (now - self._win120s[0]))
                sleep_for = min(wait1, wait2)
                if max_wait_seconds is not None:
                    elapsed = now - start_wait
                    if elapsed + sleep_for > max_wait_seconds:
                        # final wait capped
                        sleep_for = max(0.0, max_wait_seconds - elapsed)
                if sleep_for <= 0.0:
                    # tiny yield
                    sleep_for = 0.001
                self._cond.wait(timeout=sleep_for)


_global_limiter: Optional[SlidingWindowRateLimiter] = None


def get_global_limiter() -> SlidingWindowRateLimiter:
    global _global_limiter
    if _global_limiter is None:
        per_sec = int(os.getenv("RIOT_LIMIT_PER_SEC", "19"))
        per_2min = int(os.getenv("RIOT_LIMIT_PER_2MIN", "99"))
        _global_limiter = SlidingWindowRateLimiter(per_sec, per_2min)
    return _global_limiter
