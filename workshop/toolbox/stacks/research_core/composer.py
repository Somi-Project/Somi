from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from config.settings import SEARXNG_DOMAIN_PROFILES
from workshop.toolbox.stacks.research_core.answer_adequacy import assess_answer_adequacy
from workshop.toolbox.stacks.research_core.browse_planner import is_shopping_compare_query, is_trip_planning_query, shopping_compare_variants, trip_planning_variants
from workshop.toolbox.stacks.research_core.evidence_claims import extract_claim_candidates
from workshop.toolbox.stacks.research_core.evidence_reconcile import reconcile_claims
from workshop.toolbox.stacks.research_core.evidence_schema import EvidenceBundle, EvidenceItem
from workshop.toolbox.stacks.research_core.evidence_scoring import classify_source_type, score_items
from workshop.toolbox.stacks.research_core.reader import deep_read_items
from workshop.toolbox.stacks.research_core.router import ResearchRouter
from workshop.toolbox.stacks.research_core.searxng import search_searxng

logger = logging.getLogger(__name__)

_RECENCY_TERMS = ("latest", "current", "new", "recent", "as of", "today")
_RISK_TERMS = ("treatment", "dose", "clinical", "guideline", "drug", "law", "legal", "invest", "financial")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(seed: str) -> str:
    return sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _canonical_url(url: str) -> str:
    p = urlparse((url or "").strip())
    if not p.scheme or not p.netloc:
        return (url or "").strip()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, "", urlencode(q, doseq=True), ""))


def _needs_recency(question: str) -> bool:
    ql = (question or "").lower()
    return any(t in ql for t in _RECENCY_TERMS)


def _risk_mode(question: str, requested: str) -> str:
    if requested in {"high", "normal"}:
        return requested
    return "high" if any(t in (question or "").lower() for t in _RISK_TERMS) else "normal"


def _infer_domain(question: str) -> str:
    ql = (question or "").lower()
    if any(k in ql for k in ("github", "repo", "repository", "readme", "documentation", "package", "library", "framework")):
        return "general"
    if is_shopping_compare_query(question) or is_trip_planning_query(question):
        return "general"
    if any(k in ql for k in ("pmid", "pubmed", "clinical", "guideline", "trial", "therapy", "dose", "treatment", "hypertension", "cardio")):
        return "biomed"
    if any(k in ql for k in ("finite element", "fea", "signal processing", "rf", "antenna", "circuit", "mechanical", "electrical")):
        return "engineering"
    if any(k in ql for k in ("nutrition", "calorie", "protein", "macros", "vitamin", "diet", "food facts")):
        return "nutrition"
    if any(k in ql for k in ("religion", "theology", "bible", "quran", "hadith", "torah", "talmud")):
        return "religion"
    if any(k in ql for k in ("movie", "film", "anime", "manga", "game", "gaming", "box office", "imdb")):
        return "entertainment"
    if any(k in ql for k in ("business", "management", "operations", "leadership", "marketing", "accounting", "mba")):
        return "business_administrator"
    if any(k in ql for k in ("journalism", "media", "newsroom", "misinformation", "coverage", "public opinion")):
        return "journalism_communication"
    return "science"


def _profile_for_domain(domain_key: str) -> Dict[str, Any]:
    cfg = SEARXNG_DOMAIN_PROFILES if isinstance(SEARXNG_DOMAIN_PROFILES, dict) else {}
    base = cfg.get("science", {}) if str(domain_key or "") != "general" else cfg.get("general", {})
    chosen = cfg.get(str(domain_key or "science"), base)
    return dict(chosen or base or {})


