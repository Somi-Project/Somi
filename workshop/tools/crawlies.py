from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import inspect
import io
import json
import logging
import os
import re
import time
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlparse, urlunparse

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    from config.settings import INSTRUCT_MODEL as _INSTRUCT_MODEL
    from config.settings import SCRAPER_MODEL as _SCRAPER_MODEL
    from config.settings import SEARXNG_BASE_URL as _SEARXNG_BASE_URL
    from config.settings import SCRAPLING_SERVICE_ENABLED as _SCRAPLING_SERVICE_ENABLED
    from config.settings import SCRAPLING_SERVICE_BASE_URL as _SCRAPLING_SERVICE_BASE_URL
    from config.settings import SCRAPLING_SERVICE_PATH as _SCRAPLING_SERVICE_PATH
    from config.settings import SCRAPLING_SERVICE_TIMEOUT_SECONDS as _SCRAPLING_SERVICE_TIMEOUT_SECONDS
except Exception:
    _INSTRUCT_MODEL = "qwen3:8b"
    _SCRAPER_MODEL = "qwen3.5:0.8b"
    _SEARXNG_BASE_URL = "http://localhost:8080"
    _SCRAPLING_SERVICE_ENABLED = False
    _SCRAPLING_SERVICE_BASE_URL = ""
    _SCRAPLING_SERVICE_PATH = "/fetch"
    _SCRAPLING_SERVICE_TIMEOUT_SECONDS = 4.0

logger = logging.getLogger("crawlies")


@dataclass
class CrawliesConfig:
    searx_base_url: str = str(_SEARXNG_BASE_URL or "http://localhost:8080")
    category: str = "general"
    max_pages: int = 2
    max_candidates: int = 12
    max_open_links: int = 3
    request_timeout_s: float = 8.0
    scrape_timeout_s: float = 12.0
    min_quality_stop: float = 35.0
    use_scrapling: bool = True
    use_scrapling_service: bool = bool(_SCRAPLING_SERVICE_ENABLED)
    scrapling_service_url: str = str(_SCRAPLING_SERVICE_BASE_URL or "").rstrip("/")
    scrapling_service_path: str = str(_SCRAPLING_SERVICE_PATH or "/fetch")
    scrapling_service_timeout_s: float = float(_SCRAPLING_SERVICE_TIMEOUT_SECONDS or 4.0)
    use_playwright: bool = True
    use_llm_rerank: bool = False
    llm_model: str = str(_SCRAPER_MODEL or _INSTRUCT_MODEL)
    artifact_dir: str = "sessions/scrape_tmp"
    save_artifacts: bool = True
    log_level: str = "INFO"


@dataclass
class Candidate:
    url: str
    title: str
    snippet: str
    query_variant: str
    page_no: int
    source: str = "searxng"
    score: float = 0.0


@dataclass
class CrawlDoc:
    url: str
    title: str
    snippet: str
    content: str
    method: str
    status_code: int = 0
    is_pdf: bool = False
    quality: float = 0.0
    duration_ms: float = 0.0
    screenshot_path: str = ""
    error: str = ""


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # Keep crawlies logs visible while suppressing noisy library output.
    warn_level = ("httpx", "httpcore", "urllib3", "playwright")
    for name in warn_level:
        logging.getLogger(name).setLevel(logging.WARNING)

    # pdfminer emits repetitive non-actionable page warnings on many PDFs.
    for name in ("pdfminer", "pdfminer.pdfpage", "pdfplumber"):
        logging.getLogger(name).setLevel(logging.ERROR)


def canonicalize_url(url: str) -> str:
    try:
        u = str(url or "").strip()
        if not u:
            return ""
        p = urlparse(u)
        if not p.scheme or not p.netloc:
            return u

        host = (p.netloc or "").lower()
        if ":" in host:
            h, port = host.rsplit(":", 1)
            if (p.scheme == "http" and port == "80") or (p.scheme == "https" and port == "443"):
                host = h

        clean_q = []
        for k, v in parse_qsl(p.query, keep_blank_values=True):
            lk = (k or "").lower()
            if lk.startswith("utm_") or lk in {"gclid", "fbclid", "mc_cid", "mc_eid", "ref"}:
                continue
            clean_q.append((k, v))

        return urlunparse((p.scheme.lower(), host, p.path or "", "", urlencode(clean_q, doseq=True), ""))
    except Exception:
        return str(url or "").strip()


