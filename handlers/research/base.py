# handlers/research/base.py
"""
Research foundation for Somi.

Goal:
- Provide ONE stable result contract used by all research domains (biomed, coding, etc).
- Keep scoring/ranking logic centralized so domains remain easy to add/replace without breaking interoperability.

This module is intentionally:
- dependency-light (stdlib only)
- deterministic (no LLM needed)
"""

from __future__ import annotations


import math
import random
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# -----------------------------
# Result contract
# -----------------------------
@dataclass
class ResearchResult:
    title: str
    url: str
    description: str

    source: str
    domain: str

    id_type: str
    id: str

    published: str
    evidence_level: str

    score: float = 0.0
    match_score: float = 0.0
    intent_alignment: float = 0.0

    evidence_spans: List[str] = field(default_factory=list)  # <- FIXED

    volatile: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def pack_result(
    *,
    title: str,
    url: str,
    description: str,
    source: str,
    domain: str,
    id_type: str = "none",
    id: str = "",
    published: str = "",
    evidence_level: str = "other",
    evidence_spans: Optional[List[str]] = None,
) -> Dict[str, Any]:
    rr = ResearchResult(
        title=(title or "").strip(),
        url=(url or "").strip(),
        description=(description or "").strip(),
        source=(source or "").strip() or "other",
        domain=(domain or "").strip() or "general",
        id_type=(id_type or "none").strip(),
        id=(id or "").strip(),
        published=_parse_date_any(published),
        evidence_level=(evidence_level or "other").strip() or "other",
        evidence_spans=evidence_spans or [],
    )
    return rr.to_dict()


# -----------------------------
# Text / date utils
# -----------------------------
def now_utc() -> datetime:
    return datetime.utcnow()


def safe_trim(s: str, n: int) -> str:
    s = (s or "").strip().replace("\r", "")
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