def _dedupe_queries(rows: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for row in rows:
        clean = " ".join(str(row or "").split()).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def plan_queries(question: str, *, seed_queries: List[str] | None = None) -> List[str]:
    q = (question or "").strip()
    if not q:
        return []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    domain_key = _infer_domain(q)

    queries: List[str] = list(seed_queries or [])
    if domain_key == "biomed":
        queries.extend(
            [
                q,
                f"{q} evidence review",
                f"{q} official guideline",
                f"{q} systematic review",
                f"{q} limitations criticism",
            ]
        )
    elif domain_key == "general" and any(k in q.lower() for k in ("github", "repo", "repository", "readme", "documentation", "package", "library", "framework")):
        queries.extend(
            [
                q,
                f"site:github.com {q}",
                f"{q} readme",
                f"{q} documentation",
                f"{q} release notes",
            ]
        )
    elif domain_key == "general" and is_shopping_compare_query(q):
        queries.extend(shopping_compare_variants(q))
        queries.extend(
            [
                f"{q} buying guide",
                f"{q} pros and cons",
                f"{q} review",
            ]
        )
    elif domain_key == "general" and is_trip_planning_query(q):
        queries.extend(trip_planning_variants(q))
        queries.extend(
            [
                f"{q} neighborhood guide",
                f"{q} food guide",
                f"{q} first time visitor",
            ]
        )
    else:
        queries.extend(
            [
                q,
                f"{q} official source",
                f"{q} overview",
                f"{q} documentation",
                f"{q} limitations",
            ]
        )

    if _needs_recency(q):
        queries.extend([f"{q} as of {now}", f"{q} updated official source"])

    return _dedupe_queries(queries)[:10]


def _extract_identifiers(row: Dict[str, Any], url: str, title: str) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    for key in ("doi", "pmid", "nct", "arxiv_id", "s2_id", "id"):
        val = str(row.get(key) or "").strip()
        if not val:
            continue
        if key == "id":
            idt = str(row.get("id_type") or "").strip().lower()
            if idt in {"doi", "pmid", "nct", "arxiv"}:
                ids["arxiv_id" if idt == "arxiv" else idt] = val
        else:
            ids[key] = val

    text = f"{title} {url}"
    m = re.search(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", text, re.IGNORECASE)
    if m and "doi" not in ids:
        ids["doi"] = m.group(0)
    m = re.search(r"\bpmid[:\s]*(\d{5,10})\b", text, re.IGNORECASE)
    if m and "pmid" not in ids:
        ids["pmid"] = m.group(1)
    m = re.search(r"\bnct\d{8}\b", text, re.IGNORECASE)
    if m and "nct" not in ids:
        ids["nct"] = m.group(0).upper()
    m = re.search(r"\b(\d{4}\.\d{4,5})(v\d+)?\b", text)
    if m and "arxiv_id" not in ids and "arxiv" in text.lower():
        ids["arxiv_id"] = m.group(1)
    return ids


def _normalize_result(row: Dict[str, Any], *, retrieved_at: str) -> EvidenceItem | None:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    if not title or not url:
        return None
    canon_url = _canonical_url(url)
    snippet = str(row.get("description") or row.get("snippet") or "").strip() or None
    provider_hint = str(row.get("source") or row.get("provider") or "")
    source_type = classify_source_type(canon_url, provider_hint=provider_hint)
    identifiers = _extract_identifiers(row, canon_url, title)
    iid = _stable_id("|".join([canon_url, identifiers.get("doi", ""), identifiers.get("pmid", ""), identifiers.get("nct", ""), title.lower()]))
    return EvidenceItem(
        id=iid,
        title=title,
        url=canon_url,
        source_type=source_type,
        published_date=(str(row.get("published") or row.get("published_at") or "").strip() or None),
        retrieved_at=retrieved_at,
        snippet=snippet,
        content_excerpt=None,
        identifiers=identifiers,
        domain=(str(row.get("domain") or "").strip() or None),
        score=0.0,
        score_breakdown={},
    )


def dedupe_items(items: List[EvidenceItem]) -> List[EvidenceItem]:
    kept: Dict[str, EvidenceItem] = {}

    def _quality(it: EvidenceItem) -> tuple[int, int, int]:
        return (len(it.identifiers), 1 if it.published_date else 0, len(it.content_excerpt or it.snippet or ""))

    for it in items:
        key = it.identifiers.get("doi") or it.identifiers.get("pmid") or it.identifiers.get("nct") or it.identifiers.get("arxiv_id") or it.url
        cur = kept.get(key)
        if cur is None or _quality(it) > _quality(cur):
            kept[key] = it
    return list(kept.values())


def _claim_sources(claim, items_by_id: Dict[str, EvidenceItem]) -> List[str]:
    out: List[str] = []
    for item_id in claim.supporting_item_ids[:3]:
        item = items_by_id.get(item_id)
        if item is None:
            continue
        label = item.title
        if item.published_date:
            label += f" ({item.published_date})"
        out.append(label)
    return out


def _build_answer(question: str, claims, conflicts, queries: List[str], limitations: List[str], items: List[EvidenceItem]) -> str:
    items_by_id = {item.id: item for item in items}
    high = [claim for claim in claims if claim.confidence in {"high", "medium"}]
    if not high:
        if items:
            best = items[0]
            parts = [f"Best available source: {best.title}."]
            if best.published_date:
                parts.append(f"Published or updated: {best.published_date}.")
            if best.content_excerpt or best.snippet:
                parts.append((best.content_excerpt or best.snippet or "")[:420])
            if limitations:
                parts.append("Research limits: " + "; ".join(limitations[:2]))
            return " ".join(p for p in parts if p).strip()
        searched = "; ".join(queries[:4])
        return f"I could not gather enough evidence yet for '{question}'. Searches tried: {searched}."

    lines = [high[0].text]
    supporting = high[1:4]
    if supporting:
        lines.append("Key supporting findings:")
        for claim in supporting:
            sources = _claim_sources(claim, items_by_id)
            source_note = f" Sources: {', '.join(sources)}." if sources else ""
            lines.append(f"- {claim.text}{source_note}")
    if conflicts:
        reasons = [str(cf.get("reason") or "").strip() for cf in conflicts[:3] if str(cf.get("reason") or "").strip()]
        if reasons:
            lines.append("Uncertainty: " + "; ".join(reasons))
    if limitations:
        lines.append("Research limits: " + "; ".join(limitations[:3]))
    return "\n".join(lines).strip()


def _compute_calculations(claims) -> List[Dict[str, Any]]:
    calculations: List[Dict[str, Any]] = []
    for claim in claims:
        if claim.numbers and claim.numbers.get("values"):
            vals = [x.get("value") for x in claim.numbers["values"] if isinstance(x.get("value"), (int, float))]
            if vals:
                calculations.append({"claim_id": claim.id, "mean": sum(vals) / len(vals), "count": len(vals)})
    return calculations


def _bundle_intent(question: str) -> str:
    ql = (question or "").lower()
    if any(term in ql for term in ("compare", " vs ", " versus ", "pros and cons", "which is better", "should i buy")):
        return "comparison"
    if is_trip_planning_query(question):
        return "planning"
    if any(term in ql for term in ("what changed", "what's new", "whats new", "release notes", "changelog")):
        return "changes"
    if any(term in ql for term in _RECENCY_TERMS):
        return "latest"
    return "analysis"


def _decompose_subquestions(question: str, *, intent: str, queries: List[str]) -> List[str]:
    q = (question or "").strip()
    ql = q.lower()
    if not q:
        return []
    if intent == "comparison":
        return [
            f"What are the main decision dimensions for {q}?",
            f"What stands out most in the strongest sources about {q}?",
            f"What tradeoffs or caveats should the user know about {q}?",
        ]
    if intent == "planning":
        return [
            f"What is the most practical structure for {q}?",
            f"What timing, logistics, or sequencing details matter most for {q}?",
            f"What constraints, caveats, or optional additions show up in the sources for {q}?",
        ]
    if intent == "changes":
        return [
            f"What are the headline changes for {q}?",
            f"What source-backed details explain those changes for {q}?",
            f"What limitations or unanswered questions remain for {q}?",
        ]
    if intent == "latest":
        return [
            f"What is the most recent authoritative answer to {q}?",
            f"What source confirms the date or recency for {q}?",
            f"What caveats or older adjacent sources should be treated carefully for {q}?",
        ]
    if any(term in ql for term in ("github", "repo", "repository", "readme", "docs", "documentation")):
        return [
            f"What is the project or resource behind {q}?",
            f"What setup, structure, or recent-change clues show up for {q}?",
            f"What limitations or open questions remain after reviewing {q}?",
        ]
    derived = [row for row in queries[:3] if row and row.strip().lower() != ql]
    prompts = [f"What is the direct answer to {q}?"]
    for row in derived[:2]:
        prompts.append(f"What does this angle add to the answer: {row}?")
    return prompts[:3]


def _section_templates(question: str, *, intent: str, needs_recency: bool) -> List[Dict[str, str]]:
    q = (question or "").strip()
    if intent == "comparison":
        return [
            {"title": "Decision frame", "guiding_question": f"What is the main choice behind {q}?"},
            {"title": "Tradeoffs", "guiding_question": f"What tradeoffs do the sources emphasize for {q}?"},
            {"title": "Caveats", "guiding_question": f"What cautions or missing details remain for {q}?"},
        ]
    if intent == "planning":
        return [
            {"title": "Recommended structure", "guiding_question": f"What is the best overall structure for {q}?"},
            {"title": "Logistics", "guiding_question": f"What timing or sequencing details matter for {q}?"},
            {"title": "Constraints", "guiding_question": f"What limitations or optional extras show up for {q}?"},
        ]
    if intent == "changes":
        return [
            {"title": "Headline changes", "guiding_question": f"What changed most for {q}?"},
            {"title": "Supporting details", "guiding_question": f"What source-backed details explain those changes for {q}?"},
            {"title": "Open questions", "guiding_question": f"What remains uncertain or easy to misread about {q}?"},
        ]
    if needs_recency or intent == "latest":
        return [
            {"title": "Current answer", "guiding_question": f"What is the most recent source-backed answer to {q}?"},
            {"title": "Authority and date", "guiding_question": f"Which sources best establish the recency and authority for {q}?"},
            {"title": "Caveats", "guiding_question": f"What nearby but weaker sources could confuse the answer to {q}?"},
        ]
    return [
        {"title": "Direct answer", "guiding_question": f"What is the main answer to {q}?"},
        {"title": "Supporting evidence", "guiding_question": f"What evidence best supports the answer to {q}?"},
        {"title": "Limitations", "guiding_question": f"What limitations or open questions remain for {q}?"},
    ]


def _claim_text(claim: Any) -> str:
    return str(getattr(claim, "text", "") or "").strip()


def _item_text(item: EvidenceItem) -> str:
    return " ".join(
        part
        for part in (
            str(getattr(item, "title", "") or "").strip(),
            str(getattr(item, "content_excerpt", "") or "").strip(),
            str(getattr(item, "snippet", "") or "").strip(),
        )
        if part
    ).lower()


def _section_relevance_score(template: Dict[str, str], claim: Any, supporting_items: List[EvidenceItem], *, intent: str) -> int:
    title = str(template.get("title") or "").lower()
    text = _claim_text(claim).lower()
    item_blob = " ".join(_item_text(item) for item in supporting_items)
    blob = f"{text} {item_blob}"
    score = 0
    if title in {"direct answer", "current answer", "headline changes", "recommended structure", "decision frame"}:
        score += 2
    if title in {"tradeoffs", "decision frame"} and any(term in blob for term in ("tradeoff", "versus", "vs", "pros", "cons", "better", "worse", "portability", "battery", "price", "camera", "performance")):
        score += 5
    if title in {"recommended structure", "logistics"} and any(term in blob for term in ("day", "days", "itinerary", "route", "logistics", "timing", "neighborhood", "transport", "budget")):
        score += 5
    if title in {"headline changes", "supporting details"} and any(term in blob for term in ("change", "new", "release", "updated", "highlight", "interpreter", "free-threaded", "jit", "deprecated")):
        score += 5
    if title in {"authority and date", "current answer"} and any(term in blob for term in ("guideline", "official", "published", "updated", "202", "released")):
        score += 4
    if title in {"caveats", "limitations", "open questions"} and any(term in blob for term in ("limit", "uncertain", "mixed", "conflict", "however", "older", "thin", "caveat")):
        score += 4
    if intent == "comparison" and title == "tradeoffs":
        score += 2
    if intent == "planning" and title == "recommended structure":
        score += 2
    if intent == "changes" and title == "headline changes":
        score += 2
    if intent == "latest" and title == "current answer":
        score += 2
    return score


def _build_research_brief(
    question: str,
    *,
    queries: List[str],
    domain_key: str,
    chosen_risk_mode: str,
    needs_recency: bool,
    browse_mode: str,
    claims: List[Any],
    limitations: List[str],
) -> Dict[str, Any]:
    intent = _bundle_intent(question)
    subquestions = _decompose_subquestions(question, intent=intent, queries=queries)
    objective = (question or "").strip()
    if intent == "comparison":
        objective = f"Compare {question.strip()} using source-backed tradeoffs and caveats."
    elif intent == "planning":
        objective = f"Build a practical plan for {question.strip()} using current itinerary and logistics sources."
    elif intent == "changes":
        objective = f"Identify the headline changes and source-backed details for {question.strip()}."
    elif intent == "latest":
        objective = f"Find the most recent authoritative answer to {question.strip()} and verify its date."
    return {
        "objective": objective,
        "intent": intent,
        "domain": domain_key,
        "risk_mode": chosen_risk_mode,
        "browse_mode": browse_mode,
        "needs_recency": bool(needs_recency),
        "queries_considered": list(queries[:6]),
        "subquestions": subquestions[:4],
        "claim_count": len(list(claims or [])),
        "limitation_count": len(list(limitations or [])),
    }


def _build_section_bundles(
    question: str,
    *,
    brief: Dict[str, Any],
    claims: List[Any],
    items: List[EvidenceItem],
    conflicts: List[Dict[str, Any]],
    limitations: List[str],
) -> List[Dict[str, Any]]:
    templates = _section_templates(
        question,
        intent=str(brief.get("intent") or "analysis"),
        needs_recency=bool(brief.get("needs_recency")),
    )
    items_by_id = {item.id: item for item in list(items or [])}
    remaining_claims = [claim for claim in list(claims or []) if _claim_text(claim)]
    sections: List[Dict[str, Any]] = []

    for template in templates:
        chosen: List[Any] = []
        scored_claims: List[tuple[int, Any]] = []
        for claim in remaining_claims:
            supporting_items = [items_by_id[item_id] for item_id in list(getattr(claim, "supporting_item_ids", []) or []) if item_id in items_by_id]
            score = _section_relevance_score(template, claim, supporting_items, intent=str(brief.get("intent") or "analysis"))
            if score > 0:
                scored_claims.append((score, claim))
        scored_claims.sort(key=lambda row: row[0], reverse=True)
        for _, claim in scored_claims[:2]:
            if claim not in chosen:
                chosen.append(claim)
        if not chosen and remaining_claims:
            chosen.append(remaining_claims[0])
        if not chosen and template.get("title", "").lower() in {"caveats", "limitations", "open questions"} and (limitations or conflicts):
            sections.append(
                {
                    "title": str(template.get("title") or "").strip(),
                    "guiding_question": str(template.get("guiding_question") or "").strip(),
                    "summary": "; ".join(list(limitations or [])[:2]) or "; ".join(str((row or {}).get("reason") or "").strip() for row in conflicts[:2] if str((row or {}).get("reason") or "").strip()),
                    "claim_ids": [],
                    "source_urls": [],
                    "source_titles": [],
                    "confidence": "low",
                }
            )
            continue
        if not chosen:
            continue

        section_urls: List[str] = []
        section_titles: List[str] = []
        claim_ids: List[str] = []
        summary_bits: List[str] = []
        confidence = "low"
        for claim in chosen:
            claim_text = _claim_text(claim)
            if claim_text and claim_text not in summary_bits:
                summary_bits.append(claim_text)
            claim_id = str(getattr(claim, "id", "") or "").strip()
            if claim_id:
                claim_ids.append(claim_id)
            confidence = str(getattr(claim, "confidence", "") or confidence or "low")
            for item_id in list(getattr(claim, "supporting_item_ids", []) or [])[:2]:
                item = items_by_id.get(item_id)
                if item is None:
                    continue
                if item.url and item.url not in section_urls:
                    section_urls.append(item.url)
                if item.title and item.title not in section_titles:
                    section_titles.append(item.title)
        sections.append(
            {
                "title": str(template.get("title") or "").strip(),
                "guiding_question": str(template.get("guiding_question") or "").strip(),
                "summary": " ".join(summary_bits[:2]).strip(),
                "claim_ids": claim_ids[:4],
                "source_urls": section_urls[:4],
                "source_titles": section_titles[:4],
                "confidence": confidence or "low",
            }
        )
        remaining_claims = [claim for claim in remaining_claims if claim not in chosen]

    if limitations:
        has_limits = any(str(section.get("title") or "").lower() in {"caveats", "limitations", "open questions"} for section in sections)
        if not has_limits:
            sections.append(
                {
                    "title": "Limitations",
                    "guiding_question": f"What remains uncertain about {question.strip()}?",
                    "summary": "; ".join(list(limitations or [])[:2]),
                    "claim_ids": [],
                    "source_urls": [],
                    "source_titles": [],
                    "confidence": "low",
                }
            )
    return sections[:4]


async def research_compose(
    question: str,
    *,
    max_web_results: int = 10,
    max_enrich_results_per_domain: int = 6,
    max_deep_reads: int = 8,
    risk_mode: str = "auto",
    seed_queries: List[str] | None = None,
    max_rounds: int = 2,
    domain_override: str | None = None,
    browse_mode: str = "deep",
) -> EvidenceBundle:
    question = (question or "").strip()
    queries = plan_queries(question, seed_queries=seed_queries)
    now = _now_iso()
    chosen_risk_mode = _risk_mode(question, risk_mode)
    needs_recency = _needs_recency(question)
    domain_key = str(domain_override or _infer_domain(question) or "general")
    limitations: List[str] = []

    logger.info("research_compose start q='%s' risk=%s domain=%s", question, chosen_risk_mode, domain_key)
    logger.info("research_compose queries=%s", queries)

    async def _web_discovery(qset: List[str]) -> List[Dict[str, Any]]:
        if not qset:
            return []
        p = _profile_for_domain(domain_key)
        async with httpx.AsyncClient(timeout=8.0) as client:
            tasks = [
                search_searxng(
                    client,
                    q,
                    max_results=min(int(p.get("max_results", max_web_results)), int(max_web_results)),
                    max_pages=int(p.get("max_pages", 2)),
                    profile=str(p.get("profile") or ("general" if domain_key == "general" else "science")),
                    category=str(p.get("category") or ("general" if domain_key == "general" else "science")),
                    source_name=str(p.get("source_name") or f"searxng_{domain_key}"),
                    domain=("general" if domain_key == "general" else domain_key),
                )
                for q in qset
            ]
            rows = await asyncio.gather(*tasks, return_exceptions=True)

        out: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, list):
                out.extend(row)

        if not out:
            gp = _profile_for_domain("general")
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    out = await search_searxng(
                        client,
                        qset[0],
                        max_results=min(int(gp.get("max_results", max_web_results)), int(max_web_results)),
                        max_pages=int(gp.get("max_pages", 2)),
                        profile=str(gp.get("profile") or "general"),
                        category=str(gp.get("category") or "general"),
                        source_name=str(gp.get("source_name") or "searxng_general"),
                        domain="general",
                    )
            except Exception:
                pass
        return out


    async def _enrichment() -> List[Dict[str, Any]]:
        if domain_key == "general":
            return []
        try:
            router = ResearchRouter(max_total=max(4, max_enrich_results_per_domain * 2))
            rows = await router.search(question)
            return (rows or [])[: max_enrich_results_per_domain * 3]
        except Exception:
            logger.exception("research_compose enrichment failed")
            return []

    enrich_rows = await _enrichment()
    collected_rows: List[Dict[str, Any]] = list(enrich_rows)
    seen_queries: set[str] = set()
    scored: List[EvidenceItem] = []
    claims = []
    conflicts: List[Dict[str, Any]] = []
    calculations: List[Dict[str, Any]] = []

    rounds = max(1, int(max_rounds))
    for round_index in range(rounds):
        qset = []
        for query in queries:
            key = query.lower().strip()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            qset.append(query)
            if len(qset) >= 3:
                break
        if not qset and round_index > 0:
            break

        web_rows = await _web_discovery(qset)
        logger.info("research_compose round=%d web=%d enrich=%d", round_index + 1, len(web_rows), len(enrich_rows))
        collected_rows.extend(web_rows)

        normalized: List[EvidenceItem] = []
        for row in collected_rows:
            if not isinstance(row, dict):
                continue
            item = _normalize_result(row, retrieved_at=now)
            if item:
                normalized.append(item)

        deduped = dedupe_items(normalized)
        scored = score_items(deduped, question=question, needs_recency=needs_recency)
        if scored and max_deep_reads > 0:
            scored = await deep_read_items(scored, max_reads=max_deep_reads, timeout_s=10.0)
        elif not scored:
            limitations.append("No items available for deep read.")

        candidates = extract_claim_candidates(scored[: max_deep_reads or len(scored)], max_claims_per_item=5)
        items_by_id = {item.id: item for item in scored}
        claims, conflicts = reconcile_claims(candidates, items_by_id=items_by_id, risk_mode=chosen_risk_mode)
        calculations = _compute_calculations(claims)

        adequacy = assess_answer_adequacy(
            question,
            items=scored[: max(4, max_deep_reads)],
            claims=claims,
            conflicts=conflicts,
            domain_key=domain_key,
            browse_mode=browse_mode,
        )
        if adequacy.adequate:
            break
        if round_index < rounds - 1 and adequacy.follow_up_queries:
            limitations.append("Additional browse round triggered: " + ", ".join(adequacy.missing[:3]))
            queries = _dedupe_queries([*queries, *adequacy.follow_up_queries])[:12]

    if not scored:
        limitations.append("No items retrieved from web discovery and enrichment.")

    research_brief = _build_research_brief(
        question,
        queries=queries,
        domain_key=domain_key,
        chosen_risk_mode=chosen_risk_mode,
        needs_recency=needs_recency,
        browse_mode=browse_mode,
        claims=claims,
        limitations=limitations,
    )
    section_bundles = _build_section_bundles(
        question,
        brief=research_brief,
        claims=claims,
        items=scored,
        conflicts=conflicts,
        limitations=limitations,
    )
    answer = _build_answer(question, claims, conflicts, queries, limitations, scored)
    return EvidenceBundle(
        question=question,
        queries=queries,
        items=scored,
        claims=claims,
        conflicts=conflicts,
        calculations=calculations,
        answer=answer,
        limitations=limitations,
        research_brief=research_brief,
        section_bundles=section_bundles,
    )
