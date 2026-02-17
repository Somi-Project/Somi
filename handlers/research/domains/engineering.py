"""
EngineeringDomain — free, no-auth engineering / CS / applied science retrieval.

Sources:
- arXiv (export API)
- Crossref (REST)
- Semantic Scholar (Graph API; no key required for basic usage, rate-limited)
- OpenAlex (REST)

Returns list[dict] matching handlers/research/base.py contract via pack_result().
Ranking is handled centrally by base.rank_and_finalize() (or your router).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from handlers.research.searxng import search_searxng 

from handlers.research.base import (
    extract_arxiv_id,
    extract_doi,
    id_type_and_value,
    infer_evidence_level,
    make_spans_from_text,
    normalize_query,
    pack_result,
    safe_trim,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 8.0
HTTP_SEM_LIMIT = 6
SRC_SEM_LIMIT = 3

MAX_PER_SOURCE = 8


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
    try:
        dt = datetime.strptime(s, "%Y %b %d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _xml_unescape(s: str) -> str:
    s = (s or "")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = s.replace("&quot;", '"').replace("&#39;", "'")
    return s


def _looks_like_engineering(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "ieee", "acm", "conference", "proceedings",
        "signal processing", "control", "pid", "kalman", "state space", "system identification",
        "rf", "antenna", "circuit", "pcb", "verilog", "vhdl", "embedded", "microcontroller",
        "finite element", "fea", "cad", "thermodynamics", "fluid", "aerodynamics",
        "computer vision", "nlp", "transformer", "llm", "diffusion", "reinforcement learning",
        "deep learning", "machine learning",
    ])


def _normalize_doi_input(x: str) -> str:
    x = (x or "").strip()
    if not x:
        return ""
    m = re.search(r"doi\.org/(10\.\d{4,9}/\S+)", x, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(").,;\"'")
    d = extract_doi(x)
    return (d or x).strip().rstrip(").,;\"'")


# --- NEW: Simple OpenAlex abstract reconstruction ---
def _reconstruct_openalex_abstract(inv_index: Optional[Dict[str, Any]]) -> str:
    if not isinstance(inv_index, dict):
        return ""
    words = []
    for word, positions in sorted(inv_index.items(), key=lambda x: min(x[1])):
        words.extend([word] * len(positions))
    return " ".join(words)


class EngineeringDomain:
    DOMAIN = "engineering"

    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = float(timeout_s)
        self._http_sem = asyncio.Semaphore(HTTP_SEM_LIMIT)
        self._src_sem = asyncio.Semaphore(SRC_SEM_LIMIT)

    async def search(self, query: str, *, retries: int = 2, backoff_factor: float = 0.5) -> List[Dict[str, Any]]:
        q = normalize_query(query)
        if not q:
            return [self._sentinel("Science search insufficient coverage", "Empty query.")]

        want_id_type, want_id = id_type_and_value(q)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s,
                headers={"User-Agent": "SomiEngineering/1.0"},
                follow_redirects=True,
            ) as client:

                # --- Identifier-first: DOI / arXiv ---
                if want_id_type in ("doi", "arxiv") and want_id:
                    resolved = await self._resolve_identifier(
                        client, want_id_type, want_id, retries=retries, backoff_factor=backoff_factor
                    )
                    if resolved and not self._is_only_sentinel_list(resolved):
                        return resolved

                # --- Topic search (parallel) ---
                tasks: List[Any] = [
                    self._search_arxiv(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_crossref(client, q, max_n=min(MAX_PER_SOURCE, 6), retries=retries, backoff_factor=backoff_factor),
                    self._search_semantic_scholar(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_openalex(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    # NEW: Parallel SearXNG enrichment
                    search_searxng(client, q, max_results=6, domain=self.DOMAIN),
                ]

                gathered = await asyncio.gather(*tasks, return_exceptions=True)

                merged: List[Dict[str, Any]] = []
                for g in gathered:
                    if isinstance(g, list):
                        merged.extend([x for x in g if isinstance(x, dict)])

                non_sentinels = [r for r in merged if not self._is_sentinel_dict(r)]
                merged = non_sentinels or merged

                if not merged:
                    return [self._sentinel(
                        "Science search insufficient coverage",
                        "No results returned from arXiv/Crossref/SemanticScholar/OpenAlex.",
                        query=q,
                    )]

                eng = _looks_like_engineering(q)
                for r in merged:
                    src = str(r.get("source") or "")
                    if src == "arxiv":
                        r["intent_alignment"] = 1.0 if eng else 0.85
                    elif src in ("semanticscholar", "openalex"):
                        r["intent_alignment"] = 0.85 if eng else 0.80
                    elif src == "crossref":
                        r["intent_alignment"] = 0.70
                    else:
                        r["intent_alignment"] = 0.70

                return merged

        except Exception as e:
            logger.warning(f"EngineeringDomain search failed: {type(e).__name__}: {e}")
            return [self._sentinel(
                "Science search unavailable",
                "Engineering sources unreachable (network/client error).",
                query=q,
            )]

    # -----------------------------
    # Sentinels (unchanged)
    # -----------------------------
    def _sentinel(self, title: str, msg: str, *, query: str = "") -> Dict[str, Any]:
        spans = [safe_trim(msg, 260)]
        if query:
            spans.append(safe_trim(f"Query: {query}", 260))

        r = pack_result(
            title=title,
            url="",
            description=msg,
            source="engineering",
            domain=self.DOMAIN,
            id_type="none",
            id="",
            published="",
            evidence_level="other",
            evidence_spans=spans[:4],
        )
        r["volatile"] = True
        return r

    def _is_sentinel_dict(self, r: Dict[str, Any]) -> bool:
        t = str((r or {}).get("title") or "").lower()
        return ("science search insufficient coverage" in t) or ("science search unavailable" in t)

    def _is_only_sentinel_list(self, items: List[Dict[str, Any]]) -> bool:
        if not items:
            return True
        return all(self._is_sentinel_dict(r) for r in items if isinstance(r, dict))

    # -----------------------------
    # HTTP helpers (unchanged)
    # -----------------------------

    # -----------------------------
    # Identifier resolution (unchanged)
    # -----------------------------

    # -----------------------------
    # arXiv — ENHANCED: authors + PDF
    # -----------------------------
    async def _search_arxiv(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qs = quote_plus(q)
            url = (
                f"http://export.arxiv.org/api/query"
                f"?search_query=all:{qs}&start=0&max_results={int(max_n)}&sortBy=submittedDate&sortOrder=descending"
            )
            txt = await self._get_text(client, url, retries=retries, backoff_factor=backoff_factor)
            if not txt:
                return []

            out: List[Dict[str, Any]] = []
            entries = re.split(r"<entry>", txt)[1:]
            for e in entries:
                title_m = re.search(r"<title>(.*?)</title>", e, re.DOTALL)
                if not title_m:
                    continue

                title = _xml_unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()).rstrip(".")
                if not title or title.lower() == "arxiv query results":
                    continue

                idm = re.search(r"<id>(.*?)</id>", e, re.DOTALL)
                abs_url = (idm.group(1).strip() if idm else "").strip()

                pm = re.search(r"<published>(.*?)</published>", e, re.DOTALL)
                published = _parse_date_any(pm.group(1).strip() if pm else "")

                sm = re.search(r"<summary>(.*?)</summary>", e, re.DOTALL)
                summ = _xml_unescape(re.sub(r"\s+", " ", sm.group(1)).strip()) if sm else ""

                # Authors
                auths = []
                for a in re.finditer(r"<author>.*?<name>(.*?)</name>", e, re.DOTALL):
                    name = _xml_unescape(a.group(1).strip())
                    if name:
                        auths.append(name)
                authors_str = ", ".join(auths[:6]) + (" et al." if len(auths) > 6 else "")

                # arXiv ID + PDF
                axid = extract_arxiv_id(abs_url or "") or ""
                pdf_url = f"https://arxiv.org/pdf/{axid}.pdf" if axid else ""

                spans = [f"Authors: {authors_str}"] if authors_str else []
                spans += make_spans_from_text(summ) if summ else []
                spans.append(f"PDF: {pdf_url}" if pdf_url else "PDF: Not directly available")

                r = pack_result(
                    title=title,
                    url=abs_url or (f"https://arxiv.org/abs/{axid}" if axid else ""),
                    description=safe_trim(summ, 1200),
                    source="arxiv",
                    domain=self.DOMAIN,
                    id_type="arxiv" if axid else "url",
                    id=axid or abs_url,
                    published=published,
                    evidence_level="preprint",
                    evidence_spans=spans[:5],
                )
                r["volatile"] = True
                out.append(r)
            return out

    # _fetch_arxiv_by_id can be similarly enhanced (authors + PDF) — omitted for brevity, copy pattern above

    # -----------------------------
    # Semantic Scholar — ENHANCED: authors, venue, openAccessPdf
    # -----------------------------
    async def _search_semantic_scholar(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qq = quote_plus(q)
            fields = quote_plus("title,abstract,year,url,externalIds,authors,venue,openAccessPdf")
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={qq}&limit={int(max_n)}&fields={fields}"
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js or not isinstance(js, dict):
                return []

            data = js.get("data", [])
            out: List[Dict[str, Any]] = []
            for it in data:
                if not isinstance(it, dict):
                    continue

                title = str(it.get("title") or "").strip().rstrip(".")
                if not title:
                    continue
                abstract = str(it.get("abstract") or "").strip()
                year = it.get("year")
                url2 = str(it.get("url") or "").strip()

                ext = it.get("externalIds") or {}
                doi = str(ext.get("DOI") or "").strip()
                arxiv = str(ext.get("ArXiv") or "").strip()

                # Authors
                authors_list = it.get("authors", [])
                authors_str = ", ".join(a.get("name", "") for a in authors_list[:6])
                if len(authors_list) > 6:
                    authors_str += " et al."

                # Venue
                venue = str(it.get("venue") or "").strip()

                # PDF
                pdf_url = ""
                oa = it.get("openAccessPdf")
                if isinstance(oa, dict):
                    pdf_url = str(oa.get("url") or "").strip()

                published = f"{int(year)}-01-01" if isinstance(year, (int, float)) else ""
                ev = infer_evidence_level(title, pub_types=None, source="semanticscholar")
                spans = []
                if authors_str:
                    spans.append(f"Authors: {authors_str}")
                if venue:
                    spans.append(f"Venue: {venue}")
                if pdf_url:
                    spans.append(f"Open PDF: {pdf_url}")
                spans += make_spans_from_text(abstract) if abstract else []

                id_type = "doi" if doi else ("arxiv" if arxiv else "url")
                idv = doi or arxiv or url2
                if not url2 and doi:
                    url2 = f"https://doi.org/{doi}"

                r = pack_result(
                    title=title,
                    url=url2,
                    description=safe_trim(abstract, 1200),
                    source="semanticscholar",
                    domain=self.DOMAIN,
                    id_type=id_type,
                    id=idv,
                    published=published,
                    evidence_level=ev,
                    evidence_spans=spans[:6],
                )
                r["volatile"] = True
                out.append(r)

            return out

    # -----------------------------
    # OpenAlex — ENHANCED: authors, abstract reconstruction, PDF
    # -----------------------------
    async def _search_openalex(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qq = quote_plus(q)
            url = f"https://api.openalex.org/works?search={qq}&per-page={int(max_n)}&select=title,publication_date,authorships,abstract_inverted_index,primary_location,open_access"
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js:
                return []

            results = js.get("results", [])
            out: List[Dict[str, Any]] = []
            for it in results:
                if not isinstance(it, dict):
                    continue

                title = str(it.get("title") or "").strip().rstrip(".")
                if not title:
                    continue

                published = _parse_date_any(str(it.get("publication_date") or "").strip())

                # Authors
                auths = it.get("authorships", [])
                authors_str = ", ".join(
                    a.get("author", {}).get("display_name", "") for a in auths[:6] if isinstance(a, dict)
                )
                if len(auths) > 6:
                    authors_str += " et al."

                # Abstract
                inv_idx = it.get("abstract_inverted_index")
                abstract = _reconstruct_openalex_abstract(inv_idx)

                # PDF / landing page
                oa = it.get("open_access", {})
                pdf_url = str(oa.get("oa_url") or "").strip() if isinstance(oa, dict) else ""
                landing = it.get("primary_location", {})
                landing_url = str(landing.get("landing_page_url") or "") if isinstance(landing, dict) else ""

                url_final = pdf_url or landing_url or str(it.get("id") or "")

                doi = str(it.get("doi") or "").replace("https://doi.org/", "") if it.get("doi") else ""

                ev = infer_evidence_level(title, pub_types=None, source="openalex")

                spans = []
                if authors_str:
                    spans.append(f"Authors: {authors_str}")
                if pdf_url:
                    spans.append(f"Open PDF: {pdf_url}")
                spans += make_spans_from_text(abstract) if abstract else []

                id_type = "doi" if doi else "url"
                idv = doi or url_final

                r = pack_result(
                    title=title,
                    url=url_final or (f"https://doi.org/{doi}" if doi else ""),
                    description=safe_trim(abstract, 1200),
                    source="openalex",
                    domain=self.DOMAIN,
                    id_type=id_type,
                    id=idv,
                    published=published,
                    evidence_level=ev,
                    evidence_spans=spans[:6],
                )
                r["volatile"] = True
                out.append(r)

            return out