def build_query_variants(query: str) -> List[str]:
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    if not q:
        return []

    variants = [
        q,
        f"{q} official guideline OR consensus OR statement",
        f"{q} latest update site:.gov OR site:.org",
        f"{q} PDF",
    ]

    out: List[str] = []
    seen = set()
    for v in variants:
        key = v.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out[:4]


def _tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", str(text or "").lower()) if t]


def _domain_boost(url: str) -> float:
    host = (urlparse(str(url or "")).netloc or "").lower()
    trusted = (
        "who.int",
        "cdc.gov",
        "nih.gov",
        "heart.org",
        "escardio.org",
        "acc.org",
        "ahajournals.org",
        "hypertension.ca",
        "nice.org.uk",
        "gov",
    )
    for d in trusted:
        if d in host:
            return 8.0
    return 0.0


def score_candidate(query: str, candidate: Candidate) -> float:
    q_tokens = set(_tokenize(query))
    blob = f"{candidate.title} {candidate.snippet} {candidate.url}".lower()
    overlap = sum(1 for t in q_tokens if t in blob)

    score = float(overlap)
    if any(k in blob for k in ("guideline", "consensus", "recommendation", "statement")):
        score += 4.0
    if ".pdf" in candidate.url.lower():
        score += 2.5
    score += _domain_boost(candidate.url)
    return score


def score_content_quality(query: str, doc: CrawlDoc) -> float:
    text = str(doc.content or "")
    if not text:
        return 0.0

    q_tokens = set(_tokenize(query))
    blob = f"{doc.title} {doc.snippet} {text[:4000]}".lower()
    overlap = sum(1 for t in q_tokens if t in blob)

    length_score = min(50.0, len(text) / 90.0)
    signal = 0.0
    if any(k in blob for k in ("guideline", "consensus", "recommendation", "statement")):
        signal += 8.0
    if re.search(r"\b(202[4-9]|203\d)\b", blob):
        signal += 4.0

    domain = _domain_boost(doc.url)
    method_bonus = 2.0 if doc.method in {"pdfplumber", "scrapling"} else 0.0

    return round(length_score + overlap * 5.0 + signal + domain + method_bonus, 2)


def _extract_main_text(html: str) -> str:
    if not html:
        return ""

    try:
        import trafilatura

        extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
        if extracted and len(extracted.strip()) > 80:
            return extracted.strip()
    except Exception:
        pass

    try:
        from readability import Document

        doc = Document(html)
        summary_html = doc.summary()
        if summary_html:
            html = summary_html
    except Exception:
        pass

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    except Exception:
        return ""


async def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            chunks: List[str] = []
            for page in pdf.pages[:4]:
                txt = (page.extract_text() or "").strip()
                if txt:
                    chunks.append(txt)
            return "\n\n".join(chunks).strip()
    except Exception:
        return ""


