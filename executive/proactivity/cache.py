from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Entry:
    value: object
    expires_at: float


class WebsearchCache:
    TTL = {
        "weather_routine": 4 * 3600,
        "weather_alert": 45 * 60,
        "news_routine": 5 * 3600,
        "news_breaking": 45 * 60,
        "markets": 30 * 60,
    }

    def __init__(self):
        self._data: dict[str, _Entry] = {}

    def get(self, key: str):
        item = self._data.get(key)
        if not item:
            return None
        if time.time() > item.expires_at:
            self._data.pop(key, None)
            return None
        return item.value

    def set(self, lane: str, key: str, value: object):
        ttl = int(self.TTL.get(lane, 3600))
        self._data[key] = _Entry(value=value, expires_at=time.time() + ttl)
