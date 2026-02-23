from __future__ import annotations

import time
from collections import deque

from runtime.errors import RateLimitError


class SlidingRateLimit:
    def __init__(self, max_events: int, window_s: int) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self.events = deque()

    def hit(self) -> None:
        now = time.time()
        while self.events and now - self.events[0] > self.window_s:
            self.events.popleft()
        if len(self.events) >= self.max_events:
            raise RateLimitError("Rate limit exceeded")
        self.events.append(now)
