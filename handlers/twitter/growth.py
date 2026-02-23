def persona_fit_score(text: str, include, avoid) -> float:
    source = (text or "").lower()
    if not source:
        return 0.0
    include_hits = sum(1 for t in include if t.lower() in source)
    avoid_hits = sum(1 for t in avoid if t.lower() in source)
    score = min(1.0, include_hits / max(1, len(include))) - (0.4 * avoid_hits)
    return max(0.0, min(1.0, score))
