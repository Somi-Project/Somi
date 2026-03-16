from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from config.settings import SEARXNG_DOMAIN_PROFILES
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


def plan_queries(question: str) -> List[str]:
    q = (question or "").strip()
    if not q:
        return []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    queries = [
        q,
        f"{q} evidence review",
        f"{q} official guideline",
        f"{q} limitations criticism",
        f"{q} systematic review",
    ]
    if _needs_recency(q):
        queries.append(f"{q} as of {now}")
    seen, out = set(), []
    for x in queries:
        xl = x.lower().strip()
        if xl and xl not in seen:
            seen.add(xl)
            out.append(x)
    return out[:8]


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


def _build_answer(question: str, claims, conflicts, queries: List[str], limitations: List[str]) -> str:
    high = [c for c in claims if c.confidence in {"high", "medium"}]
    if not high:
        searched = "; ".join(queries[:4])
        return f"Insufficient evidence found from current retrieval for: {question}. Searched: {searched}."
    lines = [f"Direct answer: {high[0].text}"]
    lines.append("Evidence summary:")
    for c in high[:5]:
        cites = ", ".join(c.supporting_item_ids[:3])
        lines.append(f"- {c.text} [sources: {cites}] ({c.confidence})")
    if conflicts:
        lines.append("Conflicts/uncertainty:")
        for cf in conflicts[:4]:
            lines.append(f"- {cf.get('reason')}")
    lines.append("What was searched: " + "; ".join(queries[:5]))
    if limitations:
        lines.append("Limitations: " + "; ".join(limitations[:4]))
    return "\n".join(lines)


async def research_compose(
    question: str,
    *,
    max_web_results: int = 10,
    max_enrich_results_per_domain: int = 6,
    max_deep_reads: int = 8,
    risk_mode: str = "auto",
) -> EvidenceBundle:
    question = (question or "").strip()
    queries = plan_queries(question)
    now = _now_iso()
    chosen_risk_mode = _risk_mode(question, risk_mode)
    needs_recency = _needs_recency(question)

    logger.info("research_compose start q='%s' risk=%s", question, chosen_risk_mode)
    logger.info("research_compose queries=%s", queries)

    async def _web_discovery() -> List[Dict[str, Any]]:
        qset = queries[:3]
        domain_key = _infer_domain(question)
        p = _profile_for_domain(domain_key)

        async with httpx.AsyncClient(timeout=8.0) as client:
            tasks = [
                search_searxng(
                    client,
                    q,
                    max_results=min(int(p.get("max_results", max_web_results)), int(max_web_results)),
                    max_pages=int(p.get("max_pages", 2)),
                    profile=str(p.get("profile") or "science"),
                    category=str(p.get("category") or "science"),
                    source_name=str(p.get("source_name") or f"searxng_{domain_key}"),
                    domain=domain_key,
                )
                for q in qset
            ]
            rows = await asyncio.gather(*tasks, return_exceptions=True)

        out: List[Dict[str, Any]] = []
        for r in rows:
            if isinstance(r, list):
                out.extend(r)

        # Safety fallback: if domain profile returns nothing, retry first query with general profile.
        if not out and qset:
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
        try:
            router = ResearchRouter(max_total=max(4, max_enrich_results_per_domain * 2))
            rows = await router.search(question)
            return (rows or [])[: max_enrich_results_per_domain * 3]
        except Exception:
            logger.exception("research_compose enrichment failed")
            return []

    web_rows, enrich_rows = await asyncio.gather(_web_discovery(), _enrichment())
    logger.info("research_compose retrieval web=%d enrich=%d", len(web_rows), len(enrich_rows))

    normalized: List[EvidenceItem] = []
    for row in web_rows + enrich_rows:
        if not isinstance(row, dict):
            continue
        item = _normalize_result(row, retrieved_at=now)
        if item:
            normalized.append(item)

    logger.info("research_compose pre-dedupe items=%d", len(normalized))
    deduped = dedupe_items(normalized)
    logger.info("research_compose post-dedupe items=%d", len(deduped))

    scored = score_items(deduped, question=question, needs_recency=needs_recency)
    logger.info("research_compose top_scores=%s", [round(x.score, 3) for x in scored[:5]])

    limitations: List[str] = []
    if scored and max_deep_reads > 0:
        scored = await deep_read_items(scored, max_reads=max_deep_reads, timeout_s=10.0)
    else:
        limitations.append("Deep read disabled or no items available.")

    candidates = extract_claim_candidates(scored[: max_deep_reads or len(scored)], max_claims_per_item=5)
    logger.info("research_compose claim_candidates=%d", len(candidates))

    items_by_id = {i.id: i for i in scored}
    claims, conflicts = reconcile_claims(candidates, items_by_id=items_by_id, risk_mode=chosen_risk_mode)
    logger.info("research_compose claims=%d conflicts=%d", len(claims), len(conflicts))

    calculations: List[Dict[str, Any]] = []
    for c in claims:
        if c.numbers and c.numbers.get("values"):
            vals = [x.get("value") for x in c.numbers["values"] if isinstance(x.get("value"), (int, float))]
            if vals:
                calculations.append({"claim_id": c.id, "mean": sum(vals) / len(vals), "count": len(vals)})

    answer = _build_answer(question, claims, conflicts, queries, limitations)
    if not scored:
        limitations.append("No items retrieved from web discovery and enrichment.")

    return EvidenceBundle(
        question=question,
        queries=queries,
        items=scored,
        claims=claims,
        conflicts=conflicts,
        calculations=calculations,
        answer=answer,
        limitations=limitations,
    )

