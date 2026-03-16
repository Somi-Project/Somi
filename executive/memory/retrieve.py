from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List


def not_expired(item: Dict) -> bool:
    ex = str(item.get("expires_at") or "")
    if not ex:
        return True
    try:
        dt = datetime.fromisoformat(ex.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc)
    except Exception:
        return True


def rrf_merge(fts_ids: List[str], vec_ids: List[str], k: int = 60) -> List[str]:
    scores: Dict[str, float] = {}
    for rank, iid in enumerate(fts_ids, start=1):
        scores[iid] = scores.get(iid, 0.0) + (1.0 / (k + rank))
    for rank, iid in enumerate(vec_ids, start=1):
        scores[iid] = scores.get(iid, 0.0) + (1.0 / (k + rank))
    return [iid for iid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]
