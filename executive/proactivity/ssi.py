from __future__ import annotations


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def compute_confidence(evidence_count: int, unknown_count: int) -> float:
    total = max(1, evidence_count + unknown_count)
    return max(0.2, min(1.0, evidence_count / total))


def compute_novelty(suppressed_recently: bool, active_recently: bool, quiet_hours: bool) -> float:
    n = 1.0
    if suppressed_recently:
        n *= 0.5
    if active_recently:
        n *= 0.85
    if quiet_hours:
        n *= 0.7
    return max(0.2, n)


def compute_ssi(weight: float, confidence: float, urgency: float, impact: float, novelty: float) -> int:
    raw = round(100 * weight * confidence * urgency * impact * novelty)
    return clamp(raw, 0, 100)
