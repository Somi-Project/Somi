from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .validators import message_fingerprint


@dataclass
class AlertRecord:
    topic: str
    severity: str
    text: str


class AlertsLane:
    def __init__(self, suppression_minutes: int = 90):
        self.suppression_minutes = max(1, int(suppression_minutes))
        self.seen: dict[str, tuple[str, datetime]] = {}

    def should_emit(self, alert: AlertRecord, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        fp = message_fingerprint(f"{alert.topic}|{alert.severity}|{alert.text}")
        old = self.seen.get(alert.topic)
        if old:
            prev_fp, expires_at = old
            if prev_fp == fp and current <= expires_at:
                return False
        self.seen[alert.topic] = (fp, current + timedelta(minutes=self.suppression_minutes))
        return True