def normalize_query(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(r"\s+", " ", q)
    return q


def _parse_date_any(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"[Tt].*$", "", s).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    # common loose format: "2024 Jan 12"
    try:
        dt = datetime.strptime(s, "%Y %b %d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def days_old(published_ymd: str) -> Optional[int]:
    d = _parse_date_any(published_ymd)
    if not d:
        return None
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return max(0, (now_utc() - dt).days)
    except Exception:
        return None


def make_spans_from_text(text: str, *, max_spans: int = 4, span_char_limit: int = 260) -> List[str]:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return []
    parts = re.split(r"(?<=[\.\!\?])\s+", t)
    spans: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        spans.append(safe_trim(p, span_char_limit))
        if len(spans) >= max_spans:
            break
    if not spans:
        spans = [safe_trim(t, span_char_limit)]
    return spans


# -----------------------------
# Identifier detection
# -----------------------------
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
PMID_LABELED_RE = re.compile(r"\bpmid[:\s]*([0-9]{6,9})\b", re.IGNORECASE)
ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b", re.IGNORECASE)
ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+\/\d{7})(v\d+)?\b", re.IGNORECASE)
NCT_RE = re.compile(r"\bNCT(\d{8})\b", re.IGNORECASE)


def extract_doi(q: str) -> Optional[str]:
    m = DOI_RE.search(q or "")
    if not m:
        return None
    return m.group(0).rstrip(").,;\"'")


def extract_pmid(q: str) -> Optional[str]:
    m = PMID_LABELED_RE.search(q or "")
    if m:
        return m.group(1)
    ql = (q or "").lower()
    if "pubmed" in ql or "pmid" in ql:
        m2 = re.search(r"\b([0-9]{6,9})\b", ql)
        if m2:
            return m2.group(1)
    return None


def extract_arxiv_id(q: str) -> Optional[str]:
    ql = (q or "").lower()

    m = ARXIV_NEW_RE.search(q or "")
    if m:
        ax = (m.group(1) + (m.group(2) or "")).strip()
        if "arxiv" in ql or "abs/" in ql or len(ax) >= 9:
            return ax

    m2 = ARXIV_OLD_RE.search(q or "")
    if m2:
        ax = (m2.group(1) + (m2.group(2) or "")).strip()
        if "arxiv" in ql or "abs/" in ql or len(normalize_query(q)) <= 40:
            return ax

    return None


def extract_nct(q: str) -> Optional[str]:
    m = NCT_RE.search(q or "")
    if m:
        return f"NCT{m.group(1)}"
    ql = (q or "").lower()
    if "clinicaltrials" in ql or "trial id" in ql or "nct" in ql:
        m2 = re.search(r"\b(nct\s*[:#]?\s*\d{8})\b", ql, re.IGNORECASE)
        if m2:
            return re.sub(r"\s+", "", m2.group(1)).upper().replace(":", "").replace("#", "")
    return None


def id_type_and_value(q: str) -> Tuple[str, str]:
    # Priority matters
    pmid = extract_pmid(q)
    if pmid:
        return ("pmid", pmid)
    doi = extract_doi(q)
    if doi:
        return ("doi", doi)
    nct = extract_nct(q)
    if nct:
        return ("nct", nct)
    ax = extract_arxiv_id(q)
    if ax:
        return ("arxiv", ax)
    return ("none", "")


def is_identifier_query(q: str) -> bool:
    t, v = id_type_and_value(q or "")
    return bool(v and t != "none")


# -----------------------------
# Evidence inference + scoring
# -----------------------------
EVIDENCE_BASE = {
    "guideline": 1.00,
    "systematic_review": 0.95,
    "rct": 0.90,
    "observational": 0.78,
    "review": 0.70,
    "case_report": 0.62,
    "preprint": 0.58,
    "other": 0.55,
}

# Default source authority; domains can override/extend
SOURCE_AUTHORITY = {
    "pubmed": 0.92,
    "europepmc": 0.90,
    "clinicaltrials": 0.90,
    "crossref": 0.82,
    "semanticscholar": 0.84,
    "arxiv": 0.72,
    "gdelt": 0.70,
    "wikidata": 0.78,
    "openlibrary": 0.76,
    "other": 0.70,
}


def infer_evidence_level(title: str, pub_types: Optional[Sequence[str]] = None, source: str = "") -> str:
    tl = (title or "").lower()
    pts = [p.lower() for p in (pub_types or []) if isinstance(p, str)]
    joined = " | ".join(pts)

    def has_any(hay: str, needles: Sequence[str]) -> bool:
        return any(n in hay for n in needles)

    if has_any(tl, ["guideline", "practice guideline", "consensus", "position statement"]) or has_any(joined, ["practice guideline", "guideline"]):
        return "guideline"
    if has_any(tl, ["systematic review", "meta-analysis", "metaanalysis"]) or has_any(joined, ["meta-analysis", "systematic review"]):
        return "systematic_review"
    if has_any(tl, ["randomized", "randomised", "trial"]) or has_any(joined, ["randomized controlled trial", "clinical trial"]):
        return "rct"
    if has_any(tl, ["cohort", "case-control", "cross-sectional", "observational"]):
        return "observational"
    if has_any(tl, ["case report", "case series"]) or has_any(joined, ["case reports"]):
        return "case_report"
    if has_any(tl, ["review"]) or has_any(joined, ["review"]):
        return "review"
    if source == "arxiv" or has_any(tl, ["preprint", "medrxiv", "biorxiv"]):
        return "preprint"
    return "other"


def token_set(s: str) -> set:
    # cheap + deterministic
    return set(re.findall(r"[a-z]{3,}", (s or "").lower()))


def match_score(query: str, title: str, abstractish: str) -> float:
    q = token_set(query)
    if not q:
        return 0.5
    t = token_set((title or "") + " " + (abstractish or ""))
    inter = len(q & t)
    return float(0.10 + 0.90 * (inter / max(1, len(q))))  # 0.10..1.0


def recency_factor(published_ymd: str) -> float:
    days = days_old(published_ymd)
    if days is None:
        return 0.80
    # smooth decay over ~2.5 years
    return float(0.35 + 0.65 * math.exp(-days / 900.0))


def score_record(
    *,
    query: str,
    source: str,
    evidence_level: str,
    published: str,
    id_type: str,
    want_id_type: str,
    intent_alignment: float,
    title: str,
    description: str,
    source_authority: Optional[Dict[str, float]] = None,
) -> Tuple[float, float]:
    auth_map = source_authority or SOURCE_AUTHORITY
    base = EVIDENCE_BASE.get(evidence_level, EVIDENCE_BASE["other"])
    auth = auth_map.get(source, auth_map.get("other", 0.70))
    rec = recency_factor(published)
    ms = match_score(query, title, description)

    if want_id_type and want_id_type != "none":
        id_boost = 1.35 if id_type == want_id_type else 0.80
    else:
        id_boost = 1.0

    # keep intent alignment in [0, 1]
    align = max(0.0, min(1.0, float(intent_alignment)))

    # tiny deterministic-ish jitter to break ties without chaos
    jitter = 0.995 + random.random() * 0.01
    score = float(base * auth * rec * ms * (0.60 + 0.40 * align) * id_boost * jitter)
    return score, ms


def rank_and_finalize(
    results: List[Dict[str, Any]],
    *,
    query: str,
    want_id_type: str = "none",
    max_total: int = 12,
    dedupe: bool = True,
    source_authority: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    if not results:
        return []

    q = normalize_query(query)

    items = [r for r in results if isinstance(r, dict)]

    if dedupe:
        seen: Dict[str, Dict[str, Any]] = {}
        for r in items:
            url = str(r.get("url") or "").strip()
            idt = str(r.get("id_type") or "none").strip()
            idv = str(r.get("id") or "").strip()
            title = str(r.get("title") or "").strip().lower()

            if idt in ("pmid", "doi", "arxiv", "nct") and idv:
                key = f"{idt}:{idv.lower()}"
            elif url:
                key = f"url:{url.lower()}"
            elif title:
                key = f"title:{title}"
            else:
                continue

            if key not in seen:
                seen[key] = r
            else:
                # merge best fields
                if not seen[key].get("description") and r.get("description"):
                    seen[key]["description"] = r["description"]
                if (not seen[key].get("evidence_spans")) and r.get("evidence_spans"):
                    seen[key]["evidence_spans"] = r["evidence_spans"]

        items = list(seen.values())

    for r in items:
        title = str(r.get("title") or "").strip()
        desc = str(r.get("description") or "").strip()
        source = str(r.get("source") or "other").strip() or "other"

        r["title"] = title
        r["description"] = desc
        r["source"] = source

        r["published"] = _parse_date_any(str(r.get("published") or ""))

        ev = str(r.get("evidence_level") or "").strip()
        if not ev:
            ev = infer_evidence_level(title, pub_types=None, source=source)
        r["evidence_level"] = ev

        spans = r.get("evidence_spans")
        if not isinstance(spans, list) or not spans:
            if desc:
                r["evidence_spans"] = make_spans_from_text(desc)
            else:
                r["evidence_spans"] = [f"Title: {safe_trim(title, 260)}"]

        # intent_alignment is optional; default mid
        align = float(r.get("intent_alignment") or 0.6)

        sc, ms = score_record(
            query=q,
            source=source,
            evidence_level=ev,
            published=str(r.get("published") or ""),
            id_type=str(r.get("id_type") or "none"),
            want_id_type=want_id_type,
            intent_alignment=align,
            title=title,
            description=desc,
            source_authority=source_authority,
        )
        r["score"] = float(sc)
        r["match_score"] = float(ms)
        r["intent_alignment"] = float(max(0.0, min(1.0, align)))

        # research is volatile by default
        r["volatile"] = bool(r.get("volatile", True))

    items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return items[: max(1, int(max_total))]
