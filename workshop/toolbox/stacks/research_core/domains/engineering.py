"""
EngineeringDomain â€” free, no-auth engineering / CS / applied science retrieval.

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
from workshop.toolbox.stacks.research_core.searxng import search_searxng 

from workshop.toolbox.stacks.research_core.base import (
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
    # arXiv â€” ENHANCED: authors + PDF
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

    def _should_retry_status(self, status: int) -> bool:
        return status in (408, 425, 429) or (500 <= status <= 599)

    async def _sleep_backoff(self, attempt: int, backoff_factor: float, retry_after_s: Optional[float] = None) -> None:
        base = backoff_factor * (2 ** attempt)
        if retry_after_s is not None and retry_after_s > 0:
            await asyncio.sleep(min(30.0, max(base, retry_after_s)))
        else:
            await asyncio.sleep(min(30.0, base))

    async def _get_json(self, client: httpx.AsyncClient, url: str, *, retries: int, backoff_factor: float) -> Optional[Dict[str, Any]]:
        last: Optional[Exception] = None
        for attempt in range(max(1, retries + 1)):
            try:
                async with self._http_sem:
                    response = await client.get(url)
                if response.status_code >= 400:
                    if self._should_retry_status(response.status_code) and attempt < retries:
                        retry_after = None
                        try:
                            retry_header = response.headers.get("Retry-After")
                            if retry_header and retry_header.strip().isdigit():
                                retry_after = float(int(retry_header.strip()))
                        except Exception:
                            retry_after = None
                        await self._sleep_backoff(attempt, backoff_factor, retry_after_s=retry_after)
                        continue
                    return None
                try:
                    return response.json()
                except Exception as exc:
                    last = exc
                    if attempt < retries:
                        await self._sleep_backoff(attempt, backoff_factor)
                        continue
                    return None
            except Exception as exc:
                last = exc
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        if last:
            logger.debug(f"_get_json failed: {url} ({type(last).__name__})")
        return None

    async def _get_text(self, client: httpx.AsyncClient, url: str, *, retries: int, backoff_factor: float) -> Optional[str]:
        last: Optional[Exception] = None
        for attempt in range(max(1, retries + 1)):
            try:
                async with self._http_sem:
                    response = await client.get(url)
                if response.status_code >= 400:
                    if self._should_retry_status(response.status_code) and attempt < retries:
                        retry_after = None
                        try:
                            retry_header = response.headers.get("Retry-After")
                            if retry_header and retry_header.strip().isdigit():
                                retry_after = float(int(retry_header.strip()))
                        except Exception:
                            retry_after = None
                        await self._sleep_backoff(attempt, backoff_factor, retry_after_s=retry_after)
                        continue
                    return None
                return response.text
            except Exception as exc:
                last = exc
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        if last:
            logger.debug(f"_get_text failed: {url} ({type(last).__name__})")
        return None

    async def _resolve_identifier(
        self,
        client: httpx.AsyncClient,
        id_type: str,
        id_value: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            if id_type == "doi":
                result = await self._fetch_crossref_by_doi(client, id_value, retries=retries, backoff_factor=backoff_factor)
                if result:
                    out.append(result)
            elif id_type == "arxiv":
                result = await self._fetch_arxiv_by_id(client, id_value, retries=retries, backoff_factor=backoff_factor)
                if result:
                    out.append(result)
        except Exception as exc:
            logger.debug(f"Engineering identifier resolve failed: {type(exc).__name__}: {exc}")
        return out

    async def _fetch_arxiv_by_id(
        self,
        client: httpx.AsyncClient,
        arxiv_id: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> Optional[Dict[str, Any]]:
        axid = extract_arxiv_id(arxiv_id)
        if not axid:
            return None
        url = f"http://export.arxiv.org/api/query?id_list={quote_plus(axid)}"
        txt = await self._get_text(client, url, retries=retries, backoff_factor=backoff_factor)
        if not txt:
            return None
        entries = re.split(r"<entry>", txt)[1:]
        if not entries:
            return None
        entry = entries[0]
        title_m = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        if not title_m:
            return None
        title = _xml_unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()).rstrip(".")
        summary_m = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
        summary = _xml_unescape(re.sub(r"\s+", " ", summary_m.group(1)).strip()) if summary_m else ""
        pub_m = re.search(r"<published>(.*?)</published>", entry, re.DOTALL)
        published = _parse_date_any(pub_m.group(1).strip() if pub_m else "")
        spans = make_spans_from_text(summary) if summary else [f"Title: {title}"]
        result = pack_result(
            title=title,
            url=f"https://arxiv.org/abs/{axid}",
            description=safe_trim(summary, 1200),
            source="arxiv",
            domain=self.DOMAIN,
            id_type="arxiv",
            id=axid,
            published=published,
            evidence_level="preprint",
            evidence_spans=spans[:5],
        )
        result["volatile"] = True
        return result

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
                title = str(title_list[0] or "").strip().rstrip(".") if isinstance(title_list, list) and title_list else ""
                if not title:
                    continue
                doi = _normalize_doi_input(str(it.get("DOI") or it.get("doi") or ""))
                if not doi:
                    continue
                published = ""
                published_meta = it.get("published-print") or it.get("published-online") or it.get("created") or {}
                if isinstance(published_meta, dict):
                    parts = published_meta.get("date-parts") or []
                    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                        year = parts[0][0]
                        month = parts[0][1] if len(parts[0]) > 1 else 1
                        day = parts[0][2] if len(parts[0]) > 2 else 1
                        published = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
                result = pack_result(
                    title=title,
                    url=f"https://doi.org/{doi}",
                    description="",
                    source="crossref",
                    domain=self.DOMAIN,
                    id_type="doi",
                    id=doi,
                    published=published,
                    evidence_level=infer_evidence_level(title, pub_types=None, source="crossref"),
                    evidence_spans=[f"Title: {title}"],
                )
                result["volatile"] = True
                out.append(result)
            return out

    async def _fetch_crossref_by_doi(
        self,
        client: httpx.AsyncClient,
        doi: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> Optional[Dict[str, Any]]:
        normalized = _normalize_doi_input(doi)
        if not normalized:
            return None
        url = f"https://api.crossref.org/works/{quote_plus(normalized)}"
        js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
        if not js:
            return None
        item = js.get("message") or {}
        title_list = item.get("title") or []
        title = str(title_list[0] or "").strip().rstrip(".") if isinstance(title_list, list) and title_list else ""
        if not title:
            return None
        result = pack_result(
            title=title,
            url=f"https://doi.org/{normalized}",
            description="",
            source="crossref",
            domain=self.DOMAIN,
            id_type="doi",
            id=normalized,
            published="",
            evidence_level=infer_evidence_level(title, pub_types=None, source="crossref"),
            evidence_spans=[f"Title: {title}"],
        )
        result["volatile"] = True
        return result
    # _fetch_arxiv_by_id can be similarly enhanced (authors + PDF) â€” omitted for brevity, copy pattern above

    # -----------------------------
    # Semantic Scholar â€” ENHANCED: authors, venue, openAccessPdf
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
    # OpenAlex â€” ENHANCED: authors, abstract reconstruction, PDF
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

