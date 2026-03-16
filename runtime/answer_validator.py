from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _has_citation_or_url(text: str) -> bool:
    t = str(text or "")
    return bool(re.search(r"\[[0-9]{1,2}\]", t) or re.search(r"https?://", t, flags=re.IGNORECASE))


def _severity_weight(level: str) -> int:
    order = {"low": 1, "medium": 2, "high": 3}
    return order.get(str(level or "medium").lower(), 2)


def validate_answer(
    *,
    content: str,
    intent: str,
    should_search: bool,
    evidence_contract: Dict[str, Any] | None = None,
    citation_map: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    text = str(content or "")
    out: List[Dict[str, Any]] = []
    intent_l = str(intent or "general").strip().lower()
    contract = dict(evidence_contract or {})
    citations = list(citation_map or [])

    if should_search:
        found_sources = int(contract.get("found_sources") or len(citations) or 0)
        if found_sources > 0 and not _has_citation_or_url(text):
            out.append({"code": "missing_citation", "severity": "medium", "message": "Web-backed answer is missing citations/URLs."})

    if intent_l in {"crypto", "forex", "stock/commodity", "weather", "news", "science", "research"}:
        if should_search and int(contract.get("found_sources") or 0) <= 0:
            out.append({"code": "critical_no_sources", "severity": "high", "message": "Critical domain answer has zero sources."})

    if int(contract.get("required_min_sources") or 0) > int(contract.get("found_sources") or 0):
        if re.search(r"\b(always|guaranteed|certainly|definitely|no doubt)\b", text.lower()):
            out.append({"code": "overconfident_without_evidence", "severity": "high", "message": "Answer is overconfident despite insufficient evidence."})

    return out


def repair_answer(
    content: str,
    issues: List[Dict[str, Any]],
    *,
    citation_map: List[Dict[str, Any]] | None = None,
) -> str:
    text = str(content or "").strip()
    if not issues:
        return text

    top = sorted(issues, key=lambda x: _severity_weight(str(x.get("severity") or "medium")), reverse=True)[0]
    code = str(top.get("code") or "")

    if code in {"critical_no_sources", "overconfident_without_evidence"}:
        if "Evidence note:" not in text:
            text = "Evidence note: source coverage is limited for this answer, so treat specifics as provisional.\n\n" + text

    if any(str(i.get("code") or "") == "missing_citation" for i in issues):
        urls = []
        seen = set()
        for row in list(citation_map or []):
            u = str((row or {}).get("url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            urls.append(u)
            if len(urls) >= 3:
                break
        if urls and "Sources:" not in text:
            text += "\n\nSources:\n" + "\n".join([f"- {u}" for u in urls])

    return text


def validate_and_repair_answer(
    *,
    content: str,
    intent: str,
    should_search: bool,
    evidence_contract: Dict[str, Any] | None = None,
    citation_map: List[Dict[str, Any]] | None = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    issues = validate_answer(
        content=content,
        intent=intent,
        should_search=should_search,
        evidence_contract=evidence_contract,
        citation_map=citation_map,
    )
    repaired = repair_answer(content, issues, citation_map=citation_map)
    return repaired, issues
