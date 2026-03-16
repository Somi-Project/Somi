from __future__ import annotations

from typing import Dict, Tuple

_KEYWORDS: Dict[str, set[str]] = {
    "finance": {"price", "quote", "market", "stock", "shares", "bitcoin", "btc", "eth", "oil", "wti", "brent", "fx", "exchange rate", "crypto"},
    "weather": {"weather", "forecast", "temperature", "rain", "humidity", "wind", "storm", "climate"},
    "news": {"news", "headline", "headlines", "current events", "breaking", "press"},
    "sports": {"sports", "match", "game", "score", "fixture", "standings", "league", "tournament"},
    "software": {"software", "release", "version", "changelog", "patch", "github", "library", "framework"},
}


def classify_domain(text: str) -> Tuple[str, float]:
    tl = str(text or "").lower()
    scores = {d: 0 for d in _KEYWORDS}
    for domain, keys in _KEYWORDS.items():
        for k in keys:
            if k in tl:
                scores[domain] += 1
    best = max(scores, key=scores.get)
    top = scores[best]
    if top <= 0:
        return "general", 0.2
    total = sum(scores.values()) or 1
    return best, max(0.35, min(0.99, top / total))
