"""
BiomedDomain — free, no-auth biomedical research retrieval.

Sources (all no-key):
- PubMed (NCBI E-utilities: ESearch + EFetch XML)
- Europe PMC (REST search)
- ClinicalTrials.gov (API v2)
- Crossref (metadata fallback for DOI-heavy queries)

Returns: list[dict] matching handlers/research/base.py contract.
Router will merge + rank across domains, so this domain focuses on:
- good primary-source hits
- identifier-first resolution for PMID / DOI / NCT
- stable behavior under slow/partial network conditions (no freezes)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from handlers.research.base import (
    id_type_and_value,
    infer_evidence_level,
    make_spans_from_text,
    normalize_query,
    pack_result,
    safe_trim,
)

# NEW: SearXNG import
from handlers.research.searxng import search_searxng

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 8.0

# Concurrency:
HTTP_SEM_LIMIT = 6  # total concurrent outbound requests
SRC_SEM_LIMIT = 3   # concurrent *sources* (avoid hitting too many endpoints at once)

MAX_PER_SOURCE = 8

# Soft budget for PubMed EFetch loop (seconds). Prevents "slow PubMed blocks everything".
PUBMED_EFETCH_BUDGET_S = 6.5


# -----------------------------
# Cheap intent heuristics (no LLM)
# -----------------------------
def _clinical_intent(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "guideline", "consensus", "practice guideline", "nice", "who", "cdc", "aha", "acc", "esc",
        "trial", "randomized", "randomised", "phase", "systematic review", "meta-analysis", "metaanalysis",
        "dose", "mg", "mcg", "threshold", "cutoff", "targets", "treatment",
        "diagnosis", "prognosis", "sensitivity", "specificity",
        "stroke", "seizure", "epilepsy", "multiple sclerosis", "nmosd", "migraine",
    ])


def _trial_intent(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in ["randomized", "randomised", "trial", "phase 2", "phase 3", "placebo", "clinical trial"])


# -----------------------------
# Date parsing helpers
# -----------------------------
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
    """
    Best-effort PubMed pubdate extraction from EFetch XML (regex-based).
    Returns YYYY-MM-DD (defaults month/day to 1 if missing).
    """
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


# -----------------------------
# Domain
# -----------------------------
class BiomedDomain:
    DOMAIN = "biomed"

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
                headers={"User-Agent": "SomiBiomed/1.0"},
                follow_redirects=True,
            ) as client:

                # 1) Identifier-first
                if want_id_type != "none" and want_id:
                    resolved = await self._resolve_identifier(
                        client, want_id_type, want_id, retries=retries, backoff_factor=backoff_factor
                    )
                    if resolved and not self._is_only_sentinel_list(resolved):
                        return self._finalize_results(resolved, q)

                # 2) Topic search (parallel)
                tasks: List[Any] = [
                    self._search_pubmed(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_europepmc(client, q, max_n=MAX_PER_SOURCE, retries=retries, backoff_factor=backoff_factor),
                    self._search_crossref(client, q, max_n=min(4, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor),
                    # NEW: Parallel SearXNG enrichment
                    search_searxng(client, q, max_results=6, domain=self.DOMAIN),
                ]

                if _clinical_intent(q) or _trial_intent(q) or "nct" in q.lower() or "clinicaltrials" in q.lower():
                    tasks.append(self._search_clinicaltrials(client, q, max_n=min(6, MAX_PER_SOURCE), retries=retries, backoff_factor=backoff_factor))

                gathered = await asyncio.gather(*tasks, return_exceptions=True)

                merged: List[Dict[str, Any]] = []
                for g in gathered:
                    if isinstance(g, Exception):
                        logger.debug(f"BiomedDomain source task error: {type(g).__name__}: {g}")
                        continue
                    if isinstance(g, list):
                        merged.extend([x for x in g if isinstance(x, dict)])

                # Remove sentinels if we also have real results
                non_sentinels = [r for r in merged if not self._is_sentinel_dict(r)]
                merged = non_sentinels or merged

                if not merged:
                    return [self._sentinel(
                        "Science search insufficient coverage",
                        "No results returned from PubMed/EuropePMC/Crossref/ClinicalTrials.",
                        query=q,
                    )]

                # Intent alignment signal (router will rank)
                clinical = _clinical_intent(q)
                for r in merged:
                    src = str(r.get("source") or "")
                    if clinical:
                        r["intent_alignment"] = 1.0 if src in ("pubmed", "europepmc", "clinicaltrials") else 0.60
                    else:
                        r["intent_alignment"] = 0.85 if src in ("pubmed", "europepmc") else 0.70

                return self._finalize_results(merged, q)

        except Exception as e:
            logger.warning(f"BiomedDomain search failed: {type(e).__name__}: {e}")
            return [self._sentinel(
                "Science search unavailable",
                "Biomed sources unreachable (network/client error).",
                query=q,
            )]

    def _finalize_results(self, results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """
        Ensures consistent keys for downstream compatibility.
        """
        out: List[Dict[str, Any]] = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            rr = dict(r)
            rr.setdefault("domain", self.DOMAIN)
            rr.setdefault("volatile", True)
            # Leave intent_alignment if present.
            out.append(rr)
        return out

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
            source="biomed",
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

                try:
                    return r.json()
                except Exception as je:
                    last = je
                    if attempt < retries:
                        await self._sleep_backoff(attempt, backoff_factor)
                        continue
                    return None

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
    # Identifier resolution
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
                # EuropePMC often maps DOI->PMID; Crossref provides metadata fallback
                r = await self._fetch_europepmc_by_doi(client, id_value, retries=retries, backoff_factor=backoff_factor)
                if r:
                    out.append(r)
                r2 = await self._fetch_crossref_by_doi(client, id_value, retries=retries, backoff_factor=backoff_factor)
                if r2:
                    out.append(r2)

            elif id_type == "nct":
                r = await self._fetch_clinicaltrials_by_nct(client, id_value, retries=retries, backoff_factor=backoff_factor)
                if r:
                    out.append(r)

        except Exception as e:
            logger.debug(f"Identifier resolve failed: {type(e).__name__}: {e}")

        if not out:
            return [self._sentinel(
                "Science search insufficient coverage",
                f"Could not resolve identifier {id_type}:{id_value} from biomed sources.",
                query=f"{id_type}:{id_value}",
            )]

        return out

    # -----------------------------
    # PubMed (ESearch + EFetch XML)
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

        pub_types = [re.sub(r"<.*?>", "", p).strip() for p in re.findall(r"<PublicationType.*?>(.*?)</PublicationType>", txt, re.DOTALL)]
        pub_types = [p for p in pub_types if p]

        published = _parse_pubmed_pubdate(txt)

        ev = infer_evidence_level(title, pub_types=pub_types, source="pubmed")
        spans = make_spans_from_text(abstract) if abstract else [f"Title: {title}"]

        r = pack_result(
            title=title,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            description=safe_trim(abstract, 360) if abstract else "",
            source="pubmed",
            domain=self.DOMAIN,
            id_type="pmid",
            id=pmid,
            published=published,
            evidence_level=ev,
            evidence_spans=spans[:4],
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
            start = time.time()

            term = quote_plus(q)
            esearch = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
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
                # Soft budget: don't let slow EFetch consume the whole domain time
                if (time.time() - start) > PUBMED_EFETCH_BUDGET_S and out:
                    break

                r = await self._fetch_pubmed_by_pmid_efetch(client, pmid, retries=retries, backoff_factor=backoff_factor)
                if r:
                    out.append(r)

            return out

    # -----------------------------
    # Europe PMC
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
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
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

                pub_types: List[str] = []
                pt = h.get("pubTypeList") or {}
                if isinstance(pt, dict):
                    pub_types = pt.get("pubType", []) or []
                    if isinstance(pub_types, str):
                        pub_types = [pub_types]

                ev = infer_evidence_level(title, pub_types=pub_types, source="europepmc")
                spans = make_spans_from_text(abstract) if abstract else [f"Title: {title}"]

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
                    description=safe_trim(abstract, 360) if abstract else "",
                    source="europepmc",
                    domain=self.DOMAIN,
                    id_type=id_type,
                    id=idv,
                    published=published,
                    evidence_level=ev,
                    evidence_spans=spans[:4],
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
        doi = (doi or "").strip()
        if not doi:
            return None

        url = (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
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

        ev = infer_evidence_level(title, pub_types=None, source="europepmc")
        spans = make_spans_from_text(abstract) if abstract else [f"Title: {title}"]

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
            description=safe_trim(abstract, 360) if abstract else "",
            source="europepmc",
            domain=self.DOMAIN,
            id_type=id_type,
            id=idv,
            published=published,
            evidence_level=ev,
            evidence_spans=spans[:4],
        )
        r["volatile"] = True
        return r

    # -----------------------------
    # Crossref
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
                        published = _ymd(int(y), int(m), int(d))

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
        doi = (doi or "").strip()
        if not doi:
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
    # ClinicalTrials.gov v2
    # -----------------------------
    async def _fetch_clinicaltrials_by_nct(
        self,
        client: httpx.AsyncClient,
        nct: str,
        *,
        retries: int,
        backoff_factor: float,
    ) -> Optional[Dict[str, Any]]:
        nct = (nct or "").strip().upper()
        if not re.search(r"\bNCT\d{8}\b", nct):
            return None

        url = f"https://clinicaltrials.gov/api/v2/studies/{quote_plus(nct)}"
        js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
        if not js or not isinstance(js, dict):
            return None

        proto = js.get("protocolSection") or {}
        ident = (proto.get("identificationModule") or {}) if isinstance(proto, dict) else {}

        title = (ident.get("briefTitle") or ident.get("officialTitle") or "").strip()
        if not title:
            title = f"Clinical trial {nct}"

        status = (proto.get("statusModule") or {}) if isinstance(proto, dict) else {}
        start_date = ""
        if isinstance(status, dict):
            start_date = str((status.get("startDateStruct") or {}).get("date") or "").strip()

        desc = (proto.get("descriptionModule") or {}) if isinstance(proto, dict) else {}
        brief = str(desc.get("briefSummary") or "").strip()

        spans = make_spans_from_text(brief) if brief else [f"Title: {title}"]

        r = pack_result(
            title=title,
            url=f"https://clinicaltrials.gov/study/{nct}",
            description=safe_trim(brief, 360) if brief else "",
            source="clinicaltrials",
            domain=self.DOMAIN,
            id_type="nct",
            id=nct,
            published=start_date,
            evidence_level="other",
            evidence_spans=spans[:4],
        )
        r["volatile"] = True
        return r

    async def _search_clinicaltrials(
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
            url = f"https://clinicaltrials.gov/api/v2/studies?query.term={qs}&pageSize={int(max_n)}"
            js = await self._get_json(client, url, retries=retries, backoff_factor=backoff_factor)
            if not js or not isinstance(js, dict):
                return []

            studies = js.get("studies") or []
            out: List[Dict[str, Any]] = []

            for s in studies:
                if not isinstance(s, dict):
                    continue
                proto = s.get("protocolSection") or {}
                if not isinstance(proto, dict):
                    continue
                ident = proto.get("identificationModule") or {}
                if not isinstance(ident, dict):
                    continue

                nct = str(ident.get("nctId") or "").strip().upper()
                if not nct or not re.search(r"\bNCT\d{8}\b", nct):
                    continue

                title = str(ident.get("briefTitle") or ident.get("officialTitle") or "").strip()
                if not title:
                    continue

                desc = proto.get("descriptionModule") or {}
                brief = str(desc.get("briefSummary") or "").strip() if isinstance(desc, dict) else ""

                status = proto.get("statusModule") or {}
                start_date = ""
                if isinstance(status, dict):
                    start_date = str((status.get("startDateStruct") or {}).get("date") or "").strip()

                spans = make_spans_from_text(brief) if brief else [f"Title: {title}"]

                r = pack_result(
                    title=title,
                    url=f"https://clinicaltrials.gov/study/{nct}",
                    description=safe_trim(brief, 360) if brief else "",
                    source="clinicaltrials",
                    domain=self.DOMAIN,
                    id_type="nct",
                    id=nct,
                    published=start_date,
                    evidence_level="other",
                    evidence_spans=spans[:4],
                )
                r["volatile"] = True
                out.append(r)

            return out