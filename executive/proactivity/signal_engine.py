from __future__ import annotations

from collections import defaultdict

from .ssi import compute_confidence, compute_novelty, compute_ssi

IMPACT_MAP = {"low": 0.5, "moderate": 0.8, "high": 1.0}
WEIGHTS = {"weather": 0.8, "news": 0.7, "markets": 0.75, "tasks": 0.8, "strategic_signals": 0.9, "alerts": 1.0}


class ProactivitySignalEngine:
    def __init__(self):
        self.escalation: dict[tuple[str, str], int] = {}

    def score(self, signal: dict) -> dict:
        weight = WEIGHTS.get(str(signal.get("topic") or "strategic_signals"), 0.7)
        conf = compute_confidence(int(signal.get("evidence_count") or 0), int(signal.get("unknown_count") or 0))
        urg = float(signal.get("urgency") or 0.7)
        impact = IMPACT_MAP.get(str(signal.get("impact") or "moderate"), 0.8)
        novelty = compute_novelty(bool(signal.get("suppressed_recently")), bool(signal.get("active_recently")), bool(signal.get("quiet_hours")))
        signal["ssi"] = compute_ssi(weight, conf, urg, impact, novelty)
        return signal

    def group(self, signals: list[dict]) -> list[list[dict]]:
        buckets = defaultdict(list)
        for s in signals:
            key = s.get("project_id") or s.get("goal_id") or s.get("signal_type") or s.get("topic")
            buckets[str(key)].append(s)
        return [v[:2] for v in buckets.values()]

    def update_escalation(self, signal_type: str, entity_id: str, persistent_days: int, progressed: bool, dismissed: bool) -> int:
        key = (signal_type, entity_id)
        if progressed or dismissed:
            self.escalation[key] = 0
            return 0
        stage = self.escalation.get(key, 0)
        if persistent_days >= 2:
            stage = min(3, stage + 1)
        self.escalation[key] = stage
        return stage

    def stagnation(self, impact: str, open_tasks: int, days_without_progress: int) -> bool:
        if open_tasks <= 0:
            return False
        if impact == "high":
            return days_without_progress >= 2
        if impact == "moderate":
            return days_without_progress >= 4
        return False


def has_progress_event(events: list[dict]) -> bool:
    for e in events:
        typ = str(e.get("type") or "")
        if typ in {"task_status_changed", "artifact_linked", "open_task_count_decreased", "risk_score_decreased"}:
            return True
    return False
