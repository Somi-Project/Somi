from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def rrf_fuse(fts_results: List[Tuple[str, float]], vec_results: List[str], k: int = 60) -> List[str]:
    scores: Dict[str, float] = {}
    for rank, (iid, _) in enumerate(fts_results, start=1):
        scores[iid] = scores.get(iid, 0.0) + (1.0 / (k + rank))
    for rank, iid in enumerate(vec_results, start=1):
        scores[iid] = scores.get(iid, 0.0) + (1.0 / (k + rank))
    return [iid for iid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


def apply_filters_and_caps(items: List[Dict], caps_by_scope: Optional[Dict[str, int]] = None) -> List[Dict]:
    caps_by_scope = caps_by_scope or {}
    out: List[Dict] = []
    scope_counts: Dict[str, int] = {}
    now = datetime.now(timezone.utc)

    for it in items:
        status = str(it.get("status", "active"))
        if status in {"superseded", "suppressed", "expired"}:
            continue

        ex = str(it.get("expires_at") or "").strip()
        if ex:
            try:
                dt = datetime.fromisoformat(ex.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= now:
                    continue
            except Exception:
                pass

        scope = str(it.get("scope") or "conversation")
        cap = int(caps_by_scope.get(scope, 999))
        if scope_counts.get(scope, 0) >= cap:
            continue
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        out.append(it)
    return out


def rerank_items(items: List[Dict], query: str) -> List[Dict]:
    q_tokens = [t for t in query.lower().split() if len(t) > 2][:12]
    now = datetime.now(timezone.utc)

    def score(it: Dict) -> float:
        txt = f"{it.get('text','')} {it.get('content','')} {it.get('tags','')}".lower()
        overlap = sum(1 for t in q_tokens if t in txt)
        rel = overlap / max(1, len(q_tokens)) if q_tokens else 0.4

        recency = 0.3
        ts_raw = str(it.get("updated_at") or it.get("created_at") or it.get("ts") or "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
            recency = 1.0 / (1.0 + (age_days / 14.0))
        except Exception:
            pass

        conf = float(it.get("confidence", 0.6) or 0.6)
        return (0.6 * rel) + (0.25 * conf) + (0.15 * recency)

    return sorted(items, key=score, reverse=True)
