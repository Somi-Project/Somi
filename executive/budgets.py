from __future__ import annotations

from runtime.ratelimit import SlidingRateLimit


class ExecutiveBudgets:
    def __init__(self):
        self.intent_limit = SlidingRateLimit(10, 3600)

    def allow_intent(self) -> None:
        self.intent_limit.hit()
