from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _has_citation_or_url(text: str) -> bool:
    t = str(text or "")
    return bool(re.search(r"\[[0-9]{1,2}\]", t) or re.search(r"https?://", t, flags=re.IGNORECASE))


_HIGH_STAKES_QUERY = re.compile(
    r"\b("
    r"dosage|dose|medication|prescription|diagnosis|treatment|guideline|guidance|"
    r"hypertension|blood pressure|drug interaction|legal|law|lawsuit|tax|"
    r"mortgage|investment|crypto|stock|forex|passport requirement|visa|immigration"
    r")\b",
    re.IGNORECASE,
)
_RECENCY_QUERY = re.compile(r"\b(latest|current|recent|newest|updated|update|what changed|changes?)\b", re.IGNORECASE)
_EXPLICIT_DATE = re.compile(
    r"\b(?:20\d{2}(?:-\d{2}(?:-\d{2})?)?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+20\d{2})\b",
    re.IGNORECASE,
)
_UNCERTAINTY_TEXT = re.compile(
    r"\b("
    r"uncertain|not enough evidence|couldn't verify|could not verify|can't verify|cannot verify|"
    r"limited coverage|source coverage is limited|provisional|might be|may be|thin evidence"
    r")\b",
    re.IGNORECASE,
)


def _severity_weight(level: str) -> int:
    order = {"low": 1, "medium": 2, "high": 3}
    return order.get(str(level or "medium").lower(), 2)


def _is_high_stakes(intent: str, query_text: str) -> bool:
    intent_l = str(intent or "").strip().lower()
    if intent_l in {"crypto", "forex", "stock/commodity"}:
        return True
    return bool(_HIGH_STAKES_QUERY.search(str(query_text or "")))


def _needs_recency_date(query_text: str) -> bool:
    return bool(_RECENCY_QUERY.search(str(query_text or "")))


def _has_explicit_date(text: str) -> bool:
    return bool(_EXPLICIT_DATE.search(str(text or "")))


def _extract_citation_date(row: Dict[str, Any] | None) -> str:
    payload = dict(row or {})
    for key in ("published_at", "published", "date", "source_date", "updated_at"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:20]
    return ""


def _best_citation_date(citation_map: List[Dict[str, Any]] | None = None) -> str:
    values = [item for item in [_extract_citation_date(row) for row in list(citation_map or [])] if item]
    if not values:
        return ""
    return sorted(values, reverse=True)[0]


