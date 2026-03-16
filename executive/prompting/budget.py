from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Deterministic rough token estimate (~4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)
