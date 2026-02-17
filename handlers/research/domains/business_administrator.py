"""
BusinessAdministratorDomain — free, no-auth retrieval for business knowledge:
company overviews, leadership, strategy, management, operations, marketing, HR,
acquisitions, revenue trends (qualitative), industry analysis, case studies, etc.

Design goals:
- Academic sources for research papers on business topics
- Wikipedia for up-to-date company profiles, recent events, leadership changes
- All sources no-key/public
- Complements finance.py (prices/rates) — this domain focuses on qualitative business intel
- Parallel searches
- Graceful sentinel fallback to general web search (for breaking news, deep financials)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from handlers.research.searxng import search_searxng 
from handlers.research.base import (
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


def _looks_like_business(q: str) -> bool:
    """Broad intent detection for business/administration topics"""
    ql = (q or "").lower()
    triggers = [
        "business", "company", "ceo", "executive", "leadership", "management",
        "strategy", "operations", "marketing", "sales", "hr", "human resources",
        "acquisition", "merger", "revenue", "profit", "market share", "competitor",
        "startup", "venture", "funding", "valuation", "ipo", "quarterly report",
        "swot", "porter", "five forces", "case study", "harvard business",
        "mba", "kpi", "okr", "supply chain", "logistics", "corporate governance",
    ]
    return any(t in ql for t in triggers)


def _reconstruct_openalex_abstract(inv_index: Optional[Dict[str, Any]]) -> str:
    if not isinstance(inv_index, dict):
        return ""
    words = []
    for word, positions in sorted(inv_index.items(), key=lambda x: min(x[1])):
        words.extend([word] * len(positions))
    return " ".join(words)


class BusinessAdministratorDomain:
    DOMAIN = "business_administrator"

    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = float(timeout_s)
        self._http_sem = asyncio.Semaphore(HTTP_SEM_LIMIT)
        self._src_sem = asyncio.Semaphore(SRC_SEM_LIMIT)

    async def search(self, query: str, *, retries: int = 2, backoff_factor: float = 0.5) -> List[Dict[str, Any]]:
        q = normalize_query(query)
        if not q:
            return [self._sentinel("Science search insufficient coverage", "Empty query.")]

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s,
                headers={"User-Agent": "SomiBusiness/1.0"},
                follow_redirects=True,
            ) as client:

                # Parallel: academic + Wikipedia for company/business overviews
                tasks: List[Any] = [
                    self._search_semantic_scholar(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_openalex(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_crossref(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_arxiv(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_wikipedia(client, q, retries=retries, backoff_factor=backoff_factor),
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
                        "No relevant business data found in academic or Wikipedia sources. Falling back to general search for latest company news/financials.",
                        query=q,
                    )]

                bus = _looks_like_business(q)
                for r in merged:
                    src = str(r.get("source") or "")
                    if src == "wikipedia":
                        r["intent_alignment"] = 1.2 if bus else 0.95  # Boost for company overviews
                    elif src in ("semanticscholar", "openalex"):
                        r["intent_alignment"] = 1.0 if bus else 0.85
                    elif src == "arxiv":
                        r["intent_alignment"] = 0.90 if bus else 0.80
                    elif src == "crossref":
                        r["intent_alignment"] = 0.75
                    else:
                        r["intent_alignment"] = 0.70

                logger.info(f"BusinessAdministratorDomain returned {len(merged)} results for '{q}'")
                return merged

        except Exception as e:
            logger.warning(f"BusinessAdministratorDomain search failed: {type(e).__name__}: {e}")
            return [self._sentinel(
                "Science search unavailable",
                "Business sources unreachable (network error).",
                query=q,
            )]

    # -----------------------------
    # Sentinels
    # -----------------------------
    def _sentinel(self, title: str, msg: str, *, query: str = "") -> Dict[str, Any]:
        spans = [safe_trim(msg, 260)]
        if query:
            spans.append(safe_trim(f"Query: {query}", 260))

        r = pack_result(
            title=title,
            url="",
            description=msg,
            source="business_administrator",
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

    # -----------------------------
    # HTTP helpers (robust)
    # -----------------------------
    def _should_retry_status(self, status: int) -> bool:
        return status in (408, 425, 429) or (500 <= status <= 599)

    async def _sleep_backoff(self, attempt: int, backoff_factor: float, retry_after_s: Optional[float] = None) -> None:
        base = backoff_factor * (2 ** attempt)
        sleep_time = min(30.0, max(base, retry_after_s or 0))
        await asyncio.sleep(sleep_time)

    async def _get_json(self, client: httpx.AsyncClient, url: str, *, retries: int, backoff_factor: float) -> Optional[Dict[str, Any]]:
        for attempt in range(max(1, retries + 1)):
            try:
                async with self._http_sem:
                    r = await client.get(url)
                if r.status_code >= 400:
                    if self._should_retry_status(r.status_code) and attempt < retries:
                        ra = float(r.headers.get("Retry-After", 0)) if r.headers.get("Retry-After", "").isdigit() else None
                        await self._sleep_backoff(attempt, backoff_factor, ra)
                        continue
                    return None
                return r.json()
            except Exception:
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        return None

    async def _get_text(self, client: httpx.AsyncClient, url: str, *, retries: int, backoff_factor: float) -> Optional[str]:
        for attempt in range(max(1, retries + 1)):
            try:
                async with self._http_sem:
                    r = await client.get(url)
                if r.status_code >= 400:
                    if self._should_retry_status(r.status_code) and attempt < retries:
                        ra = float(r.headers.get("Retry-After", 0)) if r.headers.get("Retry-After", "").isdigit() else None
                        await self._sleep_backoff(attempt, backoff_factor, ra)
                        continue
                    return None
                return r.text
            except Exception:
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        return None

    # -----------------------------
    # Semantic Scholar — business research papers
    # -----------------------------
    async def _search_semantic_scholar(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float,
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

                authors_list = it.get("authors", [])
                authors_str = ", ".join(a.get("name", "") for a in authors_list[:6])
                if len(authors_list) > 6:
                    authors_str += " et al."
                venue = str(it.get("venue") or "").strip()

                pdf_url = ""
                oa = it.get("openAccessPdf")
                if isinstance(oa, dict):
                    pdf_url = str(oa.get("url") or "").strip()

                ext = it.get("externalIds") or {}
                doi = str(ext.get("DOI") or "").strip()
                arxiv = str(ext.get("ArXiv") or "").strip()

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
    # OpenAlex — business research
    # -----------------------------
    async def _search_openalex(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qq = quote_plus(q)
            url = f"https://api.openalex.org/works?search={qq}&per-page={int(max_n)}&select=title,publication_date,authorships,abstract_inverted_index,primary_location,open_access,journal"
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js:
                url2 = url.replace("per-page", "per_page")
                js = await self._get_json(client, url2, retries=retries, backoff_factor=backoff_factor)

            if not js or not isinstance(js, dict):
                return []

            results = js.get("results") or []
            out: List[Dict[str, Any]] = []
            for it in results:
                if not isinstance(it, dict):
                    continue

                title = str(it.get("title") or "").strip().rstrip(".")
                if not title:
                    continue

                published = str(it.get("publication_date") or "").strip()[:10]

                auths = it.get("authorships", [])
                authors_str = ", ".join(
                    a.get("author", {}).get("display_name", "") for a in auths[:6] if isinstance(a, dict)
                )
                if len(auths) > 6:
                    authors_str += " et al."

                journal = str(it.get("journal", {}).get("display_name") or "").strip()

                abstract = _reconstruct_openalex_abstract(it.get("abstract_inverted_index"))

                oa = it.get("open_access", {})
                pdf_url = str(oa.get("oa_url") or "").strip() if isinstance(oa, dict) else ""
                landing_url = str(it.get("primary_location", {}).get("landing_page_url") or "")

                url_final = pdf_url or landing_url or str(it.get("id") or "")

                doi = str(it.get("doi") or "").replace("https://doi.org/", "") if it.get("doi") else ""

                ev = infer_evidence_level(title, pub_types=None, source="openalex")

                spans = []
                if authors_str:
                    spans.append(f"Authors: {authors_str}")
                if journal:
                    spans.append(f"Journal: {journal}")
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

    # -----------------------------
    # Crossref — metadata fallback
    # -----------------------------
    async def _search_crossref(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qs = quote_plus(q)
            url = f"https://api.crossref.org/works?query={qs}&rows={int(max_n)}&sort=published&order=desc"
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js:
                return []

            items = (((js.get("message") or {}).get("items")) or [])
            out: List[Dict[str, Any]] = []

            for it in items:
                if not isinstance(it, dict):
                    continue

                title_list = it.get("title") or []
                title = str(title_list[0] or "").strip().rstrip(".") if title_list else ""
                if not title:
                    continue

                doi = str(it.get("DOI") or "").strip()
                if not doi:
                    continue

                published = ""
                pub = it.get("published-print") or it.get("published-online") or {}
                if isinstance(pub, dict):
                    parts = pub.get("date-parts", []) or []
                    if parts and parts[0]:
                        y = parts[0][0]
                        published = str(y)

                ev = infer_evidence_level(title, pub_types=None, source="crossref")

                r = pack_result(
                    title=title,
                    url=f"https://doi.org/{doi}",
                    description="",
                    source="crossref",
                    domain=self.DOMAIN,
                    id_type="doi",
                    id=doi,
                    published=published,
                    evidence_level=ev,
                    evidence_spans=[f"Title: {title}"],
                )
                r["volatile"] = True
                out.append(r)

            return out

    # -----------------------------
    # arXiv — emerging business research
    # -----------------------------
    async def _search_arxiv(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qs = quote_plus(q)
            url = f"http://export.arxiv.org/api/query?search_query=all:{qs}&start=0&max_results={int(max_n)}&sortBy=relevance&sortOrder=descending"
            txt = await self._get_text(client, url, retries=retries, backoff_factor=backoff_factor)
            if not txt:
                return []

            try:
                from xml.etree import ElementTree as ET
                root = ET.fromstring(txt)
            except Exception:
                return []

            ns = {"atom": "http://www.w3.org/2005/Atom"}
            out: List[Dict[str, Any]] = []
            for entry in root.findall("atom:entry", ns):
                title_elem = entry.find("atom:title", ns)
                title = title_elem.text if title_elem is not None else "Untitled"
                title = re.sub(r"\s+", " ", title).strip()

                summary_elem = entry.find("atom:summary", ns)
                summary = summary_elem.text if summary_elem is not None else ""
                summary = re.sub(r"\s+", " ", summary).strip()

                published_elem = entry.find("atom:published", ns)
                published = published_elem.text[:10] if published_elem is not None and published_elem.text else ""

                authors = ", ".join(
                    a.find("atom:name", ns).text or "" for a in entry.findall("atom:author", ns)
                )

                link_elem = entry.find("atom:id", ns)
                link = link_elem.text if link_elem is not None else ""
                arxiv_id = link.split("/")[-1] if link else ""
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""

                spans = [f"Authors: {authors}"] if authors else []
                spans += make_spans_from_text(summary)
                if pdf_url:
                    spans.append(f"PDF: {pdf_url}")

                r = pack_result(
                    title=title,
                    url=link or f"https://arxiv.org/abs/{arxiv_id}",
                    description=safe_trim(summary922, 1200),
                    source="arxiv",
                    domain=self.DOMAIN,
                    id_type="arxiv",
                    id=arxiv_id,
                    published=published,
                    evidence_level="preprint",
                    evidence_spans=spans[:6],
                )
                r["volatile"] = True
                out.append(r)

            return out

    # -----------------------------
    # Wikipedia — company profiles, recent business events
    # -----------------------------
    async def _search_wikipedia(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            # Search for company/business pages
            search_q = quote_plus(q + " company OR business OR corporation OR CEO OR acquisition")
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={search_q}&srlimit=10&format=json"
            search_js = await self._get_json(client, search_url, retries=retries, backoff_factor=backoff_factor)
            if not search_js:
                return []

            pages = search_js.get("query", {}).get("search", []) or []
            out: List[Dict[str, Any]] = []

            for page in pages[:4]:
                if not isinstance(page, dict):
                    continue
                title = page.get("title", "")
                if not title:
                    continue

                extract_url = (
                    f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&titles={quote_plus(title)}&format=json"
                )
                extract_js = await self._get_json(client, extract_url, retries=retries, backoff_factor=backoff_factor)
                if not extract_js:
                    continue

                page_data = list(extract_js.get("query", {}).get("pages", {}).values())
                if not page_data or not page_data[0]:
                    continue
                content = page_data[0].get("extract", "") or ""

                wiki_url = f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"

                spans = make_spans_from_text(content)[:8]
                spans.insert(0, f"Business overview: {title}")

                r = pack_result(
                    title=f"Business: {title}",
                    url=wiki_url,
                    description=safe_trim(content, 1200),
                    source="wikipedia",
                    domain=self.DOMAIN,
                    id_type="url",
                    id=wiki_url,
                    published="",
                    evidence_level="encyclopedia",
                    evidence_spans=spans[:10],
                )
                r["volatile"] = True
                out.append(r)

            return out