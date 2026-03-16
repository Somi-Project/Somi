from __future__ import annotations

from executive.life_modeling.artifact_store import ArtifactStore


class ProactivityMetrics:
    KEYS = ("sent_notify_count", "sent_brief_count", "logged_count", "dismissed_count", "engaged_count", "snoozed_count")

    def __init__(self, store: ArtifactStore):
        self.store = store
        self.counts = {k: 0 for k in self.KEYS}

    def inc(self, key: str, n: int = 1):
        if key in self.counts:
            self.counts[key] += n

    def flush(self) -> dict:
        row = {"type": "proactivity_metrics_v1", "no_autonomy": True, **self.counts}
        return self.store.write("proactivity_metrics_v1", row)
