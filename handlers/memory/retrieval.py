from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence

import numpy as np


def recency_score(ts_iso: str) -> float:
    try:
        dt = datetime.fromisoformat((ts_iso or "").replace("Z", ""))
        age_h = max(0.0, (datetime.utcnow() - dt).total_seconds() / 3600.0)
        return float(np.exp(-age_h / 72.0))
    except Exception:
        return 0.2


def type_boost(memory_type: str) -> float:
    mt = (memory_type or "").lower()
    if mt == "instructions":
        return 0.18
    if mt == "preferences":
        return 0.14
    if mt == "facts":
        return 0.1
    return 0.05


def rank_claims(
    query_vec: np.ndarray,
    candidates: Sequence[Dict[str, Any]],
    claim_embeddings: Dict[str, np.ndarray],
    min_score: float = 0.2,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    rows = []
    for c in candidates:
        cid = c.get("claim_id", "")
        emb = claim_embeddings.get(cid)
        if emb is None:
            sim = 0.0
        else:
            sim = float(np.dot(emb, query_vec))
        if sim < min_score:
            continue
        score = (
            0.58 * sim
            + 0.18 * type_boost(c.get("memory_type", ""))
            + 0.16 * recency_score(c.get("ts_updated", ""))
            + 0.08 * float(c.get("salience", 0.5))
        )
        row = dict(c)
        row["sim"] = sim
        row["rank_score"] = score
        rows.append(row)
    rows.sort(key=lambda x: x["rank_score"], reverse=True)
    return rows[:limit]
