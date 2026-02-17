"""
NutritionDomain — free, no-auth nutrition / diet / metabolism research retrieval.

Design goals:
- Prefer biomedical-grade sources when possible (PubMed, Europe PMC)
- Use OpenAlex + Crossref as breadth/metadata fallbacks
- Add Open Food Facts for precise food composition/nutrient facts (no key required)
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


_MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _ymd(y: int, m: int = 1, d: int = 1) -> str:
    try:
        return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _parse_pubmed_pubdate(xml: str) -> str:
    if not xml:
        return ""

    y = None
    m = None
    d = None

    ym = re.search(r"<PubDate>.*?<Year>(\d{4})</Year>", xml, re.DOTALL)
    if ym:
        y = int(ym.group(1))

        mm = re.search(r"<PubDate>.*?<Month>([^<]+)</Month>", xml, re.DOTALL)
        if mm:
            ms = mm.group(1).strip().lower()
            if ms.isdigit():
                m = int(ms)
            else:
                m = _MONTH_MAP.get(ms[:3], _MONTH_MAP.get(ms, None))

        dm = re.search(r"<PubDate>.*?<Day>(\d{1,2})</Day>", xml, re.DOTALL)
        if dm:
            d = int(dm.group(1))

        return _ymd(y, m or 1, d or 1)

    md = re.search(r"<MedlineDate>([^<]+)</MedlineDate>", xml, re.DOTALL)
    if md:
        s = md.group(1).strip()
        y2 = re.search(r"\b(\d{4})\b", s)
        if y2:
            return _ymd(int(y2.group(1)), 1, 1)

    return ""


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


def _looks_like_nutrition(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "nutrition", "diet", "dietary", "calorie", "calories", "macros", "protein", "carb", "carbs",
        "fat", "fiber", "fibre", "micronutrient", "vitamin", "mineral", "iron", "b12", "folate",
        "omega-3", "omega 3", "lipid", "cholesterol", "ldl", "hdl", "triglyceride",
        "glycemic", "glycaemic", "insulin resistance", "metabolic syndrome", "obesity", "weight loss",
        "ketogenic", "keto", "low carb", "mediterranean diet", "dash diet",
        "rda", "recommended daily", "dietary reference intake", "dri",
        "supplement", "probiotic", "prebiotic",
    ])


def _looks_like_food_query(q: str) -> bool:
    """Detect queries that are clearly about specific food nutrient facts"""
    ql = (q or "").lower()
    food_indicators = [
        " in ", " per ", "100g", "serving", "calories", "protein", "fat", "carb",
        "nutrition facts", "macros", "how much", "how many", "amount of",
    ]
    return any(ind in ql for ind in food_indicators)


def _normalize_doi_input(x: str) -> str:
    x = (x or "").strip()
    if not x:
        return ""
    m = re.search(r"doi\.org/(10\.\d{4,9}/\S+)", x, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(").,;\"'")
    d = extract_doi(x)
    return (d or x).strip().rstrip(").,;\"'")


# --- OpenAlex abstract reconstruction ---
def _reconstruct_openalex_abstract(inv_index: Optional[Dict[str, Any]]) -> str:
    if not isinstance(inv_index, dict):
        return ""
    words = []
    for word, positions in sorted(inv_index.items(), key=lambda x: min(x[1])):
        words.extend([word] * len(positions))
    return " ".join(words)


class NutritionDomain:
    DOMAIN = "nutrition"

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
                headers={"User-Agent": "SomiNutrition/1.0"},
                follow_redirects=True,
            ) as client:

                # Identifier-first: PMID or DOI
                if want_id_type in ("pmid", "doi") and want_id:
                    resolved = await self._resolve_identifier(
                        client, want_id_type, want_id, retries=retries, backoff_factor=backoff_factor
                    )
                    if resolved and not self._is_only_sentinel_list(resolved):
                        return resolved

                # Parallel tasks — includes Open Food Facts
                tasks: List[Any] = [
                    self._search_pubmed(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_europepmc(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_openalex(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_crossref(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    self._search_openfoodfacts(client, q, max_n=6, retries=retries, backoff_factor=backoff_factor),
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
                        "No results returned from PubMed/EuropePMC/OpenAlex/Crossref/OpenFoodFacts.",
                        query=q,
                    )]

                nut = _looks_like_nutrition(q)
                food_query = _looks_like_food_query(q)

                for r in merged:
                    src = str(r.get("source") or "")
                    if src in ("pubmed", "europepmc"):
                        r["intent_alignment"] = 1.0 if nut else 0.85
                    elif src == "openfoodfacts":
                        r["intent_alignment"] = 1.3 if food_query else 0.9  # Strong boost for food fact queries
                    elif src == "openalex":
                        r["intent_alignment"] = 0.80 if nut else 0.75
                    elif src == "crossref":
                        r["intent_alignment"] = 0.70
                    else:
                        r["intent_alignment"] = 0.70

                return merged

        except Exception as e:
            logger.warning(f"NutritionDomain search failed: {type(e).__name__}: {e}")
            return [self._sentinel(
                "Science search unavailable",
                "Nutrition sources unreachable (network/client error).",
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
            source="nutrition",
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
    # HTTP helpers (retry on 429/5xx)
    # -----------------------------
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
                    r = await client.get(url)

                if r.status_code >= 400:
                    if self._should_retry_status(r.status_code) and attempt < retries:
                        ra = None
                        try:
                            ra_hdr = r.headers.get("Retry-After")
                            if ra_hdr and ra_hdr.strip().isdigit():
                                ra = float(int(ra_hdr.strip()))
                        except Exception:
                            ra = None
                        await self._sleep_backoff(attempt, backoff_factor, retry_after_s=ra)
                        continue
                    return None

                return r.json()

            except Exception as e:
                last = e
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
                    r = await client.get(url)

                if r.status_code >= 400:
                    if self._should_retry_status(r.status_code) and attempt < retries:
                        ra = None
                        try:
                            ra_hdr = r.headers.get("Retry-After")
                            if ra_hdr and ra_hdr.strip().isdigit():
                                ra = float(int(ra_hdr.strip()))
                        except Exception:
                            ra = None
                        await self._sleep_backoff(attempt, backoff_factor, retry_after_s=ra)
                        continue
                    return None

                return r.text

            except Exception as e:
                last = e
                if attempt < retries:
                    await self._sleep_backoff(attempt, backoff_factor)
        if last:
            logger.debug(f"_get_text failed: {url} ({type(last).__name__})")
        return None

    # -----------------------------
    # Identifier resolution (PMID / DOI)
    # -----------------------------
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
            if id_type == "pmid":
                r = await self._fetch_pubmed_by_pmid_efetch(client, id_value, retries=retries, backoff_factor=backoff_factor)
                if r:
                    out.append(r)

            elif id_type == "doi":
                doi = _normalize_doi_input(id_value)
                r = await self._fetch_europepmc_by_doi(client, doi, retries=retries, backoff_factor=backoff_factor)
                if r:
                    out.append(r)
                r2 = await self._fetch_crossref_by_doi(client, doi, retries=retries, backoff_factor=backoff_factor)
                if r2:
                    out.append(r2)

        except Exception as e:
            logger.debug(f"Identifier resolve failed: {type(e).__name__}: {e}")

        if not out:
            return [self._sentinel(
                "Science search insufficient coverage",
                f"Could not resolve identifier {id_type}:{id_value} from nutrition sources.",
                query=f"{id_type}:{id_value}",
            )]
        return out

    # -----------------------------
    # PubMed — ENHANCED: authors, journal
    # -----------------------------
    async def _fetch_pubmed_by_pmid_efetch(
        self,
        client: httpx.AsyncClient,
        pmid: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> Optional[Dict[str, Any]]:
        pmid = str(pmid).strip()
        if not pmid.isdigit():
            return None

        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
        txt = await self._get_text(client, url, retries=retries, backoff_factor=backoff_factor)
        if not txt:
            return None

        title_m = re.search(r"<ArticleTitle>(.*?)</ArticleTitle>", txt, re.DOTALL)
        if not title_m:
            return None
        title = re.sub(r"<.*?>", "", title_m.group(1)).strip().rstrip(".")

        abs_parts = re.findall(r"<AbstractText.*?>(.*?)</AbstractText>", txt, re.DOTALL)
        abstract = " ".join(re.sub(r"<.*?>", "", a).strip() for a in abs_parts if a and a.strip())
        abstract = re.sub(r"\s+", " ", abstract).strip()

        # Authors
        auths = []
        for a in re.finditer(r"<Author.*?ValidYN=\"Y\".*?>\s*<LastName>(.*?)</LastName>\s*<ForeName>(.*?)</ForeName>", txt, re.DOTALL):
            last = re.sub(r"<.*?>", "", a.group(1)).strip()
            fore = re.sub(r"<.*?>", "", a.group(2)).strip()
            if last:
                auths.append(f"{last} {fore}".strip())
        authors_str = ", ".join(auths[:6]) + (" et al." if len(auths) > 6 else "")

        # Journal
        journal_m = re.search(r"<Journal>.*?<Title>(.*?)</Title>", txt, re.DOTALL)
        journal = re.sub(r"<.*?>", "", journal_m.group(1)).strip() if journal_m else ""

        pub_types = [re.sub(r"<.*?>", "", p).strip() for p in re.findall(r"<PublicationType.*?>(.*?)</PublicationType>", txt, re.DOTALL)]
        pub_types = [p for p in pub_types if p]

        published = _parse_pubmed_pubdate(txt)

        ev = infer_evidence_level(title, pub_types=pub_types, source="pubmed")

        spans = []
        if authors_str:
            spans.append(f"Authors: {authors_str}")
        if journal:
            spans.append(f"Journal: {journal}")
        spans += make_spans_from_text(abstract) if abstract else []

        r = pack_result(
            title=title,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            description=safe_trim(abstract, 1200),
            source="pubmed",
            domain=self.DOMAIN,
            id_type="pmid",
            id=pmid,
            published=published,
            evidence_level=ev,
            evidence_spans=spans[:6],
        )
        r["volatile"] = True
        return r

    async def _search_pubmed(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            term = quote_plus(q)
            esearch = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                f"?db=pubmed&retmode=json&retmax={int(max_n)}&sort=date&term={term}"
            )
            js = await self._get_json(client, esearch, retries=retries, backoff_factor=backoff_factor)
            if not js:
                return []

            ids = (js.get("esearchresult", {}) or {}).get("idlist", []) or []
            ids = [str(x) for x in ids if str(x).isdigit()]
            if not ids:
                return []

            out: List[Dict[str, Any]] = []
            for pmid in ids[: min(len(ids), int(max_n))]:
                r = await self._fetch_pubmed_by_pmid_efetch(client, pmid, retries=retries, backoff_factor=backoff_factor)
                if r:
                    out.append(r)
            return out

    # -----------------------------
    # Europe PMC — ENHANCED: authors, journal, OA PDF
    # -----------------------------
    async def _search_europepmc(
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
            url = (
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
                f"?query={qs}&format=json&pageSize={int(max_n)}&sort_date=y"
            )
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js:
                return []

            hit_list = (((js.get("resultList") or {}).get("result")) or [])
            out: List[Dict[str, Any]] = []

            for h in hit_list:
                if not isinstance(h, dict):
                    continue

                title = (h.get("title") or "").strip().rstrip(".")
                if not title:
                    continue

                pmid = str(h.get("pmid") or "").strip()
                doi = str(h.get("doi") or "").strip()
                published = str(h.get("firstPublicationDate") or h.get("pubYear") or "").strip()
                abstract = (h.get("abstractText") or "").strip()

                # Authors
                auth_list = h.get("authorList") or {}
                authors = []
                if isinstance(auth_list, dict):
                    full_names = auth_list.get("author", []) or []
                    for a in full_names[:6]:
                        if isinstance(a, dict):
                            fn = a.get("fullName") or ""
                            if fn:
                                authors.append(fn)
                authors_str = ", ".join(authors) + (" et al." if len(authors) >= 6 else "")

                # Journal
                journal = str(h.get("journalTitle") or "").strip()

                # OA PDF
                pdf_url = ""
                if h.get("fullTextUrlList"):
                    for ft in h["fullTextUrlList"].get("fullTextUrl", []):
                        if isinstance(ft, dict) and ft.get("documentStyle") == "pdf" and ft.get("availability") == "Open access":
                            pdf_url = ft.get("url", "")
                            break

                pub_types: List[str] = []
                pt = h.get("pubTypeList") or {}
                if isinstance(pt, dict):
                    pub_types = pt.get("pubType", []) or []
                    if isinstance(pub_types, str):
                        pub_types = [pub_types]

                ev = infer_evidence_level(title, pub_types=pub_types, source="europepmc")

                spans = []
                if authors_str:
                    spans.append(f"Authors: {authors_str}")
                if journal:
                    spans.append(f"Journal: {journal}")
                if pdf_url:
                    spans.append(f"Open PDF: {pdf_url}")
                spans += make_spans_from_text(abstract) if abstract else []

                if pmid.isdigit():
                    url2 = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                    id_type = "pmid"
                    idv = pmid
                elif doi:
                    url2 = f"https://doi.org/{doi}"
                    id_type = "doi"
                    idv = doi
                else:
                    src_id = (h.get("id") or "").strip()
                    src = (h.get("source") or "MED").strip()
                    url2 = f"https://europepmc.org/article/{src}/{src_id}" if src_id else ""
                    id_type = "url"
                    idv = url2 or ""

                r = pack_result(
                    title=title,
                    url=url2,
                    description=safe_trim(abstract, 1200),
                    source="europepmc",
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

    async def _fetch_europepmc_by_doi(
        self,
        client: httpx.AsyncClient,
        doi: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> Optional[Dict[str, Any]]:
        doi = (doi or "").strip().rstrip(").,;\"'")
        if not doi:
            return None

        url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query=DOI:{quote_plus(doi)}&format=json&pageSize=1"
        )
        js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
        if not js:
            return None

        hit_list = (((js.get("resultList") or {}).get("result")) or [])
        if not hit_list or not isinstance(hit_list[0], dict):
            return None

        h = hit_list[0]
        title = (h.get("title") or "").strip().rstrip(".")
        if not title:
            return None

        pmid = str(h.get("pmid") or "").strip()
        published = str(h.get("firstPublicationDate") or h.get("pubYear") or "").strip()
        abstract = (h.get("abstractText") or "").strip()

        # Authors / Journal / PDF (reuse pattern from search)
        auth_list = h.get("authorList") or {}
        authors = []
        if isinstance(auth_list, dict):
            full_names = auth_list.get("author", []) or []
            for a in full_names[:6]:
                if isinstance(a, dict):
                    fn = a.get("fullName") or ""
                    if fn:
                        authors.append(fn)
        authors_str = ", ".join(authors) + (" et al." if len(authors) >= 6 else "")

        journal = str(h.get("journalTitle") or "").strip()

        pdf_url = ""
        if h.get("fullTextUrlList"):
            for ft in h["fullTextUrlList"].get("fullTextUrl", []):
                if isinstance(ft, dict) and ft.get("documentStyle") == "pdf" and ft.get("availability") == "Open access":
                    pdf_url = ft.get("url", "")
                    break

        ev = infer_evidence_level(title, pub_types=None, source="europepmc")

        spans = []
        if authors_str:
            spans.append(f"Authors: {authors_str}")
        if journal:
            spans.append(f"Journal: {journal}")
        if pdf_url:
            spans.append(f"Open PDF: {pdf_url}")
        spans += make_spans_from_text(abstract) if abstract else []

        if pmid.isdigit():
            url2 = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            id_type = "pmid"
            idv = pmid
        else:
            url2 = f"https://doi.org/{doi}"
            id_type = "doi"
            idv = doi

        r = pack_result(
            title=title,
            url=url2,
            description=safe_trim(abstract, 1200),
            source="europepmc",
            domain=self.DOMAIN,
            id_type=id_type,
            id=idv,
            published=published,
            evidence_level=ev,
            evidence_spans=spans[:6],
        )
        r["volatile"] = True
        return r

    # -----------------------------
    # Crossref — unchanged (minimal fallback)
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
                title = str(title_list[0] or "").strip().rstrip(".") if isinstance(title_list, list) and title_list else ""
                if not title:
                    continue

                doi = str(it.get("DOI") or it.get("doi") or "").strip()
                if not doi:
                    continue

                published = ""
                pub = it.get("published-print") or it.get("published-online") or it.get("created") or {}
                if isinstance(pub, dict):
                    parts = pub.get("date-parts") or []
                    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                        y = parts[0][0]
                        m = parts[0][1] if len(parts[0]) > 1 else 1
                        d = parts[0][2] if len(parts[0]) > 2 else 1
                        published = _parse_date_any(f"{y}-{m:02d}-{d:02d}")

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

    async def _fetch_crossref_by_doi(
        self,
        client: httpx.AsyncClient,
        doi: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> Optional[Dict[str, Any]]:
        doi = _normalize_doi_input(doi)
        if not doi or not doi.lower().startswith("10."):
            return None

        url = f"https://api.crossref.org/works/{quote_plus(doi)}"
        js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
        if not js:
            return None

        it = js.get("message") or {}
        title_list = it.get("title") or []
        title = str(title_list[0] or "").strip().rstrip(".") if isinstance(title_list, list) and title_list else ""
        if not title:
            return None

        ev = infer_evidence_level(title, pub_types=None, source="crossref")

        r = pack_result(
            title=title,
            url=f"https://doi.org/{doi}",
            description="",
            source="crossref",
            domain=self.DOMAIN,
            id_type="doi",
            id=doi,
            published="",
            evidence_level=ev,
            evidence_spans=[f"Title: {title}"],
        )
        r["volatile"] = True
        return r

    # -----------------------------
    # OpenAlex — ENHANCED: authors, journal, abstract recon, OA PDF
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

                published = _parse_date_any(str(it.get("publication_date") or "").strip())

                # Authors
                auths = it.get("authorships", [])
                authors_str = ", ".join(
                    a.get("author", {}).get("display_name", "") for a in auths[:6] if isinstance(a, dict)
                )
                if len(auths) > 6:
                    authors_str += " et al."

                # Journal
                journal = str(it.get("journal", {}).get("display_name") or "").strip()

                # Abstract reconstruction
                abstract = _reconstruct_openalex_abstract(it.get("abstract_inverted_index"))

                # OA PDF / landing
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
    # Open Food Facts — food composition facts (no key!)
    # -----------------------------
    async def _search_openfoodfacts(
        self,
        client: httpx.AsyncClient,
        q: str,
        *,
        max_n: int = 6,
        retries: int,
        backoff_factor: float,
    ) -> List[Dict[str, Any]]:
        async with self._src_sem:
            qs = quote_plus(q)
            url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={qs}&search_simple=1&action=process&json=1&page_size={int(max_n)}"
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js or not isinstance(js, dict):
                return []

            products = js.get("products", []) or []
            out: List[Dict[str, Any]] = []

            for p in products:
                if not isinstance(p, dict):
                    continue

                name = str(p.get("product_name") or p.get("product_name_en") or "Unknown food").strip()
                if not name:
                    continue

                brand = str(p.get("brands") or "").strip()
                full_name = f"{name}" + (f" ({brand})" if brand else "")

                nut = p.get("nutriments", {}) or {}
                calories = nut.get("energy-kcal_100g") or nut.get("energy-kcal", nut.get("energy_100g"))
                protein = nut.get("proteins_100g") or nut.get("proteins")
                fat = nut.get("fat_100g") or nut.get("fat")
                carbs = nut.get("carbohydrates_100g") or nut.get("carbohydrates")
                fiber = nut.get("fiber_100g") or nut.get("fiber")
                sugars = nut.get("sugars_100g") or nut.get("sugars")
                sodium = nut.get("sodium_100g") or nut.get("sodium")
                vit_c = nut.get("vitamin-c_100g") or nut.get("vitamin-c")
                iron = nut.get("iron_100g") or nut.get("iron")

                spans = [f"Food: {full_name} (per 100g)"]
                if calories is not None:
                    spans.append(f"Calories: {calories:.0f} kcal")
                if protein is not None:
                    spans.append(f"Protein: {protein:.1f}g")
                if fat is not None:
                    spans.append(f"Fat: {fat:.1f}g")
                if carbs is not None:
                    spans.append(f"Carbohydrates: {carbs:.1f}g")
                if fiber is not None:
                    spans.append(f"Fiber: {fiber:.1f}g")
                if sugars is not None:
                    spans.append(f"Sugars: {sugars:.1f}g")
                if sodium is not None:
                    spans.append(f"Sodium: {sodium * 1000:.0f}mg")
                if vit_c is not None:
                    spans.append(f"Vitamin C: {vit_c * 1000:.1f}mg")
                if iron is not None:
                    spans.append(f"Iron: {iron * 1000:.1f}mg")

                url2 = str(p.get("url") or "").strip() or f"https://world.openfoodfacts.org/product/{p.get('code', '')}"

                r = pack_result(
                    title=f"Nutrition facts: {full_name}",
                    url=url2,
                    description="Nutrient breakdown per 100g from Open Food Facts database.",
                    source="openfoodfacts",
                    domain=self.DOMAIN,
                    id_type="url",
                    id=url2,
                    published="",
                    evidence_level="database",
                    evidence_spans=spans[:10],
                )
                r["volatile"] = True
                out.append(r)

            return out