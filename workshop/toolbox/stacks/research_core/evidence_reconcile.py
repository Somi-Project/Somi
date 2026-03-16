from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha1
from typing import Dict, List, Tuple

from workshop.toolbox.stacks.research_core.evidence_claims import ClaimCandidate
from workshop.toolbox.stacks.research_core.evidence_schema import Claim, EvidenceItem

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 2}


def _group_key(text: str) -> str:
    toks = sorted(_norm_tokens(text) - {"study", "result", "data", "patients", "patient", "shows"})
    return " ".join(toks[:8])


def _has_opposition(text: str) -> int:
    tl = (text or "").lower()
    pos = any(k in tl for k in ("increase", "improve", "higher", "benefit", "reduce"))
    neg = any(k in tl for k in ("decrease", "worse", "lower", "harm", "no benefit"))
    if pos and not neg:
        return 1
    if neg and not pos:
        return -1
    return 0


def reconcile_claims(
    candidates: List[ClaimCandidate],
    *,
    items_by_id: Dict[str, EvidenceItem],
    risk_mode: str = "normal",
) -> Tuple[List[Claim], List[Dict[str, str]]]:
    groups: Dict[str, List[ClaimCandidate]] = defaultdict(list)
    for c in candidates:
        groups[_group_key(c.text)].append(c)

    claims: List[Claim] = []
    conflicts: List[Dict[str, str]] = []

    for gk, rows in groups.items():
        if not rows:
            continue
        support_ids = sorted({r.item_id for r in rows})
        independent = len({(items_by_id.get(i).domain or items_by_id.get(i).url) for i in support_ids if i in items_by_id})
        types = {items_by_id[i].source_type for i in support_ids if i in items_by_id}
        need_strict = risk_mode == "high"
        has_strong = bool(types & {"official", "academic"})

        score = min(1.0, 0.35 + 0.25 * independent + (0.15 if has_strong else 0.0))
        confidence = "low"
        if independent >= 2 and (not need_strict or has_strong):
            confidence = "high" if score >= 0.75 else "medium"
        elif independent >= 1:
            confidence = "medium" if score >= 0.55 else "low"

        dirs = [_has_opposition(r.text) for r in rows]
        if any(d > 0 for d in dirs) and any(d < 0 for d in dirs):
            conflicts.append({"type": "directional", "claim_a": "", "claim_b": "", "reason": "Opposing directional language detected across supporting sources."})
        text = max(rows, key=lambda x: len(x.text)).text
        cid = sha1(f"{gk}|{text}".encode("utf-8", errors="ignore")).hexdigest()[:16]
        claim = Claim(
            id=cid,
            text=text,
            scope=None,
            numbers=rows[0].numbers,
            supporting_item_ids=support_ids,
            contradicting_item_ids=[],
            confidence=confidence,
            confidence_score=round(score, 4),
        )
        claims.append(claim)

    # lightweight conflict detection across resulting claims
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a, b = claims[i], claims[j]
            overlap = len(_norm_tokens(a.text) & _norm_tokens(b.text))
            if overlap < 3:
                continue
            ad, bd = _has_opposition(a.text), _has_opposition(b.text)
            if ad != 0 and bd != 0 and ad != bd:
                a.contradicting_item_ids = sorted(set(a.contradicting_item_ids + b.supporting_item_ids))
                b.contradicting_item_ids = sorted(set(b.contradicting_item_ids + a.supporting_item_ids))
                conflicts.append({"type": "directional", "claim_a": a.id, "claim_b": b.id, "reason": "Opposing directional language detected."})
                continue

            if a.numbers and b.numbers:
                av = a.numbers.get("values", [{}])[0].get("value")
                bv = b.numbers.get("values", [{}])[0].get("value")
                if isinstance(av, (int, float)) and isinstance(bv, (int, float)) and min(abs(av), abs(bv)) > 0:
                    delta = abs(av - bv) / min(abs(av), abs(bv))
                    if delta > 0.2:
                        conflicts.append({"type": "numeric", "claim_a": a.id, "claim_b": b.id, "reason": f"Numeric disagreement ({delta:.1%}) exceeds threshold."})

    return claims, conflicts