class CrawliesEngine:
    def __init__(self, config: Optional[CrawliesConfig] = None):
        self.config = config or CrawliesConfig()
        self._searx_sem = asyncio.Semaphore(6)
        self._scrapling_service_checked = False
        self._scrapling_service_online = False
        self._scrapling_disabled_reason = ""
        self._playwright_disabled_reason = ""

    def _scrapling_service_endpoint(self) -> tuple[str, int] | tuple[None, None]:
        base = str(self.config.scrapling_service_url or "").strip()
        if not base:
            return (None, None)
        p = urlparse(base)
        host = p.hostname
        if not host:
            return (None, None)
        if p.port:
            port = int(p.port)
        elif (p.scheme or "").lower() == "https":
            port = 443
        else:
            port = 80
        return (host, port)

    async def _check_scrapling_service(self) -> bool:
        if not self.config.use_scrapling_service:
            self._scrapling_service_checked = True
            self._scrapling_service_online = False
            return False

        host, port = self._scrapling_service_endpoint()
        if not host or not port:
            self._scrapling_service_checked = True
            self._scrapling_service_online = False
            return False

        timeout = max(0.3, min(2.0, float(self.config.scrapling_service_timeout_s)))

        def _ping() -> bool:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except Exception:
                return False

        ok = await asyncio.to_thread(_ping)
        self._scrapling_service_checked = True
        self._scrapling_service_online = bool(ok)
        return self._scrapling_service_online

    async def _search_searx_page(self, client: httpx.AsyncClient, query_variant: str, page_no: int) -> List[Candidate]:
        base = str(self.config.searx_base_url or "").rstrip("/")
        url = urljoin(base + "/", "search")
        params = {
            "q": query_variant,
            "format": "json",
            "categories": str(self.config.category or "general"),
            "pageno": int(page_no),
        }

        t0 = time.perf_counter()
        async with self._searx_sem:
            try:
                r = await client.get(url, params=params, timeout=self.config.request_timeout_s)
                ms = (time.perf_counter() - t0) * 1000.0
                if r.status_code != 200:
                    logger.warning("searx page failed status=%s q='%s' page=%s ms=%.1f", r.status_code, query_variant, page_no, ms)
                    return []
                js = r.json()
            except Exception as e:
                ms = (time.perf_counter() - t0) * 1000.0
                logger.warning("searx page exception q='%s' page=%s ms=%.1f err=%s", query_variant, page_no, ms, e)
                return []

        rows = js.get("results", []) if isinstance(js, dict) else []
        out: List[Candidate] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            url2 = canonicalize_url(str(row.get("url") or "").strip())
            if not url2.startswith("http"):
                continue
            out.append(
                Candidate(
                    url=url2,
                    title=str(row.get("title") or "").strip(),
                    snippet=str(row.get("content") or row.get("snippet") or row.get("description") or "").strip(),
                    query_variant=query_variant,
                    page_no=int(page_no),
                    source="searxng",
                )
            )

        logger.info("searx page ok q='%s' page=%s rows=%s", query_variant, page_no, len(out))
        return out


    async def _search_searx_page_requests(self, query_variant: str, page_no: int) -> List[Candidate]:
        if requests is None:
            logger.warning("requests unavailable for SearX fallback q='%s' page=%s", query_variant, page_no)
            return []

        base = str(self.config.searx_base_url or "").rstrip("/")
        url = urljoin(base + "/", "search")
        params = {
            "q": query_variant,
            "format": "json",
            "categories": str(self.config.category or "general"),
            "pageno": int(page_no),
        }

        t0 = time.perf_counter()

        def _run_request():
            return requests.get(url, params=params, timeout=self.config.request_timeout_s)

        try:
            r = await asyncio.to_thread(_run_request)
            ms = (time.perf_counter() - t0) * 1000.0
            if int(getattr(r, "status_code", 0)) != 200:
                logger.warning("searx requests fallback failed status=%s q='%s' page=%s ms=%.1f", getattr(r, "status_code", 0), query_variant, page_no, ms)
                return []
            js = r.json()
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000.0
            logger.warning("searx requests fallback exception q='%s' page=%s ms=%.1f err=%s", query_variant, page_no, ms, e)
            return []

        rows = js.get("results", []) if isinstance(js, dict) else []
        out: List[Candidate] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            url2 = canonicalize_url(str(row.get("url") or "").strip())
            if not url2.startswith("http"):
                continue
            out.append(
                Candidate(
                    url=url2,
                    title=str(row.get("title") or "").strip(),
                    snippet=str(row.get("content") or row.get("snippet") or row.get("description") or "").strip(),
                    query_variant=query_variant,
                    page_no=int(page_no),
                    source="searxng",
                )
            )

        logger.info("searx requests fallback ok q='%s' page=%s rows=%s", query_variant, page_no, len(out))
        return out

    async def discover_candidates(self, query: str) -> List[Candidate]:
        variants = build_query_variants(query)
        if not variants:
            return []

        logger.info("discover start variants=%s pages=%s", len(variants), self.config.max_pages)

        tasks = []
        if httpx is None:
            logger.warning("httpx not available; using requests fallback for SearX discovery")
            for v in variants:
                for p in range(1, int(self.config.max_pages) + 1):
                    tasks.append(self._search_searx_page_requests(v, p))
            rows = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            async with httpx.AsyncClient(follow_redirects=True, timeout=self.config.request_timeout_s) as client:
                for v in variants:
                    for p in range(1, int(self.config.max_pages) + 1):
                        tasks.append(self._search_searx_page(client, v, p))

                rows = await asyncio.gather(*tasks, return_exceptions=True)

        merged: List[Candidate] = []
        for r in rows:
            if isinstance(r, list):
                merged.extend(r)

        deduped: Dict[str, Candidate] = {}
        for c in merged:
            if c.url not in deduped:
                deduped[c.url] = c

        candidates = list(deduped.values())
        for c in candidates:
            c.score = score_candidate(query, c)
        candidates.sort(key=lambda x: x.score, reverse=True)

        top = candidates[: int(self.config.max_candidates)]
        logger.info("discover done raw=%s dedup=%s top=%s", len(merged), len(candidates), len(top))
        return top

    async def _fetch_pdf_httpx(self, client: httpx.AsyncClient, c: Candidate) -> CrawlDoc:
        t0 = time.perf_counter()
        try:
            r = await client.get(c.url, timeout=self.config.scrape_timeout_s)
            txt = await _extract_pdf_text(r.content[:2_500_000])
            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content=txt,
                method="pdfplumber",
                status_code=int(r.status_code),
                is_pdf=True,
                duration_ms=ms,
            )
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content="",
                method="pdfplumber",
                is_pdf=True,
                duration_ms=ms,
                error=str(e),
            )

    async def _fetch_httpx_html(self, client: httpx.AsyncClient, c: Candidate) -> CrawlDoc:
        t0 = time.perf_counter()
        try:
            r = await client.get(c.url, timeout=self.config.scrape_timeout_s)
            raw = r.content[:2_000_000]
            ctype = str(r.headers.get("content-type") or "").lower()
            if "application/pdf" in ctype or c.url.lower().endswith(".pdf"):
                txt = await _extract_pdf_text(raw)
                ms = (time.perf_counter() - t0) * 1000.0
                return CrawlDoc(
                    url=c.url,
                    title=c.title,
                    snippet=c.snippet,
                    content=txt,
                    method="pdfplumber",
                    status_code=int(r.status_code),
                    is_pdf=True,
                    duration_ms=ms,
                )

            try:
                html = raw.decode(r.encoding or "utf-8", errors="ignore")
            except Exception:
                html = raw.decode("utf-8", errors="ignore")

            txt = _extract_main_text(html)
            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content=txt,
                method="httpx",
                status_code=int(r.status_code),
                duration_ms=ms,
            )
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content="",
                method="httpx",
                duration_ms=ms,
                error=str(e),
            )

    async def _fetch_scrapling_service(self, c: Candidate) -> CrawlDoc:
        t0 = time.perf_counter()
        if not self.config.use_scrapling_service:
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="scrapling_service", error="disabled")
        if self._scrapling_service_checked and not self._scrapling_service_online:
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="scrapling_service", error="service_unavailable")
        if httpx is None:
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="scrapling_service", error="httpx_unavailable")

        base = str(self.config.scrapling_service_url or "").rstrip("/")
        if not base:
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="scrapling_service", error="service_url_missing")

        raw_path = str(self.config.scrapling_service_path or "/fetch").strip() or "/fetch"
        path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
        endpoint = f"{base}{path}"

        try:
            timeout = float(self.config.scrapling_service_timeout_s)
        except Exception:
            timeout = 4.0
        timeout = max(0.8, timeout)

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                r = await client.post(endpoint, json={"url": c.url}, headers={"accept": "application/json"})
                if int(r.status_code) in (404, 405, 415):
                    r = await client.get(endpoint, params={"url": c.url}, headers={"accept": "application/json"})

            status = int(r.status_code)
            content_type = str(r.headers.get("content-type") or "").lower()
            payload: Dict[str, Any] = {}
            err = ""
            title = c.title
            html = ""
            txt = ""

            if "json" in content_type:
                try:
                    js = r.json()
                except Exception:
                    js = None

                if isinstance(js, dict):
                    payload = js.get("data") if isinstance(js.get("data"), dict) else js
                    title = str(payload.get("title") or c.title)
                    html = str(payload.get("html") or "")
                    txt = str(payload.get("text") or payload.get("content") or payload.get("markdown") or "")
                    err = str(payload.get("error") or js.get("error") or "")
                elif isinstance(js, str):
                    txt = js
                else:
                    txt = r.text or ""
            else:
                html = r.text or ""

            body = _extract_main_text(html) if html else (txt or "").strip()
            if not body and html:
                body = html.strip()

            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=str(payload.get("url") or c.url),
                title=title,
                snippet=c.snippet,
                content=body,
                method="scrapling_service",
                status_code=status,
                duration_ms=ms,
                error=err,
            )
        except Exception as e:
            self._scrapling_service_checked = True
            self._scrapling_service_online = False
            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content="",
                method="scrapling_service",
                duration_ms=ms,
                error=str(e),
            )

    async def _fetch_scrapling(self, c: Candidate) -> CrawlDoc:
        t0 = time.perf_counter()

        service_err = ""
        if self.config.use_scrapling_service:
            service_doc = await self._fetch_scrapling_service(c)
            if (service_doc.content or "").strip():
                return service_doc
            service_err = str(service_doc.error or "").strip()

        if self._scrapling_disabled_reason:
            suffix = f";service:{service_err}" if service_err else ""
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content="",
                method="scrapling",
                error=f"disabled:{self._scrapling_disabled_reason}{suffix}",
            )

        if not self.config.use_scrapling:
            suffix = f";service:{service_err}" if service_err else ""
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="scrapling", error=f"disabled{suffix}")

        try:
            fetchers = importlib.import_module("scrapling.fetchers")
        except Exception as e:
            base_err = f"import:{e}"
            if service_err:
                base_err = f"{base_err};service:{service_err}"
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="scrapling", error=base_err)

        last_err = ""
        for cls_name in ("StaticFetcher", "DynamicFetcher", "StealthyFetcher"):
            try:
                cls = getattr(fetchers, cls_name, None)
            except Exception as e:
                last_err = str(e)
                logger.debug("scrapling class unavailable cls=%s err=%s", cls_name, e)
                continue

            if cls is None:
                continue

            try:
                got = None

                # Newer scrapling versions expose class-level fetch(url),
                # while older versions may only expose instance get(url).
                class_fetch = getattr(cls, "fetch", None)
                if callable(class_fetch):
                    try:
                        if inspect.iscoroutinefunction(class_fetch):
                            got = await class_fetch(c.url)
                        else:
                            got = await asyncio.to_thread(class_fetch, c.url)
                    except TypeError:
                        got = None

                if got is None:
                    fetcher = cls()
                    bound_fetch = getattr(fetcher, "fetch", None)
                    if callable(bound_fetch):
                        if inspect.iscoroutinefunction(bound_fetch):
                            got = await bound_fetch(c.url)
                        else:
                            got = await asyncio.to_thread(bound_fetch, c.url)
                    else:
                        bound_get = getattr(fetcher, "get", None)
                        if callable(bound_get):
                            if inspect.iscoroutinefunction(bound_get):
                                got = await bound_get(c.url)
                            else:
                                got = await asyncio.to_thread(bound_get, c.url)
                        else:
                            raise AttributeError(f"{cls_name} has neither fetch() nor get()")

                if inspect.isawaitable(got):
                    got = await got

                html = ""
                status = 0
                for attr in ("html", "text", "body", "content"):
                    val = getattr(got, attr, None)
                    if isinstance(val, (bytes, bytearray)):
                        try:
                            val = bytes(val).decode("utf-8", errors="ignore")
                        except Exception:
                            val = ""
                    if isinstance(val, str) and len(val.strip()) > 40:
                        html = val
                        break
                if not html and hasattr(got, "to_html"):
                    maybe = got.to_html()  # type: ignore[attr-defined]
                    if isinstance(maybe, str):
                        html = maybe

                status = int(getattr(got, "status", 0) or getattr(got, "status_code", 0) or 0)
                txt = _extract_main_text(html) if html else ""
                ms = (time.perf_counter() - t0) * 1000.0
                return CrawlDoc(
                    url=c.url,
                    title=c.title,
                    snippet=c.snippet,
                    content=txt,
                    method="scrapling",
                    status_code=status,
                    duration_ms=ms,
                )
            except Exception as e:
                last_err = f"{cls_name}:{e}"
                lowered = last_err.lower()
                if ("access is denied" in lowered) or ("winerror 5" in lowered) or ("playwright sync api" in lowered):
                    self._scrapling_disabled_reason = last_err[:180]
                    break
                continue

        ms = (time.perf_counter() - t0) * 1000.0
        err = f"all_fetchers_failed:{last_err}" if last_err else "all_fetchers_failed"
        if service_err:
            err = f"{err};service:{service_err}"
        return CrawlDoc(
            url=c.url,
            title=c.title,
            snippet=c.snippet,
            content="",
            method="scrapling",
            duration_ms=ms,
            error=err,
        )

    async def _fetch_playwright(self, c: Candidate, ordinal: int) -> CrawlDoc:
        t0 = time.perf_counter()
        if not self.config.use_playwright:
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="playwright", error="disabled")
        if self._playwright_disabled_reason:
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content="",
                method="playwright",
                error=f"disabled:{self._playwright_disabled_reason}",
            )

        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            return CrawlDoc(url=c.url, title=c.title, snippet=c.snippet, content="", method="playwright", error=f"import:{e}")

        shot_path = ""
        base_dir = str(self.config.artifact_dir or "sessions/scrape_tmp")
        os.makedirs(base_dir, exist_ok=True)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(c.url, wait_until="domcontentloaded", timeout=int(self.config.scrape_timeout_s * 1000))
                await page.wait_for_timeout(450)

                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                shot_path = os.path.join(base_dir, f"crawlies_page_{ordinal}_{stamp}.png")
                await page.screenshot(path=shot_path, full_page=True)
                html = await page.content()
                txt = _extract_main_text(html)

                await page.close()
                await context.close()
                await browser.close()

            ms = (time.perf_counter() - t0) * 1000.0
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content=txt,
                method="playwright",
                duration_ms=ms,
                screenshot_path=shot_path,
            )
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000.0
            msg = str(e)
            lowered = msg.lower()
            if ("access is denied" in lowered) or ("winerror 5" in lowered) or ("browser type.launch" in lowered):
                self._playwright_disabled_reason = msg[:180]
            return CrawlDoc(
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                content="",
                method="playwright",
                duration_ms=ms,
                screenshot_path=shot_path,
                error=msg,
            )

    async def crawl_candidate(self, query: str, candidate: Candidate, ordinal: int) -> CrawlDoc:
        logger.info("crawl start idx=%s url=%s", ordinal, candidate.url)

        best = CrawlDoc(url=candidate.url, title=candidate.title, snippet=candidate.snippet, content="", method="none")

        # PDFs are better handled by direct download + pdfplumber; skip browser-heavy methods first.
        if candidate.url.lower().endswith(".pdf"):
            methods = ["httpx", "playwright"]
        else:
            methods = ["scrapling", "httpx", "playwright"]
        if httpx is None:
            methods = [m for m in methods if m != "httpx"]

        async def _run_method(method: str, client: Any) -> CrawlDoc:
            if method == "scrapling":
                return await self._fetch_scrapling(candidate)
            if method == "httpx":
                if client is None:
                    return CrawlDoc(url=candidate.url, title=candidate.title, snippet=candidate.snippet, content="", method="httpx", error="httpx_unavailable")
                return await self._fetch_httpx_html(client, candidate)
            return await self._fetch_playwright(candidate, ordinal)

        if httpx is None:
            for method in methods:
                try:
                    doc = await _run_method(method, None)
                except Exception as e:
                    doc = CrawlDoc(
                        url=candidate.url,
                        title=candidate.title,
                        snippet=candidate.snippet,
                        content="",
                        method=method,
                        error=str(e),
                    )
                doc.quality = score_content_quality(query, doc)
                logger.info(
                    "crawl method idx=%s method=%s quality=%.2f len=%s status=%s err=%s",
                    ordinal,
                    doc.method,
                    doc.quality,
                    len(doc.content or ""),
                    doc.status_code,
                    (doc.error or "-")[:120],
                )
                if doc.quality > best.quality:
                    best = doc
                if best.quality >= float(self.config.min_quality_stop):
                    logger.info("crawl stop idx=%s reason=min_quality_reached quality=%.2f", ordinal, best.quality)
                    break
            return best

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.config.scrape_timeout_s) as client:
            for method in methods:
                try:
                    doc = await _run_method(method, client)
                except Exception as e:
                    doc = CrawlDoc(
                        url=candidate.url,
                        title=candidate.title,
                        snippet=candidate.snippet,
                        content="",
                        method=method,
                        error=str(e),
                    )

                doc.quality = score_content_quality(query, doc)
                logger.info(
                    "crawl method idx=%s method=%s quality=%.2f len=%s status=%s err=%s",
                    ordinal,
                    doc.method,
                    doc.quality,
                    len(doc.content or ""),
                    doc.status_code,
                    (doc.error or "-")[:120],
                )

                if doc.quality > best.quality:
                    best = doc

                if best.quality >= float(self.config.min_quality_stop):
                    logger.info("crawl stop idx=%s reason=min_quality_reached quality=%.2f", ordinal, best.quality)
                    break

        return best

    async def _rerank_with_llm(self, query: str, docs: List[CrawlDoc]) -> List[CrawlDoc]:
        if not self.config.use_llm_rerank or not docs:
            return docs

        try:
            import ollama
        except Exception as e:
            logger.warning("llm rerank skipped: %s", e)
            return docs

        payload = []
        for i, d in enumerate(docs, 1):
            payload.append({
                "idx": i,
                "url": d.url,
                "title": d.title[:220],
                "snippet": d.snippet[:320],
                "excerpt": (d.content or "")[:700],
                "quality": d.quality,
            })

        prompt = (
            "Rank these documents for answering the query. Return ONLY JSON array of idx values best to worst.\n\n"
            f"Query: {query}\n\nCandidates:\n{json.dumps(payload, ensure_ascii=True)}"
        )

        try:
            resp = await asyncio.to_thread(
                ollama.chat,
                model=self.config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "keep_alive": 120, "think": False},
            )
            raw = str((resp.get("message", {}) or {}).get("content", "") or "").strip()
            raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r"```$", "", raw).strip()
            if "[" in raw and "]" in raw:
                raw = raw[raw.find("[") : raw.rfind("]") + 1]
            idxs = json.loads(raw)
            if not isinstance(idxs, list):
                return docs

            order = []
            for x in idxs:
                try:
                    i = int(x)
                    if 1 <= i <= len(docs):
                        order.append(i - 1)
                except Exception:
                    continue

            ranked = [docs[i] for i in order]
            ranked.extend([d for i, d in enumerate(docs) if i not in set(order)])
            return ranked
        except Exception as e:
            logger.warning("llm rerank failed: %s", e)
            return docs

    def _save_artifact(self, query: str, candidates: List[Candidate], docs: List[CrawlDoc], elapsed_ms: float) -> str:
        if not self.config.save_artifacts:
            return ""

        os.makedirs(self.config.artifact_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        digest = hashlib.sha1(f"{query}|{stamp}".encode("utf-8", errors="ignore")).hexdigest()[:10]
        path = os.path.join(self.config.artifact_dir, f"crawlies_{stamp}_{digest}.json")

        payload = {
            "query": query,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round(elapsed_ms, 2),
            "config": asdict(self.config),
            "candidates": [asdict(c) for c in candidates],
            "docs": [asdict(d) for d in docs],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return path

    async def crawl(self, query: str) -> Dict[str, Any]:
        q = re.sub(r"\s+", " ", str(query or "")).strip()
        if not q:
            return {"query": q, "error": "empty_query", "docs": [], "candidates": []}

        t0 = time.perf_counter()

        if self.config.use_scrapling_service and not self._scrapling_service_checked:
            ok = await self._check_scrapling_service()
            if not ok:
                logger.warning(
                    "scrapling service offline url=%s - falling back to local methods",
                    (self.config.scrapling_service_url or "") or "-",
                )

        candidates = await self.discover_candidates(q)
        selected = candidates[: max(1, int(self.config.max_open_links))]

        logger.info("crawl selected=%s", len(selected))
        tasks = [self.crawl_candidate(q, c, i + 1) for i, c in enumerate(selected)]
        docs = await asyncio.gather(*tasks, return_exceptions=True)

        final_docs: List[CrawlDoc] = []
        for d in docs:
            if isinstance(d, CrawlDoc):
                final_docs.append(d)
            elif isinstance(d, Exception):
                logger.warning("crawl task exception: %s", d)

        final_docs.sort(key=lambda x: x.quality, reverse=True)
        final_docs = await self._rerank_with_llm(q, final_docs)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        artifact_path = self._save_artifact(q, candidates, final_docs, elapsed_ms)

        logger.info("crawl done docs=%s elapsed_ms=%.1f artifact=%s", len(final_docs), elapsed_ms, artifact_path or "-")

        return {
            "query": q,
            "elapsed_ms": round(elapsed_ms, 2),
            "artifact_path": artifact_path,
            "candidates": [asdict(c) for c in candidates],
            "docs": [asdict(d) for d in final_docs],
        }


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crawlies standalone retrieval debugger")
    p.add_argument("query", type=str, help="Search query")
    p.add_argument("--searx", type=str, default=str(_SEARXNG_BASE_URL or "http://localhost:8080"), help="SearXNG base URL")
    p.add_argument("--pages", type=int, default=2, help="SearX pages per variant")
    p.add_argument("--candidates", type=int, default=12, help="Max deduped candidates")
    p.add_argument("--open", type=int, default=3, help="Top links to open and scrape")
    p.add_argument("--no-scrapling", action="store_true", help="Disable local Scrapling method")
    p.add_argument("--scrapling-service", type=str, default=str(_SCRAPLING_SERVICE_BASE_URL or ""), help="Base URL for Scrapling HTTP service")
    p.add_argument("--no-scrapling-service", action="store_true", help="Disable Scrapling HTTP service")
    p.add_argument("--no-playwright", action="store_true", help="Disable Playwright method")
    p.add_argument("--llm-rerank", action="store_true", help="Enable ollama LLM rerank")
    p.add_argument("--model", type=str, default=str(_SCRAPER_MODEL or _INSTRUCT_MODEL), help="LLM model for rerank")
    p.add_argument("--log", type=str, default="INFO", help="Log level (DEBUG/INFO/WARNING)")
    p.add_argument("--json", action="store_true", help="Print full JSON output")
    return p


async def _main_async(args: argparse.Namespace) -> int:
    cfg = CrawliesConfig(
        searx_base_url=args.searx,
        max_pages=max(1, int(args.pages)),
        max_candidates=max(1, int(args.candidates)),
        max_open_links=max(1, int(args.open)),
        use_scrapling=not bool(args.no_scrapling),
        use_scrapling_service=not bool(args.no_scrapling_service),
        scrapling_service_url=str(args.scrapling_service or "").rstrip("/"),
        use_playwright=not bool(args.no_playwright),
        use_llm_rerank=bool(args.llm_rerank),
        llm_model=str(args.model),
        log_level=str(args.log),
    )

    configure_logging(cfg.log_level)
    engine = CrawliesEngine(cfg)
    out = await engine.crawl(args.query)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"Query: {out.get('query')}")
        print(f"Elapsed: {out.get('elapsed_ms')} ms")
        print(f"Artifact: {out.get('artifact_path') or '-'}")
        docs = out.get("docs") or []
        if not docs:
            print("No docs extracted.")
        for i, d in enumerate(docs[:3], 1):
            print(f"[{i}] {d.get('title') or '-'}")
            print(f"    URL: {d.get('url')}")
            print(f"    Method: {d.get('method')} | Quality: {d.get('quality')} | Len: {len(str(d.get('content') or ''))}")
            if d.get("error"):
                print(f"    Error: {d.get('error')}")

    return 0


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())


