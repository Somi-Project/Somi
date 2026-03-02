from __future__ import annotations

import hashlib


def message_fingerprint(text: str) -> str:
    return hashlib.sha1((text or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def passes_quality_gate(card: dict) -> bool:
    claim = str(card.get("claim") or "").strip()
    so_what = str(card.get("why_it_matters") or "").strip()
    action = str(card.get("action") or "").strip()
    if not claim or not so_what or not action:
        return False
    sent = f"{claim}. {so_what}. {action}".strip()
    sentences = [x for x in sent.split(".") if x.strip()]
    return len(sentences) <= 3 and len(sent) <= 420


def is_duplicate(text: str, fingerprints: set[str]) -> bool:
    fp = message_fingerprint(text)
    if fp in fingerprints:
        return True
    fingerprints.add(fp)
    return False
