from __future__ import annotations

from datetime import datetime, timezone
import re
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
    seen_keys = set()

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

        # De-dup same memory slot/value pairs to reduce repeated context noise.
        dedupe_key = str(it.get("slot_key") or "").strip().lower()
        if not dedupe_key:
            dedupe_key = f"{str(it.get('mkey') or '').strip().lower()}::{str(it.get('value') or '').strip().lower()}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        scope = str(it.get("scope") or "conversation")
        cap = int(caps_by_scope.get(scope, 999))
        if scope_counts.get(scope, 0) >= cap:
            continue
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        out.append(it)
    return out


def _tokens(text: str, *, max_items: int = 18) -> List[str]:
    out = []
    for tok in re.findall(r"[a-z0-9_\-]{3,}", str(text or "").lower()):
        if tok in out:
            continue
        out.append(tok)
        if len(out) >= max_items:
            break
    return out


def rerank_items(items: List[Dict], query: str, *, thread_hint: str = "") -> List[Dict]:
    q_tokens = _tokens(query, max_items=16)
    th_tokens = _tokens(thread_hint, max_items=16)
    now = datetime.now(timezone.utc)

    def score(it: Dict) -> float:
        txt = f"{it.get('text','')} {it.get('tags','')} {it.get('value','')}".lower()
        overlap = sum(1 for t in q_tokens if t in txt)
        rel = overlap / max(1, len(q_tokens)) if q_tokens else 0.45

        thread_overlap = sum(1 for t in th_tokens if t in txt)
        thread_rel = thread_overlap / max(1, len(th_tokens)) if th_tokens else 0.0

        recency = 0.35
        age_days = 30.0
        ts_raw = str(it.get("updated_at") or it.get("created_at") or "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
            recency = 1.0 / (1.0 + (age_days / 10.0))
        except Exception:
            pass

        stale_decay = 1.0
        if age_days > 120:
            stale_decay = 0.55
        elif age_days > 60:
            stale_decay = 0.72
        elif age_days > 30:
            stale_decay = 0.86

        conf = float(it.get("confidence", 0.6) or 0.6)
        imp = float(it.get("importance", 0.5) or 0.5)

        base = (0.45 * rel) + (0.18 * conf) + (0.15 * recency) + (0.12 * imp) + (0.10 * thread_rel)
        return base * stale_decay

    return sorted(items, key=score, reverse=True)
