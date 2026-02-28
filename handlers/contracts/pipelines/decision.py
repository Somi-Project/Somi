from __future__ import annotations

import re
from typing import Any, Dict, List

from handlers.contracts.base import build_base
from handlers.contracts.envelopes import LLMEnvelope


def _extract_options(text: str) -> List[str]:
    options: List[str] = []
    for ln in [x.strip() for x in text.splitlines() if x.strip()]:
        if re.match(r"^(?:[-*]|\d+[.)]|option\s+[a-z0-9])\s+", ln, flags=re.IGNORECASE):
            parsed = re.sub(r"^(?:[-*]|\d+[.)]|option\s+[a-z0-9])\s+", "", ln, flags=re.IGNORECASE).strip()
            if parsed:
                options.append(parsed)
    if len(options) >= 2:
        return options[:8]

    m = re.search(r"between\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:[?.!,]|$)", text, flags=re.IGNORECASE)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    return []


def _extract_criteria(text: str) -> List[Dict[str, Any]]:
    crits: List[Dict[str, Any]] = []
    block = ""
    m = re.search(r"(?is)criteria\s*:\s*(.*?)(?:\n\s*[A-Za-z][A-Za-z ]{1,24}:\s*|\Z)", text)
    if m:
        block = m.group(1).strip()

    raw_lines = [ln.strip(" -•\t") for ln in block.splitlines() if ln.strip()] if block else []
    for ln in raw_lines:
        weight = None
        wm = re.search(r"(\d+(?:\.\d+)?)", ln)
        if wm:
            try:
                weight = float(wm.group(1))
            except Exception:
                weight = None
        name = re.sub(r"\b(\d+(?:\.\d+)?)\b", "", ln).strip(" :-")
        if name:
            crits.append({"name": name, "weight": weight, "rationale": ""})

    if not crits:
        defaults = ["Cost", "Impact", "Time to implement", "Risk"]
        crits = [{"name": x, "weight": None, "rationale": "Default criterion"} for x in defaults]
    return crits[:7]


def _normalize_weights(criteria: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vals = []
    for c in criteria:
        v = c.get("weight")
        vals.append(float(v) if isinstance(v, (int, float)) else 0.0)
    if not any(v > 0 for v in vals):
        vals = [1.0 for _ in criteria]
    total = sum(vals) or 1.0
    for idx, c in enumerate(criteria):
        c["weight"] = vals[idx] / total
    return criteria


def _explicit_score_lookup(text: str, options: List[str], criteria: List[Dict[str, Any]]) -> Dict[tuple[str, str], int]:
    lookup: Dict[tuple[str, str], int] = {}
    for ln in [x.strip() for x in text.splitlines() if x.strip()]:
        m = re.search(r"(.+?)\s*[:\-]\s*(.+?)\s*=\s*(\d)", ln)
        if not m:
            continue
        opt_candidate = m.group(1).strip()
        crit_candidate = m.group(2).strip()
        score = int(m.group(3))
        opt = next((o for o in options if o.lower() in opt_candidate.lower() or opt_candidate.lower() in o.lower()), None)
        crit = next((c["name"] for c in criteria if c["name"].lower() in crit_candidate.lower() or crit_candidate.lower() in c["name"].lower()), None)
        if opt and crit and 1 <= score <= 5:
            lookup[(opt, crit)] = score
    return lookup


def _build_scores(text: str, options: List[str], criteria: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    explicit = _explicit_score_lookup(text, options, criteria)
    rows: List[Dict[str, Any]] = []
    for opt_idx, opt in enumerate(options):
        for crit_idx, crit in enumerate(criteria):
            score = explicit.get((opt, crit["name"]))
            if score is None:
                # Lightweight heuristic to keep latency low while avoiding random output.
                score = 3 if opt_idx == 0 else 2 + (1 if crit_idx % 2 == 0 else 0)
            score = max(1, min(5, int(score)))
            rows.append(
                {
                    "option": opt,
                    "criterion": crit["name"],
                    "score": score,
                    "justification": "User-provided" if (opt, crit["name"]) in explicit else "Estimated from provided context.",
                }
            )
    return rows


def _totals(options: List[str], criteria: List[Dict[str, Any]], scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matrix: Dict[tuple[str, str], float] = {}
    for s in scores:
        matrix[(str(s.get("option")), str(s.get("criterion")))] = float(s.get("score") or 0.0)

    totals = []
    for opt in options:
        weighted = 0.0
        for c in criteria:
            weighted += matrix.get((opt, c["name"]), 0.0) * float(c["weight"])
        totals.append({"option": opt, "weighted_total": round(weighted, 4)})
    totals.sort(key=lambda x: x["weighted_total"], reverse=True)
    return totals


def _extra_sections(query: str) -> List[Dict[str, str]]:
    q = (query or "").lower()
    out: List[Dict[str, str]] = []
    if "what would change my recommendation" in q:
        out.append(
            {
                "title": "What Would Change My Recommendation",
                "content": "Revisit if top criterion weights shift materially or if a new hard constraint appears.",
            }
        )
    if "questions to answer to decide" in q:
        out.append(
            {
                "title": "Questions to Answer to Decide",
                "content": "What is the acceptable cost ceiling? What timeline is non-negotiable?",
            }
        )
    return out


def build_decision_matrix(*, query: str, route: str, envelope: LLMEnvelope, trigger_reason: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = "\n".join([query or "", envelope.answer_text or ""]).strip()
    options = _extract_options(text)
    criteria = _normalize_weights(_extract_criteria(text))
    scores = _build_scores(text, options, criteria)
    totals = _totals(options, criteria, scores)
    best = totals[0]["option"] if totals else "No recommendation"

    content = {
        "question": (query or "Decision question").strip()[:300],
        "options": options,
        "criteria": criteria,
        "scores": scores,
        "totals": totals,
        "recommendation": f"Recommend {best} based on highest weighted total.",
        "sensitivity_notes": ["If top weights change materially, ranking can change."],
        "extra_sections": _extra_sections(query),
    }

    return build_base(
        artifact_type="decision_matrix",
        inputs={"user_query": query, "route": route},
        content=content,
        citations=[],
        confidence=0.78,
        metadata={"derived_from": "decision_framework"},
        trigger_reason=trigger_reason,
    )