def validate_answer(
    *,
    content: str,
    intent: str,
    should_search: bool,
    query_text: str = "",
    evidence_contract: Dict[str, Any] | None = None,
    citation_map: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    text = str(content or "")
    out: List[Dict[str, Any]] = []
    intent_l = str(intent or "general").strip().lower()
    contract = dict(evidence_contract or {})
    citations = list(citation_map or [])
    high_stakes = _is_high_stakes(intent_l, query_text)
    found_sources = int(contract.get("found_sources") or len(citations) or 0)

    if should_search:
        if found_sources > 0 and not _has_citation_or_url(text):
            out.append({"code": "missing_citation", "severity": "medium", "message": "Web-backed answer is missing citations/URLs."})
        if _needs_recency_date(query_text) and found_sources > 0 and not _has_explicit_date(text):
            out.append(
                {
                    "code": "missing_freshness_date",
                    "severity": "medium",
                    "message": "Recency-focused answer should surface a concrete date or freshness note.",
                }
            )
        if found_sources <= 0 and len(text) >= 80 and not _UNCERTAINTY_TEXT.search(text):
            out.append(
                {
                    "code": "thin_evidence_without_uncertainty",
                    "severity": "medium",
                    "message": "Answer reads as firmer than the available evidence allows.",
                }
            )

    if intent_l in {"crypto", "forex", "stock/commodity", "weather", "news", "science", "research"}:
        if should_search and int(contract.get("found_sources") or 0) <= 0:
            out.append({"code": "critical_no_sources", "severity": "high", "message": "Critical domain answer has zero sources."})

    if int(contract.get("required_min_sources") or 0) > int(contract.get("found_sources") or 0):
        if re.search(r"\b(always|guaranteed|certainly|definitely|no doubt)\b", text.lower()):
            out.append({"code": "overconfident_without_evidence", "severity": "high", "message": "Answer is overconfident despite insufficient evidence."})

    if high_stakes:
        required = max(2, int(contract.get("required_min_sources") or 0))
        found = int(contract.get("found_sources") or len(citations) or 0)
        if should_search and found < required:
            out.append(
                {
                    "code": "high_stakes_low_evidence",
                    "severity": "high",
                    "message": "High-stakes answer has thinner evidence than the trust policy expects.",
                }
            )

    return out


def repair_answer(
    content: str,
    issues: List[Dict[str, Any]],
    *,
    query_text: str = "",
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

    if any(str(i.get("code") or "") == "high_stakes_low_evidence" for i in issues):
        caution = (
            "Caution: this topic can affect health, legal, or financial decisions, "
            "and source coverage is limited here, so verify specifics with an official "
            "or qualified source before acting."
        )
        if caution not in text:
            text = caution + "\n\n" + text
        next_step = "Next step: ask me to verify this with official-only sources or open the cited guidance directly."
        if next_step not in text:
            text = text.rstrip() + "\n\n" + next_step

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

    if any(str(i.get("code") or "") == "missing_freshness_date" for i in issues):
        best_date = _best_citation_date(citation_map)
        freshness = (
            f"Freshness note: the newest cited source I found is dated {best_date}."
            if best_date
            else "Freshness note: check the publication or update dates in the cited sources before treating this as the latest view."
        )
        if freshness not in text:
            text = text.rstrip() + "\n\n" + freshness

    if any(str(i.get("code") or "") == "thin_evidence_without_uncertainty" for i in issues):
        note = "Evidence note: coverage is thin here, so treat this as a best-effort answer until it is verified."
        if note not in text:
            text = note + "\n\n" + text

    return text


def build_answer_trust_summary(
    *,
    issues: List[Dict[str, Any]] | None = None,
    should_search: bool,
    query_text: str = "",
    evidence_contract: Dict[str, Any] | None = None,
    citation_map: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    contract = dict(evidence_contract or {})
    citations = list(citation_map or [])
    rows = list(issues or [])
    found_sources = int(contract.get("found_sources") or len(citations) or 0)
    caution_count = len(rows)
    latest_date = _best_citation_date(citations)
    high_severity = any(str(item.get("severity") or "").lower() == "high" for item in rows)
    recency_needed = _needs_recency_date(query_text)

    if not should_search:
        level = "local"
        summary = "Trust LOCAL: this answer did not depend on live web evidence."
    elif found_sources <= 0:
        level = "thin"
        summary = "Trust THIN: source backing is limited right now."
    elif high_severity or caution_count >= 2:
        level = "guarded"
        summary = "Trust GUARDED: there is useful evidence, but coverage or certainty is still a bit thin."
    elif found_sources >= 3 and (latest_date or not recency_needed):
        level = "high"
        summary = "Trust HIGH: multiple corroborating sources support this answer."
    else:
        level = "solid"
        summary = "Trust SOLID: evidence coverage looks healthy for this answer."

    if latest_date and should_search:
        summary = f"{summary} Newest source date: {latest_date}."
    return {
        "level": level,
        "summary": summary,
        "caution_count": caution_count,
        "found_sources": found_sources,
        "latest_date": latest_date,
        "issue_codes": [str(item.get('code') or '') for item in rows],
    }


def validate_and_repair_answer(
    *,
    content: str,
    intent: str,
    should_search: bool,
    query_text: str = "",
    evidence_contract: Dict[str, Any] | None = None,
    citation_map: List[Dict[str, Any]] | None = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    issues = validate_answer(
        content=content,
        intent=intent,
        should_search=should_search,
        query_text=query_text,
        evidence_contract=evidence_contract,
        citation_map=citation_map,
    )
    repaired = repair_answer(content, issues, query_text=query_text, citation_map=citation_map)
    return repaired, issues
