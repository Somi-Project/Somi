# handlers/research/agentpedia.py
"""
Agentpedia Orchestrator — memory-first research + write-back curation.

Purpose:
- Local-first (Verified / Textbook / Researched stores)
- If weak coverage -> call ResearchRouter (structured web)
- Optionally write-back high quality router hits into ResearchedScienceStore
- Return ONE unified ranked list of ResearchResult dicts compatible with websearch.py

Design goals:
- Deterministic
- Safe by default (write_back OFF unless enabled)
- Freeze-resistant (timeouts around router)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from handlers.research.base import (
    id_type_and_value,
    normalize_query,
    pack_result,
    rank_and_finalize,
    safe_trim,
)
from handlers.research.router import ResearchRouter
from handlers.research.science_stores import (
    VerifiedScienceStore,
    ResearchedScienceStore,
    TextbookFactsStore,
    AgentpediaManager,
)

logger = logging.getLogger(__name__)

# -----------------------------
# Tunables
# -----------------------------
DEFAULT_LOCAL_LIMIT = 6
DEFAULT_TOTAL_LIMIT = 12
DEFAULT_WRITEBACK_LIMIT = 4
DEFAULT_MIN_MATCH_FOR_WRITEBACK = 0.50
DEFAULT_ROUTER_TIMEOUT_S = 18.0


def _collapse_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _is_url(s: str) -> bool:
    s = (s or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def _looks_insufficient(results: List[Dict[str, Any]]) -> bool:
    """
    Coverage gate:
    - empty -> insufficient
    - sentinel -> insufficient
    - low match_score -> insufficient
    - tiny/noisy local hit -> insufficient
    """
    if not results:
        return True

    try:
        top = results[0] if isinstance(results[0], dict) else {}
        top_title = str(top.get("title") or "").lower().strip()
        if "insufficient coverage" in top_title:
            return True

        ms = top.get("match_score")
        if ms is not None and float(ms) < 0.35:
            return True

        desc = str(top.get("description") or "").strip()
        spans = top.get("evidence_spans")
        span0 = ""
        if isinstance(spans, list) and spans:
            span0 = str(spans[0] or "").strip()

        best_text = desc or span0 or str(top.get("title") or "").strip()
        if len(results) < 2 and len(best_text) < 40:
            return True
    except Exception:
        return True

    return False


def _map_store_item_to_research_result(
    item: Dict[str, Any],
    *,
    domain_hint: str,
    source_label: str,
) -> Dict[str, Any]:
    title = _collapse_whitespace(str(item.get("title") or ""))
    desc = _collapse_whitespace(str(item.get("description") or item.get("fact") or ""))
    url = _collapse_whitespace(str(item.get("url") or item.get("source") or ""))

    store = str(item.get("store") or item.get("source") or source_label).lower().strip()
    conf = str(item.get("confidence") or "").lower().strip()

    if store == "verified":
        ev = "guideline" if "guideline" in title.lower() else "systematic_review"
    elif store == "textbook":
        ev = "review"
    else:
        ev = "observational" if conf in ("high", "very_high") else "other"

    spans: List[str] = []
    if desc:
        spans = [safe_trim(desc, 260)]
    elif title:
        spans = [safe_trim(title, 260)]
    else:
        spans = ["Agentpedia fact."]

    return pack_result(
        title=title or "Agentpedia fact",
        url=url if _is_url(url) else "",
        description=safe_trim(desc, 360) if desc else safe_trim(title, 360),
        source=store or source_label,
        domain=domain_hint or "biomed",
        id_type="none",
        id="",
        published="",
        evidence_level=ev,
        evidence_spans=spans[:3],
    )


@dataclass
class AgentpediaConfig:
    local_limit: int = DEFAULT_LOCAL_LIMIT
    total_limit: int = DEFAULT_TOTAL_LIMIT
    write_back: bool = False
    writeback_limit: int = DEFAULT_WRITEBACK_LIMIT
    min_match_for_writeback: float = DEFAULT_MIN_MATCH_FOR_WRITEBACK
    router_timeout_s: float = DEFAULT_ROUTER_TIMEOUT_S


class Agentpedia:
    def __init__(
        self,
        *,
        config: Optional[AgentpediaConfig] = None,
        write_back: Optional[bool] = None,
        local_limit: Optional[int] = None,
        total_limit: Optional[int] = None,
        writeback_limit: Optional[int] = None,
        router_timeout_s: Optional[float] = None,
    ):
        cfg = config or AgentpediaConfig()

        if write_back is not None:
            cfg.write_back = bool(write_back)
        if local_limit is not None:
            cfg.local_limit = int(local_limit)
        if total_limit is not None:
            cfg.total_limit = int(total_limit)
        if writeback_limit is not None:
            cfg.writeback_limit = int(writeback_limit)
        if router_timeout_s is not None:
            cfg.router_timeout_s = float(router_timeout_s)

        cfg.local_limit = max(1, cfg.local_limit)
        cfg.total_limit = max(1, cfg.total_limit)
        cfg.writeback_limit = max(0, cfg.writeback_limit)
        cfg.router_timeout_s = max(4.0, float(cfg.router_timeout_s))

        self.cfg = cfg

        self.verified = VerifiedScienceStore()
        self.researched = ResearchedScienceStore()
        self.textbook = TextbookFactsStore()
        self.manager = AgentpediaManager(
            verified=self.verified,
            researched=self.researched,
            textbook=self.textbook,
        )

        self.router = ResearchRouter()

    async def _router_search_bounded(self, q: str) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Returns (results, timed_out)
        """
        try:
            res = await asyncio.wait_for(self.router.search(q), timeout=self.cfg.router_timeout_s)
            if isinstance(res, list):
                return (self._sanitize_results(res), False)
            return ([], False)
        except asyncio.TimeoutError:
            return ([], True)
        except Exception as e:
            logger.warning(f"Agentpedia router.search failed: {type(e).__name__}: {e}")
            return ([], False)

    def _router_results_unusable_for_id(self, results: List[Dict[str, Any]]) -> bool:
        """
        For identifier queries, router is only 'usable' if it yields at least one URL-backed result.
        Sentinel-only output is treated as unusable so websearch can fallback cleanly.
        """
        if not results:
            return True
        urls = 0
        for r in results:
            if not isinstance(r, dict):
                continue
            u = str(r.get("url") or "").strip()
            if u.startswith("http"):
                urls += 1
        return urls < 1

    def _id_warning(self, *, q: str, want_id_type: str, want_id: str) -> Dict[str, Any]:
        msg = (
            "Identifier lookup could not be verified from structured live sources "
            "(router timeout/unavailable/insufficient). Showing any local cached facts if present. "
            "Web fallback recommended."
        )
        return pack_result(
            title="Agentpedia insufficient coverage",
            url="",
            description=msg,
            source="agentpedia",
            domain="agentpedia",
            id_type=want_id_type or "none",
            id=want_id or "",
            published="",
            evidence_level="other",
            evidence_spans=[safe_trim(msg, 260), safe_trim(f"Query: {q}", 260)],
        )

    async def search(
        self,
        query: str,
        *,
        domain_hint: str = "biomed",
        allow_router: bool = True,
        write_back: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        q = normalize_query(query)
        if not q:
            return [pack_result(
                title="Agentpedia insufficient coverage",
                url="",
                description="Empty query.",
                source="agentpedia",
                domain="agentpedia",
                evidence_level="other",
                evidence_spans=["Empty query."],
            )]

        want_id_type, want_id = id_type_and_value(q)

        local_results = self._local_lookup(q, domain_hint=domain_hint)

        if not want_id and not _looks_insufficient(local_results):
            return rank_and_finalize(
                self._sanitize_results(local_results),
                query=q,
                want_id_type=want_id_type,
                max_total=self.cfg.total_limit,
                dedupe=True,
            )

        router_results: List[Dict[str, Any]] = []
        router_timed_out = False
        if allow_router:
            router_results, router_timed_out = await self._router_search_bounded(q)

        merged: List[Dict[str, Any]] = []
        merged.extend(self._sanitize_results(local_results))
        merged.extend(self._sanitize_results(router_results))

        if not merged:
            return [pack_result(
                title="Agentpedia insufficient coverage",
                url="",
                description="No local results and router returned nothing; web fallback recommended.",
                source="agentpedia",
                domain="agentpedia",
                evidence_level="other",
                evidence_spans=[safe_trim(f"Query: {q}", 260)],
            )]

        ranked = rank_and_finalize(
            merged,
            query=q,
            want_id_type=want_id_type,
            max_total=self.cfg.total_limit,
            dedupe=True,
        )

        # ---- FIX: identifier warning is injected AFTER ranking so it never gets buried/dropped ----
        if want_id:
            router_bad = router_timed_out or self._router_results_unusable_for_id(router_results)
            if router_bad:
                warning = self._id_warning(q=q, want_id_type=want_id_type or "none", want_id=want_id or "")
                ranked = [warning] + [r for r in ranked if isinstance(r, dict)]
                ranked = ranked[: self.cfg.total_limit]

        effective_write_back = self.cfg.write_back if write_back is None else bool(write_back)
        if effective_write_back:
            try:
                self._write_back_from_ranked(
                    ranked,
                    query=q,
                    domain_hint=domain_hint,
                    want_id_type=want_id_type,
                    want_id=want_id,
                )
            except Exception as e:
                logger.debug(f"Agentpedia write-back failed: {type(e).__name__}: {e}")

        return ranked

    def _local_lookup(self, q: str, *, domain_hint: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        try:
            verified = self.verified.lookup(q, min_confidence="high", limit=self.cfg.local_limit)
        except Exception:
            verified = []

        try:
            textbook = self.textbook.lookup(q, limit=self.cfg.local_limit)
        except Exception:
            textbook = []

        try:
            researched = self.researched.lookup(q, domain=None, limit=self.cfg.local_limit)
        except Exception:
            researched = []

        for it in (verified or []):
            if isinstance(it, dict):
                out.append(_map_store_item_to_research_result(it, domain_hint=domain_hint, source_label="verified"))
        for it in (textbook or []):
            if isinstance(it, dict):
                out.append(_map_store_item_to_research_result(it, domain_hint=domain_hint, source_label="textbook"))
        for it in (researched or []):
            if isinstance(it, dict):
                out.append(_map_store_item_to_research_result(it, domain_hint=domain_hint, source_label="researched"))

        return out

    def _sanitize_results(self, results: Any) -> List[Dict[str, Any]]:
        if not results or not isinstance(results, list):
            return []
        out: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, dict):
                out.append(r)
        return out

    def _write_back_from_ranked(
        self,
        ranked: List[Dict[str, Any]],
        *,
        query: str,
        domain_hint: str,
        want_id_type: str,
        want_id: str,
    ) -> None:
        if not ranked or self.cfg.writeback_limit <= 0:
            return

        to_store: List[Dict[str, Any]] = []

        for r in ranked:
            if not isinstance(r, dict):
                continue

            src = str(r.get("source") or "").lower().strip()
            if src in ("verified", "textbook", "researched"):
                continue

            title = _collapse_whitespace(str(r.get("title") or ""))
            desc = _collapse_whitespace(str(r.get("description") or ""))
            url = _collapse_whitespace(str(r.get("url") or ""))

            if not title or not _is_url(url):
                continue

            ms = r.get("match_score")
            try:
                if ms is not None and float(ms) < float(self.cfg.min_match_for_writeback):
                    continue
            except Exception:
                pass

            spans = r.get("evidence_spans")
            snippet = ""
            if isinstance(spans, list) and spans:
                snippet = _collapse_whitespace(str(spans[0] or ""))
            elif desc:
                snippet = safe_trim(desc, 260)

            fact = title
            if desc:
                fact = f"{title} — {safe_trim(desc, 240)}"

            to_store.append({
                "topic": safe_trim(query, 140),
                "fact": safe_trim(fact, 420),
                "source": url,
                "confidence": "medium",
                "domain": domain_hint or str(r.get("domain") or "general"),
                "tags": safe_trim(f"{src},{want_id_type}".strip(","), 80),
                "evidence_snippet": safe_trim(snippet, 260),
            })

            if len(to_store) >= self.cfg.writeback_limit:
                break

        if not to_store:
            return

        # Deduplicate by (url, fact)
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for f in to_store:
            key = (str(f.get("source") or "").strip(), str(f.get("fact") or "").strip())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(f)
        to_store = deduped

        if not to_store:
            return

        try:
            for f in to_store[:2]:
                conflicts = self.manager.detect_conflicts(f["topic"], f["fact"], threshold=0.84)
                if conflicts:
                    logger.debug(f"Agentpedia conflict candidates: {len(conflicts)} for topic='{f['topic'][:50]}'")
        except Exception:
            pass

        try:
            added = self.researched.add_facts(to_store, domain=domain_hint)
            try:
                added_n = int(added)
            except Exception:
                added_n = 0
            logger.info(f"Agentpedia write-back: stored {added_n}/{len(to_store)} researched facts")
        except Exception as e:
            logger.debug(f"ResearchedScienceStore.add_facts failed: {type(e).__name__}: {e}")
            return
