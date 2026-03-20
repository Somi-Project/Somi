from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import List

from workshop.toolbox.stacks.research_core.evidence_schema import Claim, EvidenceItem


_RECENCY_TERMS = ("latest", "current", "today", "now", "updated", "newest", "most recent", "recent")
_OFFICIAL_TERMS = ("guideline", "guidelines", "official", "policy", "recommendation", "documentation", "docs")
_HIGH_STAKES_TERMS = ("hypertension", "treatment", "dose", "clinical", "drug", "legal", "invest")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


@dataclass
class AdequacyReport:
    adequate: bool
    missing: List[str] = field(default_factory=list)
    follow_up_queries: List[str] = field(default_factory=list)


def _extract_year(text: str | None) -> int | None:
    if not text:
        return None
    match = _YEAR_RE.search(str(text))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _has_recent_source(items: List[EvidenceItem], *, window_years: int = 4) -> bool:
    now_year = datetime.now(timezone.utc).year
    for item in items:
        year = _extract_year(item.published_date) or _extract_year(item.snippet) or _extract_year(item.title)
        if year is not None and year >= (now_year - window_years):
            return True
    return False


def _has_authoritative_source(items: List[EvidenceItem], *, github_mode: bool = False) -> bool:
    if github_mode:
        return any("github.com/" in str(item.url or "").lower() for item in items)
    return any(item.source_type in {"official", "academic", "vendor"} for item in items)


def _dedupe_queries(rows: List[str]) -> List[str]:
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


def assess_answer_adequacy(
    question: str,
    *,
    items: List[EvidenceItem],
    claims: List[Claim],
    conflicts: List[dict],
    domain_key: str = "general",
    browse_mode: str = "deep",
) -> AdequacyReport:
    q = str(question or "").strip()
    ql = q.lower()
    missing: List[str] = []
    follow_ups: List[str] = []
    high_claims = [claim for claim in claims if str(claim.confidence or "").lower() in {"high", "medium"}]
    needs_recency = any(term in ql for term in _RECENCY_TERMS)
    needs_authority = any(term in ql for term in _OFFICIAL_TERMS) or any(term in ql for term in _HIGH_STAKES_TERMS)
    github_mode = browse_mode == "github"

    if not items:
        missing.append("no_sources")
        follow_ups.extend([f"{q} official source", f"{q} overview"])

    if not high_claims:
        missing.append("low_corroboration")
        follow_ups.extend([f"{q} overview", f"{q} documentation" if github_mode else f"{q} consensus"])

    if needs_recency and not _has_recent_source(items):
        missing.append("missing_recent_source")
        follow_ups.extend([f"{q} 2026", f"{q} updated official source"])

    if needs_authority and not _has_authoritative_source(items, github_mode=github_mode):
        missing.append("missing_authority")
        if github_mode:
            follow_ups.extend([f"site:github.com {q}", f"{q} readme"])
        elif domain_key == "biomed":
            follow_ups.extend([f"site:who.int {q}", f"site:cdc.gov {q}"])
        else:
            follow_ups.extend([f"{q} official source", f"{q} documentation"])

    if conflicts and not high_claims:
        missing.append("unresolved_conflict")
        follow_ups.append(f"{q} consensus")

    return AdequacyReport(
        adequate=not missing,
        missing=missing,
        follow_up_queries=_dedupe_queries(follow_ups)[:6],
    )
