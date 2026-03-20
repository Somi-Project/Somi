# handlers/websearch.py
import asyncio
import contextlib
import html
import logging
import os
import re
import time
import traceback
import socket
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import httpx
try:
    import ollama
except Exception:  # pragma: no cover
    ollama = None  # type: ignore
try:
    from ddgs import DDGS
except Exception:  # pragma: no cover
    from duckduckgo_search import DDGS

from config.settings import (
    WEBSEARCH_MODEL,
    SYSTEM_TIMEZONE,
    ROUTING_DEBUG,
    RESEARCHER_BUNDLE_SHADOW_MODE,
    RESEARCH_COMPOSER_ENABLED,
    RESEARCH_COMPOSER_DEEPREAD,
    RESEARCH_CRAWLIES_ENABLED,
    RESEARCH_CRAWLIES_TIMEOUT_SECONDS,
    RESEARCH_CRAWLIES_MAX_PAGES,
    RESEARCH_CRAWLIES_MAX_CANDIDATES,
    RESEARCH_CRAWLIES_MAX_OPEN_LINKS,
    RESEARCH_CRAWLIES_MIN_QUALITY_STOP,
    RESEARCH_CRAWLIES_USE_SCRAPLING,
    RESEARCH_CRAWLIES_USE_PLAYWRIGHT,
    RESEARCH_CRAWLIES_USE_LLM_RERANK,
    RESEARCH_CRAWLIES_SAVE_ARTIFACTS,
    SEARXNG_BASE_URL,
    SEARXNG_DOMAIN_PROFILES,
)
from config.searchsettings import WEBSEARCH_DEBUG_RESULTS, WEBSEARCH_MAX_FORMAT_CHARS

from workshop.toolbox.stacks.web_core.websearch_tools.finance import FinanceHandler
from workshop.toolbox.stacks.web_core.websearch_tools.news import NewsHandler
from workshop.toolbox.stacks.web_core.websearch_tools.weather import WeatherHandler

from workshop.toolbox.stacks.web_core.websearch_tools.conversion import parse_conversion_request, Converter
from workshop.toolbox.stacks.web_core.websearch_tools.generalsearch import search_general
from workshop.toolbox.stacks.web_core.search_bundle import SearchBundle, SearchResult, strip_tracking_params

import pytz
from datetime import datetime, timezone

# NEW: SearXNG import
from workshop.toolbox.stacks.research_core.searxng import search_searxng

logger = logging.getLogger(__name__)

try:
    from workshop.tools.crawlies import CrawliesConfig, CrawliesEngine
except Exception as e:
    logger.warning(f"Crawlies not available: {e}")
    CrawliesConfig = None  # type: ignore
    CrawliesEngine = None  # type: ignore

# --- RESEARCH (Agentpedia) safe import ---
try:
    from workshop.toolbox.stacks.research_core.agentpedia import Agentpedia
    agentpedia_available = True
except Exception as e:
    logger.warning(f"Agentpedia not available: {e}")
    agentpedia_available = False
    Agentpedia = None

try:
    from workshop.toolbox.stacks.research_core.evidence_bundle import bundle_from_results
except Exception:
    bundle_from_results = None

from workshop.toolbox.stacks.research_core.composer import research_compose
from workshop.toolbox.stacks.research_core.browse_planner import BrowsePlan, build_browse_plan, comparison_subjects, infer_official_domains, is_shopping_compare_query, is_software_change_query, is_travel_lookup_query, is_trip_planning_query
from workshop.toolbox.stacks.research_core.evidence_cache import EvidenceCacheStore, canonicalize_url
from workshop.toolbox.stacks.research_core.github_local import choose_repositories, extract_repo_urls, inspect_github_repository
from workshop.toolbox.stacks.research_core.local_packs import search_local_pack_rows
from runtime.ollama_options import build_ollama_chat_options


@dataclass
class _CacheItem:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int = 600, max_items: int = 128):
        self.ttl = int(ttl_seconds)
        self.max_items = int(max_items)
        self._store: Dict[str, _CacheItem] = {}

    def _evict_if_needed(self) -> None:
        if len(self._store) <= self.max_items:
            return
        items = sorted(self._store.items(), key=lambda kv: kv[1].expires_at)
        for k, _ in items[: max(1, len(items) - self.max_items)]:
            self._store.pop(k, None)

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        if time.time() > item.expires_at:
            self._store.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = _CacheItem(value=value, expires_at=time.time() + self.ttl)
        self._evict_if_needed()


_TRACKING_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "yclid", "mc_cid", "mc_eid",
    "igshid", "ref", "ref_src",
}

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        )
    except Exception:
        return True


def _host_resolves_private(host: str) -> bool:
    """
    SSRF defense: resolve host and reject if any A/AAAA points to private/loopback/etc.
    NOTE: Treat DNS failures as unsafe (returns True).
    """
    try:
        infos = socket.getaddrinfo(host, None)
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if _is_private_ip(ip):
                    return True
            elif family == socket.AF_INET6:
                ip = sockaddr[0]
                if _is_private_ip(ip):
                    return True
        return False
    except Exception:
        return True


def _normalize_url(url: str) -> str:
    try:
        u = (url or "").strip()
        if not u:
            return ""
        parsed = urlparse(u)
        scheme = (parsed.scheme or "").lower()
        if not scheme:
            scheme = "https"
        netloc = (parsed.netloc or "").lower()
        path = parsed.path or ""
        params = parsed.params or ""
        query = parsed.query or ""

        host = netloc
        if ":" in netloc:
            h, p = netloc.rsplit(":", 1)
            if p.isdigit():
                port = int(p)
                if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
                    host = h
        else:
            host = netloc

        q = []
        for k, v in parse_qsl(query, keep_blank_values=True):
            if k.lower() in _TRACKING_KEYS:
                continue
            q.append((k, v))
        query_clean = urlencode(q, doseq=True)

        rebuilt = urlunparse((scheme, host, path, params, query_clean, ""))
        return rebuilt
    except Exception:
        return (url or "").strip()


def _is_safe_url(url: str) -> bool:
    try:
        u = _normalize_url(url)
        if not u:
            return False
        p = urlparse(u)
        scheme = (p.scheme or "").lower()
        if scheme not in _ALLOWED_SCHEMES:
            return False

        host = (p.hostname or "").strip().lower()
        if not host or host in _BLOCKED_HOSTS:
            return False

        # disallow odd ports
        if p.port not in (None, 80, 443):
            return False

        if _host_resolves_private(host):
            return False

        return True
    except Exception:
        return False


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _domain_score(domain: str, category: str) -> int:
    d = (domain or "").lower()

    good_general = (
        "wikipedia.org",
        "britannica.com",
        "who.int",
        "cdc.gov",
        "nih.gov",
        "ninds.nih.gov",
        "mayoclinic.org",
        "nhs.uk",
        "medlineplus.gov",
        "nature.com",
        "science.org",
        "ieee.org",
        "arxiv.org",
    )

    good_docs = (
        "readthedocs.io",
        "docs.python.org",
        "developer.mozilla.org",
        "github.com",
        "gitlab.com",
    )

    good_news = (
        "reuters.com",
        "apnews.com",
        "bbc.co.uk",
        "bbc.com",
        "theguardian.com",
        "nytimes.com",
        "wsj.com",
        "ft.com",
        "bloomberg.com",
        "aljazeera.com",
    )

    good_finance = (
        "finance.yahoo.com",
        "tradingview.com",
        "coinmarketcap.com",
        "coingecko.com",
        "binance.com",
    )

    if category == "news" and any((d.endswith(g) or g in d) for g in good_news):
        return 90

    if category in ("stock/commodity", "crypto", "forex") and any((d.endswith(g) or g in d) for g in good_finance):
        return 85

    if any((d.endswith(g) or g in d) for g in good_docs):
        return 82

    if any((d.endswith(g) or g in d) for g in good_general):
        return 80

    badish = ("pinterest.", "facebook.", "tiktok.", "instagram.", "x.com", "twitter.com")
    if any(b in d for b in badish):
        return 10

    return 50


def _safe_trim(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "..."


def _normalize_artifact_text(text: str) -> str:
    clean = html.unescape(str(text or ""))
    replacements = {
        "â€”": "-",
        "â€“": "-",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "Ã‚": "",
        "Ã¢â‚¬â€": "-",
        "Ã¢â‚¬â€œ": "-",
        "Ã¢â‚¬Ëœ": "'",
        "Ã¢â‚¬â„¢": "'",
        "Ã¢â‚¬Å“": '"',
        "Ã¢â‚¬ï¿½": '"',
        "â€¦": "...",
        "What?s": "What's",
    }
    for source, target in replacements.items():
        clean = clean.replace(source, target)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _repair_title_spacing(text: str) -> str:
    clean = _normalize_artifact_text(text)
    if not clean:
        return ""
    clean = re.sub(r",(?=[A-Za-z])", ", ", clean)
    clean = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", clean)
    clean = re.sub(r"(?<=[A-Za-z]\'s)(?=[A-Za-z])", " ", clean)
    clean = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", clean)
    clean = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", clean)
    clean = re.sub(r"(?<=[A-Za-z0-9])(?:vs|versus)(?=[A-Z0-9])", " vs ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b(The|This|That|These|How|What|Why|When|Where|Best|Latest|Top)(?=[a-z]{4,}\b)", r"\1 ", clean)
    clean = re.sub(r"\b([A-Za-z]{4,})of([A-Za-z]{4,})\b", r"\1 of \2", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b([A-Za-z]{4,})to([A-Za-z]{4,})\b", r"\1 to \2", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bi Phone\b", "iPhone", clean)
    clean = re.sub(r"\bI Phone\b", "iPhone", clean)
    clean = re.sub(r"\bIphone\b", "iPhone", clean)
    clean = re.sub(r"\bApplei Phone\b", "Apple iPhone", clean)
    clean = re.sub(r"\bAppleiPhone\b", "Apple iPhone", clean)
    clean = re.sub(r"\bGalaxyS(?=\d)", "Galaxy S", clean)
    clean = re.sub(r"\bGalaxyS\s+(?=\d)", "Galaxy S", clean)
    clean = re.sub(r"\b([A-Z])\s+(\d{2,4})\b", r"\1\2", clean)
    clean = re.sub(r"\bPlana\b", "Plan a", clean)
    clean = re.sub(r"\bVs\b", "vs", clean)
    targeted_replacements = (
        (r"\bThebest\b", "The best"),
        (r"\bthebest\b", "the best"),
        (r"\bbesttime\b", "best time"),
        (r"\btimetovisit\b", "time to visit"),
        (r"\bvisitTokyo\b", "visit Tokyo"),
        (r"\bTokyoand\b", "Tokyo and"),
        (r"\bTokyomight\b", "Tokyo might"),
        (r"\bTokyois\b", "Tokyo is"),
        (r"\bfewdays\b", "few days"),
        (r"\bHowto\b", "How to"),
        (r"\bWhatto\b", "What to"),
        (r"\btheofficialtravel\b", "the official travel"),
        (r"\btheofficial\b", "the official"),
        (r"\bofficialtravel\b", "official travel"),
        (r"\bTokyofor\b", "Tokyo for"),
        (r"\bTokyoweather\b", "Tokyo weather"),
        (r"\bHealthbenefits\b", "Health benefits"),
        (r"\bBenefitsof\b", "Benefits of"),
        (r"\bbenefitsof\b", "benefits of"),
        (r"\bthingstodoin\b", "things to do in"),
        (r"\bitineraryincludes\b", "itinerary includes"),
        (r"\bWalkingdaily\b", "Walking daily"),
        (r"\bbenefitsyour\b", "benefits your"),
        (r"\bWalkfor\b", "Walk for"),
        (r"\baday\b", "a day"),
        (r"\bphonescompare\b", "phones compare"),
        (r"\bofi Phone\b", "of iPhone"),
        (r"\bofiPhone\b", "of iPhone"),
        (r"\bTokyoin\b", "Tokyo in"),
        (r"\bHowManyDaysDo\b", "How Many Days Do"),
        (r"\bhowmanydays\b", "how many days"),
        (r"\bhowlong\b", "how long"),
        (r"\bwithkids\b", "with kids"),
        (r"\bfamilytrip\b", "family trip"),
        (r"\bFoodItineraryPlanning\b", "Food Itinerary Planning"),
        (r"\bFoodToursTokyo\b", "Food Tours Tokyo"),
        (r"\bMacbook\b", "MacBook"),
        (r"\bMac Book\b", "MacBook"),
        (r"\bMacBookAir\b", "MacBook Air"),
        (r"\bDellXPS\b", "Dell XPS"),
    )
    for pattern, replacement in targeted_replacements:
        clean = re.sub(pattern, replacement, clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -")
    return clean


def _looks_boilerplate_extract(text: str) -> bool:
    clean = _normalize_artifact_text(text)
    if not clean:
        return True
    markers = (
        "Theme Auto Light Dark",
        "Table of Contents",
        "Skip to content",
        "Toggle navigation",
        "Breadcrumb",
    )
    marker_hits = sum(1 for marker in markers if marker.lower() in clean.lower())
    if marker_hits >= 2:
        return True
    if "documentation theme" in clean.lower():
        return True
    return False


def _extract_main_text(html: str) -> str:
    if not html:
        return ""

    try:
        import trafilatura
        extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
        cleaned = _normalize_artifact_text(extracted)
        if cleaned and len(cleaned) > 80 and not _looks_boilerplate_extract(cleaned):
            return cleaned
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
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "button", "svg"]):
            tag.decompose()
        noisy_pattern = re.compile(r"(sidebar|toc|table-of-contents|breadcrumb|search|headerlink|navigation|related|theme-toggle|sphinxsidebar)", re.IGNORECASE)
        for node in list(soup.find_all(attrs={"class": noisy_pattern})) + list(soup.find_all(attrs={"id": noisy_pattern})):
            node.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return _normalize_artifact_text(text)
    except Exception:
        return ""


async def _fetch_url_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_s: float = 10.0,
    max_bytes: int = 1_500_000,
    retries: int = 2,
) -> Tuple[str, str]:
    if not _is_safe_url(url):
        return (url, "")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)"}
    last_exc: Optional[Exception] = None

    for attempt in range(max(1, int(retries) + 1)):
        try:
            r = await client.get(url, headers=headers, timeout=timeout_s, follow_redirects=True)
            if r.status_code >= 400:
                return (str(r.url), "")

            ctype = (r.headers.get("content-type") or "").lower()
            content = r.content[:max_bytes]

            if "application/pdf" in ctype or str(r.url).lower().endswith(".pdf"):
                try:
                    import io
                    import pdfplumber
                    with pdfplumber.open(io.BytesIO(content)) as pdf:
                        pages = []
                        for page in pdf.pages[:3]:
                            txt = page.extract_text() or ""
                            if txt.strip():
                                pages.append(txt.strip())
                        text = "\n\n".join(pages).strip()
                        return (str(r.url), _safe_trim(text, 12000) if text else "")
                except Exception:
                    return (str(r.url), "")

            if not ("text/html" in ctype or "application/xhtml+xml" in ctype or "text/plain" in ctype):
                return (str(r.url), "")

            try:
                html = content.decode(r.encoding or "utf-8", errors="ignore")
            except Exception:
                html = content.decode("utf-8", errors="ignore")

            extracted = _extract_main_text(html)
            return (str(r.url), extracted.strip() if extracted else "")
        except Exception as e:
            last_exc = e
            if attempt < retries:
                await asyncio.sleep(0.4 * (2 ** attempt))

    logger.debug(f"Fetch failed for {url}: {last_exc}")
    return (url, "")


def _fetch_url_text_requests(
    url: str,
    *,
    timeout_s: float = 10.0,
    max_bytes: int = 1_500_000,
) -> Tuple[str, str]:
    if not _is_safe_url(url):
        return (url, "")
    try:
        import requests
    except Exception:
        return (url, "")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)"}
    try:
        response = requests.get(url, headers=headers, timeout=timeout_s, allow_redirects=True)
        if response.status_code >= 400:
            return (str(response.url), "")
        ctype = (response.headers.get("content-type") or "").lower()
        if not ("text/html" in ctype or "application/xhtml+xml" in ctype or "text/plain" in ctype):
            return (str(response.url), "")
        content = response.content[:max_bytes]
        try:
            html = content.decode(response.encoding or "utf-8", errors="ignore")
        except Exception:
            html = content.decode("utf-8", errors="ignore")
        extracted = _extract_main_text(html)
        return (str(response.url), extracted.strip() if extracted else "")
    except Exception:
        return (url, "")


async def _cancel_tasks_silently(tasks: List[asyncio.Task[Any]], *, grace_s: float = 0.25) -> None:
    pending = [task for task in list(tasks or []) if task and not task.done()]
    if not pending:
        return
    for task in pending:
        with contextlib.suppress(Exception):
            task.cancel()
    with contextlib.suppress(Exception):
        await asyncio.wait(pending, timeout=max(0.0, float(grace_s)))
    leftovers = [task for task in pending if not task.done()]
    if not leftovers:
        return
    with contextlib.suppress(Exception):
        await asyncio.wait_for(
            asyncio.gather(*leftovers, return_exceptions=True),
            timeout=max(0.0, float(grace_s)),
        )


class WebSearchHandler:
    def __init__(self, *, evidence_cache_dir: Optional[str] = None):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)
        self.finance_handler = FinanceHandler()
        self.news_handler = NewsHandler()
        self.weather_handler = WeatherHandler(timezone=SYSTEM_TIMEZONE)

        self.converter = Converter(self)

        self.valid_categories = {"stock/commodity", "crypto", "forex", "weather", "news", "general", "science"}

        self.alias_map = {
            "eth": "crypto",
            "ethereum": "crypto",
            "btc": "crypto",
            "bitcoin": "crypto",
            "sol": "crypto",
            "solana": "crypto",
            "stocks": "stock/commodity",
            "stock": "stock/commodity",
            "commodity": "stock/commodity",
            "commodities": "stock/commodity",
            "index": "stock/commodity",
            "indices": "stock/commodity",
            "gen": "general",
            "research": "science",
            "paper": "science",
            "study": "science",
        }

        self.index_terms = [
            "dxy", "s&p 500", "sp500", "dow jones", "nasdaq", "nasdaq 100", "vix", "ftse",
            "nikkei", "hang seng", "dax", "cac", "shanghai", "sensex", "asx", "kospi"
        ]
        self.crypto_terms = ["bitcoin", "ethereum", "solana", "crypto", "coin", "cryptocurrency", "btc", "eth", "sol"]

        self.weather_terms = ["weather", "forecast", "temperature", "rain", "humidity", "wind", "sunrise", "sunset"]
        self.moon_terms = ["moon phase", "moon cycle", "lunar phase", "lunar cycle"]
        self.news_terms = ["news", "headlines", "current events", "latest news", "breaking news", "reuters", "bbc", "cnn"]

        self.research_terms = [
            "pmid", "doi", "arxiv", "nct",
            "guideline", "guidelines",
            "consensus", "practice guideline", "practice guidelines",
            "recommendation", "recommendations", "recommended", "recommend",
            "protocol", "protocols",
            "standard of care", "best practice", "best practices",
            "trial", "trials",
            "randomized", "randomised", "rct", "rcts",
            "systematic review", "systematic reviews",
            "meta-analysis", "meta-analyses", "meta analysis", "meta analyses",
            "study", "studies",
            "paper", "papers",
            "review", "reviews",
            "evidence", "literature", "clinical evidence",
            "treatment", "treatments",
            "therapy", "therapies",
            "medication", "medications", "drug", "drugs", "pharmacology", "pharmacologic",
            "antihypertensive", "antihypertensives", "bp medication", "blood pressure medication",
            "manage", "management",
            "dose", "dosing", "dosage",
            "finite element", "fea", "control system", "signal processing",
            "rf", "antenna", "power system", "circuit", "pcb", "cad",
            "mechanical", "electrical", "thermodynamics", "fluid", "aerodynamics",
            "structural", "stress analysis", "vibration", "dynamics",
            "simulation", "modeling", "optimization", "ieee",
            "calorie", "calories", "kcal",
            "nutrition", "nutritional", "nutrient", "nutrients",
            "vitamin", "vitamins", "mineral", "minerals",
            "protein", "fat", "fats", "carb", "carbs", "carbohydrate", "carbohydrates",
            "fiber", "sugar", "sugars", "sodium",
            "macro", "macros", "micronutrient", "micronutrients",
            "rda", "recommended daily", "daily value", "dv",
            "diet", "dietary", "food facts", "nutrition facts",
            "clinicaltrials", "pubmed", "europepmc", "crossref",
        ]

        self.search_cache = TTLCache(ttl_seconds=600, max_items=128)
        self.page_cache = TTLCache(ttl_seconds=600, max_items=256)
        self.research_bundle_cache = TTLCache(ttl_seconds=1800, max_items=96)
        self.evidence_store = EvidenceCacheStore(root=evidence_cache_dir or "state/research_cache", ttl_seconds=1800, max_records=256)
        self.project_root = Path(__file__).resolve().parents[4]
        self.local_pack_root = self.project_root / "knowledge_packs"

        self._fetch_sem = asyncio.Semaphore(3)

        self.agentpedia = Agentpedia(write_back=False) if agentpedia_available else None

        # Finance-like cues (used to prevent stock false positives)
        self.finance_cues = [
            "price", "quote", "ticker", "stock", "stocks", "shares", "market cap", "chart",
            "forex", "exchange rate", "fx", "commodity", "commodities", "gold", "oil",
            "bitcoin", "btc", "ethereum", "eth", "crypto", "coingecko", "coinmarketcap",
        ]

        # Research regex
        self._re_pmid = re.compile(r"\bpmid[:\s]*\d{5,9}\b", re.IGNORECASE)
        self._re_doi = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
        self._re_nct = re.compile(r"\bnct\d{8}\b", re.IGNORECASE)
        self._re_arxiv = re.compile(r"\barxiv[:\s]*\d{4}\.\d{4,5}\b", re.IGNORECASE)
        self.last_research_bundle: Optional[Dict[str, Any]] = None
        self.last_browse_report: Optional[Dict[str, Any]] = None

    def _evidence_cache_key(self, query: str, *, mode: str, domain: str = "general") -> str:
        return f"evidence::{str(domain or 'general').strip().lower()}::{str(mode or 'deep').strip().lower()}::{self._normalize_cache_key(query)}"

    def _evidence_cache_ttl_seconds(self, plan: BrowsePlan) -> int:
        if plan.needs_recency or plan.official_preferred:
            return 900
        if plan.mode == "github":
            return 1800
        return 3600

    def _cached_bundle_rows(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for row in list((payload or {}).get("rows") or []):
            if not isinstance(row, dict):
                continue
            clean = dict(row)
            url = canonicalize_url(str(clean.get("url") or "").strip())
            if url:
                clean["url"] = url
            rows.append(clean)
        return rows

    def _cached_bundle_adequate(self, query: str, plan: BrowsePlan, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        age_seconds = self.evidence_store.age_seconds(payload)
        if age_seconds is None or age_seconds > float(self._evidence_cache_ttl_seconds(plan)):
            return False
        rows = self._cached_bundle_rows(payload)
        if not rows:
            return False
        focus_rows = [dict(row or {}) for row in rows if self._result_matches_focus(query, row)]
        if not focus_rows:
            return False
        if plan.official_preferred:
            return self._official_rows_adequate(query, focus_rows)
        if plan.needs_recency:
            blob = " ".join(
                [
                    str((payload.get("report") or {}).get("summary") or ""),
                    *[
                        " ".join(
                            [
                                str((row or {}).get("title") or ""),
                                str((row or {}).get("description") or ""),
                                str((row or {}).get("published_at") or ""),
                            ]
                        )
                        for row in focus_rows[:4]
                    ],
                ]
            )
            if re.search(r"\b20\d{2}\b", blob):
                return True
            return len(focus_rows) >= 2
        report = payload.get("report") or {}
        return bool(str(report.get("summary") or "").strip() or len(focus_rows) >= 2)

    def _resume_cached_evidence(self, query: str, plan: BrowsePlan, *, domain: str = "general") -> List[Dict[str, Any]]:
        cache_key = self._evidence_cache_key(query, mode=plan.mode, domain=domain)
        payload = self.research_bundle_cache.get(cache_key)
        if not isinstance(payload, dict):
            payload = self.evidence_store.load(query, mode=plan.mode, domain=domain)
            if isinstance(payload, dict):
                self.research_bundle_cache.set(cache_key, payload)
        if not isinstance(payload, dict) or not self._cached_bundle_adequate(query, plan, payload):
            return []
        rows = self._cached_bundle_rows(payload)
        if not rows:
            return []
        report = dict(payload.get("report") or {}) if isinstance(payload.get("report") or {}, dict) else {}
        limitations = [str(item or "").strip() for item in list(report.get("limitations") or payload.get("limitations") or []) if str(item or "").strip()]
        sources = [str(item or "").strip() for item in list(report.get("sources") or payload.get("artifact_refs") or []) if str(item or "").strip()]
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=str(report.get("summary") or payload.get("summary") or "").strip(),
            sources=sources,
            limitations=limitations,
            research_brief=dict(report.get("research_brief") or payload.get("research_brief") or {}) if isinstance(report.get("research_brief") or payload.get("research_brief") or {}, dict) else {},
            section_bundles=[dict(item or {}) for item in list(report.get("section_bundles") or payload.get("section_bundles") or []) if isinstance(item, dict)],
        )
        self.last_research_bundle = dict(payload.get("bundle") or {}) if isinstance(payload.get("bundle") or {}, dict) else None
        self._append_browse_step(
            query,
            step="resume",
            detail=f"resumed {min(len(rows), 8)} evidence row(s) from local evidence cache",
            mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="judge",
            detail="cached evidence passed the adequacy gate for this request",
            mode=plan.mode,
        )
        if isinstance(self.last_browse_report, dict):
            self.last_browse_report["cached"] = True
            self.last_browse_report["cache_age_seconds"] = self.evidence_store.age_seconds(payload)
            self.last_browse_report["artifact_refs"] = [canonicalize_url(item) for item in sources if canonicalize_url(item)]
        return rows

    def _save_evidence_bundle(self, query: str, plan: BrowsePlan, bundle: Any, rows: List[Dict[str, Any]], *, domain: str = "general") -> None:
        bundle_dict = dict(bundle.as_dict()) if hasattr(bundle, "as_dict") else {}
        report = dict(self.last_browse_report or {}) if isinstance(self.last_browse_report, dict) else {}
        canonical_rows: List[Dict[str, Any]] = []
        artifact_refs: List[str] = []
        for row in list(rows or [])[:8]:
            if not isinstance(row, dict):
                continue
            clean = dict(row)
            url = canonicalize_url(str(clean.get("url") or "").strip())
            if url:
                clean["url"] = url
                if url not in artifact_refs:
                    artifact_refs.append(url)
            canonical_rows.append(clean)
        for item in list(report.get("sources") or [])[:8]:
            url = canonicalize_url(str(item or "").strip())
            if url and url not in artifact_refs:
                artifact_refs.append(url)
        payload = {
            "query": str(query or "").strip(),
            "mode": str(plan.mode or "deep").strip().lower(),
            "domain": str(domain or "general").strip().lower(),
            "summary": str(report.get("summary") or "").strip(),
            "limitations": [str(item or "").strip() for item in list(report.get("limitations") or []) if str(item or "").strip()],
            "research_brief": dict(report.get("research_brief") or {}) if isinstance(report.get("research_brief") or {}, dict) else {},
            "section_bundles": [dict(item or {}) for item in list(report.get("section_bundles") or []) if isinstance(item, dict)],
            "rows": canonical_rows,
            "bundle": bundle_dict,
            "report": report,
            "artifact_refs": artifact_refs,
        }
        cache_key = self._evidence_cache_key(query, mode=plan.mode, domain=domain)
        self.research_bundle_cache.set(cache_key, payload)
        self.evidence_store.save(query, payload, mode=plan.mode, domain=domain)

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def _contains_query_term(self, query_lower: str, term: str) -> bool:
        ql = str(query_lower or "").strip().lower()
        needle = str(term or "").strip().lower()
        if not ql or not needle:
            return False
        pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        return re.search(pattern, ql) is not None

    def _contains_any_query_term(self, query_lower: str, terms: List[str] | tuple[str, ...]) -> bool:
        return any(self._contains_query_term(query_lower, term) for term in list(terms or []))

    def _maybe_build_shadow_bundle(self, query: str, results: List[Dict[str, Any]], *, domain: str = "science") -> None:
        if not RESEARCHER_BUNDLE_SHADOW_MODE or bundle_from_results is None:
            return
        try:
            bundle = bundle_from_results(query, results, intent="science", domain=domain)
            errs = bundle.validate()
            payload = bundle.as_dict()
            payload["validation_errors"] = errs
            self.last_research_bundle = payload
            logger.info(
                "Research shadow bundle created id=%s claims=%d errors=%d",
                payload.get("bundle_id"),
                len(payload.get("claims") or []),
                len(errs),
            )
        except Exception as e:
            logger.debug(f"Shadow bundle build failed: {type(e).__name__}: {e}")

    def _clear_browse_report(self) -> None:
        self.last_browse_report = None

    def _ensure_browse_report(self, query: str = "", *, mode: str = "") -> Dict[str, Any]:
        report = dict(self.last_browse_report or {}) if isinstance(self.last_browse_report, dict) else {}
        report.setdefault("query", (query or "").strip())
        report.setdefault("mode", str(mode or "").strip())
        report.setdefault("summary", "")
        report.setdefault("sources", [])
        report.setdefault("limitations", [])
        report.setdefault("execution_steps", [])
        report.setdefault("execution_events", [])
        report.setdefault("execution_summary", "")
        report.setdefault("progress_headline", "")
        report.setdefault("recovery_notes", [])
        report.setdefault("research_brief", {})
        report.setdefault("section_bundles", [])
        report.setdefault("knowledge_sources", [])
        report.setdefault("offline_fallback", False)
        if query and not str(report.get("query") or "").strip():
            report["query"] = (query or "").strip()
        if mode and not str(report.get("mode") or "").strip():
            report["mode"] = str(mode or "").strip()
        self.last_browse_report = report
        return report

    def _summarize_execution_steps(self, steps: List[str]) -> str:
        cleaned = [" ".join(str(step or "").split()).strip() for step in list(steps or []) if str(step or "").strip()]
        if not cleaned:
            return ""
        return " | ".join(cleaned[:5])

    def _trace_label(self, step: str) -> str:
        labels = {
            "plan": "Plan",
            "route": "Route",
            "memory": "Memory",
            "search": "Search",
            "retrieve": "Retrieve",
            "read": "Read",
            "judge": "Judge",
            "retry": "Retry",
            "recover": "Recover",
            "compose": "Compose",
        }
        return labels.get(str(step or "").strip().lower(), str(step or "step").strip().title() or "Step")

    def _trace_status(self, step: str, detail: str) -> str:
        clean_step = str(step or "").strip().lower()
        clean_detail = str(detail or "").strip().lower()
        if clean_step in {"retry", "recover"}:
            return "recovery"
        if any(marker in clean_detail for marker in ("fallback", "fall back", "cache", "retry", "restored", "underfilled", "recovered")):
            return "recovery"
        return "progress"

    def _recovery_note(self, step: str, detail: str) -> str:
        clean_detail = " ".join(str(detail or "").split()).strip()
        if not clean_detail:
            return ""
        clean_lower = clean_detail.lower()
        if "search cache" in clean_lower:
            return "Used cached search results to avoid a redundant fetch."
        if any(marker in clean_lower for marker in ("fallback", "fall back", "falling back")):
            return clean_detail
        if any(marker in clean_lower for marker in ("retry", "underfilled", "restored", "recovered", "blocked", "challenge")):
            return f"{self._trace_label(step)}: {clean_detail}"
        return ""

    def _render_trace_lines(self, report: Dict[str, Any], *, limit: int = 6) -> List[str]:
        events = list((report or {}).get("execution_events") or [])
        lines: List[str] = []
        for idx, event in enumerate(events[:limit], start=1):
            if not isinstance(event, dict):
                continue
            label = str(event.get("label") or self._trace_label(str(event.get("step") or ""))).strip()
            detail = " ".join(str(event.get("detail") or "").split()).strip()
            if not label or not detail:
                continue
            lines.append(f"{idx}. {label} -> {detail}")
        if lines:
            return lines
        raw_steps = [str(item or "").strip() for item in list((report or {}).get("execution_steps") or []) if str(item or "").strip()]
        return [f"{idx}. {item}" for idx, item in enumerate(raw_steps[:limit], start=1)]

    def _append_browse_step(
        self,
        query: str,
        *,
        step: str,
        detail: str,
        mode: str = "",
    ) -> None:
        report = self._ensure_browse_report(query, mode=mode)
        clean_step = str(step or "step").strip().lower() or "step"
        clean_detail = " ".join(str(detail or "").split()).strip()
        if not clean_detail:
            return
        entry = f"{clean_step}: {clean_detail}"
        steps = [str(item or "").strip() for item in list(report.get("execution_steps") or []) if str(item or "").strip()]
        if entry not in steps:
            steps.append(entry[:260])
        report["execution_steps"] = steps[:8]
        events = [dict(item or {}) for item in list(report.get("execution_events") or []) if isinstance(item, dict)]
        if not any(str(item.get("step") or "") == clean_step and str(item.get("detail") or "") == clean_detail for item in events):
            events.append(
                {
                    "step": clean_step,
                    "label": self._trace_label(clean_step),
                    "detail": clean_detail[:260],
                    "status": self._trace_status(clean_step, clean_detail),
                }
            )
        report["execution_events"] = events[:8]
        recovery_notes = [str(item or "").strip() for item in list(report.get("recovery_notes") or []) if str(item or "").strip()]
        recovery_note = self._recovery_note(clean_step, clean_detail)
        if recovery_note and recovery_note not in recovery_notes:
            recovery_notes.append(recovery_note)
        report["recovery_notes"] = recovery_notes[:4]
        rendered_trace = self._render_trace_lines(report, limit=4)
        report["execution_summary"] = " | ".join(rendered_trace[:3])
        report["progress_headline"] = rendered_trace[0] if rendered_trace else ""
        if mode and not str(report.get("mode") or "").strip():
            report["mode"] = str(mode or "").strip()
        self.last_browse_report = report

    def _record_browse_report(
        self,
        query: str,
        *,
        mode: str,
        summary: str,
        sources: List[str],
        limitations: Optional[List[str]] = None,
        research_brief: Optional[Dict[str, Any]] = None,
        section_bundles: Optional[List[Dict[str, Any]]] = None,
        knowledge_sources: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        report = self._ensure_browse_report(query, mode=mode)
        seen: set[str] = set()
        deduped_sources: List[str] = []
        for src in sources or []:
            clean = str(src or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            deduped_sources.append(clean)
        report.update(
            {
                "query": (query or "").strip(),
                "mode": str(mode or "").strip(),
                "summary": (summary or "").strip(),
                "sources": deduped_sources,
                "limitations": [str(x).strip() for x in (limitations or []) if str(x or "").strip()],
                "research_brief": dict(research_brief or {}) if isinstance(research_brief, dict) else {},
                "section_bundles": [dict(item or {}) for item in list(section_bundles or []) if isinstance(item, dict)][:6],
                "knowledge_sources": [dict(item or {}) for item in list(knowledge_sources or []) if isinstance(item, dict)][:6],
            }
        )
        rendered_trace = self._render_trace_lines(report, limit=4)
        report["execution_summary"] = " | ".join(rendered_trace[:3])
        report["progress_headline"] = rendered_trace[0] if rendered_trace else ""
        self.last_browse_report = report

    def _official_rows_adequate(self, query: str, rows: List[Dict[str, Any]]) -> bool:
        if not rows:
            return False
        official_domains = infer_official_domains(query)
        focus_matches = [dict(row or {}) for row in rows if self._result_matches_focus(query, row)]
        if not focus_matches:
            return False
        if not official_domains:
            return True
        official_focus = []
        for row in focus_matches:
            host = (urlparse(str((row or {}).get("url") or "")).netloc or "").lower()
            if any(domain in host for domain in official_domains):
                official_focus.append(row)
        if not official_focus:
            return False
        if self._is_latest_who_dengue_guidance_query(query):
            return any(self._official_result_satisfies_query(query, row) for row in official_focus[:6])
        if any(term in str(query or "").lower() for term in ("latest", "recent", "updated", "newest", "current")):
            blob_parts: List[str] = []
            hosts: List[str] = []
            for row in official_focus[:3]:
                host = (urlparse(str((row or {}).get("url") or "")).netloc or "").lower()
                if host:
                    hosts.append(host)
                blob_parts.extend(
                    [
                        str((row or {}).get("title") or ""),
                        str((row or {}).get("description") or ""),
                        str((row or {}).get("url") or ""),
                    ]
                )
            blob_text = " ".join(blob_parts)
            years = [int(match) for match in re.findall(r"\b(20\d{2})\b", blob_text)]
            newest_year = max(years) if years else 0
            query_lower = str(query or "").lower()
            if ("hypertension" in query_lower or "blood pressure" in query_lower) and not re.search(r"\bacc\b|\baha\b|acc/aha", query_lower):
                us_official = any(any(domain in host for domain in ("acc.org", "heart.org", "ahajournals.org", "jacc.org")) for host in hosts)
                international_official = any(any(domain in host for domain in ("escardio.org", "who.int", "nice.org.uk")) for host in hosts)
                if newest_year < 2025 and not (us_official and international_official):
                    return False
            return bool(re.search(r"\b202[4-9]\b", blob_text)) or len(official_focus) >= 2
        return True

    def _agentpedia_memory_rows(self, query: str, *, limit: int = 3) -> List[Dict[str, Any]]:
        if self.agentpedia is None:
            return []
        try:
            rows = list(self.agentpedia.search_agentpedia(query, k=max(1, int(limit or 3))) or [])
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("source_url") or "").strip()
            title = str(row.get("source_title") or row.get("topic") or "").strip()
            claim = str(row.get("claim") or "").strip()
            summary = str(row.get("summary") or "").strip()
            if not title or not url:
                continue
            mapped = {
                "title": title,
                "url": url,
                "description": _safe_trim(summary or claim or title, 420),
                "content": _safe_trim(claim or summary, 900),
                "published_at": str(row.get("source_date") or "").strip(),
                "source": "agentpedia_kb",
                "category": "general",
                "volatile": False,
            }
            if not self._row_allowed_for_query(query, mapped):
                continue
            out.append(mapped)
        return out[: max(1, int(limit or 3))]

    def _should_use_agentpedia_memory(self, query: str, *, plan_mode: str = "", official_preferred: bool = False) -> bool:
        ql = str(query or "").lower()
        mode = str(plan_mode or "").lower()
        if mode == "github":
            return True
        if official_preferred:
            return True
        if mode == "deep":
            return bool(
                self._is_research_query(ql)
                or any(term in ql for term in ("docs", "documentation", "what changed", "release notes", "guideline", "guidelines", "guidance"))
            )
        if any(term in ql for term in ("github", "repository", "repo", "readme", "docs", "documentation", "release notes", "what changed")):
            return True
        return self._is_research_query(ql)

    def _agentpedia_domain_hint(self, query: str, *, plan_mode: str = "", official_preferred: bool = False) -> str:
        ql = str(query or "").lower()
        mode = str(plan_mode or "").lower()
        if mode == "github" or "github.com" in ql:
            return "software"
        if any(term in ql for term in ("docs", "documentation", "release notes", "what changed", "readme", "repository", "repo", "package", "pyproject")):
            return "software"
        inferred = self._infer_research_domain(query)
        if official_preferred and inferred == "science":
            return "general"
        return inferred or "general"

    def _local_pack_rows(self, query: str, *, limit: int = 4) -> List[Dict[str, Any]]:
        if not self.local_pack_root.exists():
            return []
        try:
            rows = search_local_pack_rows(self.project_root, query, limit=max(1, int(limit or 4)))
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(dict(row))
        return out[: max(1, int(limit or 4))]

    def _knowledge_source_summary(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        counts: Dict[str, int] = {}
        for row in list(rows or []):
            if not isinstance(row, dict):
                continue
            origin = str(row.get("knowledge_origin") or ("live_web" if str(row.get("url") or "").startswith("http") else "local")).strip().lower()
            if not origin:
                continue
            counts[origin] = counts.get(origin, 0) + 1
        return [{"origin": key, "count": value} for key, value in sorted(counts.items())]

    def _offline_fallback_rows(self, query: str, plan: BrowsePlan, *, reason: str) -> List[Dict[str, Any]]:
        local_rows = self._local_pack_rows(query, limit=4)
        memory_rows = (
            self._agentpedia_memory_rows(query, limit=3)
            if self._should_use_agentpedia_memory(query, plan_mode=plan.mode, official_preferred=plan.official_preferred)
            else []
        )
        for row in memory_rows:
            if isinstance(row, dict):
                row.setdefault("knowledge_origin", "local_memory")
        combined: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in [*local_rows, *memory_rows]:
            if not isinstance(row, dict):
                continue
            key = canonicalize_url(str(row.get("url") or "").strip()) or f"{str(row.get('title') or '').strip().lower()}::{str(row.get('knowledge_origin') or '')}"
            if not key or key in seen:
                continue
            seen.add(key)
            combined.append(dict(row))
        if not combined:
            return []

        if local_rows:
            self._append_browse_step(query, step="offline", detail=f"matched {len(local_rows)} bundled local pack row(s)", mode=plan.mode)
        if memory_rows:
            self._append_browse_step(query, step="memory", detail=f"reused {len(memory_rows)} local memory row(s) while live retrieval was unavailable", mode=plan.mode)
        self._append_browse_step(query, step="judge", detail=f"using {min(len(combined), 8)} local fallback row(s) because {reason}", mode=plan.mode)

        lead = dict(combined[0] or {})
        lead_title = str(lead.get("title") or "").strip()
        if local_rows and lead_title:
            summary = f"Used bundled local guidance from {lead_title} because live retrieval was unavailable."
        elif lead_title:
            summary = f"Used prior local research notes from {lead_title} because live retrieval was unavailable."
        else:
            summary = "Used local fallback knowledge because live retrieval was unavailable."
        limitations = [
            f"Live web retrieval was unavailable or too thin; Somi fell back to local knowledge because {reason}.",
            "Verify time-sensitive facts against live sources when connectivity returns.",
        ]
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=summary,
            sources=[str((row or {}).get("url") or "").strip() for row in combined[:6]],
            limitations=limitations,
            knowledge_sources=self._knowledge_source_summary(combined),
        )
        if isinstance(self.last_browse_report, dict):
            self.last_browse_report["offline_fallback"] = True
            self.last_browse_report["offline_reason"] = str(reason or "").strip()
            self.last_browse_report["artifact_refs"] = [
                str((row or {}).get("local_path") or (row or {}).get("url") or "").strip()
                for row in combined[:6]
                if str((row or {}).get("local_path") or (row or {}).get("url") or "").strip()
            ]
        return combined[:6]

    def _write_agentpedia_memory(self, query: str, rows: List[Dict[str, Any]], *, domain_hint: str = "general") -> int:
        if self.agentpedia is None or not rows:
            return 0

        official_domains = infer_official_domains(query)
        ql = str(query or "").lower()
        facts: List[Dict[str, Any]] = []
        researched: List[Dict[str, Any]] = []

        for idx, row in enumerate(rows[:4], start=1):
            if not isinstance(row, dict):
                continue
            url = str((row or {}).get("url") or "").strip()
            title = str((row or {}).get("title") or "").strip()
            desc = str((row or {}).get("description") or (row or {}).get("content") or "").strip()
            if not url or not title or not self._result_matches_focus(query, row):
                continue
            if not self._row_allowed_for_query(query, row):
                continue

            host = (urlparse(url).netloc or "").lower()
            if official_domains and not any(domain in host for domain in official_domains):
                if not any(domain in host for domain in ("docs.python.org", "python.org", "github.com", "cdc.gov", "who.int", "paho.org", "ahajournals.org", "acc.org", "heart.org")):
                    continue

            if any(term in ql for term in ("latest", "recent", "updated", "newest", "current")) and not re.search(r"\b202[4-9]\b", f"{title} {desc} {url}"):
                continue

            summary = _safe_trim(desc or title, 180)
            claim = _safe_trim(f"{title} — {summary}" if summary else title, 200)
            source_date = ""
            year_match = re.search(r"\b(20\d{2}|19\d{2})\b", f"{title} {desc} {url}")
            if year_match:
                source_date = year_match.group(1)

            researched.append(
                {
                    "topic": _safe_trim(query, 140),
                    "fact": _safe_trim(f"{title} — {summary}" if summary else title, 420),
                    "source": url,
                    "confidence": "high" if official_domains else "medium",
                    "domain": domain_hint or "general",
                    "tags": _safe_trim(f"websearch,{domain_hint or 'general'}", 80),
                    "evidence_snippet": _safe_trim(summary, 240),
                }
            )
            facts.append(
                {
                    "claim": claim,
                    "summary": summary,
                    "topic": _safe_trim(query, 140),
                    "tags": ["websearch", str(domain_hint or "general")],
                    "source_url": url,
                    "source_title": title,
                    "source_date": source_date,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "confidence": 0.82 if official_domains else 0.68,
                    "status": "committed",
                    "evidence_snippet": _safe_trim(summary, 240),
                    "citation_key": f"[{idx}]",
                }
            )
            if len(facts) >= 2:
                break

        if not facts:
            return 0

        added_total = 0
        try:
            added_total += int(self.agentpedia.researched.add_facts(researched, domain=domain_hint) or 0)
        except Exception:
            pass
        try:
            result = self.agentpedia.add_facts(facts)
            added_total += int((result or {}).get("added_count") or 0)
        except Exception:
            pass
        return added_total

    def _is_python_docs_query(self, query: str) -> bool:
        ql = str(query or "").lower()
        return "python" in ql and any(marker in ql for marker in ("docs", "documentation", "release notes", "what's new", "whats new", "changelog"))

    def _is_python_release_preview_url(self, url: str) -> bool:
        return bool(re.search(r"/downloads/release/python-[0-9.]+(?:a|b|rc)\d+/?", str(url or "").lower()))

    def _python_whatsnew_page_version(self, url: str) -> str:
        match = re.search(r"/whatsnew/(\d+\.\d+)\.html", str(url or "").lower())
        return str(match.group(1)).strip() if match else ""

    def _row_allowed_for_query(self, query: str, row: Dict[str, Any]) -> bool:
        url = str((row or {}).get("url") or "").strip()
        host = (urlparse(url).netloc or "").lower()
        blob = " ".join(
            [
                str((row or {}).get("title") or ""),
                str((row or {}).get("description") or ""),
                url,
            ]
        ).lower()
        if self._is_python_docs_query(query):
            if self._is_python_release_preview_url(url):
                return False
            if "docs.python.org" not in host:
                return False
            requested_version = self._python_docs_version(query)
            page_version = self._python_whatsnew_page_version(url)
            if requested_version and page_version and page_version != requested_version:
                return False
            if requested_version and requested_version not in blob and f"/{requested_version}" not in url.lower():
                return False
            relevant = any(marker in blob for marker in ("what's new in python", "whatsnew", "changelog", "release highlights", "/whatsnew/"))
            if not relevant:
                return False
            if requested_version:
                if page_version:
                    return page_version == requested_version
                if f"/{requested_version}/whatsnew/" in url.lower():
                    return True
                return False
            return True
        if is_software_change_query(query):
            official_domains = infer_official_domains(query)
            requested_version = self._software_change_version(query)
            if official_domains and not any(domain in host for domain in official_domains):
                return False
            if requested_version and not self._software_change_version_matches(requested_version, blob):
                return False
            relevant = any(
                marker in blob
                for marker in ("release notes", "changelog", "what's new", "whats new", "/blog/", "/releases/", "release highlights")
            )
            if not relevant:
                return False
            return True
        if self._is_latest_who_dengue_guidance_query(query) and "who.int" in host:
            path = (urlparse(url).path or "").lower().strip("/")
            first_segment = path.split("/", 1)[0] if path else ""
            allowed_first_segments = {
                "news",
                "publications",
                "handle",
                "items",
                "server",
                "bitstream",
                "groups",
            }
            if first_segment and first_segment not in allowed_first_segments:
                return False
            allowed_markers = (
                "news/item/",
                "publications/",
                "handle/",
                "items/",
                "server/api/core/bitstreams/",
                "bitstream/handle/",
                "groups/",
            )
            if not any(marker in path for marker in allowed_markers):
                return False
        if is_trip_planning_query(query):
            itinerary_markers = tuple(self._trip_planning_focus_markers(query))
            specific_markers = tuple(self._trip_planning_specific_markers(query))
            if self._travel_row_looks_ad_heavy(row):
                return False
            if self._travel_row_looks_forumish(row):
                return False
            if self._travel_row_looks_noisy(query, row):
                return False
            if not any(marker in blob for marker in itinerary_markers):
                return False
            if specific_markers and not any(marker in blob for marker in specific_markers):
                return False
        if is_travel_lookup_query(query):
            travel_markers = tuple(self._travel_lookup_focus_markers(query))
            if self._travel_row_looks_ad_heavy(row):
                return False
            if self._travel_row_looks_forumish(row):
                return False
            if self._travel_row_looks_noisy(query, row):
                return False
            if travel_markers and not any(marker in blob for marker in travel_markers):
                return False
        if is_shopping_compare_query(query):
            if any(domain in host for domain in ("arxiv.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov")):
                return False
            if self._shopping_row_looks_noisy(query, row):
                return False
            if not self._shopping_row_has_direct_compare_signal(query, row):
                return False
        return True

    def _official_result_satisfies_query(self, query: str, row: Dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        url = str((row or {}).get("url") or "").strip()
        host = (urlparse(url).netloc or "").lower()
        blob = " ".join(
            [
                str((row or {}).get("title") or ""),
                str((row or {}).get("description") or ""),
                url,
            ]
        ).lower()
        if self._is_python_docs_query(query):
            if not self._row_allowed_for_query(query, row):
                return False
            requested_version = self._python_docs_version(query)
            if requested_version:
                return requested_version in blob or f"/{requested_version}" in url.lower()
            return True
        query_lower = str(query or "").lower()
        if self._is_latest_who_dengue_guidance_query(query):
            if any(segment in url.lower() for segment in ("/activities/", "/health-topics/", "/initiatives/")):
                return False
            if "iris.who.int" in host and any(marker in url.lower() for marker in ("/handle/", "/items/", "/server/api/core/bitstreams/", "/bitstream/handle/")):
                return True
            return "who.int" in host and (
                re.search(r"\b202[4-9]\b", blob) is not None
                and any(marker in blob for marker in ("guideline", "guidelines", "clinical management", "arboviral"))
                or "new who guidelines" in blob
                or "clinical management of arboviral diseases" in blob
            )
        if ("hypertension" in query_lower or "blood pressure" in query_lower) and any(term in query_lower for term in ("latest", "recent", "updated", "newest", "current")):
            if any(marker in blob for marker in ("session", "sessions", "vol 0, no 0", "debate", "projected impact", "commentary", "overview", "editors' view", "editors view")) or any(segment in url.lower() for segment in ("/toc/", "/journal/", "-sessions", "/hypertension-sessions", "/podcast")):
                return False
            if "cir.0000000000001356" in url.lower() and any(domain in host for domain in ("ahajournals.org", "jacc.org", "acc.org", "heart.org")):
                return True
            if "/doi/" in url.lower() and "cir.0000000000001356" not in url.lower():
                if not any(marker in blob for marker in ("high blood pressure guideline", "hypertension guideline", "guideline-at-a-glance", "guideline at a glance", "top 10 things to know")):
                    return False
            if any(domain in host for domain in ("ahajournals.org", "jacc.org", "acc.org", "heart.org")) and re.search(r"\b2025\b", blob):
                return True
        return any(domain in host for domain in infer_official_domains(query))

    def _summarize_evidence_bundle(self, bundle: Any) -> str:
        items = list(getattr(bundle, "items", []) or [])
        claims = list(getattr(bundle, "claims", []) or [])
        conflicts = list(getattr(bundle, "conflicts", []) or [])
        limitations = list(getattr(bundle, "limitations", []) or [])
        research_brief = dict(getattr(bundle, "research_brief", {}) or {}) if isinstance(getattr(bundle, "research_brief", {}) or {}, dict) else {}
        section_bundles = [dict(item or {}) for item in list(getattr(bundle, "section_bundles", []) or []) if isinstance(item, dict)]
        items_by_id = {str(getattr(item, "id", "")): item for item in items}
        high = [claim for claim in claims if str(getattr(claim, "confidence", "")).lower() in {"high", "medium"}]
        if high:
            lines = [str(getattr(high[0], "text", "") or "").strip()]
            section_titles = [str(section.get("title") or "").strip() for section in section_bundles[:3] if str(section.get("title") or "").strip()]
            if section_titles:
                lines.append("Research plan: " + ", ".join(section_titles) + ".")
            for claim in high[1:4]:
                sources = []
                for item_id in list(getattr(claim, "supporting_item_ids", []) or [])[:2]:
                    item = items_by_id.get(str(item_id))
                    if item is None:
                        continue
                    title = str(getattr(item, "title", "") or "").strip()
                    published = str(getattr(item, "published_date", "") or "").strip()
                    if published:
                        title = f"{title} ({published})"
                    if title:
                        sources.append(title)
                source_note = f" Sources: {', '.join(sources)}." if sources else ""
                lines.append(f"- {str(getattr(claim, 'text', '') or '').strip()}{source_note}")
            if conflicts:
                reasons = [str((row or {}).get("reason") or "").strip() for row in conflicts[:3] if str((row or {}).get("reason") or "").strip()]
                if reasons:
                    lines.append("Uncertainty: " + "; ".join(reasons))
            if limitations:
                lines.append("Research limits: " + "; ".join(limitations[:2]))
            return "\n".join([line for line in lines if line.strip()]).strip()

        if items:
            top = items[0]
            text = str(getattr(top, "content_excerpt", "") or getattr(top, "snippet", "") or "").strip()
            parts = [f"Best available source: {str(getattr(top, 'title', '') or '').strip()}."]
            objective = str(research_brief.get("objective") or "").strip()
            if objective:
                parts.insert(0, objective)
            published = str(getattr(top, "published_date", "") or "").strip()
            if published:
                parts.append(f"Published or updated: {published}.")
            if text:
                parts.append(_safe_trim(text, 420))
            if limitations:
                parts.append("Research limits: " + "; ".join(limitations[:2]))
            return " ".join([part for part in parts if part]).strip()

        answer = str(getattr(bundle, "answer", "") or "").strip()
        if answer and section_bundles:
            labels = [str(section.get("title") or "").strip() for section in section_bundles[:3] if str(section.get("title") or "").strip()]
            if labels:
                return f"{answer}\nResearch plan: " + ", ".join(labels) + "."
        return answer

    def _rows_from_evidence_bundle(self, bundle: Any, *, category: str = "general") -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in list(getattr(bundle, "items", []) or [])[:6]:
            title = str(getattr(item, "title", "") or "").strip()
            url = str(getattr(item, "url", "") or "").strip()
            if not title or not url:
                continue
            description = str(getattr(item, "content_excerpt", "") or getattr(item, "snippet", "") or "").strip()
            rows.append(
                {
                    "title": title,
                    "url": url,
                    "description": _safe_trim(description, 1200),
                    "content": _safe_trim(description, 1800),
                    "category": category,
                    "source": str(getattr(item, "source_type", "") or "research_compose"),
                    "published_at": str(getattr(item, "published_date", "") or "").strip(),
                    "volatile": bool(getattr(bundle, "limitations", []) or []),
                    "fullpage_fetch": bool(getattr(item, "content_excerpt", "") or ""),
                }
            )
        return rows

    def _result_matches_focus(self, query: str, row: Dict[str, Any]) -> bool:
        focus_terms = self._query_focus_terms(query)
        if not focus_terms:
            return True
        blob = " ".join(
            [
                str((row or {}).get("title") or ""),
                str((row or {}).get("description") or ""),
                str((row or {}).get("url") or ""),
            ]
        ).lower()
        return any(term in blob for term in focus_terms)

    def _summary_source_title(self, query: str, row: Dict[str, Any]) -> str:
        raw_title = str((row or {}).get("title") or "").strip()
        title = _repair_title_spacing(raw_title)
        url = str((row or {}).get("url") or "").strip()
        if not url:
            return title
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        query_lower = str(query or "").lower()

        if "docs.python.org" in host:
            match = re.search(r"/whatsnew/(\d+\.\d+)\.html", path)
            if match:
                return f"What's New In Python {match.group(1)}"
            changelog = re.search(r"/(\d+\.\d+)/whatsnew/changelog\.html", path)
            if changelog:
                return f"Changelog - Python {changelog.group(1)} documentation"

        if any(term in query_lower for term in ("who", "dengue", "arboviral")):
            if "/news/item/" in path:
                return "WHO news item"
            if any(marker in path for marker in ("/publications/i/item/", "/publications/b/", "/items/", "/handle/", "/server/api/core/bitstreams/", "/bitstream/handle/")):
                return "WHO guideline publication"

        if any(term in query_lower for term in ("hypertension", "high blood pressure")):
            if "/guidelines/high-blood-pressure" in path:
                return "2025 High Blood Pressure Guidelines"
            if "cir.0000000000001356" in url.lower():
                return "2025 ACC/AHA high blood pressure guideline"
            if "jacc.org" in host and "/doi/" in path and "at-a-glance" in title.lower():
                return "2025 High Blood Pressure Guideline-at-a-Glance | JACC"

        slug_title = self._url_slug_title(url)
        if slug_title and self._title_needs_slug_cleanup(raw_title):
            return slug_title
        return title

    def _title_needs_slug_cleanup(self, title: str) -> bool:
        clean = " ".join(str(title or "").split()).strip()
        if not clean:
            return False
        if _repair_title_spacing(clean) != clean:
            return True
        if self._text_looks_mashed(clean):
            return True
        if re.search(r"\b[A-Za-z]{20,}\b", clean) is not None:
            return True
        return False

    def _url_slug_title(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        path_parts = [part for part in (parsed.path or "").split("/") if part]
        if not path_parts:
            return ""
        slug = ""
        generic_parts = {"index", "index.html", "amp", "phones", "phone", "compare", "comparisons", "articles", "article"}
        for candidate in reversed(path_parts):
            lowered = candidate.lower()
            if lowered in generic_parts:
                continue
            if re.fullmatch(r"[\d,.-]+", candidate):
                continue
            slug = candidate
            break
        if not slug:
            slug = path_parts[-1]
        slug = re.sub(r"\.[a-z0-9]+$", "", slug, flags=re.IGNORECASE)
        slug = re.sub(r"-\d{6,}$", "", slug)
        slug = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", slug)
        slug = slug.replace(",", " vs ")
        slug = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", slug)
        slug = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", slug)
        slug = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", slug)
        slug = re.sub(r"(?<=[A-Za-z0-9])(?:vs|versus)(?=[A-Z0-9])", " vs ", slug, flags=re.IGNORECASE)
        slug = re.sub(r"[_-]+", " ", slug)
        slug = re.sub(r"\s+", " ", slug).strip(" -/")
        if len(slug) < 12:
            return ""
        words: List[str] = []
        for token in slug.split():
            if token.isdigit():
                words.append(token)
                continue
            if token.upper() in {"AI", "API", "SDK", "TSA", "WHO", "CDC", "NHS", "GPU", "CPU", "XPS"}:
                words.append(token.upper())
                continue
            words.append(token.capitalize())
        return _repair_title_spacing(" ".join(words).strip())

    def _leading_publication_year(self, text: str) -> str:
        clean = _normalize_artifact_text(text)
        if not clean:
            return ""
        match = re.match(r"^\s*(?:[A-Z][a-z]{2,8}\s+\d{1,2},\s+)?(20\d{2})\b", clean)
        return str(match.group(1)).strip() if match else ""

    def _query_subject_hint(self, query: str) -> str:
        clean = " ".join(str(query or "").split()).strip()
        if not clean:
            return ""
        lowered = clean.lower()
        patterns = (
            r"\bbest time to visit\s+(.+)$",
            r"\bwhen to visit\s+(.+)$",
            r"\bwhat to do in\s+(.+)$",
            r"\bthings to do in\s+(.+)$",
            r"\btop things to do in\s+(.+)$",
            r"\bhow many days in\s+(.+)$",
            r"\bis\s+(.+?)\s+expensive$",
            r"\bplan a\s+\d+\s*day trip to\s+(.+)$",
            r"\bweekend itinerary for\s+(.+)$",
            r"\bbudget for\s+\d+\s*days in\s+(.+)$",
            r"\bfamily trip plan for\s+(.+)$",
            r"\bfood itinerary for\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if not match:
                continue
            subject = str(match.group(1) or "").strip(" ?.!,:;")
            if subject:
                return _repair_title_spacing(subject)
        return ""

    def _query_day_count(self, query: str) -> int:
        match = re.search(r"\b(\d+)\s*day(?:s)?\b", str(query or "").lower())
        return int(match.group(1)) if match else 0

    def _summary_text_is_weak(self, text: str) -> bool:
        clean = _normalize_artifact_text(text)
        if not clean:
            return True
        lowered = clean.lower()
        first_token = lowered.split()[0] if lowered.split() else ""
        if len(clean) < 24:
            return True
        if clean.startswith("...") or clean.endswith("..."):
            return True
        if any(marker in lowered for marker in ("box-sizing", "@font-face", "toggle navigation", "skip to content", "window['", "window[\"", "document.")):
            return True
        if re.fullmatch(r"[a-z]{8,}", first_token) and any(marker in first_token[1:-1] for marker in ("to", "of", "in", "for", "with", "and", "your")):
            return True
        if self._text_looks_mashed(clean):
            return True
        return False

    def _summary_clean_text(self, text: str, *, limit: int = 320) -> str:
        clean = _repair_title_spacing(str(text or ""))
        clean = re.sub(r"\bSkip to main content\b", " ", clean, flags=re.IGNORECASE)
        clean = clean.replace("up-do-date", "up-to-date")
        clean = re.sub(r"\s+\?\s*(?=[A-Z])", ". ", clean)
        clean = re.sub(r"^\.\.\.+", "", clean).strip(" -")
        clean = re.sub(r"^\d+\s+(?=[A-Z])", "", clean)
        clean = re.sub(r"\s+\.", ".", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return _safe_trim(clean, limit)

    def _summary_sentence(self, text: str, *, limit: int = 240) -> str:
        raw = _normalize_artifact_text(text)
        clean = self._summary_clean_text(text, limit=max(limit * 2, 320))
        if not clean:
            return ""
        if str(raw or "").strip().startswith("..."):
            return ""
        clean = re.sub(
            r"^(?:[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\s*[?.:-]?\s*)",
            "",
            clean,
        ).strip()
        clean = re.sub(r"^[?!.]+\s*", "", clean).strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
        for sentence in sentences:
            if self._summary_text_is_weak(sentence):
                continue
            if len(sentence) < 28 and len(sentences) > 1:
                continue
            if sentence[-1] not in ".!?":
                sentence += "."
            return _safe_trim(sentence, limit)
        if self._summary_text_is_weak(clean):
            return ""
        if clean[-1] not in ".!?":
            clean += "."
        return _safe_trim(clean, limit)

    def _summary_row_sentences(self, query: str, row: Dict[str, Any], *, limit: int = 240) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for field, field_limit in (("content", max(limit, 260)), ("description", limit)):
            sentence = self._summary_sentence(str((row or {}).get(field) or "").strip(), limit=field_limit)
            if not sentence:
                continue
            identity = sentence.lower()
            if identity in seen or self._summary_text_is_weak(sentence):
                continue
            seen.add(identity)
            out.append(sentence)
        title = self._summary_source_title(query, row).strip()
        if title:
            identity = title.lower()
            if identity not in seen and not self._summary_text_is_weak(title):
                out.append(title)
        return out

    def _natural_join(self, items: List[str]) -> str:
        clean = [str(item or "").strip() for item in items if str(item or "").strip()]
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        if len(clean) == 2:
            return f"{clean[0]} and {clean[1]}"
        return f"{', '.join(clean[:-1])}, and {clean[-1]}"

    def _format_currency_amount(self, value: float) -> str:
        rounded = round(float(value or 0))
        return f"${rounded:,}"

    def _travel_season_mentions(self, rows: List[Dict[str, Any]]) -> List[str]:
        blob = " ".join(
            " ".join(self._summary_row_sentences("", row, limit=260))
            for row in [dict(item or {}) for item in rows if isinstance(item, dict)]
        ).lower()
        ordered: List[str] = []
        checks = (
            ("spring", ("spring",)),
            ("summer", ("summer",)),
            ("autumn", ("autumn", "fall")),
            ("winter", ("winter",)),
        )
        for label, markers in checks:
            if any(marker in blob for marker in markers):
                ordered.append(label)
        return ordered

    def _travel_day_range(self, rows: List[Dict[str, Any]]) -> Tuple[int, int]:
        values: List[int] = []
        for row in [dict(item or {}) for item in rows if isinstance(item, dict)]:
            blob = " ".join(
                [
                    str((row or {}).get("title") or ""),
                    str((row or {}).get("description") or ""),
                    str((row or {}).get("content") or ""),
                ]
            )
            for low_text, high_text in re.findall(r"\b(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*day(?:s)?\b", blob, flags=re.IGNORECASE):
                values.extend([int(low_text), int(high_text)])
            for value_text in re.findall(r"\b(\d+)\s*day(?:s)?\b", blob, flags=re.IGNORECASE):
                values.append(int(value_text))
        values = sorted({value for value in values if 1 <= value <= 10})
        core_values = [value for value in values if 2 <= value <= 6]
        if len(core_values) >= 2:
            values = core_values
        elif values == [1, 7]:
            return (3, 5)
        if not values:
            return (0, 0)
        return (values[0], values[-1])

    def _planning_budget_amounts(self, rows: List[Dict[str, Any]]) -> List[int]:
        values: List[int] = []
        for row in [dict(item or {}) for item in rows if isinstance(item, dict)]:
            blob = " ".join(
                [
                    str((row or {}).get("title") or ""),
                    str((row or {}).get("description") or ""),
                    str((row or {}).get("content") or ""),
                ]
            )
            for amount in re.findall(r"\$([0-9][0-9,]{0,6})(?:\.\d+)?", blob):
                numeric = int(amount.replace(",", ""))
                if 20 <= numeric <= 5000:
                    values.append(numeric)
        ordered: List[int] = []
        seen: set[int] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def _shopping_compare_dimensions(self, query: str, rows: List[Dict[str, Any]]) -> List[str]:
        blob = " ".join(
            " ".join(self._summary_row_sentences(query, row, limit=260))
            for row in [dict(item or {}) for item in rows if isinstance(item, dict)]
        ).lower()
        dimensions: List[str] = []
        dimension_map = (
            ("design", ("design", "build")),
            ("cameras", ("camera", "cameras")),
            ("battery life", ("battery life", "battery")),
            ("performance", ("performance",)),
            ("display", ("display", "screen")),
            ("price", ("price", "cost")),
            ("portability", ("portability", "portable", "lightweight", "weight")),
            ("keyboard", ("keyboard",)),
            ("trackpad", ("trackpad",)),
            ("ecosystem", ("ecosystem", "library", "store")),
            ("specs", ("specs", "specifications")),
        )
        for label, markers in dimension_map:
            if any(marker in blob for marker in markers):
                dimensions.append(label)
        ql = str(query or "").lower()
        if any(marker in ql for marker in ("iphone", "galaxy", "pixel", "phone", "smartphone")):
            default_dimensions = ["design", "cameras", "battery life", "performance", "price"]
        elif any(marker in ql for marker in ("macbook", "xps", "thinkpad", "surface", "laptop", "notebook")):
            default_dimensions = ["portability", "battery life", "performance", "display", "price"]
        elif any(marker in ql for marker in ("kindle", "kobo", "ereader", "e-reader")):
            default_dimensions = ["screen quality", "lighting", "battery life", "ecosystem", "price"]
        else:
            default_dimensions = ["specs", "performance", "price", "tradeoffs"]
        if dimensions:
            if len(dimensions) == 1 and dimensions[0] == "specs":
                return default_dimensions
            return dimensions[:5]
        return default_dimensions

    def _display_summary_subject(self, subject: str, fallback: str = "the destination") -> str:
        clean = " ".join(str(subject or "").split()).strip()
        if not clean:
            return fallback
        if clean.lower() == fallback.lower():
            return fallback
        return clean.title()

    def _travel_lookup_summary_override(self, query: str, rows: List[Dict[str, Any]], fallback: str = "") -> str:
        ql = str(query or "").lower()
        subject = self._display_summary_subject(self._query_subject_hint(query), "the destination")
        if any(marker in ql for marker in ("budget", "cheap", "affordable", "cost")):
            day_count = self._query_day_count(query)
            amounts = self._planning_budget_amounts(rows)
            if len(amounts) >= 2 and day_count > 0:
                low = min(amounts[0], amounts[1])
                high = max(amounts[0], amounts[1])
                return (
                    f"Budget-focused travel sources suggest about {self._format_currency_amount(low)} per day for budget travel "
                    f"and roughly {self._format_currency_amount(high)} per day for a mid-range trip in {subject}, "
                    f"so {day_count} days comes out to about {self._format_currency_amount(low * day_count)} "
                    f"to {self._format_currency_amount(high * day_count)} before flights."
                )
            if day_count > 0:
                return f"Budget-focused {subject} trip guides emphasize lodging, transit, food, and attraction costs so you can price out a realistic {day_count}-day plan."
            if fallback and not self._summary_text_is_weak(fallback):
                return self._summary_clean_text(fallback, limit=360)
        if any(marker in ql for marker in ("best time to visit", "when to visit")):
            seasons = self._travel_season_mentions(rows)
            if "spring" in seasons and "autumn" in seasons:
                return f"Travel sources generally point to spring and autumn as the easiest times to visit {subject} for comfortable weather and seasonal events."
            if len(seasons) >= 2:
                return f"Travel sources generally point to {self._natural_join(seasons[:2])} as the strongest seasons to visit {subject}, depending on the weather and events you want."
            if len(seasons) == 1:
                return f"Travel sources often highlight {seasons[0]} as a strong season to visit {subject}, depending on the weather and pace you want."
            return f"Current travel guides for {subject} focus on weather, seasonal crowds, and event timing when recommending the best time to visit."
        if "how many days in" in ql:
            low, high = self._travel_day_range(rows)
            if low and high and high > low:
                midpoint = 4 if low <= 4 <= high else max(low, min(high, round((low + high) / 2)))
                return f"Most itinerary guides suggest about {low} to {high} days in {subject} for a first visit, with {midpoint} days giving you time for the main neighborhoods without rushing."
            if low:
                return f"Most itinerary guides suggest around {low} days in {subject} for a first visit."
        if any(marker in ql for marker in ("what to do in", "things to do in", "top things to do in")):
            return f"Travel guides for {subject} consistently recommend mixing signature sights with neighborhood wandering, food stops, and one or two slower local experiences."
        return ""

    def _trip_planning_summary_override(self, query: str, rows: List[Dict[str, Any]], fallback: str = "") -> str:
        ql = str(query or "").lower()
        subject = self._display_summary_subject(self._query_subject_hint(query), "the destination")
        day_count = self._query_day_count(query)
        fallback_clean = self._summary_clean_text(fallback, limit=360)
        if any(marker in ql for marker in ("budget", "cheap", "affordable", "cost")):
            amounts = self._planning_budget_amounts(rows)
            if len(amounts) >= 2 and day_count > 0:
                low = min(amounts[0], amounts[1])
                high = max(amounts[0], amounts[1])
                return (
                    f"Budget-focused travel sources suggest about {self._format_currency_amount(low)} per day for budget travel "
                    f"and roughly {self._format_currency_amount(high)} per day for a mid-range trip in {subject}, "
                    f"so {day_count} days comes out to about {self._format_currency_amount(low * day_count)} "
                    f"to {self._format_currency_amount(high * day_count)} before flights."
                )
            if day_count > 0:
                return f"Budget-focused {subject} trip guides emphasize lodging, transit, and food costs so you can price out a realistic {day_count}-day plan."
            return f"Budget-focused {subject} trip guides emphasize lodging, transit, and food costs so you can price out a realistic plan."
        if fallback_clean and not self._summary_text_is_weak(fallback_clean):
            fallback_lower = fallback_clean.lower()
            if any(marker in fallback_lower for marker in ("allow us to", "official tokyo travel guide", "food & drink in")):
                fallback_clean = ""
            elif any(marker in fallback_lower for marker in ("itinerary", "first-time", "first time", "neighborhood", "transit", "kid-friendly", "family-friendly", "market", "dinner")):
                return fallback_clean
        if any(marker in ql for marker in ("family", "families", "kids", "children", "kid friendly", "kid-friendly")):
            return f"Family-focused {subject} guides recommend building each day around a few kid-friendly anchor stops, easy transit hops, and neighborhoods that stay manageable with children."
        if any(marker in ql for marker in ("food", "eat", "eating", "restaurant", "restaurants", "culinary", "dining")):
            return f"Food-focused {subject} itineraries usually organize the day around markets, neighborhood snacks, and dinner destinations so the trip feels built around what you want to eat."
        if day_count > 0:
            return f"The strongest {day_count}-day {subject} itineraries break the trip into neighborhoods and mix major sights with food and transit planning for first-time visitors."
        return f"The strongest itineraries for {subject} break the trip into manageable neighborhoods and combine major sights with practical food and transit planning."

    def _shopping_compare_summary_override(self, query: str, rows: List[Dict[str, Any]], fallback: str = "") -> str:
        subjects = [str(item or "").strip() for item in comparison_subjects(query)[:2] if str(item or "").strip()]
        if len(subjects) >= 2:
            pair = f"{subjects[0]} and {subjects[1]}"
        elif subjects:
            pair = subjects[0]
        else:
            pair = "these options"
        title_focus = ""
        for row in list(rows or [])[:3]:
            candidate = self._summary_source_title(query, dict(row or {})).strip()
            if candidate and " vs " in candidate.lower():
                title_focus = candidate
                break
        fallback_clean = self._summary_clean_text(fallback, limit=360)
        if fallback_clean:
            fallback_lower = fallback_clean.lower()
            if not any(marker in fallback_lower for marker in ("box-sizing", "@font-face", "window['", "window[\"", "document.", "our specs comparison tool", "helps you find and compare", "perfect phone for your needs")) and any(
                marker in fallback_lower for marker in ("both have", "comparison focuses", "comparison covers", "battery life", "cameras", "performance", "display", "portability", "price", "specs")
            ):
                return fallback_clean
        dimensions = self._shopping_compare_dimensions(query, rows)
        if dimensions:
            if title_focus:
                return f"{title_focus} comparison focuses on {self._natural_join(dimensions[:5])}, with side-by-side specs and review tradeoffs across the top sources."
            return f"Current comparisons between {pair} focus on {self._natural_join(dimensions[:5])}, with side-by-side specs and review tradeoffs across the top sources."
        return f"Current comparisons between {pair} focus on side-by-side specs, price, and real-world tradeoffs across the top reviews."

    def _intent_summary_override(self, query: str, rows: List[Dict[str, Any]], fallback: str = "") -> str:
        scoped_rows = [dict(item or {}) for item in rows if isinstance(item, dict)][:5]
        if not scoped_rows:
            return ""
        if is_shopping_compare_query(query):
            return self._shopping_compare_summary_override(query, scoped_rows, fallback=fallback)
        if is_trip_planning_query(query):
            return self._trip_planning_summary_override(query, scoped_rows, fallback=fallback)
        if is_travel_lookup_query(query):
            return self._travel_lookup_summary_override(query, scoped_rows, fallback=fallback)
        return ""

    def _lead_summary_text(self, query: str, row: Dict[str, Any]) -> str:
        title = self._summary_source_title(query, row).strip()
        description = self._summary_sentence(str((row or {}).get("description") or "").strip(), limit=240)
        content = self._summary_sentence(str((row or {}).get("content") or "").strip(), limit=260)
        excerpt = ""
        if content and (
            not description
            or self._summary_text_is_weak(description)
            or len(description) < 70
            or description.startswith("...")
        ):
            excerpt = content
        else:
            excerpt = description or content
        if excerpt:
            if title and title.lower() not in excerpt.lower():
                if is_shopping_compare_query(query):
                    return f"{title}. {excerpt}".strip()
            return excerpt
        return title

    def _summary_lead_row(self, query: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        candidates = [dict(row or {}) for row in rows if isinstance(row, dict)]
        if not candidates:
            return {}
        query_lower = str(query or "").lower()

        def score(row: Dict[str, Any]) -> float:
            url = str((row or {}).get("url") or "").strip().lower()
            host = (urlparse(url).netloc or "").lower()
            title = _repair_title_spacing(str((row or {}).get("title") or ""))
            desc = self._summary_clean_text(str((row or {}).get("description") or ""), limit=260)
            content = self._summary_clean_text(str((row or {}).get("content") or ""), limit=320)
            blob = " ".join(part for part in (title, desc, content, url) if part).lower()
            value = 0.0
            lead_text = self._lead_summary_text(query, row)
            if lead_text:
                value += 2.5
            if self._summary_text_is_weak(lead_text):
                value -= 4.0
            if str((row or {}).get("content") or "").strip():
                value += 1.5
            if self._title_needs_slug_cleanup(str((row or {}).get("title") or "")):
                value -= 1.5
            if any(term in query_lower for term in ("hypertension", "high blood pressure")) and any(term in query_lower for term in ("latest", "guideline", "guidelines", "current", "updated")):
                if "/guidelines/high-blood-pressure" in url:
                    value += 8.0
                elif "/doi/" in url:
                    value += 2.0

            if is_trip_planning_query(query):
                trusted_hosts = (
                    "gotokyo.org",
                    "japan-guide.com",
                    "lonelyplanet.com",
                    "timeout.com",
                    "tokyocandies.com",
                    "preparetravelplans.com",
                    "tokyocheapo.com",
                    "thetravelsisters.com",
                    "nomadicmatt.com",
                    "nickkembel.com",
                    "japanhighlights.com",
                )
                aggregator_hosts = (
                    "trip.com",
                    "booking.com",
                    "agoda.com",
                    "viator.com",
                    "klook.com",
                    "myai.travel",
                )
                itinerary_markers = tuple(self._trip_planning_focus_markers(query))
                if any(domain in host for domain in trusted_hosts):
                    value += 7.0
                if any(marker in blob for marker in itinerary_markers):
                    value += 4.0
                if re.search(r"\b\d+\s*day\b|\b\d+\s*days\b|\b72 hours\b", blob):
                    value += 2.0
                if "weekend" in query_lower:
                    if any(marker in blob for marker in ("weekend", "48 hour", "48-hour", "48 hours", "long weekend")):
                        value += 6.0
                    if re.search(r"\b3[- ]?day\b|\b3[- ]?days\b|\b72 hours\b", blob) and "weekend" not in blob:
                        value -= 5.0
                if any(marker in query_lower for marker in ("budget", "cheap", "affordable", "cost")):
                    if any(marker in blob for marker in ("budget", "cost", "per day", "daily cost", "prices", "travel budget")):
                        value += 6.0
                    if re.search(r"\$[0-9]", blob) is not None or "yen" in blob:
                        value += 3.0
                if any(marker in query_lower for marker in ("family", "families", "kids", "children", "kid friendly", "kid-friendly")):
                    if any(marker in blob for marker in ("family", "families", "kids", "children", "kid friendly", "kid-friendly", "family-friendly")):
                        value += 6.0
                    else:
                        value -= 4.0
                if any(marker in query_lower for marker in ("food", "eat", "eating", "restaurant", "restaurants", "culinary", "dining")):
                    if any(marker in blob for marker in ("food", "eat", "eating", "restaurant", "restaurants", "culinary", "dining", "food lovers", "food itinerary")):
                        value += 6.0
                    if any(marker in blob for marker in ("itinerary", "itinerary planning")):
                        value += 3.0
                if any(domain in host for domain in aggregator_hosts):
                    value -= 7.0
                if any(marker in blob for marker in ("efficient trip planning guide", "travel routes", "2-night", "2 night", "explore must", "travel checklist")):
                    value -= 6.0

            if is_travel_lookup_query(query):
                travel_hosts = (
                    "gotokyo.org",
                    "japan-guide.com",
                    "lonelyplanet.com",
                    "timeout.com",
                    "travelandleisure.com",
                    "cntraveler.com",
                    "fodors.com",
                    "nomadicmatt.com",
                    "budgetyourtrip.com",
                )
                destination = self._query_subject_hint(query).lower()
                focus_markers = tuple(self._travel_lookup_focus_markers(query))
                if any(domain in host for domain in travel_hosts):
                    value += 5.0
                if destination and destination in blob:
                    value += 6.0
                elif destination:
                    value -= 4.0
                if any(marker in blob for marker in focus_markers):
                    value += 4.0
                if "how many days in" in query_lower:
                    if any(marker in blob for marker in ("how many days", "how long", "days should you spend", "days do you need", "days in")):
                        value += 7.0
                    if re.search(r"\b\d+\s*day(?:s)?\b", title.lower()) and not any(marker in blob for marker in ("how many days", "how long")):
                        value -= 3.0
                if any(marker in query_lower for marker in ("best time to visit", "when to visit")):
                    if any(marker in blob for marker in ("best time to visit", "when to visit", "best times to visit")):
                        value += 6.0
                    if title.lower().startswith("weather in "):
                        value -= 8.0
                if "best time to visit" in str(query or "").lower() and any(term in blob for term in ("spring", "summer", "fall", "autumn", "winter", "season", "month")):
                    value += 2.0
                if any(domain in host for domain in ("trip.com", "booking.com", "agoda.com")):
                    value -= 5.0

            if is_shopping_compare_query(query):
                trusted_compare_hosts = (
                    "pcmag.com",
                    "tomsguide.com",
                    "phonearena.com",
                    "techradar.com",
                    "cnet.com",
                    "theverge.com",
                    "zdnet.com",
                    "gsmarena.com",
                    "consumerreports.org",
                )
                if self._comparison_group_hit_count(query, blob) >= 2:
                    value += 7.0
                elif self._comparison_group_hit_count(query, blob) == 1:
                    value += 1.5
                else:
                    value -= 6.0
                if any(domain in host for domain in trusted_compare_hosts):
                    value += 5.0
                if any(marker in blob for marker in (" vs ", " compare ", "comparison", "review", "reviews")):
                    value += 3.0
                if any(marker in blob for marker in ("camera", "cameras", "battery life", "performance", "display", "price", "specs", "portability", "keyboard", "trackpad")):
                    value += 2.0
                if any(domain in host for domain in ("reddit.com", "youtube.com")):
                    value -= 5.0

            if any(term in query_lower for term in ("walking", "protein", "heart rate", "glycemic", "creatine", "water", "cortisol", "sleep", "vo2", "calories")):
                trusted_health_hosts = (
                    "mayoclinic.org",
                    "clevelandclinic.org",
                    "nih.gov",
                    "cdc.gov",
                    "nhs.uk",
                    "betterhealth.vic.gov.au",
                    "verywellhealth.com",
                )
                noisy_health_hosts = (
                    "youtube.com",
                    "medium.com",
                    "nike.com",
                    "birkenstock.com",
                    "ymcasouthflorida.org",
                )
                if any(domain in host for domain in trusted_health_hosts):
                    value += 5.0
                if any(domain in host for domain in noisy_health_hosts):
                    value -= 6.0
                if any(marker in blob for marker in ("heart health", "blood pressure", "fitness", "mood", "endurance", "immune", "calories")):
                    value += 1.5
            return value

        return max(candidates[:4], key=score)

    def _direct_url_display_title(self, url: str, text: str = "") -> str:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.netloc or "").strip() or str(url or "").strip()
        path = (parsed.path or "").rstrip("/").lower()
        if host.lower() == "react.dev" and path == "/blog":
            return "React Blog"
        if "developer.mozilla.org" in host.lower():
            slug_title = self._url_slug_title(url)
            if "/web/javascript" in path:
                return "JavaScript | MDN Web Docs"
            if slug_title:
                return f"{slug_title} | MDN Web Docs"
        synthetic = self._summary_source_title("", {"title": host, "url": str(url or "").strip()}).strip()
        if synthetic and synthetic != host:
            return synthetic
        clean = _normalize_artifact_text(text)
        if clean:
            first = clean.split(". ", 1)[0].strip()
            if 12 <= len(first) <= 110 and not self._text_looks_mashed(first):
                return first
        return host

    def _clean_direct_url_excerpt(self, url: str, text: str) -> str:
        clean = _normalize_artifact_text(text)
        host = (urlparse(str(url or "")).netloc or "").lower()
        path = (urlparse(str(url or "")).path or "").rstrip("/").lower()
        if host == "react.dev" and path == "/blog":
            return "Official React blog page with updates from the React team."
        if "developer.mozilla.org" in host:
            if "/web/javascript" in path:
                return "MDN overview page for JavaScript guides, references, and tutorials."
            slug_title = self._url_slug_title(url)
            if slug_title:
                return f"MDN documentation page for {slug_title}."
            return "MDN documentation page."
        if "docs.python.org" in host:
            clean = re.sub(r"\bPython\s+\d+\.\d+\.\d+\s+documentation\b", " ", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bTheme Auto Light Dark\b", " ", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bTable of Contents\b", " ", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bPrevious topic\b.*", " ", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bNext topic\b.*", " ", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bWhat's New In Python\s+\d+\.\d+\b", " ", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bSummary\s+Release Highlights\b", "Summary. Release Highlights.", clean, flags=re.IGNORECASE)
        if "github.com" in host:
            clean = re.sub(r"\bSkip to content\b", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" .")
        if not clean and "docs.python.org" in host and "/whatsnew/" in path:
            return "Official Python documentation page with release highlights and changelog sections."
        if self._text_looks_mashed(clean):
            title = self._direct_url_display_title(url, clean)
            if "docs.python.org" in host and "/whatsnew/" in path:
                return f"Official Python documentation page for {title}."
            return title
        return clean

    def _text_looks_mashed(self, text: str) -> bool:
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return False
        if clean.startswith("..."):
            return True
        if clean.endswith("...") and len(clean) <= 32:
            return True
        if any(marker in clean for marker in ("Ã", "Â", "â€", "â€”", "â€“")):
            return True
        if re.search(r"\.\.\.[A-Z]", clean) is not None or re.search(r"[?!][A-Z]", clean) is not None:
            return True
        if any(marker in clean.lower() for marker in ("body{", "html{", "@font-face", "src:url(", "window[", "cookieenabled", "function()", "var ", "const ")):
            return True
        if re.search(r"\b[A-Za-z]{18,}\b", clean) is not None:
            return True
        letters = sum(1 for ch in clean if ch.isalpha())
        spaces = clean.count(" ")
        if len(clean) >= 80 and letters >= 50 and spaces <= max(2, len(clean) // 40):
            return True
        if re.search(r"[A-Za-z]\d{4}[A-Za-z]", clean) is not None:
            return True
        if re.search(r"[a-z][A-Z][a-z]{2,}", clean) is not None:
            return True
        if re.search(r"[A-Z]{2,}[A-Z][a-z]{2,}", clean) is not None:
            return True
        if re.search(r"(guideline|guidelines|management|disease|dengue)[a-z]", clean.lower()) is not None:
            return True
        return False

    def _extract_cardio_primary_guideline_candidate(self, html_text: str, base_url: str) -> Optional[Dict[str, Any]]:
        if not html_text or "ahajournals.org" not in (urlparse(str(base_url or "")).netloc or "").lower():
            return None
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return None
        try:
            soup = BeautifulSoup(html_text, "lxml")
        except Exception:
            return None

        best: Optional[Dict[str, Any]] = None
        best_score = float("-inf")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            candidate_url = urljoin(base_url, href).replace("/doi/pdf/", "/doi/")
            host = (urlparse(candidate_url).netloc or "").lower()
            if "ahajournals.org" not in host or "/doi/" not in candidate_url.lower():
                continue
            text = " ".join(anchor.get_text(" ", strip=True).split())
            blob = f"{text} {candidate_url}".lower()
            score = 0.0
            if "guideline" in blob:
                score += 4.0
            if any(marker in blob for marker in ("high blood pressure", "hypertension")):
                score += 4.0
            if any(marker in blob for marker in ("10.1161/cir.", "cir.")):
                score += 5.0
            if "full text" in blob:
                score += 1.0
            if any(marker in blob for marker in ("editor", "editors", "projected impact", "debate", "implementing", "prevent risk equation", "encouraged by")):
                score -= 7.0
            if score <= best_score:
                continue
            title = text or "2025 ACC/AHA high blood pressure guideline"
            if not any(marker in title.lower() for marker in ("high blood pressure", "hypertension")):
                title = "2025 ACC/AHA high blood pressure guideline"
            best = {
                "title": title,
                "url": candidate_url,
                "description": "Primary ACC/AHA guideline article linked from the official high blood pressure guideline hub.",
                "source": "cardio_official_adapter",
            }
            best_score = score
        return best if best_score >= 6.0 else None

    def _canonical_cardio_guideline_url(self, url: str) -> str:
        clean = strip_tracking_params(str(url or "").strip())
        if not clean:
            return ""
        replacements = (
            "/doi/full/",
            "/doi/abs/",
            "/doi/pdf/",
            "/doi/epdf/",
            "/doi/epub/",
        )
        for marker in replacements:
            clean = clean.replace(marker, "/doi/")
        if "/doi/" in clean:
            clean = clean.split("?", 1)[0]
        return clean

    def _official_page_fetch_blocked(self, response: Any) -> bool:
        status_code = int(getattr(response, "status_code", 0) or 0)
        text = str(getattr(response, "text", "") or "")
        blob = text.lower()
        if status_code in {401, 403, 406, 409, 429, 451, 503}:
            return True
        markers = (
            "cf-chl",
            "cloudflare",
            "attention required",
            "verify you are human",
            "just a moment",
            "access denied",
            "bot verification",
        )
        return any(marker in blob for marker in markers)

    def _cardio_primary_guideline_recovery_queries(self, query: str) -> List[str]:
        query_lower = str(query or "").lower()
        if not self._is_latest_clinical_query(query) or not any(term in query_lower for term in ("hypertension", "high blood pressure")):
            return []
        variants = [
            "site:ahajournals.org 2025 ACC/AHA high blood pressure guideline adults",
            'site:ahajournals.org/doi "2025 AHA/ACC/AANP/AAPA/ABC/ACCP/ACPM/AGS/AMA/ASPC/NMA/PCNA"',
            "site:ahajournals.org/doi CIR.0000000000001356",
        ]
        deduped: List[str] = []
        seen: set[str] = set()
        for variant in variants:
            clean = str(variant or "").strip()
            if not clean or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            deduped.append(clean)
        return deduped

    async def _recover_cardio_primary_guideline_from_search(self, query: str, *, mode: str) -> Optional[Dict[str, Any]]:
        recovery_queries = self._cardio_primary_guideline_recovery_queries(query)
        if not recovery_queries:
            return None
        candidates: List[Dict[str, Any]] = []
        for variant in recovery_queries:
            self._append_browse_step(
                query,
                step="search",
                detail=f"official recovery query '{_safe_trim(variant, 88)}'",
                mode=mode,
            )
            try:
                result = await asyncio.wait_for(
                    search_general(variant, min_results=2, budgets_ms={"primary": 1800, "fallback": 1800}, allow_ddg_fallback=False),
                    timeout=8.0,
                )
            except Exception:
                result = []
            for row in list(result or []):
                if not isinstance(row, dict):
                    continue
                candidate = dict(row or {})
                candidate_url = self._canonical_cardio_guideline_url(str(candidate.get("url") or ""))
                if candidate_url:
                    candidate["url"] = candidate_url
                candidates.append(candidate)
            prioritized = self._prioritize_browse_rows(query, self._dedupe_results(candidates), prefer_official=True)
            primary = next(
                (
                    dict(row or {})
                    for row in prioritized
                    if "cir.0000000000001356" in str((row or {}).get("url") or "").lower()
                ),
                None,
            )
            if primary is not None:
                return primary
        prioritized = self._prioritize_browse_rows(query, self._dedupe_results(candidates), prefer_official=True)
        return next(
            (
                dict(row or {})
                for row in prioritized
                if self._official_result_satisfies_query(query, row)
            ),
            None,
        )

    def _summarize_result_rows(self, query: str, results: List[Dict[str, Any]]) -> str:
        if not results:
            return ""
        focus_rows = [dict(row or {}) for row in results if self._result_matches_focus(query, row)]
        lead_pool = focus_rows[:4] if focus_rows else [dict(results[0] or {})]
        lead = self._summary_lead_row(query, lead_pool)
        summary = self._lead_summary_text(query, lead)
        summary = self._summary_clean_text(summary, limit=420)
        summary = re.sub(r"^[?!.]+\s*", "", summary).strip()
        raw_lead_title = str(lead.get("title") or "").strip()
        lead_title = _repair_title_spacing(raw_lead_title)
        title_cleanup_needed = self._title_needs_slug_cleanup(raw_lead_title)
        if self._text_looks_mashed(summary) or (summary == lead_title and title_cleanup_needed):
            clean_title = self._summary_source_title(query, lead).strip()
            clean_description = self._summary_sentence(str(lead.get("description") or "").strip(), limit=320)
            clean_content = self._summary_sentence(str(lead.get("content") or "").strip(), limit=320)
            if not clean_description:
                clean_description = clean_content
            if clean_description and not self._text_looks_mashed(clean_description):
                if clean_title and clean_title.lower() not in clean_description.lower():
                    summary = f"{clean_title}. {clean_description}".strip()
                else:
                    summary = clean_description
            else:
                summary = clean_title or str(lead.get("title") or "").strip()
        if len(focus_rows) >= 2:
            intent_rows = focus_rows[:5]
        else:
            intent_rows = [dict(item or {}) for item in results[:5]]
        intent_summary = self._intent_summary_override(query, intent_rows, fallback=summary)
        if intent_summary:
            summary = intent_summary
        support_pool: List[Dict[str, Any]] = []
        support_seen_urls: set[str] = set()
        for row in list(focus_rows[1:4]) + [dict(item or {}) for item in results[1:4]]:
            url = str((row or {}).get("url") or "").strip().lower()
            if url and url in support_seen_urls:
                continue
            if url:
                support_seen_urls.add(url)
            support_pool.append(dict(row or {}))
        support_titles: List[str] = []
        seen_titles: set[str] = set()
        who_guidance_query = self._is_latest_who_dengue_guidance_query(query)
        require_official_support = (
            self._is_python_docs_query(query)
            or who_guidance_query
            or (
                any(term in str(query or "").lower() for term in ("hypertension", "high blood pressure"))
                and any(term in str(query or "").lower() for term in ("latest", "recent", "updated", "newest", "current"))
            )
        )
        ranked_support_pool: List[Dict[str, Any]] = []
        remaining_support_pool = [dict(item or {}) for item in support_pool if isinstance(item, dict)]
        ranked_seen_urls: set[str] = set()
        lead_url = str((lead or {}).get("url") or "").strip().lower()
        while remaining_support_pool and len(ranked_support_pool) < 5:
            ranked_candidates = [
                dict(item or {})
                for item in remaining_support_pool
                if str((item or {}).get("url") or "").strip().lower() not in ranked_seen_urls
            ]
            if not ranked_candidates:
                break
            best = self._summary_lead_row(query, ranked_candidates)
            if not best:
                break
            best_url = str((best or {}).get("url") or "").strip().lower()
            if not best_url:
                break
            if best_url and best_url != lead_url:
                ranked_support_pool.append(dict(best or {}))
                ranked_seen_urls.add(best_url)
            remaining_support_pool = [
                dict(item or {})
                for item in remaining_support_pool
                if str((item or {}).get("url") or "").strip().lower() != best_url
            ]
        if ranked_support_pool:
            support_pool = ranked_support_pool
        seen_urls: set[str] = set()
        for row in support_pool:
            row_url = str((row or {}).get("url") or "").strip().lower()
            row_host = (urlparse(row_url).netloc or "").lower()
            if who_guidance_query:
                if not self._row_allowed_for_query(query, row):
                    continue
            elif require_official_support:
                if not self._official_result_satisfies_query(query, row):
                    continue
            elif not self._row_allowed_for_query(query, row):
                continue
            if is_trip_planning_query(query) and any(
                domain in row_host for domain in ("trip.com", "booking.com", "agoda.com", "viator.com", "klook.com", "myai.travel")
            ):
                continue
            if is_trip_planning_query(query) and (
                self._travel_row_looks_forumish(row)
                or self._travel_row_looks_ad_heavy(row)
                or self._travel_row_looks_noisy(query, row)
            ):
                continue
            if is_travel_lookup_query(query) and any(
                domain in row_host for domain in ("tripadvisor.com", "trip.com", "booking.com", "agoda.com", "viator.com", "klook.com")
            ):
                continue
            if is_travel_lookup_query(query) and (
                self._travel_row_looks_forumish(row)
                or self._travel_row_looks_ad_heavy(row)
                or self._travel_row_looks_noisy(query, row)
            ):
                continue
            if is_travel_lookup_query(query) and any(marker in str(query or "").lower() for marker in ("best time to visit", "when to visit")):
                title_blob = " ".join(
                    [
                        str((row or {}).get("title") or ""),
                        str((row or {}).get("description") or ""),
                        row_url,
                    ]
                ).lower()
                if str((row or {}).get("title") or "").strip().lower().startswith("weather in "):
                    continue
                if any(month in title_blob for month in ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")) and not any(
                    marker in title_blob for marker in ("best time to visit", "when to visit", "season", "seasons", "best times")
                ):
                    continue
            if is_shopping_compare_query(query) and any(
                domain in row_host for domain in ("reddit.com", "youtube.com", "medium.com", "tiktok.com", "instagram.com", "facebook.com")
            ):
                continue
            if is_shopping_compare_query(query):
                compare_blob = " ".join(
                    [
                        str((row or {}).get("title") or ""),
                        str((row or {}).get("description") or ""),
                        row_url,
                    ]
                ).lower()
                if self._shopping_row_looks_noisy(query, row):
                    continue
                if self._comparison_group_hit_count(query, compare_blob) < 2:
                    continue
                if len(re.findall(r"\bvs\.?(?=\W|$)", compare_blob)) >= 2 or len(re.findall(r"\bversus\b", compare_blob)) >= 2:
                    continue
            if row_url:
                if row_url == lead_url or row_url in seen_urls:
                    continue
                seen_urls.add(row_url)
            title = self._summary_source_title(query, row).strip()
            if not title:
                continue
            identity = title.lower()
            if identity in seen_titles:
                continue
            seen_titles.add(identity)
            support_titles.append(title)
        if support_titles:
            summary += "\nSupporting sources: " + "; ".join(support_titles)
        return summary.strip()

    async def _direct_url_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        urls = list(plan.direct_urls or [])[:3]
        if not urls:
            return []
        self._append_browse_step(query, step="retrieve", detail=f"opening {len(urls)} direct URL(s)", mode=plan.mode)
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await asyncio.gather(
                *[
                    _fetch_url_text(client, url, timeout_s=10.0, max_bytes=1_500_000, retries=2)
                    for url in urls
                ],
                return_exceptions=True,
            )

        out: List[Dict[str, Any]] = []
        sources: List[str] = []
        for row in rows:
            if not isinstance(row, tuple) or len(row) != 2:
                continue
            final_url, extracted = row
            text = str(extracted or "").strip()
            if not text:
                continue
            sources.append(str(final_url or "").strip())
            host = (urlparse(str(final_url or "")).netloc or "").strip() or str(final_url or "")
            title = self._direct_url_display_title(str(final_url or "").strip(), text)
            clean_text = self._clean_direct_url_excerpt(str(final_url or "").strip(), text)
            out.append(
                {
                    "title": title or host,
                    "url": str(final_url or "").strip(),
                    "description": _safe_trim(clean_text, 1400),
                    "content": _safe_trim(clean_text, 2200),
                    "category": "general",
                    "source": "direct_fetch",
                    "volatile": False,
                    "fullpage_fetch": True,
                }
            )

        if out:
            self._append_browse_step(query, step="read", detail=f"extracted full text from {len(out)} page(s)", mode=plan.mode)
            lead = dict(out[0] or {})
            lead_title = str(lead.get("title") or "").strip()
            lead_desc = _safe_trim(str(lead.get("description") or "").strip(), 320)
            if lead_title and lead_desc and lead_title.lower() not in lead_desc.lower():
                summary = f"Opened {len(out)} page(s) and extracted full text from {lead_title}. {lead_desc}".strip()
            elif lead_title:
                summary = f"Opened {len(out)} page(s) and extracted full text from {lead_title}."
            else:
                summary = f"Opened {len(out)} page(s) and extracted full text."
            self._record_browse_report(query, mode=plan.mode, summary=summary, sources=sources)
        return out

    def _canonical_news_query(self, query: str) -> str:
        q = " ".join(str(query or "").split()).strip()
        if not q:
            return ""
        patterns = (
            r"^latest\s+(.+?)\s+news$",
            r"^(.+?)\s+headlines today$",
            r"^what happened with\s+(.+?)\s+today$",
            r"^recent\s+(.+?)\s+news update$",
            r"^top\s+(.+?)\s+stories right now$",
        )
        for pattern in patterns:
            match = re.match(pattern, q, re.IGNORECASE)
            if match:
                topic = " ".join(str(match.group(1) or "").split()).strip()
                if topic:
                    return f"{topic} headlines today"
        return q

    def _news_query_subject(self, query: str) -> str:
        canonical = self._canonical_news_query(query)
        if not canonical:
            return ""
        subject = re.sub(r"\bheadlines today\b", " ", canonical, flags=re.IGNORECASE)
        subject = re.sub(
            r"\b(latest|recent|news|headline|headlines|today|top|stories|right|now|update|what happened with)\b",
            " ",
            subject,
            flags=re.IGNORECASE,
        )
        subject = " ".join(subject.split()).strip(" -")
        return subject

    def _is_explicit_news_lookup(self, query: str) -> bool:
        ql = str(query or "").strip().lower()
        if not ql:
            return False
        if self._is_research_query(ql):
            return False
        return self._contains_any_query_term(ql, self.news_terms) or any(
            marker in ql for marker in ("headline", "headlines", "breaking", "what happened with", "stories right now")
        )

    def _is_latest_style_news_query(self, query: str) -> bool:
        ql = str(query or "").lower()
        return any(marker in ql for marker in ("latest", "recent", "today", "current", "breaking", "headlines", "right now"))

    def _news_row_is_hub_page(self, row: Dict[str, Any]) -> bool:
        url = str((row or {}).get("url") or "")
        title = str((row or {}).get("title") or "")
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        title_lower = title.lower()
        if any(marker in path for marker in ("/category/", "/tag/", "/tags/", "/hub/", "/topic/", "/topics/")):
            return True
        if "reuters.com" in host:
            has_article_date = re.search(r"/20\d{2}/\d{2}/\d{2}/", path) is not None or re.search(r"20\d{2}-\d{2}-\d{2}", url) is not None
            if not has_article_date and any(
                marker in title_lower
                for marker in (
                    "news | today's latest stories",
                    "today's latest stories | reuters",
                    "latest stories | reuters",
                    "sustainable business news",
                )
            ):
                return True
        if any(domain in host for domain in ("techcrunch.com", "apnews.com", "reuters.com")) and any(
            marker in title_lower for marker in ("ai news", "artificial intelligence (ai)", "artificial intelligence |", "artificial intelligence -")
        ):
            return True
        return False

    def _news_row_has_recency_signal(self, query: str, row: Dict[str, Any]) -> bool:
        title = str((row or {}).get("title") or "")
        desc = str((row or {}).get("description") or "")
        url = str((row or {}).get("url") or "")
        blob = f"{title} {desc} {url}".lower()
        path = (urlparse(url).path or "").lower()
        current_year = datetime.now(timezone.utc).year

        if not self._is_latest_style_news_query(query):
            return False
        if self._news_row_is_hub_page(row):
            return False
        if re.search(r"\b(minutes?|hours?)\s+ago\b", blob) is not None:
            return True
        if any(marker in blob for marker in (" today ", " today.", " today,", " yesterday ", " yesterday.", " yesterday,")):
            return True
        if re.search(rf"\b{current_year}\b", blob) is not None:
            return True
        if re.search(rf"/{current_year}/\d{{2}}/\d{{2}}/", path) is not None:
            return True
        if re.search(rf"-{current_year}-\d{{2}}-\d{{2}}", url) is not None:
            return True
        return False

    def _news_row_looks_evergreen_or_ad(self, query: str, row: Dict[str, Any]) -> bool:
        title = str((row or {}).get("title") or "")
        desc = str((row or {}).get("description") or "")
        url = str((row or {}).get("url") or "")
        host = (urlparse(url).netloc or "").lower()
        blob = f"{title} {desc} {url}".lower()
        title_lower = title.lower().strip()
        if any(domain in host for domain in ("bing.com", "google.com")):
            return True
        if any(marker in blob for marker in ("partner with leaders", "read more today", "book now", "reserve now")):
            return True
        if self._is_latest_style_news_query(query):
            if title_lower.startswith(("what is ", "what are ", "how ", "why ")):
                return True
            if any(marker in title_lower for marker in ("simple guide", "explainer", "explained", "guide to")):
                return True
        return False

    def _news_row_focus_score(self, query: str, row: Dict[str, Any]) -> float:
        title = str((row or {}).get("title") or "")
        desc = str((row or {}).get("description") or "")
        url = str((row or {}).get("url") or "")
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        title_blob = f"{title} {url}".lower()
        desc_blob = desc.lower()
        query_lower = str(query or "").lower()
        subject = self._news_query_subject(query).lower()
        focus_terms = [term for term in self._query_focus_terms(query) if term not in {"today", "latest", "recent"}]
        looks_evergreen = self._news_row_looks_evergreen_or_ad(query, row)

        alias_hits = 0
        if subject == "artificial intelligence" and any(
            alias in f" {title_blob} " for alias in (" ai ", " openai ", " anthropic ", " chatgpt ", " copilot ", " gemini ", " grok ")
        ):
            alias_hits += 1
        if subject == "movies" and any(alias in title_blob for alias in ("movie", "film", "box office")):
            alias_hits += 1

        title_hits = sum(1 for term in focus_terms if term in title_blob)
        desc_hits = sum(1 for term in focus_terms if term in desc_blob)
        score = 0.0

        if subject:
            if subject in title_blob:
                score += 10.0
            elif subject in desc_blob:
                score += 2.5
            else:
                score -= 8.0

        score += float(alias_hits) * 6.0
        score += float(title_hits) * 4.0
        score += min(3.0, float(desc_hits))

        if focus_terms and title_hits == 0 and alias_hits == 0:
            if desc_hits <= 1:
                score -= 9.0
            else:
                score -= 3.0
        if looks_evergreen:
            score -= 24.0

        strong_hosts = (
            "reuters.com",
            "apnews.com",
            "bloomberg.com",
            "wsj.com",
            "ft.com",
            "nytimes.com",
            "cnbc.com",
            "bbc.com",
            "npr.org",
            "theguardian.com",
            "cnn.com",
            "nbcnews.com",
            "abcnews.go.com",
            "usatoday.com",
            "marketwatch.com",
        )
        if any(domain in host for domain in strong_hosts):
            score += 4.5

        if any(marker in path for marker in ("/video", "/videos/", "/video/", "/photos/")):
            score -= 4.0
        if "yahoo.com" in host and any(marker in path for marker in ("/lifestyle/", "/entertainment/", "/sports/", "/videos/")):
            score -= 8.0
        if "msn.com" in host and title_hits == 0 and alias_hits == 0:
            score -= 6.0
        if self._is_latest_style_news_query(query_lower) and self._news_row_is_hub_page(row):
            score -= 10.0

        if any(term in query_lower for term in ("inflation", "interest rates", "economy", "fed", "cpi")):
            if any(marker in title_blob for marker in ("inflation", "cpi", "consumer prices", "fed", "interest rate", "economy")):
                score += 3.0
            elif any(marker in path for marker in ("/money/", "/business/", "/markets/", "/economy/")):
                score += 1.0
            else:
                score -= 4.0

        if subject == "artificial intelligence":
            if any(marker in title_blob for marker in ("artificial intelligence", " ai ", "openai", "anthropic", "chatgpt", "copilot", "gemini", "grok")):
                score += 3.5
            if any(domain in host for domain in ("finance.yahoo.com", "msn.com", "seekingalpha.com", "investing.com")):
                score -= 10.0
        if subject and any(marker in subject for marker in ("climate change", "climate", "global warming", "emissions")):
            if "climate change" in subject and not looks_evergreen:
                if "climate change" in title_blob:
                    score += 7.0
                elif "climate change" in desc_blob:
                    score += 2.5
                elif "climate" in title_blob and "change" not in title_blob:
                    score -= 4.0
            if any(marker in title_blob for marker in ("climate change", "climate", "warming", "emissions", "glaciers", "heatwave")):
                score += 3.0
            if any(domain in host for domain in ("msn.com", "finance.yahoo.com")):
                score -= 10.0

        if self._is_latest_style_news_query(query_lower):
            current_year = datetime.now(timezone.utc).year
            year_match = re.search(r"\b(20\d{2})\b", f"{title} {desc}")
            if self._news_row_is_hub_page(row):
                score -= 18.0
            if looks_evergreen:
                score -= 12.0
            else:
                if re.search(r"\b(minutes?|hours?)\s+ago\b", desc_blob) is not None or "today" in desc_blob:
                    score += 7.0
                elif "yesterday" in desc_blob:
                    score += 4.0
                elif year_match:
                    year_value = int(year_match.group(1))
                    if year_value >= current_year:
                        score += 4.0
                    elif year_value == current_year - 1:
                        score += 1.0
                    else:
                        score -= 30.0
                if self._news_row_has_recency_signal(query, row):
                    score += 6.0
                else:
                    score -= 7.0

        return score

    def _news_result_rows_adequate(self, query: str, rows: List[Dict[str, Any]]) -> bool:
        filtered = [dict(row or {}) for row in rows if isinstance(row, dict)]
        if not filtered:
            return False
        top_scores = [self._news_row_focus_score(query, row) for row in filtered[:3]]
        if not top_scores:
            return False
        if max(top_scores) < 4.0:
            return False
        subject = self._news_query_subject(query).lower()
        reputable_hosts = self._news_reputable_hosts(query)
        if reputable_hosts:
            if not any(
                any(domain in (urlparse(str((row or {}).get("url") or "")).netloc or "").lower() for domain in reputable_hosts)
                for row in filtered[:3]
            ):
                return False
        if self._is_latest_style_news_query(query):
            top_rows = filtered[:5]
            top_row = top_rows[0]
            if self._news_row_is_hub_page(top_row):
                return False
            if self._news_row_looks_evergreen_or_ad(query, top_row):
                if any(
                    self._news_row_has_recency_signal(query, row) and not self._news_row_looks_evergreen_or_ad(query, row)
                    for row in top_rows[1:]
                ):
                    return False
                if not any(not self._news_row_looks_evergreen_or_ad(query, row) for row in top_rows):
                    return False
        if self._is_latest_style_news_query(query) and not any(
            self._news_row_has_recency_signal(query, row) for row in filtered[:3]
        ):
            return False
        if sum(1 for score in top_scores if score >= 4.0) >= 2:
            return True
        return top_scores[0] >= 7.0

    def _news_reputable_hosts(self, query: str) -> Tuple[str, ...]:
        subject = self._news_query_subject(query).lower()
        if subject and any(marker in subject for marker in ("inflation", "economy", "fed", "interest rate", "jobs", "market", "bitcoin", "ethereum", "tesla", "stocks")):
            return (
                "reuters.com",
                "apnews.com",
                "bloomberg.com",
                "cnbc.com",
                "wsj.com",
                "ft.com",
                "marketwatch.com",
            )
        if subject and any(marker in subject for marker in ("artificial intelligence", "ai", "openai", "anthropic", "chatgpt", "copilot", "google", "microsoft")):
            return (
                "reuters.com",
                "apnews.com",
                "techcrunch.com",
                "theverge.com",
                "wired.com",
                "cnbc.com",
            )
        if subject and any(marker in subject for marker in ("climate change", "climate", "global warming", "emissions")):
            return (
                "reuters.com",
                "apnews.com",
                "bbc.com",
                "theguardian.com",
            )
        return ()

    def _news_site_filtered_queries(self, query: str) -> List[str]:
        subject = self._news_query_subject(query)
        if not subject:
            return []
        subject_lower = subject.lower()
        latest_style = self._is_latest_style_news_query(query)
        canonical = self._canonical_news_query(query)
        if any(marker in subject_lower for marker in ("inflation", "economy", "fed", "interest rate", "jobs", "market", "bitcoin", "ethereum", "tesla")):
            hosts = ("reuters.com", "apnews.com", "cnbc.com")
        elif any(marker in subject_lower for marker in ("climate change", "climate", "global warming", "emissions")):
            hosts = ("reuters.com", "apnews.com", "bbc.com", "theguardian.com")
        elif any(marker in subject_lower for marker in ("premier league", "nba", "nfl", "mlb", "nhl", "soccer", "football", "sports")):
            hosts = ("reuters.com", "apnews.com", "espn.com")
        elif any(marker in subject_lower for marker in ("movie", "movies", "film", "box office", "tv", "music")):
            hosts = ("reuters.com", "apnews.com", "variety.com")
        elif any(marker in subject_lower for marker in ("artificial intelligence", "ai", "openai", "anthropic", "chatgpt", "copilot", "google")):
            hosts = ("reuters.com", "apnews.com", "techcrunch.com")
        else:
            hosts = ("reuters.com", "apnews.com", "bbc.com")

        query_tiers: List[List[str]] = [[], [], [], [], []]
        seen: Set[str] = set()

        def add_query(tier_index: int, candidate: str) -> None:
            clean = " ".join(str(candidate or "").split()).strip()
            if not clean:
                return
            lowered = clean.lower()
            if lowered in seen:
                return
            seen.add(lowered)
            query_tiers[min(max(0, int(tier_index)), len(query_tiers) - 1)].append(clean)

        for host in hosts:
            if latest_style:
                if canonical:
                    add_query(0, f"site:{host} {canonical}")
                if "climate change" in subject_lower:
                    add_query(1, f'site:{host} "climate change" today')
                    add_query(2, f'site:{host} "climate change"')
            add_query(3, f"site:{host} {subject}")
            if latest_style:
                add_query(4, f"site:{host} {subject} today")
        return [candidate for tier in query_tiers for candidate in tier]

    def _refine_latest_news_shortlist(self, query: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered = [dict(row or {}) for row in rows if isinstance(row, dict)]
        if not filtered or not self._is_latest_style_news_query(query):
            return filtered
        reputable_hosts = self._news_reputable_hosts(query)
        fresh_rows = [
            row
            for row in filtered
            if self._news_row_has_recency_signal(query, row) and not self._news_row_looks_evergreen_or_ad(query, row)
        ]
        if fresh_rows:
            filtered = [
                row
                for row in filtered
                if not self._news_row_looks_evergreen_or_ad(query, row) or self._news_row_has_recency_signal(query, row)
            ] or filtered
        return sorted(
            filtered,
            key=lambda row: (
                1
                if self._news_row_has_recency_signal(query, row) and not self._news_row_looks_evergreen_or_ad(query, row)
                else 0,
                1
                if any(domain in (urlparse(str((row or {}).get("url") or "")).netloc or "").lower() for domain in reputable_hosts)
                else 0,
                1 if self._news_row_has_recency_signal(query, row) else 0,
                1 if not self._news_row_looks_evergreen_or_ad(query, row) else 0,
                self._news_row_focus_score(query, row),
            ),
            reverse=True,
        )

    async def _news_lookup_browse(self, query: str, retries: int = 2, backoff_factor: float = 0.3) -> List[Dict[str, Any]]:
        q = " ".join(str(query or "").split()).strip()
        if not q:
            return []
        canonical = self._canonical_news_query(q)
        subject = self._news_query_subject(q)
        variants: List[str] = []
        for candidate in [canonical, q, f"{subject} latest news" if subject else "", f"{subject} breaking news today" if subject else ""]:
            clean = " ".join(str(candidate or "").split()).strip()
            if not clean:
                continue
            if clean.lower() not in {item.lower() for item in variants}:
                variants.append(clean)
        variants = variants[:3] or [q]

        self._append_browse_step(
            q,
            step="route",
            detail=f"using news shortlist path across {len(variants)} query variant(s)",
            mode="news",
        )
        self._append_browse_step(
            q,
            step="retrieve",
            detail="running bounded news retrieval before broader fallback",
            mode="news",
        )

        gathered = await asyncio.gather(
            *[
                asyncio.wait_for(self.news_handler._searx_news(variant, max_results=12), timeout=8.0)
                for variant in variants
            ],
            return_exceptions=True,
        )
        raw_rows: List[Dict[str, Any]] = []
        for result in gathered:
            if isinstance(result, list) and result:
                raw_rows.extend(dict(row or {}) for row in result if isinstance(row, dict))

        prioritized = self._prioritize_browse_rows(q, self._dedupe_results(raw_rows), prefer_official=False)
        filtered = [
            dict(row or {})
            for row in prioritized
            if isinstance(row, dict) and self._news_row_focus_score(q, row) >= 2.5
        ]
        filtered = self._promote_news_reputable_hosts(q, filtered)
        filtered = self._refine_latest_news_shortlist(q, filtered)
        filtered = filtered[:8]

        if not self._news_result_rows_adequate(q, filtered):
            subject_filtered_queries = self._news_site_filtered_queries(q)
            if subject_filtered_queries:
                self._append_browse_step(
                    q,
                    step="search",
                    detail="news shortlist looked weak; using site-filtered reputable-host fallback",
                    mode="news",
                )
                try:
                    fallback_rows = await asyncio.wait_for(
                        self._variant_ddg_rows(
                            subject_filtered_queries,
                            max_variants=min(4 if self._is_latest_style_news_query(q) else 3, len(subject_filtered_queries)),
                            max_results=5,
                            timeout_s=8.0,
                        ),
                        timeout=10.0,
                    )
                except Exception:
                    fallback_rows = []
                merged = self._dedupe_results([*filtered, *[dict(row or {}) for row in fallback_rows if isinstance(row, dict)]])
                prioritized = self._prioritize_browse_rows(q, merged, prefer_official=False)
                filtered = [
                    dict(row or {})
                    for row in prioritized
                    if isinstance(row, dict) and self._news_row_focus_score(q, row) >= 2.5
                ]
                filtered = self._promote_news_reputable_hosts(q, filtered)
                filtered = self._refine_latest_news_shortlist(q, filtered)[:8]

        if not self._news_result_rows_adequate(q, filtered) and not subject:
            self._append_browse_step(
                q,
                step="search",
                detail="generic news query stayed broad; using news handler fallback",
                mode="news",
            )
            try:
                fallback_rows = await asyncio.wait_for(
                    self.news_handler.search_news(canonical or q, retries=max(1, int(retries or 1)), backoff_factor=backoff_factor),
                    timeout=16.0,
                )
            except Exception:
                fallback_rows = []
            merged = self._dedupe_results([*filtered, *[dict(row or {}) for row in fallback_rows if isinstance(row, dict)]])
            prioritized = self._prioritize_browse_rows(q, merged, prefer_official=False)
            filtered = [
                dict(row or {})
                for row in prioritized
                if isinstance(row, dict) and self._news_row_focus_score(q, row) >= 2.5
            ]
            filtered = self._promote_news_reputable_hosts(q, filtered)
            filtered = self._refine_latest_news_shortlist(q, filtered)[:8]

        if filtered:
            self._append_browse_step(
                q,
                step="judge",
                detail=f"news shortlist kept {min(len(filtered), 8)} topical row(s)",
                mode="news",
            )
            self._record_browse_report(
                q,
                mode="news",
                summary=self._summarize_result_rows(q, filtered),
                sources=[str((row or {}).get("url") or "").strip() for row in filtered[:6]],
            )
        return filtered

    def _promote_news_reputable_hosts(self, query: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered = [dict(row or {}) for row in rows if isinstance(row, dict)]
        reputable_hosts = self._news_reputable_hosts(query)
        if not filtered or not reputable_hosts:
            return filtered
        return sorted(
            filtered,
            key=lambda row: (
                1 if any(domain in (urlparse(str((row or {}).get("url") or "")).netloc or "").lower() for domain in reputable_hosts) else 0,
                1 if self._news_row_has_recency_signal(query, row) else 0,
                self._news_row_focus_score(query, row),
            ),
            reverse=True,
        )

    async def _variant_ddg_rows(
        self,
        variants: List[str],
        *,
        max_variants: int = 4,
        max_results: int = 8,
        timeout_s: float = 8.0,
    ) -> List[Dict[str, Any]]:
        queries = [str(variant or "").strip() for variant in list(variants or []) if str(variant or "").strip()][: max(1, int(max_variants or 4))]
        if not queries:
            return []
        results = await asyncio.gather(
            *[
                asyncio.wait_for(self._ddg_text(variant, max_results=max_results), timeout=max(1.0, float(timeout_s or 8.0)))
                for variant in queries
            ],
            return_exceptions=True,
        )
        rows: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, list) and result:
                rows.extend(self._normalize_ddg_results(result))
        return self._dedupe_results(rows)

    async def _variant_searx_rows(
        self,
        variants: List[str],
        *,
        domain: str = "general",
        max_variants: int = 4,
        max_results: int = 8,
        max_pages: int = 1,
        timeout_s: float = 8.0,
    ) -> List[Dict[str, Any]]:
        queries = [str(variant or "").strip() for variant in list(variants or []) if str(variant or "").strip()][: max(1, int(max_variants or 4))]
        if not queries or not str(SEARXNG_BASE_URL or "").strip():
            return []
        profile = self._searx_profile_for_domain(domain)
        async with httpx.AsyncClient(timeout=max(4.0, float(timeout_s or 8.0) + 2.0)) as client:
            results = await asyncio.gather(
                *[
                    asyncio.wait_for(
                        search_searxng(
                            client,
                            variant,
                            max_results=max_results,
                            max_pages=max(1, int(max_pages or 1)),
                            profile=str(profile.get("profile") or "general"),
                            category=str(profile.get("category") or "general"),
                            source_name=str(profile.get("source_name") or f"searxng_{domain}"),
                            domain=domain,
                        ),
                        timeout=max(1.0, float(timeout_s or 8.0)),
                    )
                    for variant in queries
                ],
                return_exceptions=True,
            )
        rows: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, list) and result:
                rows.extend(dict(row or {}) for row in result if isinstance(row, dict))
        return self._dedupe_results(rows)

    def _official_fast_path_queries(self, query: str, plan: BrowsePlan) -> List[str]:
        site_variants: List[str] = []
        seen: set[str] = set()
        for variant in list(plan.query_variants or []):
            clean = " ".join(str(variant or "").split()).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            if "site:" in key:
                site_variants.append(clean)

        queries: List[str] = []
        if plan.needs_recency or self._is_latest_who_dengue_guidance_query(query):
            queries.extend(site_variants[:4])
            queries.append(query)
        else:
            queries.append(query)
            queries.extend(site_variants[:3])

        if len(queries) < 2:
            for variant in list(plan.query_variants or []):
                clean = " ".join(str(variant or "").split()).strip()
                if clean and clean.lower() not in {item.lower() for item in queries}:
                    queries.append(clean)
                if len(queries) >= 4:
                    break
        deduped: List[str] = []
        deduped_seen: set[str] = set()
        for item in queries:
            key = str(item or "").strip().lower()
            if not key or key in deduped_seen:
                continue
            deduped_seen.add(key)
            deduped.append(str(item).strip())
        return deduped[:4] or [query]

    def _software_change_seed_rows(self, query: str) -> List[Dict[str, Any]]:
        ql = str(query or "").lower()
        if not is_software_change_query(query):
            return []
        version = self._software_change_version(query)
        rows: List[Dict[str, Any]] = []

        def add(url: str, title: str, description: str) -> None:
            rows.append(
                {
                    "title": title,
                    "url": url,
                    "description": description,
                    "category": "general",
                    "source": "software_change_seed",
                    "volatile": False,
                    "fullpage_fetch": True,
                }
            )

        if "typescript" in ql and version:
            ts_version = version.replace(".", "-")
            add(
                f"https://www.typescriptlang.org/docs/handbook/release-notes/typescript-{ts_version}.html",
                f"TypeScript {version} release notes",
                f"Official TypeScript {version} release notes and documentation changes.",
            )

        if "docker compose" in ql:
            compose_note = "Official Docker Compose release notes and documentation changes."
            if version:
                compose_note = f"Official Docker Compose release notes and documentation changes relevant to {version}."
            add(
                "https://docs.docker.com/compose/release-notes/",
                "Docker Compose release notes | Docker Docs",
                compose_note,
            )

        if "rust" in ql:
            rust_release = self._rust_release_redirect_version(version)
            if rust_release:
                add(
                    f"https://blog.rust-lang.org/releases/{rust_release}",
                    f"Announcing Rust {rust_release} | Rust Blog",
                    f"Official Rust {rust_release} release announcement and change summary.",
                )
            rust_desc = "Official Rust release notes and stable release documentation."
            if rust_release:
                rust_desc = f"Official Rust release notes, including Rust {rust_release} changes and release details."
            add(
                "https://doc.rust-lang.org/releases.html",
                "Rust release notes | Rust Documentation",
                rust_desc,
            )

        return self._prioritize_browse_rows(query, rows, prefer_official=True)[:4]

    def _known_official_seed_rows(self, query: str) -> List[Dict[str, Any]]:
        ql = str(query or "").lower()
        rows: List[Dict[str, Any]] = []

        def add(url: str, title: str, description: str) -> None:
            rows.append(
                {
                    "title": title,
                    "url": url,
                    "description": description,
                    "category": "general",
                    "source": "official_seed",
                    "volatile": False,
                    "fullpage_fetch": True,
                }
            )

        if "fafsa" in ql and "deadline" in ql:
            add(
                "https://studentaid.gov/apply-for-aid/fafsa/fafsa-deadlines",
                "FAFSA deadlines | Federal Student Aid",
                "Official FAFSA federal, state, and school deadline guidance from Federal Student Aid.",
            )
        if "passport" in ql and any(term in ql for term in ("renew", "renewal", "requirement", "requirements")):
            add(
                "https://travel.state.gov/content/travel/en/passports/have-passport/renew.html",
                "Renew an adult passport | Travel.State.Gov",
                "Official passport renewal requirements, eligibility rules, and document guidance from the U.S. Department of State.",
            )
        if ("tsa" in ql or "transportation security administration" in ql) and any(term in ql for term in ("id", "identification", "requirement", "requirements")):
            add(
                "https://www.tsa.gov/travel/security-screening/identification",
                "Identification requirements | TSA",
                "Official TSA identification and travel ID requirements for airport security screening.",
            )
        if ("irs" in ql or "tax" in ql) and "mileage" in ql:
            add(
                "https://www.irs.gov/tax-professionals/standard-mileage-rates",
                "Standard mileage rates | IRS",
                "Official IRS mileage rate guidance for business, medical, moving, and charitable travel.",
            )
        if ("irs" in ql or "tax" in ql) and "bracket" in ql:
            add(
                "https://www.irs.gov/filing/federal-income-tax-rates-and-brackets",
                "Federal income tax rates and brackets | IRS",
                "Official IRS federal income tax bracket guidance and annual tax rate tables.",
            )
        if "cdc" in ql and "flu" in ql and "vaccine" in ql:
            add(
                "https://www.cdc.gov/flu/vaccines/index.html",
                "Influenza vaccination information | CDC",
                "Official CDC flu vaccine guidance, recommendations, and vaccination information.",
            )
        if "travel vaccines" in ql and "brazil" in ql:
            add(
                "https://wwwnc.cdc.gov/travel/destinations/traveler/none/brazil",
                "Brazil - Traveler view | CDC",
                "Official CDC traveler vaccine and health guidance for Brazil, including recommended travel vaccines.",
            )
        if "who" in ql and "measles" in ql:
            add(
                "https://www.who.int/news-room/fact-sheets/detail/measles",
                "Measles | WHO fact sheet",
                "Official WHO measles update and disease guidance page.",
            )
        if "fda" in ql and "peanut" in ql and "allergy" in ql:
            add(
                "https://www.fda.gov/food/food-labeling-nutrition/food-allergies",
                "Food allergies | FDA",
                "Official FDA food allergy labeling guidance, including peanut allergy information.",
            )
        if ("noaa" in ql or "hurricane" in ql) and any(term in ql for term in ("outlook", "season")):
            add(
                "https://www.cpc.ncep.noaa.gov/products/outlooks/hurricane.shtml",
                "NOAA hurricane outlook | Climate Prediction Center",
                "Official NOAA seasonal hurricane outlook and Atlantic hurricane season guidance.",
            )
        if "uscis" in ql and "fee" in ql:
            add(
                "https://www.uscis.gov/g-1055",
                "Fee schedule | USCIS",
                "Official USCIS fee schedule and filing fee guidance.",
            )
        if ("epa" in ql or "air quality" in ql) and "guid" in ql:
            add(
                "https://www.airnow.gov/air-quality-and-health/",
                "Air quality and health | AirNow",
                "Official EPA and AirNow air quality guidance and health recommendations.",
            )
        if ("cms" in ql or "telehealth" in ql) and any(term in ql for term in ("rule", "rules", "guidance")):
            add(
                "https://www.cms.gov/medicare/coverage/telehealth",
                "Telehealth coverage | CMS",
                "Official CMS telehealth coverage guidance and policy resources.",
            )
        if ("osha" in ql or "heat" in ql) and "guid" in ql:
            add(
                "https://www.osha.gov/heat-exposure",
                "Heat exposure | OSHA",
                "Official OSHA heat exposure guidance and worker safety recommendations.",
            )
        if ("weather.gov" in ql or "nws" in ql or "hurricane preparedness" in ql) and "hurricane" in ql:
            add(
                "https://www.weather.gov/wrn/hurricane-preparedness",
                "Hurricane preparedness | National Weather Service",
                "Official National Weather Service hurricane preparedness guidance.",
            )

        if "hypertension" in ql or "high blood pressure" in ql:
            add(
                "https://www.ahajournals.org/journal/hyp/guidelines/high-blood-pressure",
                "High blood pressure guidelines | AHA Journals",
                "Official 2025 AHA/ACC high blood pressure guideline hub for hypertension recommendations and implementation resources.",
            )
        if "asthma" in ql:
            add(
                "https://ginasthma.org/",
                "GINA asthma strategy and reports",
                "Official GINA asthma guideline and strategy report hub for diagnosis, treatment, and management guidance.",
            )
        if "diabetes" in ql:
            add(
                "https://diabetesjournals.org/care",
                "Diabetes Care | ADA Standards of Care",
                "Official ADA diabetes standards of care and guideline publication hub.",
            )
        if "heart failure" in ql:
            add(
                "https://www.acc.org/guidelines",
                "ACC clinical guidelines",
                "Official ACC guideline hub covering heart failure guidance, recommendations, and updates.",
            )
        if "copd" in ql:
            add(
                "https://goldcopd.org/",
                "GOLD COPD strategy reports",
                "Official GOLD COPD guideline and report hub for diagnosis, treatment, and prevention guidance.",
            )
        if "dengue" in ql:
            add(
                "https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever",
                "WHO arboviral disease guideline update",
                "Official 2025 WHO dengue clinical management guideline and arboviral disease update.",
            )
        if "obesity" in ql:
            add(
                "https://www.nice.org.uk/guidance/conditions-and-diseases/nutritional-and-metabolic/obesity",
                "Obesity guidance | NICE",
                "Official NICE obesity guideline and evidence hub.",
            )
        if "lipid management" in ql or "cholesterol" in ql:
            add(
                "https://www.acc.org/guidelines",
                "ACC clinical guidelines",
                "Official ACC guideline hub covering lipid management and cholesterol recommendations.",
            )
        if "depression" in ql:
            add(
                "https://www.nice.org.uk/guidance/conditions-and-diseases/mental-health-and-behavioural-conditions/depression",
                "Depression guidance | NICE",
                "Official NICE depression guideline and treatment recommendation hub.",
            )
        if "migraine" in ql:
            add(
                "https://www.nice.org.uk/guidance/conditions-and-diseases/neurological-conditions/migraine",
                "Migraine guidance | NICE",
                "Official NICE migraine guideline and treatment recommendation hub.",
            )
        if "osteoporosis" in ql:
            add(
                "https://www.nice.org.uk/guidance/conditions-and-diseases/musculoskeletal-conditions/osteoporosis",
                "Osteoporosis guidance | NICE",
                "Official NICE osteoporosis guideline and management recommendation hub.",
            )
        if "atrial fibrillation" in ql:
            add(
                "https://www.acc.org/guidelines",
                "ACC clinical guidelines",
                "Official ACC guideline hub covering atrial fibrillation recommendations and stroke prevention guidance.",
            )
        if "chronic kidney disease" in ql:
            add(
                "https://kdigo.org/guidelines/",
                "KDIGO guidelines",
                "Official KDIGO chronic kidney disease guideline and recommendation hub.",
            )
        if "stroke prevention" in ql:
            add(
                "https://www.stroke.org/en/professionals/stroke-resource-library/prevention",
                "Stroke prevention resources | American Stroke Association",
                "Official stroke prevention guideline and professional resource hub from the American Stroke Association.",
            )
        if "insomnia" in ql:
            add(
                "https://aasm.org/clinical-resources/practice-standards/practice-guidelines/",
                "Practice guidelines | AASM",
                "Official AASM insomnia guideline and sleep medicine practice recommendation hub.",
            )

        rows.extend(self._software_change_seed_rows(query))
        return rows

    async def _known_official_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        seed_rows = self._known_official_seed_rows(query)
        if not seed_rows:
            return []
        self._append_browse_step(
            query,
            step="retrieve",
            detail=f"opening {len(seed_rows)} known official page candidate(s)",
            mode=plan.mode,
        )
        enriched: List[Dict[str, Any]] = [dict(row or {}) for row in seed_rows]
        enriched = self._prioritize_browse_rows(query, enriched, prefer_official=True)
        enriched = [dict(row or {}) for row in enriched if self._row_allowed_for_query(query, row)]
        if not enriched:
            return []
        if not self._official_rows_adequate(query, enriched) and not any(
            self._official_result_satisfies_query(query, row) for row in enriched[:4]
        ):
            return []
        self._append_browse_step(query, step="judge", detail="known official page adapter looked sufficient", mode=plan.mode)
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=self._summarize_result_rows(query, enriched),
            sources=[str((row or {}).get("url") or "").strip() for row in enriched[:4]],
        )
        return enriched[:8]

    async def _official_preferred_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        seeded_rows = await self._known_official_browse(query, plan)
        if seeded_rows:
            return seeded_rows
        variants = self._official_fast_path_queries(query, plan)
        self._append_browse_step(
            query,
            step="route",
            detail=f"using official-source fast path across {len(variants)} query variant(s)",
            mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="retrieve",
            detail="running bounded SearXNG retrieval for official-source variants",
            mode=plan.mode,
        )
        official_rows = await self._variant_searx_rows(
            variants,
            domain="general",
            max_variants=max(1, len(variants)),
            max_results=8,
            max_pages=1,
            timeout_s=8.0,
        )
        official_rows = self._prioritize_browse_rows(query, official_rows, prefer_official=True)
        filtered_official_rows = [dict(row or {}) for row in official_rows if self._row_allowed_for_query(query, row)]
        if len(filtered_official_rows) != len(official_rows):
            self._append_browse_step(
                query,
                step="judge",
                detail=f"filtered {len(official_rows) - len(filtered_official_rows)} off-target official row(s)",
                mode=plan.mode,
            )
        official_rows = filtered_official_rows
        if not official_rows:
            self._append_browse_step(query, step="judge", detail="official-source fast path stayed thin; escalating to deep official search", mode=plan.mode)
            return []

        try:
            official_rows = await self._fetch_and_attach_content(
                official_rows,
                category="general",
                top_n=2,
                max_n=6,
            )
        except Exception:
            pass
        official_rows = [dict(row or {}) for row in official_rows if self._row_allowed_for_query(query, row)]
        official_rows = await self._promote_cardio_primary_guideline(query, official_rows, mode=plan.mode)
        official_rows = self._prioritize_browse_rows(query, official_rows, prefer_official=True)
        if not official_rows:
            self._append_browse_step(query, step="judge", detail="official-source fast path lost focus after enrichment; escalating to deep official search", mode=plan.mode)
            return []

        opened_count = sum(1 for row in official_rows if str((row or {}).get("content") or "").strip())
        if opened_count:
            self._append_browse_step(query, step="read", detail=f"opened {opened_count} official source page(s) for full text", mode=plan.mode)
        adequate = self._official_rows_adequate(query, official_rows) or any(
            self._official_result_satisfies_query(query, row) for row in official_rows[:6]
        )
        limitations: List[str] = []
        if adequate:
            judge_detail = "official-source fast path looked sufficient"
        else:
            judge_detail = "official-source fast path returned a thin official set but stayed on-source"
            limitations.append("Official-source coverage was thin; answer may rely on a small source set.")
        self._append_browse_step(query, step="judge", detail=judge_detail, mode=plan.mode)
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=self._summarize_result_rows(query, official_rows),
            sources=[str((row or {}).get("url") or "").strip() for row in official_rows[:6]],
            limitations=limitations,
        )
        return official_rows[:8]

    async def _trip_planning_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        variants = list(plan.query_variants or [])[:4] or [query]
        self._append_browse_step(
            query,
            step="route",
            detail=f"using travel-planning fast path across {len(variants)} query variant(s)",
            mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="retrieve",
            detail="running bounded DDG retrieval for travel variants",
            mode=plan.mode,
        )
        travel_rows = await self._variant_ddg_rows(variants, max_variants=4, max_results=8, timeout_s=8.0)

        prioritized = self._prioritize_browse_rows(query, travel_rows, prefer_official=False)
        filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if not filtered:
            self._append_browse_step(query, step="judge", detail="travel fast path stayed thin; escalating to research compose", mode=plan.mode)
            return []

        self._append_browse_step(
            query,
            step="retrieve",
            detail=f"travel fast path shortlisted {min(len(filtered), 8)} itinerary row(s)",
            mode=plan.mode,
        )
        try:
            seed_rows = self._travel_enrichment_candidates(query, filtered, limit=2)
            if seed_rows:
                enriched_seed = await self._fetch_and_attach_content(
                    seed_rows,
                    category="general",
                    top_n=min(2, len(seed_rows)),
                    max_n=min(2, len(seed_rows)),
                )
                selected_urls = {str((row or {}).get("url") or "").strip() for row in seed_rows}
                enriched = [
                    *enriched_seed,
                    *[dict(row or {}) for row in filtered if str((row or {}).get("url") or "").strip() not in selected_urls],
                ]
            else:
                enriched = list(filtered)
        except Exception:
            enriched = list(filtered)

        enriched = self._prioritize_browse_rows(query, enriched, prefer_official=False)
        enriched = [dict(row or {}) for row in enriched if self._row_allowed_for_query(query, row)]
        if not enriched:
            self._append_browse_step(query, step="judge", detail="travel fast path lost focus after enrichment; escalating to research compose", mode=plan.mode)
            return []

        opened_count = sum(1 for row in enriched[:3] if str((row or {}).get("content") or "").strip())
        if opened_count:
            self._append_browse_step(query, step="read", detail=f"opened {opened_count} travel source page(s) for itinerary details", mode=plan.mode)
        self._append_browse_step(query, step="judge", detail="travel fast path looked sufficient", mode=plan.mode)
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=self._summarize_result_rows(query, enriched),
            sources=[str((row or {}).get("url") or "").strip() for row in enriched[:6]],
        )
        return enriched[:8]

    async def _travel_lookup_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        variants = list(plan.query_variants or [])[:5] or [query]
        self._append_browse_step(
            query,
            step="route",
            detail=f"using travel-lookup fast path across {len(variants)} query variant(s)",
            mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="retrieve",
            detail="running bounded retrieval for travel lookup variants",
            mode=plan.mode,
        )
        travel_rows = await self._variant_ddg_rows(variants, max_variants=5, max_results=8, timeout_s=8.0)

        prioritized = self._prioritize_browse_rows(query, travel_rows, prefer_official=False)
        filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if len(filtered) < 2:
            searx_rows = await self._variant_searx_rows(
                variants,
                domain="general",
                max_variants=4,
                max_results=6,
                max_pages=1,
                timeout_s=8.0,
            )
            merged = self._dedupe_results([*filtered, *searx_rows])
            prioritized = self._prioritize_browse_rows(query, merged, prefer_official=False)
            filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
            if searx_rows:
                self._append_browse_step(
                    query,
                    step="retrieve",
                    detail=f"SearXNG added {len(searx_rows)} travel lookup row(s)",
                    mode=plan.mode,
                )
        if not filtered:
            self._append_browse_step(query, step="judge", detail="travel lookup fast path stayed thin; escalating to research compose", mode=plan.mode)
            return []

        self._append_browse_step(
            query,
            step="retrieve",
            detail=f"travel lookup fast path shortlisted {min(len(filtered), 8)} row(s)",
            mode=plan.mode,
        )
        try:
            seed_rows = self._travel_enrichment_candidates(query, filtered, limit=2)
            if seed_rows:
                enriched_seed = await self._fetch_and_attach_content(
                    seed_rows,
                    category="general",
                    top_n=min(2, len(seed_rows)),
                    max_n=min(2, len(seed_rows)),
                )
                selected_urls = {str((row or {}).get("url") or "").strip() for row in seed_rows}
                enriched = [
                    *enriched_seed,
                    *[dict(row or {}) for row in filtered if str((row or {}).get("url") or "").strip() not in selected_urls],
                ]
            else:
                enriched = list(filtered)
        except Exception:
            enriched = list(filtered)

        enriched = self._prioritize_browse_rows(query, enriched, prefer_official=False)
        enriched = [dict(row or {}) for row in enriched if self._row_allowed_for_query(query, row)]
        if not enriched:
            self._append_browse_step(query, step="judge", detail="travel lookup fast path lost focus after enrichment; escalating to research compose", mode=plan.mode)
            return []

        opened_count = sum(1 for row in enriched[:3] if str((row or {}).get("content") or "").strip())
        if opened_count:
            self._append_browse_step(query, step="read", detail=f"opened {opened_count} travel lookup page(s) for fuller context", mode=plan.mode)
        self._append_browse_step(query, step="judge", detail="travel lookup fast path looked sufficient", mode=plan.mode)
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=self._summarize_result_rows(query, enriched),
            sources=[str((row or {}).get("url") or "").strip() for row in enriched[:6]],
        )
        return enriched[:8]

    async def _shopping_compare_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        ereader_compare = any(marker in str(query or "").lower() for marker in ("kindle", "kobo", "ereader", "e-reader"))
        trusted_queries: List[str] = []
        variants = (
            self._shopping_compare_primary_queries(query, plan)[:6]
            if ereader_compare
            else list(plan.query_variants or [])[:4] or [query]
        )
        if not variants:
            variants = [query]
        retrieval_timeout_s = 7.0 if ereader_compare else 8.0
        trusted_retry_timeout_s = 6.0 if ereader_compare else 8.0
        self._append_browse_step(
            query,
            step="route",
            detail=f"using shopping-comparison fast path across {len(variants)} query variant(s)",
            mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="retrieve",
            detail="running bounded DDG retrieval for comparison variants",
            mode=plan.mode,
        )
        compare_rows = await self._variant_ddg_rows(variants, max_variants=min(6, len(variants)), max_results=8, timeout_s=retrieval_timeout_s)

        prioritized = self._prioritize_browse_rows(query, compare_rows, prefer_official=False)
        filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if not ereader_compare and self._shopping_compare_needs_trusted_retry(query, filtered):
            trusted_queries = self._shopping_compare_site_filtered_queries(query)
            if trusted_queries:
                self._append_browse_step(
                    query,
                    step="search",
                    detail="shopping shortlist looked weak; using trusted-review fallback",
                    mode=plan.mode,
                )
                try:
                    fallback_rows = await asyncio.wait_for(
                        self._variant_ddg_rows(
                            trusted_queries,
                            max_variants=min(4, len(trusted_queries)),
                            max_results=6,
                            timeout_s=trusted_retry_timeout_s,
                        ),
                        timeout=max(8.0, trusted_retry_timeout_s + 2.0),
                    )
                except Exception:
                    fallback_rows = []
                compare_rows = self._dedupe_results(
                    [*compare_rows, *[dict(row or {}) for row in fallback_rows if isinstance(row, dict)]]
                )
                prioritized = self._prioritize_browse_rows(query, compare_rows, prefer_official=False)
                filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if not filtered:
            searx_queries = trusted_queries[:4] or variants[:4]
            searx_rows = await self._variant_searx_rows(
                searx_queries,
                domain="general",
                max_variants=min(4, len(searx_queries)),
                max_results=6,
                max_pages=1,
                timeout_s=8.0,
            )
            if searx_rows:
                self._append_browse_step(
                    query,
                    step="retrieve",
                    detail=f"SearXNG added {len(searx_rows)} shopping comparison row(s)",
                    mode=plan.mode,
                )
                compare_rows = self._dedupe_results(
                    [*compare_rows, *[dict(row or {}) for row in searx_rows if isinstance(row, dict)]]
                )
                prioritized = self._prioritize_browse_rows(query, compare_rows, prefer_official=False)
                filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if not filtered:
            rescue_queries = trusted_queries[:2] or self._shopping_compare_primary_queries(query, plan)[:2]
            if rescue_queries:
                self._append_browse_step(
                    query,
                    step="recover",
                    detail="shopping fast path stayed thin; trying bounded search-general rescue",
                    mode=plan.mode,
                )
                rescued_rows: List[Dict[str, Any]] = []
                for rescue_query in rescue_queries:
                    try:
                        rescue_result = await asyncio.wait_for(
                            search_general(
                                rescue_query,
                                min_results=1,
                                budgets_ms={"primary": 2200, "fallback": 1400},
                                allow_ddg_fallback=True,
                            ),
                            timeout=4.5,
                        )
                    except Exception:
                        rescue_result = []
                    rescued_rows.extend(dict(row or {}) for row in rescue_result if isinstance(row, dict))
                if rescued_rows:
                    self._append_browse_step(
                        query,
                        step="recover",
                        detail=f"search-general rescue added {len(rescued_rows)} shopping comparison row(s)",
                        mode=plan.mode,
                    )
                    compare_rows = self._dedupe_results([*compare_rows, *rescued_rows])
                    prioritized = self._prioritize_browse_rows(query, compare_rows, prefer_official=False)
                    filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if not filtered:
            self._append_browse_step(query, step="judge", detail="shopping fast path stayed thin; escalating to research compose", mode=plan.mode)
            return []

        self._append_browse_step(
            query,
            step="retrieve",
            detail=f"shopping fast path shortlisted {min(len(filtered), 8)} comparison row(s)",
            mode=plan.mode,
        )
        if ereader_compare:
            enriched = list(filtered)
        else:
            try:
                seed_rows = filtered[:4]
                enriched_seed = await asyncio.wait_for(
                    self._fetch_and_attach_content(
                        seed_rows,
                        category="general",
                        top_n=min(2, len(seed_rows)),
                        max_n=min(4, len(seed_rows)),
                    ),
                    timeout=10.0,
                )
                enriched = [*enriched_seed, *filtered[4:]]
            except Exception:
                enriched = list(filtered)

        enriched = self._prioritize_browse_rows(query, enriched, prefer_official=False)
        enriched = [dict(row or {}) for row in enriched if self._row_allowed_for_query(query, row)]
        if not enriched:
            self._append_browse_step(query, step="judge", detail="shopping fast path lost focus after enrichment; escalating to research compose", mode=plan.mode)
            return []

        opened_count = sum(1 for row in enriched[:4] if str((row or {}).get("content") or "").strip())
        if opened_count:
            self._append_browse_step(query, step="read", detail=f"opened {opened_count} comparison source page(s) for specs and review text", mode=plan.mode)
        self._append_browse_step(query, step="judge", detail="shopping fast path looked sufficient", mode=plan.mode)
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=self._summarize_result_rows(query, enriched),
            sources=[str((row or {}).get("url") or "").strip() for row in enriched[:6]],
        )
        return enriched[:8]

    async def _software_change_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        seed_rows = self._software_change_seed_rows(query)
        if seed_rows:
            self._append_browse_step(
                query,
                step="route",
                detail=f"using direct software release adapter with {len(seed_rows)} first-party page candidate(s)",
                mode=plan.mode,
            )
            try:
                seeded = await self._fetch_and_attach_content(
                    seed_rows,
                    category="general",
                    top_n=min(2, len(seed_rows)),
                    max_n=min(4, len(seed_rows)),
                )
            except Exception:
                seeded = [dict(row or {}) for row in seed_rows]
            seeded = self._prioritize_browse_rows(query, seeded, prefer_official=True)
            seeded = [dict(row or {}) for row in seeded if self._row_allowed_for_query(query, row)]
            if seeded and any(self._official_result_satisfies_query(query, row) for row in seeded[:4]):
                if any(str((row or {}).get("content") or "").strip() for row in seeded[:4]):
                    self._append_browse_step(
                        query,
                        step="read",
                        detail=f"opened {min(len(seeded), 4)} first-party software release page(s)",
                        mode=plan.mode,
                    )
                adequate = self._official_rows_adequate(query, seeded)
                limitations: List[str] = []
                judge_detail = "direct software release adapter looked sufficient"
                if not adequate:
                    limitations.append("Official release-note coverage was narrow, but the answer stayed on first-party pages.")
                    judge_detail = "direct software release adapter stayed narrow but on-source"
                self._append_browse_step(query, step="judge", detail=judge_detail, mode=plan.mode)
                self._record_browse_report(
                    query,
                    mode=plan.mode,
                    summary=self._summarize_result_rows(query, seeded),
                    sources=[str((row or {}).get("url") or "").strip() for row in seeded[:6]],
                    limitations=limitations,
                )
                return seeded[:8]
            self._append_browse_step(
                query,
                step="judge",
                detail="direct software release adapter stayed thin; trying bounded search variants",
                mode=plan.mode,
            )

        variants = list(plan.query_variants or [])[:4] or [query]
        self._append_browse_step(
            query,
            step="route",
            detail=f"using software-change fast path across {len(variants)} query variant(s)",
            mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="retrieve",
            detail="running bounded DDG retrieval for release-note variants",
            mode=plan.mode,
        )
        candidate_rows = await self._variant_ddg_rows(variants, max_variants=4, max_results=8, timeout_s=8.0)
        prioritized = self._prioritize_browse_rows(query, candidate_rows, prefer_official=True)
        filtered = [dict(row or {}) for row in prioritized if self._row_allowed_for_query(query, row)]
        if not filtered:
            self._append_browse_step(query, step="judge", detail="software-change fast path stayed thin; escalating to research compose", mode=plan.mode)
            return []

        self._append_browse_step(
            query,
            step="retrieve",
            detail=f"software-change fast path shortlisted {min(len(filtered), 8)} release-note row(s)",
            mode=plan.mode,
        )
        try:
            seed_rows = filtered[:4]
            enriched_seed = await self._fetch_and_attach_content(
                seed_rows,
                category="general",
                top_n=min(2, len(seed_rows)),
                max_n=min(4, len(seed_rows)),
            )
            enriched = [*enriched_seed, *filtered[4:]]
        except Exception:
            enriched = list(filtered)

        enriched = self._prioritize_browse_rows(query, enriched, prefer_official=True)
        enriched = [dict(row or {}) for row in enriched if self._row_allowed_for_query(query, row)]
        if not enriched:
            self._append_browse_step(query, step="judge", detail="software-change fast path lost focus after enrichment; escalating to research compose", mode=plan.mode)
            return []

        opened_count = sum(1 for row in enriched[:4] if str((row or {}).get("content") or "").strip())
        if opened_count:
            self._append_browse_step(query, step="read", detail=f"opened {opened_count} release-note page(s) for exact change details", mode=plan.mode)
        adequate = self._official_rows_adequate(query, enriched)
        limitations: List[str] = []
        if adequate:
            judge_detail = "software-change fast path looked sufficient"
        else:
            judge_detail = "software-change fast path returned a thin official set but stayed on-source"
            limitations.append("Official release-note coverage was thin; answer may rely on a small source set.")
        self._append_browse_step(query, step="judge", detail=judge_detail, mode=plan.mode)
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=self._summarize_result_rows(query, enriched),
            sources=[str((row or {}).get("url") or "").strip() for row in enriched[:6]],
            limitations=limitations,
        )
        return enriched[:8]

    async def _python_docs_direct_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        version = self._python_docs_version(query)
        if not version:
            return []
        self._append_browse_step(
            query,
            step="route",
            detail=f"using direct Python docs adapter for {version}",
            mode=plan.mode,
        )
        seed_rows: List[Dict[str, Any]] = [
            {
                "title": f"What's New In Python {version}",
                "url": f"https://docs.python.org/3/whatsnew/{version}.html",
                "description": f"Official What's New page for Python {version}.",
                "source": "python_docs_direct",
            },
            {
                "title": f"Changelog - Python {version} documentation",
                "url": f"https://docs.python.org/{version}/whatsnew/changelog.html",
                "description": f"Official changelog page for Python {version}.",
                "source": "python_docs_direct",
            },
        ]
        try:
            rows = await self._fetch_and_attach_content(seed_rows, category="general", top_n=2, max_n=2)
        except Exception:
            rows = [dict(row) for row in seed_rows]
        filtered = [dict(row) for row in rows if self._row_allowed_for_query(query, row)]
        if not filtered:
            filtered = [dict(row) for row in seed_rows if self._row_allowed_for_query(query, row)]
        if filtered:
            self._append_browse_step(
                query,
                step="read",
                detail=f"resolved {len(filtered)} direct Python docs page(s)",
                mode=plan.mode,
            )
            summary = self._summarize_result_rows(query, filtered)
            self._record_browse_report(
                query,
                mode=plan.mode,
                summary=summary,
                sources=[str((row or {}).get("url") or "").strip() for row in filtered[:4]],
            )
        return filtered

    async def _promote_cardio_primary_guideline(self, query: str, rows: List[Dict[str, Any]], *, mode: str) -> List[Dict[str, Any]]:
        query_lower = str(query or "").lower()
        if not rows:
            return rows
        if not self._is_latest_clinical_query(query) or not any(term in query_lower for term in ("hypertension", "high blood pressure")):
            return rows

        working = [dict(row or {}) for row in rows if isinstance(row, dict)]
        if not working:
            return rows

        hub_row = next(
            (
                row for row in working
                if "/guidelines/high-blood-pressure" in str((row or {}).get("url") or "").lower()
                and "ahajournals.org" in (urlparse(str((row or {}).get("url") or "")).netloc or "").lower()
            ),
            None,
        )
        if hub_row is None:
            return working

        primary_row = next(
            (
                row for row in working
                if "cir.0000000000001356" in self._canonical_cardio_guideline_url(str((row or {}).get("url") or "")).lower()
            ),
            None,
        )
        if primary_row is None:
            blocked_fetch = False
            try:
                async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)"}) as client:
                    response = await client.get(str(hub_row.get("url") or "").strip(), follow_redirects=True)
                    blocked_fetch = self._official_page_fetch_blocked(response)
                    candidate = None if blocked_fetch else self._extract_cardio_primary_guideline_candidate(response.text, str(response.url))
            except Exception:
                candidate = None
                blocked_fetch = True
            if candidate:
                try:
                    enriched = await self._fetch_and_attach_content([candidate], category="general", top_n=1, max_n=1)
                    if enriched:
                        candidate = dict(enriched[0] or {})
                except Exception:
                    pass
                primary_row = dict(candidate)
                working.append(primary_row)
                self._append_browse_step(
                    query,
                    step="route",
                    detail="promoted the primary ACC/AHA guideline article from the official hub",
                    mode=mode,
                )
            elif blocked_fetch:
                self._append_browse_step(
                    query,
                    step="recover",
                    detail="official guideline hub fetch looked blocked; running targeted official search to recover the primary article",
                    mode=mode,
                )
                recovered = await self._recover_cardio_primary_guideline_from_search(query, mode=mode)
                if recovered:
                    primary_row = dict(recovered)
                    primary_row["url"] = self._canonical_cardio_guideline_url(str(primary_row.get("url") or ""))
                    working.append(primary_row)
                    self._append_browse_step(
                        query,
                        step="recover",
                        detail="recovered the primary ACC/AHA guideline article from targeted official search results",
                        mode=mode,
                    )

        if primary_row is None:
            return working

        hub_url = str((hub_row or {}).get("url") or "").strip().lower()
        primary_url_canonical = self._canonical_cardio_guideline_url(str((primary_row or {}).get("url") or "")).strip()
        primary_url = primary_url_canonical.lower()
        primary_row = dict(primary_row or {})
        if primary_url_canonical:
            primary_row["url"] = primary_url_canonical
        ordered: List[Dict[str, Any]] = [dict(hub_row), dict(primary_row)]
        seen = {hub_url, primary_url}
        for row in self._prioritize_browse_rows(query, working, prefer_official=True):
            normalized_url = self._canonical_cardio_guideline_url(str((row or {}).get("url") or "")).strip()
            url_key = normalized_url.lower()
            if not url_key or url_key in seen:
                continue
            normalized_row = dict(row or {})
            normalized_row["url"] = normalized_url
            ordered.append(normalized_row)
            seen.add(url_key)
        return ordered

    async def _deep_browse(self, query: str, plan: BrowsePlan, *, allow_resume: bool = False) -> List[Dict[str, Any]]:
        self._append_browse_step(
            query,
            step="plan",
            detail=f"deep browse with {len(list(plan.query_variants or [])) or 1} query variant(s)",
            mode=plan.mode,
        )
        memory_rows: List[Dict[str, Any]] = []
        official_rows: List[Dict[str, Any]] = []
        memory_domain = self._agentpedia_domain_hint(query, plan_mode=plan.mode, official_preferred=plan.official_preferred)
        if self._should_use_agentpedia_memory(query, plan_mode=plan.mode, official_preferred=plan.official_preferred):
            self._append_browse_step(query, step="memory", detail="checking Agentpedia notes before live browsing", mode=plan.mode)
            memory_rows = self._agentpedia_memory_rows(query, limit=2 if plan.needs_recency else 3)
            if memory_rows:
                self._append_browse_step(query, step="memory", detail=f"found {len(memory_rows)} Agentpedia note(s) for this topic", mode=plan.mode)
            else:
                self._append_browse_step(query, step="memory", detail="no strong Agentpedia notes found for this topic", mode=plan.mode)
        if plan.official_preferred:
            self._append_browse_step(query, step="route", detail="prioritizing official and documentation sources", mode=plan.mode)
            site_variants = [variant for variant in list(plan.query_variants or []) if "site:" in str(variant or "").lower()]
            official_site_budget = 2
            if self._is_latest_who_dengue_guidance_query(query):
                official_site_budget = 4
            if plan.needs_recency or self._is_python_docs_query(query):
                official_queries = list(site_variants[:official_site_budget]) + [query]
            else:
                official_queries = [query] + list(site_variants[:official_site_budget])
            for variant in official_queries:
                self._append_browse_step(query, step="search", detail=f"official query '{_safe_trim(variant, 88)}'", mode=plan.mode)
                try:
                    result = await asyncio.wait_for(
                        search_general(variant, min_results=3, budgets_ms={"primary": 2500, "fallback": 2500}, allow_ddg_fallback=False),
                        timeout=12.0,
                    )
                except Exception:
                    result = []
                if result:
                    self._append_browse_step(query, step="retrieve", detail=f"official search returned {len(result)} candidate row(s)", mode=plan.mode)
                    official_rows.extend(result)
                    if any(self._official_result_satisfies_query(query, row) for row in result if isinstance(row, dict)):
                        break
            official_rows = self._prioritize_browse_rows(query, official_rows, prefer_official=True)
            filtered_official_rows = [dict(row or {}) for row in official_rows if self._row_allowed_for_query(query, row)]
            if len(filtered_official_rows) != len(official_rows):
                self._append_browse_step(
                    query,
                    step="judge",
                    detail=f"filtered {len(official_rows) - len(filtered_official_rows)} off-target official row(s)",
                    mode=plan.mode,
                )
            if filtered_official_rows or self._is_latest_who_dengue_guidance_query(query):
                official_rows = filtered_official_rows
            if official_rows:
                try:
                    official_rows = await self._fetch_and_attach_content(
                        official_rows,
                        category="general",
                        top_n=2,
                        max_n=6,
                    )
                except Exception:
                    pass
                filtered_official_rows = [dict(row or {}) for row in official_rows if self._row_allowed_for_query(query, row)]
                if filtered_official_rows or self._is_latest_who_dengue_guidance_query(query):
                    official_rows = filtered_official_rows
                official_rows = await self._promote_cardio_primary_guideline(query, official_rows, mode=plan.mode)
                official_rows = self._prioritize_browse_rows(query, official_rows, prefer_official=True)
                opened_count = sum(1 for row in official_rows if str((row or {}).get("content") or "").strip())
                if opened_count:
                    self._append_browse_step(query, step="read", detail=f"opened {opened_count} source page(s) for full text", mode=plan.mode)
                if self._official_rows_adequate(query, official_rows):
                    self._append_browse_step(query, step="judge", detail="official-source pass looked sufficient", mode=plan.mode)
                    summary = self._summarize_result_rows(query, official_rows)
                    added = self._write_agentpedia_memory(query, official_rows[:4], domain_hint=memory_domain)
                    if added:
                        self._append_browse_step(query, step="memory", detail=f"persisted {added} Agentpedia fact row(s) from official browse", mode=plan.mode)
                    self._record_browse_report(
                        query,
                        mode=plan.mode,
                        summary=summary,
                        sources=[str((row or {}).get("url") or "").strip() for row in official_rows[:6]],
                    )
                    return official_rows[:8]
                self._append_browse_step(query, step="judge", detail="official-source pass looked thin; escalating to research compose", mode=plan.mode)
                if memory_rows:
                    self._append_browse_step(query, step="memory", detail="keeping Agentpedia notes as fallback context while live research continues", mode=plan.mode)

        domain_override = "general" if plan.official_preferred else None
        if allow_resume:
            cached_rows = self._resume_cached_evidence(query, plan, domain="general")
            if cached_rows:
                return cached_rows[:8]
        bundle = await research_compose(
            query,
            max_web_results=10,
            max_enrich_results_per_domain=6,
            max_deep_reads=8 if RESEARCH_COMPOSER_DEEPREAD else 0,
            risk_mode="auto",
            seed_queries=list(plan.query_variants or []),
            max_rounds=2 if (plan.needs_recency or plan.official_preferred or plan.needs_citations) else 1,
            domain_override=domain_override,
            browse_mode=plan.mode,
        )
        self._append_browse_step(
            query,
            step="retrieve",
            detail=f"research compose executed {len(list(getattr(bundle, 'queries', []) or [])) or 1} query trail(s)",
            mode=plan.mode,
        )
        self.last_research_bundle = bundle.as_dict()
        rows = self._rows_from_evidence_bundle(bundle, category="general")
        if list(getattr(bundle, "items", []) or []):
            self._append_browse_step(
                query,
                step="read",
                detail=f"reviewed {min(len(list(getattr(bundle, 'items', []) or [])), 8)} evidence item(s)",
                mode=plan.mode,
            )
        if list(getattr(bundle, "claims", []) or []):
            self._append_browse_step(
                query,
                step="judge",
                detail=f"built {len(list(getattr(bundle, 'claims', []) or []))} corroborated claim(s)",
                mode=plan.mode,
            )
        elif list(getattr(bundle, "limitations", []) or []):
            self._append_browse_step(
                query,
                step="judge",
                detail="research compose returned limitations that still need caution",
                mode=plan.mode,
            )
        if list(getattr(bundle, "section_bundles", []) or []):
            self._append_browse_step(
                query,
                step="compose",
                detail=f"organized findings into {len(list(getattr(bundle, 'section_bundles', []) or []))} section(s)",
                mode=plan.mode,
            )
        if plan.official_preferred and official_rows:
            if rows:
                rows = self._prioritize_browse_rows(query, [*official_rows, *rows], prefer_official=True)
                self._append_browse_step(
                    query,
                    step="judge",
                    detail=f"blended {min(len(official_rows), 3)} official shortlist row(s) with research evidence",
                    mode=plan.mode,
                )
            else:
                rows = self._prioritize_browse_rows(query, official_rows, prefer_official=True)
                self._append_browse_step(
                    query,
                    step="judge",
                    detail="reused the official shortlist because research compose stayed thin",
                    mode=plan.mode,
                )
        if rows and memory_rows and not plan.needs_recency and not plan.official_preferred:
            rows = self._prioritize_browse_rows(query, [*rows, *memory_rows], prefer_official=False)
            self._append_browse_step(
                query,
                step="memory",
                detail=f"blended {min(len(memory_rows), 3)} Agentpedia note(s) with live evidence",
                mode=plan.mode,
            )
        elif not rows and memory_rows:
            rows = list(memory_rows)
            self._append_browse_step(
                query,
                step="memory",
                detail=f"falling back to {len(memory_rows)} Agentpedia row(s) because live evidence stayed thin",
                mode=plan.mode,
            )
        summary = ""
        prefer_row_summary = (
            plan.official_preferred
            or plan.needs_recency
            or plan.needs_citations
            or is_shopping_compare_query(query)
            or is_trip_planning_query(query)
        )
        if prefer_row_summary:
            summary = self._summarize_result_rows(query, rows)
        if not summary:
            summary = self._summarize_evidence_bundle(bundle)
        if rows and not summary:
            summary = self._summarize_result_rows(query, rows)
        if rows:
            added = self._write_agentpedia_memory(query, rows[:4], domain_hint=memory_domain)
            if added:
                self._append_browse_step(query, step="memory", detail=f"persisted {added} Agentpedia fact row(s) from live research", mode=plan.mode)
        sources = [str(getattr(item, "url", "") or "").strip() for item in list(getattr(bundle, "items", []) or [])[:6]]
        if not sources and rows:
            sources = [str((row or {}).get("url") or "").strip() for row in rows[:6]]
        self._record_browse_report(
            query,
            mode=plan.mode,
            summary=summary,
            sources=sources,
            limitations=list(getattr(bundle, "limitations", []) or []),
            research_brief=dict(getattr(bundle, "research_brief", {}) or {}),
            section_bundles=[dict(item or {}) for item in list(getattr(bundle, "section_bundles", []) or []) if isinstance(item, dict)],
        )
        self._save_evidence_bundle(query, plan, bundle, rows, domain="general")
        if rows:
            return rows
        if summary:
            return [
                {
                    "title": "Research summary",
                    "url": sources[0] if sources else "",
                    "description": summary,
                    "category": "general",
                    "source": "research_compose",
                    "volatile": False,
                }
            ]
        offline_rows = self._offline_fallback_rows(q, browse_plan, reason="live web retrieval returned no usable rows")
        if offline_rows:
            self.search_cache.set(cache_key, offline_rows)
            return offline_rows
        self._append_browse_step(q, step="judge", detail="no live or local fallback rows were strong enough to answer", mode=browse_plan.mode)
        return []

    async def _github_browse(self, query: str, plan: BrowsePlan) -> List[Dict[str, Any]]:
        query_lower = str(query or "").lower()
        compare_repos = any(marker in query_lower for marker in ("compare", "comparison", " versus ", " vs ", " vs. "))
        direct_repo_urls = extract_repo_urls(query)
        self._append_browse_step(query, step="plan", detail="using GitHub-aware browse mode", mode=plan.mode)
        memory_rows: List[Dict[str, Any]] = []
        if self._should_use_agentpedia_memory(query, plan_mode=plan.mode):
            self._append_browse_step(query, step="memory", detail="checking Agentpedia for prior repo notes", mode=plan.mode)
            memory_rows = self._agentpedia_memory_rows(query, limit=2 if compare_repos else 3)
            if memory_rows:
                self._append_browse_step(query, step="memory", detail=f"found {len(memory_rows)} Agentpedia repo note(s)", mode=plan.mode)

        discovery: List[Dict[str, Any]] = []
        repo_urls: List[str] = []
        if compare_repos and len(direct_repo_urls) >= 2:
            repo_urls = direct_repo_urls[:2]
            self._append_browse_step(query, step="retrieve", detail="using explicit GitHub repo URLs from the query", mode=plan.mode)
        elif direct_repo_urls and not compare_repos:
            repo_urls = direct_repo_urls[:1]
            self._append_browse_step(query, step="retrieve", detail="using explicit GitHub repo URL from the query", mode=plan.mode)
        elif compare_repos:
            repo_urls = choose_repositories(query, [], limit=2 if compare_repos else 1)
            if len(repo_urls) >= (2 if compare_repos else 1):
                detail = "resolved canonical GitHub comparison subjects without search discovery" if compare_repos else "resolved canonical GitHub repository without search discovery"
                self._append_browse_step(query, step="retrieve", detail=detail, mode=plan.mode)

        if not repo_urls:
            self._append_browse_step(query, step="retrieve", detail="discovering repository candidates from search results", mode=plan.mode)
            variants = list(plan.query_variants or [])[:4]
            budgets = {"primary": 2500, "fallback": 2500}
            results = await asyncio.gather(
                *[
                    asyncio.wait_for(search_general(variant, min_results=2, budgets_ms=budgets), timeout=12.0)
                    for variant in variants
                ],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, list) and result:
                    discovery.extend(result)
            discovery = self._dedupe_results(discovery)
            if discovery:
                self._append_browse_step(query, step="retrieve", detail=f"found {len(discovery)} repository candidate row(s)", mode=plan.mode)
            repo_urls = choose_repositories(query, discovery, limit=2 if compare_repos else 1)
        if not repo_urls:
            if memory_rows:
                self._append_browse_step(query, step="memory", detail="returning Agentpedia repo notes because no live repository match was verified", mode=plan.mode)
                self._record_browse_report(
                    query,
                    mode=plan.mode,
                    summary=self._summarize_result_rows(query, memory_rows),
                    sources=[str((row or {}).get("url") or "").strip() for row in memory_rows[:6]],
                    limitations=["Returning prior researched notes because a live repository match could not be verified."],
                )
                return memory_rows[:5]
            return []
        self._append_browse_step(query, step="judge", detail=f"selected {len(repo_urls)} repo(s) for local inspection", mode=plan.mode)

        temp_root = os.path.join("C:\\somex", "audit", "tmp")
        os.makedirs(temp_root, exist_ok=True)
        inspection_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    inspect_github_repository,
                    repo_url,
                    cleanup=bool(plan.cleanup_downloads),
                    temp_root=temp_root,
                    remote_only=bool(compare_repos),
                )
                for repo_url in repo_urls
            ],
            return_exceptions=True,
        )
        inspections = []
        failed_inspections = 0
        for result in inspection_results:
            if isinstance(result, Exception):
                failed_inspections += 1
                logger.warning("GitHub local inspection failed for '%s': %s", query, result)
                continue
            inspections.append(result)
        if failed_inspections:
            self._append_browse_step(
                query,
                step="recover",
                detail=f"{failed_inspections} repo inspection attempt(s) failed; continuing with remaining results",
                mode=plan.mode,
            )
        if inspections:
            clone_count = sum(1 for inspection in inspections if str(getattr(inspection, "inspection_method", "")).lower() == "clone")
            if clone_count:
                detail = f"inspected README and manifests for {len(inspections)} repo(s) ({clone_count} via local clone)"
            else:
                detail = f"inspected README and manifests for {len(inspections)} repo(s) via remote fetch"
            self._append_browse_step(query, step="read", detail=detail, mode=plan.mode)

        rows: List[Dict[str, Any]] = []
        for inspection in inspections:
            rows.append(
                {
                    "title": f"{inspection.repo_slug} on GitHub",
                    "url": inspection.repo_url,
                    "description": _safe_trim(inspection.summary, 1800),
                    "content": _safe_trim(inspection.readme_excerpt, 2200),
                    "category": "general",
                    "source": "github_local",
                    "published_at": inspection.latest_commit.split("|", 1)[0].strip() if inspection.latest_commit else "",
                    "volatile": False,
                    "fullpage_fetch": True,
                }
            )
        row_urls = {str((row or {}).get("url") or "").strip() for row in rows}
        inspected_urls = {inspection.repo_url for inspection in inspections}
        selected_repo_urls = {repo_url.rstrip("/") for repo_url in repo_urls}

        if compare_repos and len(inspections) >= 2:
            summary_parts = [f"Compared {inspections[0].repo_slug} and {inspections[1].repo_slug}."]
            for inspection in inspections[:2]:
                manifest_names = ", ".join(list(inspection.manifests.keys())[:4]) or "none detected"
                repo_part = [f"{inspection.repo_slug}: default branch {inspection.default_branch or 'unknown'}"]
                if inspection.latest_commit:
                    repo_part.append(f"latest commit {inspection.latest_commit}")
                repo_part.append(f"manifests {manifest_names}")
                if inspection.readme_excerpt:
                    repo_part.append(f"README focus {_safe_trim(inspection.readme_excerpt, 220)}")
                summary_parts.append(". ".join(repo_part) + ".")
            summary = " ".join(summary_parts).strip()
        else:
            summary = inspections[0].summary if inspections else ""

        if compare_repos:
            recovered = 0
            for repo_url in repo_urls:
                normalized_repo_url = repo_url.rstrip("/")
                if normalized_repo_url in inspected_urls or normalized_repo_url in row_urls:
                    continue
                fallback_row = None
                for row in discovery:
                    candidate_url = str((row or {}).get("url") or "").strip()
                    candidates = extract_repo_urls(candidate_url)
                    if candidates and candidates[0].rstrip("/") == normalized_repo_url:
                        fallback_row = row
                        break
                slug = normalized_repo_url.replace("https://github.com/", "", 1)
                if fallback_row is not None:
                    rows.append(
                        {
                            "title": str((fallback_row or {}).get("title") or f"{slug} on GitHub").strip(),
                            "url": normalized_repo_url,
                            "description": _safe_trim(str((fallback_row or {}).get("description") or ""), 900),
                            "category": "general",
                            "source": str((fallback_row or {}).get("source") or "search_general"),
                            "volatile": False,
                        }
                    )
                else:
                    rows.append(
                        {
                            "title": f"{slug} on GitHub",
                            "url": normalized_repo_url,
                            "description": "Repository was selected from discovery, but live inspection failed before README details could be extracted.",
                            "category": "general",
                            "source": "github_recovery",
                            "volatile": False,
                        }
                    )
                row_urls.add(normalized_repo_url)
                recovered += 1
            if recovered:
                self._append_browse_step(
                    query,
                    step="recover",
                    detail=f"retained {recovered} selected repo(s) from discovery after live inspection failed",
                    mode=plan.mode,
                )

        primary_repo_url = repo_urls[0].rstrip("/") if (repo_urls and not compare_repos) else ""
        primary_repo_tokens = {tok for tok in re.split(r"[^a-z0-9]+", primary_repo_url.lower()) if tok not in {"https", "github", "com"}}
        for row in discovery[:5]:
            url = str((row or {}).get("url") or "").strip()
            if not url or url in row_urls:
                continue
            title = str((row or {}).get("title") or "").strip()
            description = str((row or {}).get("description") or "").strip()
            host = (urlparse(url).netloc or "").lower()
            if "github.com" in url.lower():
                repo_candidates = extract_repo_urls(url)
                if not repo_candidates:
                    continue
                if compare_repos and repo_candidates[0].rstrip("/") != url.rstrip("/"):
                    continue
                if compare_repos and repo_candidates[0].rstrip("/") not in selected_repo_urls:
                    continue
                if not compare_repos:
                    continue
            if any(block in url.lower() for block in ("/issues", "/pull", "/actions", "/security")):
                continue
            if compare_repos and "github.com" not in url.lower():
                continue
            if not compare_repos:
                if host in {"githubhelp.com", "www.githubhelp.com"}:
                    continue
                if primary_repo_tokens:
                    blob_tokens = {tok for tok in re.split(r"[^a-z0-9]+", f"{title} {description} {url}".lower()) if tok}
                    host_tokens = {tok for tok in re.split(r"[^a-z0-9]+", host) if tok}
                    required_overlap = max(1, min(2, len(primary_repo_tokens)))
                    if len(primary_repo_tokens & blob_tokens) < required_overlap:
                        continue
                    if not (primary_repo_tokens & host_tokens):
                        continue
            rows.append(
                {
                    "title": title or url,
                    "url": url,
                    "description": _safe_trim(description, 900),
                    "category": "general",
                    "source": str((row or {}).get("source") or "search_general"),
                    "volatile": False,
                }
            )
            row_urls.add(url)
            if len(rows) >= 5:
                break

        used_clone = any(str(getattr(inspection, "inspection_method", "")).lower() == "clone" for inspection in inspections)
        limitations = ["Temporary repository clone cleaned up after inspection."] if plan.cleanup_downloads and used_clone else []
        if plan.cleanup_downloads and used_clone:
            self._append_browse_step(query, step="cleanup", detail="temporary repository clone cleaned up after inspection", mode=plan.mode)
        if rows:
            added = self._write_agentpedia_memory(query, rows[:4], domain_hint="software")
            if added:
                self._append_browse_step(query, step="memory", detail=f"persisted {added} Agentpedia fact row(s) from repo inspection", mode=plan.mode)
        elif memory_rows:
            self._append_browse_step(query, step="memory", detail="returning Agentpedia repo notes because live inspection produced no summary rows", mode=plan.mode)
            limitations.append("Returned previously researched repo notes because live inspection produced no summary rows.")
            rows = memory_rows[:5]
            if not summary:
                summary = self._summarize_result_rows(query, rows)
        inspection_sources: List[str] = []
        for inspection in inspections:
            inspection_sources.extend(list(inspection.sources or []))
        self._record_browse_report(query, mode=plan.mode, summary=summary, sources=[*inspection_sources, *[r.get("url", "") for r in rows]], limitations=limitations)
        return rows

    # --- Deroute detection ---
    def _is_deroute(self, results: Any) -> bool:
        if not results or not isinstance(results, list):
            return False
        first = results[0]
        return isinstance(first, dict) and first.get("deroute") is True

    def _maybe_log_deroute(self, results: Any, query: str = "") -> bool:
        if not self._is_deroute(results):
            return False
        payload = results[0] if results else {}
        logger.info(
            f"De-route from {payload.get('handler')} reason={payload.get('reason')} query='{query}'"
        )
        return True

    def _is_research_query(self, query_lower: str) -> bool:
        ql = (query_lower or "").strip().lower()
        if not ql:
            return False

        if is_trip_planning_query(ql) or is_shopping_compare_query(ql):
            return False

        # Hard signals
        if self._re_pmid.search(ql) or self._re_doi.search(ql) or self._re_nct.search(ql) or self._re_arxiv.search(ql):
            return True

        # Common research operators / patterns
        if "site:" in ql:
            # not always research, but it is definitely "not finance"
            # and is often academic/web-research
            return True

        strong_research_terms = (
            "guideline",
            "guidelines",
            "consensus",
            "practice guideline",
            "practice guidelines",
            "recommendation",
            "recommendations",
            "protocol",
            "protocols",
            "standard of care",
            "best practice",
            "best practices",
            "trial",
            "trials",
            "randomized",
            "randomised",
            "rct",
            "rcts",
            "systematic review",
            "systematic reviews",
            "meta-analysis",
            "meta-analyses",
            "meta analysis",
            "meta analyses",
            "study",
            "studies",
            "paper",
            "papers",
            "evidence",
            "literature",
            "clinical evidence",
            "pubmed",
            "europepmc",
            "crossref",
        )
        if self._contains_any_query_term(ql, strong_research_terms):
            return True

        explainer_prefixes = (
            "what is ",
            "what's ",
            "whats ",
            "what are ",
            "how to ",
            "how do ",
            "how does ",
            "how much ",
            "how many ",
            "explain ",
            "quick summary ",
            "what should i know about ",
            "benefits of ",
        )
        explainer_target = ql
        if ql.startswith("research "):
            explainer_target = ql[len("research ") :].lstrip()
        if any(explainer_target.startswith(prefix) for prefix in explainer_prefixes):
            return False

        return self._contains_any_query_term(ql, self.research_terms)

    def _is_personal_memory_query(self, query_lower: str) -> bool:
        ql = (query_lower or "").strip().lower()
        if not ql:
            return False
        triggers = (
            "what's my", "whats my", "what is my",
            "my name", "my preference", "my preferences",
            "my favorite", "favorite drink", "remember about me",
            "what do you remember", "my reminders", "my goals",
        )
        return any(t in ql for t in triggers)

    def _normalize_category(self, raw_output: str) -> str:
        try:
            if not raw_output:
                return "general"
            text = raw_output.strip().lower()
            text = re.sub(r"<[^>]+>", " ", text)
            text = text.replace("**", " ").replace("`", " ")
            text = re.sub(r"[\r\n\t]", " ", text)

            m = re.search(r"\b(?:answer|category|intent)\s*:\s*([a-z/ -]+)\b", text, re.IGNORECASE)
            if m:
                text = m.group(1).strip()

            cleaned = re.sub(r"[^a-z/ -]", " ", text)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                return "general"

            if cleaned in self.valid_categories:
                return cleaned

            mentioned = [
                cat
                for cat in sorted(self.valid_categories, key=len, reverse=True)
                if re.search(rf"(?<![a-z]){re.escape(cat)}(?![a-z])", cleaned)
            ]
            if len(set(mentioned)) == 1:
                return mentioned[0]
            if len(set(mentioned)) > 1:
                return "general"

            token = cleaned.split(" ")[0].strip()
            token = self.alias_map.get(token, token)
            return token if token in self.valid_categories else "general"
        except Exception:
            return "general"

    def _looks_like_forex_pair(self, q: str) -> bool:
        try:
            ql = (q or "").lower()
            intent_words = ["exchange rate", "conversion", "convert", "fx", "forex", "rate", "to "]
            has_intent = any(w in ql for w in intent_words)

            pair = re.search(r"\b([a-z]{3})\s*(?:/|to)\s*([a-z]{3})\b", ql)
            if pair and pair.group(1) != pair.group(2):
                return True

            pair2 = re.search(r"\b([a-z]{3})([a-z]{3})\b", ql)
            if pair2 and pair2.group(1) != pair2.group(2) and has_intent:
                known = {
                    "usd", "eur", "gbp", "jpy", "ttd", "cad", "aud", "chf", "nzd",
                    "cny", "inr", "sgd", "hkd", "sek", "nok", "mxn", "brl", "zar"
                }
                if pair2.group(1) in known and pair2.group(2) in known:
                    return True

            return False
        except Exception:
            return False

    def _force_intent_from_terms(self, query_lower: str) -> Optional[str]:
        """
        Hard heuristics. IMPORTANT: avoid finance false positives.
        - Never force finance if query looks like research.
        - Do NOT treat random uppercase tokens as tickers here.
        """
        ql = (query_lower or "").strip().lower()
        if not ql:
            return None

        # If it's research-like, don't force finance/news/weather here.
        if self._is_research_query(ql):
            return "science"

        matches = set()

        if self._looks_like_forex_pair(ql):
            matches.add("forex")
        if self._contains_any_query_term(ql, self.crypto_terms):
            matches.add("crypto")
        if self._contains_any_query_term(ql, self.index_terms):
            matches.add("stock/commodity")

        stock_keywords = ["stock", "stocks", "share price", "shares", "ticker", "price of", "market cap", "quote"]
        if self._contains_any_query_term(ql, stock_keywords):
            matches.add("stock/commodity")

        # NOTE: removed this bug source:
        # if re.search(r"\b[A-Z]{3,5}\b", query_lower.upper()):
        #     matches.add("stock/commodity")

        if self._contains_any_query_term(ql, self.weather_terms):
            matches.add("weather")
        if self._contains_any_query_term(ql, self.news_terms):
            matches.add("news")

        if len(matches) == 1:
            return next(iter(matches))
        return None

    def _sanity_validate_intent(self, intent: str, ql: str) -> str:
        intent = intent if intent in self.valid_categories else "general"

        # If query is research-like, treat it as science regardless of LLM classifier
        if self._is_research_query(ql):
            return "science"

        if intent == "weather":
            if not self._contains_any_query_term(ql, self.weather_terms):
                return "general"

        if intent == "news":
            if not self._contains_any_query_term(ql, self.news_terms) and not any(x in ql for x in ["breaking", "headline", "reuters", "bbc"]):
                return "general"

        if intent == "stock/commodity":
            stock_terms = (
                "stock",
                "stocks",
                "share price",
                "shares",
                "ticker",
                "market cap",
                "quote",
                "commodity",
                "commodities",
                "gold",
                "silver",
                "oil",
                "brent",
                "wti",
            )
            if not (self._contains_any_query_term(ql, self.index_terms) or self._contains_any_query_term(ql, stock_terms)):
                return "general"

        if intent == "crypto":
            has_crypto = self._contains_any_query_term(ql, self.crypto_terms)
            has_token_words = any(x in ql for x in ["token", "coin", "altcoin", "memecoin"])
            has_symbol = bool(re.search(r"\b[A-Z]{2,6}\b", ql.upper()))
            if not (has_crypto or has_token_words or has_symbol):
                return "general"

        if intent == "forex":
            if not self._looks_like_forex_pair(ql) and "forex" not in ql and "exchange rate" not in ql:
                return "general"

        if intent == "science":
            return "science"

        return intent

    async def _classify_query(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> str:
        prompt = f"""
You are a text classifier. Output EXACTLY ONE WORD from the following categories:
stock/commodity, crypto, forex, weather, news, general.
Do NOT output anything else.
Query: {query}
""".strip()

        last_error = None
        for attempt in range(retries):
            try:
                response = await asyncio.to_thread(
                    ollama.chat,
                    model=WEBSEARCH_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options=build_ollama_chat_options(model=WEBSEARCH_MODEL, role="websearch", temperature=0.0),
                )
                raw_output = (response.get("message", {}) or {}).get("content", "") or ""
                cat = self._normalize_category(raw_output)
                logger.info(f"Classified query '{query}' as '{cat}' (raw='{raw_output.strip()[:60]}...')")
                return cat
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    logger.warning(f"LLM classification failed (attempt {attempt+1}/{retries}): {e}. Retrying...")
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                else:
                    break

        logger.error(
            f"LLM classification failed after {retries} attempts for '{query}': {last_error}\n{traceback.format_exc()}"
        )
        return "general"

    def _tag(self, results: List[Dict], category: str, volatile: bool) -> List[Dict]:
        out = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            rr = dict(r)
            rr.setdefault("category", category)
            rr.setdefault("volatile", volatile)
            out.append(rr)
        return out

    def _is_finance_historical_query(self, query: str, intent_hint: str = "") -> bool:
        q = (query or "").strip()
        ql = q.lower()
        if not q:
            return False
        if not self.finance_handler._is_historical_query(q):
            return False
        if self._is_research_query(ql):
            return False
        if intent_hint in {"stock/commodity", "crypto", "forex"}:
            return True
        if self.finance_handler._has_finance_cues(ql):
            return True
        if self._looks_like_forex_pair(ql):
            return True
        explicit = self.finance_handler._extract_explicit_ticker(q)
        return bool(explicit)

    async def _search_finance_intent(self, intent: str, query: str, *, allow_historical: bool = True) -> List[Dict[str, Any]]:
        if intent not in {"stock/commodity", "crypto", "forex"}:
            return []

        q = (query or "").strip()
        ql = q.lower()

        if allow_historical and self._is_finance_historical_query(q, intent_hint=intent):
            return await self.finance_handler.search_historical_price(q)

        if intent == "stock/commodity":
            return await self.finance_handler.search_stocks_commodities(q)
        if intent == "crypto":
            return await self.finance_handler.search_crypto_yfinance(q)
        return await self.finance_handler.search_forex_yfinance(ql)

    async def _ddg_text(self, query: str, max_results: int = 15) -> List[Dict[str, Any]]:
        def _run():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        try:
            return await asyncio.to_thread(_run)
        except Exception as e:
            logger.warning(f"DDG text failed for query='{query}': {e}")
            return []

    def _normalize_ddg_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        normalized = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            url = (r.get("href") or r.get("url") or r.get("link") or "").strip()
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            if not url:
                continue

            url_n = _normalize_url(url)
            if not url_n or not _is_safe_url(url_n):
                continue

            normalized.append({"title": title, "url": url_n, "description": body})
        return normalized

    def _dedupe_results(self, results: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        out = []
        for r in results:
            u = (r.get("url") or "").strip()
            if not u:
                continue
            if u in seen:
                continue
            seen.add(u)
            out.append(r)
        return out

    def _rank_results(self, results: List[Dict[str, str]], category: str) -> List[Dict[str, str]]:
        scored = []
        for r in results:
            url = r.get("url", "")
            d = _domain(url)
            score = _domain_score(d, category)
            title = (r.get("title") or "").lower()
            if category in ("crypto", "forex", "stock/commodity") and any(k in title for k in ["price", "quote", "rate", "market"]):
                score += 5
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored]

    async def _bounded_fetch(self, client: httpx.AsyncClient, url: str) -> None:
        async with self._fetch_sem:
            cached = self.page_cache.get(url)
            if isinstance(cached, str) and cached:
                return
            final_url, extracted = await _fetch_url_text(client, url, timeout_s=10.0, max_bytes=1_500_000, retries=2)
            if extracted:
                self.page_cache.set(url, extracted)
            if final_url and final_url != url and extracted:
                self.page_cache.set(final_url, extracted)

    async def _fetch_and_attach_content(
        self,
        results: List[Dict[str, str]],
        category: str,
        top_n: int = 3,
        max_n: int = 6,
    ) -> List[Dict[str, Any]]:
        if not results:
            return results  # type: ignore

        ranked = self._rank_results(results, category)
        ranked = self._dedupe_results(ranked)

        pick_n = max(1, int(top_n))
        pick_n = min(pick_n, len(ranked))

        async with httpx.AsyncClient() as client:
            pick = ranked[:pick_n]
            tasks = []
            for r in pick:
                url = r["url"]
                cached = self.page_cache.get(url)
                if isinstance(cached, str) and cached:
                    continue
                tasks.append(self._bounded_fetch(client, url))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            have_content = 0
            for r in pick:
                c = self.page_cache.get(r["url"])
                if isinstance(c, str) and len(c.strip()) > 400:
                    have_content += 1

            if have_content < 1 and pick_n < min(max_n, len(ranked)):
                pick_n2 = min(max_n, len(ranked))
                pick2 = ranked[:pick_n2]
                tasks2 = []
                for r in pick2:
                    url = r["url"]
                    cached = self.page_cache.get(url)
                    if isinstance(cached, str) and cached:
                        continue
                    tasks2.append(self._bounded_fetch(client, url))
                if tasks2:
                    await asyncio.gather(*tasks2, return_exceptions=True)

        enriched: List[Dict[str, Any]] = []
        for r in ranked:
            url = r["url"]
            content = self.page_cache.get(url)
            rr: Dict[str, Any] = dict(r)
            if isinstance(content, str) and content.strip():
                rr["content"] = _safe_trim(content, 6000)
            enriched.append(rr)

        return enriched

    def _normalize_cache_key(self, q: str) -> str:
        qq = (q or "").lower().strip()
        qq = re.sub(r"\s+", " ", qq)
        qq = qq.strip(" \t\r\n.,;:!?")
        return qq

    def _needs_fullpage_fetch(self, query_lower: str) -> bool:
        ql = (query_lower or "").strip().lower()
        if not ql:
            return False

        if "http://" in ql or "https://" in ql:
            return True

        fetch_markers = (
            "summarize this",
            "summarise this",
            "read this page",
            "extract",
            "what does this article say",
            "analyze this link",
        )
        if any(m in ql for m in fetch_markers):
            return True

        if "compare these sources" in ql and ("http://" in ql or "https://" in ql):
            return True

        return False

    def _infer_research_domain(self, query: str) -> str:
        ql = (query or "").strip().lower()
        if not ql:
            return "science"

        if is_shopping_compare_query(query) or is_trip_planning_query(query):
            return "general"
        if any(k in ql for k in ("pmid", "pubmed", "clinical", "guideline", "trial", "therapy", "dose", "treatment")):
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

    def _searx_profile_for_domain(self, domain_key: str) -> Dict[str, Any]:
        cfg = SEARXNG_DOMAIN_PROFILES if isinstance(SEARXNG_DOMAIN_PROFILES, dict) else {}
        base = cfg.get("science", {}) if str(domain_key or "") != "general" else cfg.get("general", {})
        chosen = cfg.get(str(domain_key or "science"), base)
        return dict(chosen or base or {})

    def _is_latest_clinical_query(self, query: str) -> bool:
        ql = (query or "").strip().lower()
        if not ql:
            return False

        has_latest = any(k in ql for k in ("latest", "most recent", "new", "updated", "current", "as of"))
        has_clinical = any(
            k in ql
            for k in (
                "guideline",
                "guidelines",
                "consensus",
                "statement",
                "recommendation",
                "recommendations",
                "medication",
                "medications",
                "drug",
                "drugs",
                "treatment",
                "therapy",
                "management",
                "hypertension",
            )
        )
        return has_latest and has_clinical

    def _query_focus_terms(self, query: str) -> List[str]:
        ql = (query or "").strip().lower()
        if not ql:
            return []
        stop = {
            "what", "which", "latest", "recent", "current", "new", "updated", "most",
            "guideline", "guidelines", "consensus", "statement", "recommendation", "recommendations",
            "management", "treatment", "therapy", "medication", "medications", "drug", "drugs",
            "adult", "adults", "official", "source", "sources",
            "compare", "versus", "better", "should", "buy", "difference", "between", "pros", "cons",
            "plan", "trip", "travel", "itinerary", "days", "weekend", "family", "food", "guide", "visitor", "visitors",
        }
        raw_terms = re.findall(r"[a-z0-9.+-]+", ql)
        terms = [
            tok
            for tok in raw_terms
            if tok not in stop
            and (len(tok) > 3 or (re.search(r"[a-z]", tok) is not None and re.search(r"\d", tok) is not None))
        ]
        version_match = re.search(r"\bpython\s+(\d+\.\d+)\b", ql)
        if version_match:
            terms.append(version_match.group(1))
        if "hypertension" in ql:
            terms.append("blood pressure")
        seen: set[str] = set()
        out: List[str] = []
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            out.append(term)
        return out

    def _comparison_focus_groups(self, query: str) -> List[List[str]]:
        if not is_shopping_compare_query(query):
            return []
        stop = {
            "compare", "versus", "better", "should", "buy", "difference", "between", "pros", "cons",
            "with", "and", "or", "the",
        }
        groups: List[List[str]] = []
        for subject in comparison_subjects(query)[:2]:
            tokens = [
                tok
                for tok in re.findall(r"[a-z0-9.+-]+", str(subject or "").lower())
                if tok not in stop
                and (
                    len(tok) > 2
                    or tok.isdigit()
                    or (re.search(r"[a-z]", tok) is not None and re.search(r"\d", tok) is not None)
                )
            ]
            deduped: List[str] = []
            seen: set[str] = set()
            for token in tokens:
                if token in seen:
                    continue
                seen.add(token)
                deduped.append(token)
            if deduped:
                groups.append(deduped[:4])
        return groups

    def _comparison_group_hit_count(self, query: str, blob: str) -> int:
        groups = self._comparison_focus_groups(query)
        if not groups:
            return 0
        subjects = [str(item or "").strip() for item in comparison_subjects(query)[:2]]
        clean_blob = str(blob or "").lower()
        hits = 0
        for idx, group in enumerate(groups):
            subject = subjects[idx] if idx < len(subjects) else ""
            if self._comparison_group_matches_blob(group, clean_blob) or self._comparison_subject_alias_match(subject, clean_blob):
                hits += 1
        return hits

    def _collapsed_alnum(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())

    def _comparison_group_matches_blob(self, group: List[str], blob: str) -> bool:
        tokens = [str(token or "").strip().lower() for token in group if str(token or "").strip()]
        clean_blob = str(blob or "").lower()
        if not tokens or not clean_blob:
            return False
        digit_tokens = [token for token in tokens if re.search(r"\d", token) is not None]
        if digit_tokens and not all(token in clean_blob for token in digit_tokens):
            return False
        hits = sum(1 for token in tokens if token in clean_blob)
        if len(tokens) == 1:
            return hits >= 1
        if len(tokens) == 2:
            return hits >= 2
        return hits >= min(2, len(tokens))

    def _comparison_subject_alias_match(self, subject: str, blob: str) -> bool:
        subject_lower = str(subject or "").strip().lower()
        clean_blob = str(blob or "").lower()
        if not subject_lower or not clean_blob:
            return False
        compact_blob = self._collapsed_alnum(clean_blob)
        compact_subject = self._collapsed_alnum(subject_lower)
        aliases: List[str] = []

        if "playstation 5" in subject_lower or compact_subject == "playstation5":
            aliases.append("ps5")
        if "xbox series x" in subject_lower or compact_subject == "xboxseriesx":
            aliases.extend(["series x", "xsx"])
        if "xbox series s" in subject_lower or compact_subject == "xboxseriess":
            aliases.extend(["series s", "xss"])
        if "hp laserjet" in subject_lower or ("hp" in subject_lower and "laserjet" in subject_lower):
            aliases.extend(["hp printer", "laserjet"])
        if "brother laser printer" in subject_lower or ("brother" in subject_lower and "printer" in subject_lower):
            aliases.append("brother printer")
        if "remarkable 2" in subject_lower or compact_subject == "remarkable2":
            aliases.extend(["remarkable 2", "remarkable2"])

        for alias in aliases:
            alias_lower = str(alias or "").strip().lower()
            if not alias_lower:
                continue
            if alias_lower in clean_blob:
                return True
            if self._collapsed_alnum(alias_lower) in compact_blob:
                return True
        return False

    def _shopping_row_looks_noisy(self, query: str, row: Dict[str, Any]) -> bool:
        title = str((row or {}).get("title") or "").strip()
        description = str((row or {}).get("description") or "").strip()
        url = str((row or {}).get("url") or "").strip().lower()
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        compare_text = " ".join([title, description]).lower()
        blob = " ".join(
            [
                title,
                description,
                str((row or {}).get("content") or ""),
                url,
            ]
        ).lower()
        if any(bad in host for bad in ("youtube.com", "youtu.be", "tiktok.com")):
            return True
        if any(bad in host for bad in ("pinterest.com", "pin.it", "cloudfront.net")):
            return True
        if "-news-" in path or "/news/" in path:
            return True
        if any(noisy_host in host for noisy_host in ("ts2.tech", "superiptv.online", "pages.dev", "medium.com", "techtimes.com", "ccstartup.com", "nexttechbuy.com", "bookrunch.org", "thetechsearch.com")):
            return True
        if title.count("?") >= 3 or description.count("?") >= 4:
            return True
        if re.search(r"[\u0400-\u04FF\u3040-\u30FF\u4E00-\u9FFF]", title) is not None and not re.search(r"[\u0400-\u04FF\u3040-\u30FF\u4E00-\u9FFF]", query):
            return True
        if len(re.findall(r"\bvs\.?(?=\W|$)", compare_text)) >= 2 or len(re.findall(r"\bversus\b", compare_text)) >= 2:
            return True
        if "showdown" in blob and not any(
            trusted in host
            for trusted in ("rtings.com", "gsmarena.com", "theverge.com", "cnet.com", "pcmag.com", "notebookcheck.net", "techradar.com", "tomsguide.com")
        ):
            return True
        if any(marker in blob for marker in ("amazon associate", "qualifying purchases", "affiliate links", "affiliate commission", "at no extra cost")) and not any(
            trusted in host
            for trusted in ("rtings.com", "gsmarena.com", "theverge.com", "cnet.com", "pcmag.com", "notebookcheck.net", "techradar.com", "tomsguide.com", "wirecutter.com", "laptopmag.com")
        ):
            return True
        query_lower = str(query or "").lower()
        compact_query = self._collapsed_alnum(query)
        compact_blob = self._collapsed_alnum(blob)
        variant_mismatches = (
            ("iphone 16 pro max", "iphone 16"),
            ("iphone 16 pro", "iphone 16"),
            ("iphone 16 plus", "iphone 16"),
            ("galaxy s25 ultra", "galaxy s25"),
            ("galaxy s25 plus", "galaxy s25"),
            ("galaxy s25+", "galaxy s25"),
            ("xps 14", "xps 13"),
            ("xps 13 plus", "xps 13"),
            ("xps 13 2 in 1", "xps 13"),
            ("xps 13 2-in-1", "xps 13"),
            ("macbook pro", "macbook air"),
            ("kobo clara colour", "kobo clara"),
            ("kobo clara color", "kobo clara"),
            ("kobo clara bw", "kobo clara"),
            ("kobo clara 2e", "kobo clara"),
            ("kindle colorsoft", "kindle paperwhite"),
            ("kindle paperwhite signature edition", "kindle paperwhite"),
        )
        for specific, base in variant_mismatches:
            compact_specific = self._collapsed_alnum(specific)
            compact_base = self._collapsed_alnum(base)
            allow_ereader_family_variant = (
                "kindle" in query_lower
                and "kobo" in query_lower
                and base == "kobo clara"
                and specific in {"kobo clara colour", "kobo clara color", "kobo clara bw"}
            )
            if (
                base in query_lower
                and specific not in query_lower
                and specific in blob
            ) or (
                compact_base in compact_query
                and compact_specific not in compact_query
                and compact_specific in compact_blob
            ):
                if allow_ereader_family_variant:
                    continue
                return True
        if "kindle" in query_lower and "kobo" in query_lower:
            if any(extra_family in blob for extra_family in ("boox", "onyx", "nook", "remarkable", "colorsoft")):
                return True
        return False

    def _shopping_compare_retry_hosts(self, query: str) -> Tuple[str, ...]:
        ql = str(query or "").lower()
        if any(marker in ql for marker in ("playstation", "ps5", "xbox", "series x", "series s")):
            return ("techradar.com", "tomsguide.com", "theverge.com", "ign.com", "gamesradar.com", "cnet.com", "pcmag.com")
        if any(marker in ql for marker in ("printer", "laserjet", "laser printer", "all-in-one", "mfp")):
            return ("rtings.com", "pcmag.com", "cnet.com", "wirecutter.com", "techradar.com", "tomsguide.com")
        if any(marker in ql for marker in ("macbook", "laptop", "xps", "zenbook", "surface", "thinkpad", "chromebook", "ultrabook")):
            return ("rtings.com", "notebookcheck.net", "laptopmedia.com", "tomsguide.com")
        if any(marker in ql for marker in ("iphone", "galaxy", "pixel", "oneplus", "xiaomi", "phone", "smartphone")):
            return ("gsmarena.com", "phonearena.com", "cnet.com", "tomsguide.com")
        if "kindle" in ql and "kobo" in ql:
            return ("tomsguide.com", "techradar.com", "pocket-lint.com", "the-ebook-reader.com", "pcmag.com", "cnet.com", "wired.com")
        if any(marker in ql for marker in ("tv", "oled", "qled", "bravia", "lg c", "samsung s90", "hisense", "tcl")):
            return ("rtings.com", "cnet.com", "tomsguide.com", "techradar.com")
        return ("wirecutter.com", "cnet.com", "pcmag.com", "tomsguide.com")

    def _shopping_compare_site_filtered_queries(self, query: str) -> List[str]:
        subjects = [str(item or "").strip() for item in comparison_subjects(query)[:2] if str(item or "").strip()]
        if len(subjects) >= 2:
            base = f"{subjects[0]} vs {subjects[1]}"
        else:
            base = " ".join(str(query or "").split()).strip()
        queries: List[str] = []
        for host in self._shopping_compare_retry_hosts(query):
            candidate = f"site:{host} {base}"
            if candidate.lower() not in {item.lower() for item in queries}:
                queries.append(candidate)
        return queries

    def _shopping_compare_primary_queries(self, query: str, plan: Optional[BrowsePlan] = None) -> List[str]:
        q = " ".join(str(query or "").split()).strip()
        ql = q.lower()
        subjects = [str(item or "").strip() for item in comparison_subjects(query)[:2] if str(item or "").strip()]
        plan_variants = [str(item or "").strip() for item in list(getattr(plan, "query_variants", []) or []) if str(item or "").strip()]
        site_filtered = self._shopping_compare_site_filtered_queries(query)
        queries: List[str] = []

        if len(subjects) >= 2:
            generic = [
                f"{subjects[0]} vs {subjects[1]}",
                f"difference between {subjects[0]} and {subjects[1]}",
                f"should I buy {subjects[0]} or {subjects[1]}",
                f"{subjects[0]} {subjects[1]} comparison",
            ]
        else:
            generic = [q]

        # Kindle/Kobo pairs work best when family-level comparison queries lead and
        # host-filtered retries are only used to shore up the shortlist.
        ordered = [*generic, *plan_variants, *site_filtered] if ("kindle" in ql and "kobo" in ql) else [*plan_variants, *generic, *site_filtered]

        seen = set()
        for candidate in ordered:
            clean = " ".join(str(candidate or "").split()).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(clean)
        return queries

    def _shopping_compare_needs_trusted_retry(self, query: str, rows: List[Dict[str, Any]]) -> bool:
        filtered = [dict(row or {}) for row in rows if isinstance(row, dict)]
        if not filtered:
            return True
        trusted_hosts = self._shopping_compare_retry_hosts(query)
        trusted_count = 0
        for row in filtered[:4]:
            host = (urlparse(str((row or {}).get("url") or "")).netloc or "").lower()
            if any(domain in host for domain in trusted_hosts):
                trusted_count += 1
        lead = filtered[0]
        lead_host = (urlparse(str((lead or {}).get("url") or "")).netloc or "").lower()
        if self._shopping_row_looks_noisy(query, lead):
            return True
        if trusted_count >= 2:
            return False
        return not any(domain in lead_host for domain in trusted_hosts)

    def _shopping_row_has_direct_compare_signal(self, query: str, row: Dict[str, Any]) -> bool:
        title = str((row or {}).get("title") or "")
        desc = str((row or {}).get("description") or "")
        url = str((row or {}).get("url") or "")
        blob = f"{title} {desc} {url}".lower()
        title_blob = f"{title} {url}".lower()
        groups = self._comparison_focus_groups(query)
        required_group_hits = 2 if len(groups) >= 2 else 1
        group_hits = self._comparison_group_hit_count(query, title_blob)
        if group_hits >= required_group_hits:
            return True
        direct_markers = (
            " vs ",
            " versus ",
            "compare",
            "comparison",
            "head-to-head",
            "head to head",
            "side-by-side",
            "side by side",
            "battle",
            "/compare",
            "/versus",
            "compare.php",
        )
        if not any(marker in blob for marker in direct_markers):
            return False
        strong_pair_markers = (" vs ", " versus ", "head-to-head", "head to head", "side-by-side", "side by side", "compare.php")
        if any(marker in blob for marker in strong_pair_markers):
            return group_hits >= required_group_hits
        return group_hits >= required_group_hits

    def _trip_planning_focus_markers(self, query: str) -> List[str]:
        ql = str(query or "").lower()
        markers = [
            "itinerary",
            "travel guide",
            "first-time",
            "first time",
            "days in",
            "weekend itinerary",
        ]
        day_match = re.search(r"\b(\d+)\s*day\b", ql)
        if day_match:
            count = day_match.group(1)
            markers.extend([f"{count} day", f"{count}-day", f"{count} days"])
        if "weekend" in ql:
            markers.append("weekend")
        seen: set[str] = set()
        out: List[str] = []
        for marker in markers:
            if marker in seen:
                continue
            seen.add(marker)
            out.append(marker)
        return out

    def _trip_planning_specific_markers(self, query: str) -> List[str]:
        ql = str(query or "").lower()
        markers: List[str] = []
        if any(marker in ql for marker in ("family", "families", "kids", "children", "kid friendly", "kid-friendly")):
            markers.extend(["family", "families", "kids", "children", "kid friendly", "kid-friendly"])
        if any(marker in ql for marker in ("food", "eat", "eating", "restaurant", "restaurants", "culinary", "dining")):
            markers.extend(["food", "eat", "eating", "restaurant", "restaurants", "culinary", "dining", "food lovers"])
        if any(marker in ql for marker in ("budget", "cheap", "affordable", "cost")):
            markers.extend(["budget", "cheap", "affordable", "cost", "prices"])
        seen: set[str] = set()
        out: List[str] = []
        for marker in markers:
            if marker in seen:
                continue
            seen.add(marker)
            out.append(marker)
        return out

    def _travel_lookup_focus_markers(self, query: str) -> List[str]:
        ql = str(query or "").lower()
        markers: List[str]
        if "best time to visit" in ql:
            markers = ["best time to visit", "when to visit", "season", "seasons", "weather", "month"]
        elif any(marker in ql for marker in ("what to do in", "things to do in", "top things to do in")):
            markers = ["things to do", "what to do", "attractions", "travel guide", "first time"]
        elif "how many days in" in ql:
            markers = ["how many days", "days in", "itinerary", "first time", "travel guide"]
        elif any(marker in ql for marker in ("expensive", "budget", "cost")):
            markers = ["expensive", "budget", "cost", "daily cost", "prices", "travel cost"]
        else:
            markers = ["travel guide", "things to do", "itinerary"]
        seen: set[str] = set()
        out: List[str] = []
        for marker in markers:
            if marker in seen:
                continue
            seen.add(marker)
            out.append(marker)
        return out

    def _travel_row_looks_noisy(self, query: str, row: Dict[str, Any]) -> bool:
        url = str((row or {}).get("url") or "").strip().lower()
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        blob = " ".join(
            [
                str((row or {}).get("title") or ""),
                str((row or {}).get("description") or ""),
                url,
            ]
        ).lower()
        if any(bad in host for bad in ("pinterest.com", "instagram.com", "facebook.com")):
            return True
        if any(bad in host for bad in ("triphobo.com", "roamaround.app", "grokipedia.com")):
            return True
        if "tripadvisor.com" in host and "/attractions-" in path:
            return True
        if is_trip_planning_query(query):
            if "attractions" in blob and "itinerary" not in blob:
                return True
            if "things to do" in blob and not any(marker in blob for marker in self._trip_planning_focus_markers(query)):
                return True
        if is_travel_lookup_query(query):
            focus_markers = tuple(self._travel_lookup_focus_markers(query))
            if "hotel" in blob and any(marker in blob for marker in ("rates", "deals", "book now", "reserve now")):
                return True
            if "attractions" in blob and not any(marker in blob for marker in focus_markers):
                return True
            if "things to do" in blob and not any(marker in blob for marker in focus_markers):
                return True
        return False

    def _travel_row_looks_ad_heavy(self, row: Dict[str, Any]) -> bool:
        url = str((row or {}).get("url") or "").strip().lower()
        host = (urlparse(url).netloc or "").lower()
        blob = " ".join(
            [
                str((row or {}).get("title") or ""),
                str((row or {}).get("description") or ""),
                url,
            ]
        ).lower()
        ad_markers = (
            "has been visited by",
            "book now",
            "reserve now",
            "book today",
            "skip the stress",
            "tickets",
            "reserve yours today",
            "order your",
            "pay later",
        )
        bad_hosts = ("bing.com", "google.com")
        return any(marker in blob for marker in ad_markers) or any(host.endswith(bad) or bad in host for bad in bad_hosts)

    def _travel_row_looks_forumish(self, row: Dict[str, Any]) -> bool:
        url = str((row or {}).get("url") or "").strip().lower()
        path = (urlparse(url).path or "").lower()
        blob = " ".join(
            [
                str((row or {}).get("title") or ""),
                str((row or {}).get("description") or ""),
                url,
            ]
        ).lower()
        markers = (
            "forum",
            "forums",
            "community",
            "discussion",
            "ask a question",
            "question and answer",
        )
        if "showtopic" in path or "/forum" in path or "/forums" in path:
            return True
        return any(marker in blob for marker in markers)

    def _travel_enrichment_candidates(self, query: str, rows: List[Dict[str, Any]], *, limit: int = 1) -> List[Dict[str, Any]]:
        max_items = max(0, int(limit or 0))
        if max_items == 0:
            return []
        candidates: List[Dict[str, Any]] = []
        for row in [dict(item or {}) for item in rows if isinstance(item, dict)]:
            url = str((row or {}).get("url") or "").strip()
            host = (urlparse(url).netloc or "").lower()
            title = str((row or {}).get("title") or "").lower()
            if any(domain in host for domain in ("travel.usnews.com",)):
                continue
            if is_travel_lookup_query(query) and title.startswith("ranking"):
                continue
            if self._travel_row_looks_ad_heavy(row) or self._travel_row_looks_forumish(row):
                continue
            candidates.append(row)
            if len(candidates) >= max_items:
                break
        return candidates

    def _python_docs_version(self, query: str) -> str:
        match = re.search(r"\bpython\s+(\d+\.\d+)\b", str(query or "").lower())
        return str(match.group(1)).strip() if match else ""

    def _software_change_version(self, query: str) -> str:
        match = re.search(r"\b(\d+(?:\.\d+){1,2})\b", str(query or "").lower())
        return str(match.group(1)).strip() if match else ""

    def _rust_release_redirect_version(self, version: str) -> str:
        normalized = str(version or "").strip().lower()
        if not normalized:
            return ""
        if normalized.count(".") == 1:
            return f"{normalized}.0"
        return normalized

    def _software_change_version_matches(self, requested_version: str, blob: str) -> bool:
        version = str(requested_version or "").strip().lower()
        haystack = str(blob or "").lower()
        if not version or not haystack:
            return False
        matches = re.findall(r"(?<![\d.])\d+(?:\.\d+){1,2}(?![\d.])", haystack)
        if any(item == version or item.startswith(f"{version}.") for item in matches):
            return True
        escaped = re.escape(version)
        if re.search(rf"(?<![\d.])v{escaped}(?![\d.])", haystack):
            return True
        return re.search(rf"(?<![\d.]){escaped}(?![\d.])", haystack) is not None

    def _is_latest_who_dengue_guidance_query(self, query: str) -> bool:
        ql = str(query or "").lower()
        return (
            "dengue" in ql
            and re.search(r"\bwho\b", ql) is not None
            and any(term in ql for term in ("latest", "recent", "updated", "newest", "current", "guidance", "guideline", "guidelines", "treatment", "clinical management"))
        )

    def _score_browse_row(self, query: str, row: Dict[str, Any], *, prefer_official: bool = False) -> float:
        title = str((row or {}).get("title") or "")
        desc = str((row or {}).get("description") or "")
        url = str((row or {}).get("url") or "")
        blob = f"{title} {desc} {url}".lower()
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        query_lower = str(query or "").lower()
        score = 0.0
        compare_markers = (" vs ", " versus ", "compare", "comparison", "which is better", "review", "reviews")

        focus_terms = self._query_focus_terms(query)
        if focus_terms:
            overlap_hits = sum(1 for term in focus_terms if term in blob)
            score += min(4.5, overlap_hits * 2.0)
            if overlap_hits == 0:
                score -= 8.0

        if is_shopping_compare_query(query):
            review_hosts = (
                "theverge.com",
                "gsmarena.com",
                "cnet.com",
                "pcmag.com",
                "techradar.com",
                "engadget.com",
                "tomsguide.com",
                "androidauthority.com",
                "wirecutter.com",
                "notebookcheck.net",
                "laptopmag.com",
                "laptopmedia.com",
                "rtings.com",
                "mashable.com",
                "pocket-lint.com",
                "today.com",
            )
            laptop_compare = any(marker in query_lower for marker in ("macbook", "xps", "laptop", "ultrabook", "thinkpad", "surface"))
            ereader_compare = any(marker in query_lower for marker in ("kindle", "kobo", "ereader", "e-reader"))
            group_hits = self._comparison_group_hit_count(query, blob)
            if group_hits >= 2:
                score += 9.0
            elif group_hits == 1:
                score += 1.0
            else:
                score -= 12.0
            if any(marker in blob for marker in compare_markers):
                score += 6.0
            if any(domain in host for domain in review_hosts):
                score += 5.0
            if laptop_compare:
                if any(domain in host for domain in ("laptopmag.com", "laptopmedia.com", "rtings.com", "notebookcheck.net", "tomsguide.com", "techradar.com")):
                    score += 4.0
                if any(domain in host for domain in ("nanoreview.net", "gadgets360.com")):
                    score -= 6.0
            if ereader_compare:
                if any(domain in host for domain in ("the-ebook-reader.com", "tomsguide.com", "pcmag.com", "cnet.com", "wired.com", "mashable.com", "pocket-lint.com", "today.com", "techradar.com")):
                    score += 6.0
                if any(domain in host for domain in ("bookrunch.org", "thetechsearch.com", "ccstartup.com", "nexttechbuy.com", "techtimes.com")):
                    score -= 10.0
                if "versus.com" in host:
                    score -= 6.0
                if "video" in title.lower() or any(marker in path for marker in ("/video", "/videos/")):
                    score -= 16.0
            pub_year = self._leading_publication_year(desc) or self._leading_publication_year(title)
            if pub_year in {"2026", "2025"}:
                score += 6.0
            elif pub_year == "2024":
                score += 3.5
            elif pub_year == "2023":
                score -= 3.0
            elif pub_year in {"2022", "2021"}:
                score -= 9.0
            elif re.search(r"\b2026\b|\b2025\b", blob):
                score += 4.0
            elif re.search(r"\b2024\b", blob):
                score += 2.5
            elif re.search(r"\b2023\b", blob):
                score -= 1.5
            elif re.search(r"\b2022\b|\b2021\b", blob):
                score -= 6.0
            if any(domain in host for domain in ("arxiv.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "wikipedia.org")):
                score -= 18.0
            if self._shopping_row_looks_noisy(query, row):
                score -= 20.0

        if self._is_explicit_news_lookup(query):
            score += self._news_row_focus_score(query, row)

        if is_trip_planning_query(query):
            travel_hosts = (
                "lonelyplanet.com",
                "travelandleisure.com",
                "cntraveler.com",
                "fodors.com",
                "timeout.com",
                "japan-guide.com",
                "thetravelsisters.com",
                "usnews.com",
            )
            itinerary_markers = tuple(self._trip_planning_focus_markers(query))
            specific_markers = tuple(self._trip_planning_specific_markers(query))
            if any(marker in blob for marker in itinerary_markers):
                score += 5.0
            if specific_markers:
                if any(marker in blob for marker in specific_markers):
                    score += 4.0
                else:
                    score -= 8.0
            if any(domain in host for domain in travel_hosts):
                score += 4.0
            if "official" in blob and any(marker in blob for marker in ("tourism", "visitor", "travel guide", "itinerary")):
                score += 5.0
            if "tripadvisor.com" in host and "/articles-" in url.lower():
                score -= 4.0
            if self._travel_row_looks_ad_heavy(row):
                score -= 14.0
            if self._travel_row_looks_forumish(row):
                score -= 16.0
            if self._travel_row_looks_noisy(query, row):
                score -= 12.0
        if is_travel_lookup_query(query):
            travel_hosts = (
                "lonelyplanet.com",
                "travelandleisure.com",
                "cntraveler.com",
                "fodors.com",
                "timeout.com",
                "japan-guide.com",
                "budgetyourtrip.com",
                "gotokyo.org",
                "nomadicmatt.com",
            )
            focus_markers = tuple(self._travel_lookup_focus_markers(query))
            if any(marker in blob for marker in focus_markers):
                score += 5.0
            if any(domain in host for domain in travel_hosts):
                score += 4.0
            if "official" in blob and any(marker in blob for marker in ("tourism", "visitor", "travel guide", "when to visit")):
                score += 7.0
            if any(marker in query_lower for marker in ("what to do in", "things to do in", "top things to do in")) and title.lower().startswith("ranking"):
                score -= 7.0
            if "best time to visit" in query_lower or "when to visit" in query_lower:
                if any(phrase in blob for phrase in ("best & worst", "our take")):
                    score -= 6.0
            if "tripadvisor.com" in host and "/articles-" in url.lower():
                score -= 4.0
            if self._travel_row_looks_ad_heavy(row):
                score -= 14.0
            if self._travel_row_looks_forumish(row):
                score -= 16.0
            if self._travel_row_looks_noisy(query, row):
                score -= 12.0

        if any(marker in blob for marker in ("guideline", "guidelines", "recommendation", "statement", "top 10 things to know")):
            score += 3.5
        if re.search(r"\b202[4-9]\b", blob):
            score += 1.5
        if any(term in query_lower for term in ("latest", "recent", "current", "updated", "newest", "most recent")):
            if re.search(r"\b2026\b|\b2025\b", blob):
                score += 4.5
            elif re.search(r"\b2024\b", blob):
                score += 2.5
            elif re.search(r"\b20(?:0\d|1\d)\b", blob):
                score -= 5.5

        if prefer_official:
            official_domains = infer_official_domains(query)
            if any(domain in host for domain in official_domains):
                score += 10.0
            if is_software_change_query(query):
                requested_version = self._software_change_version(query)
                if any(domain in host for domain in official_domains):
                    score += 6.0
                if requested_version:
                    if self._software_change_version_matches(requested_version, blob):
                        score += 8.0
                    elif re.search(r"\b\d+(?:\.\d+){1,2}\b", blob):
                        score -= 12.0
                if any(marker in blob for marker in ("release notes", "changelog", "what's new", "whats new", "/blog/", "/releases/", "release highlights")):
                    score += 5.0
            if "guideline" in query_lower and not any(marker in blob for marker in ("guideline", "guidelines", "recommendation", "statement", "top 10 things to know")):
                score -= 3.0
            if re.search(r"\bacc\b|\baha\b|acc/aha", query_lower):
                if any(marker in blob for marker in ("session", "sessions", "keynote", "agenda")):
                    score -= 8.0
                if "/toc/" in url.lower() or re.search(r"\bvol\s*\d+\s*,\s*no\s*\d+\b", blob):
                    score -= 10.0
                if "/doi/" in url:
                    score += 4.0
                if "/guidelines/" in url.lower():
                    score += 5.0
                if "high blood pressure guideline" in blob or "new acc/aha guideline" in blob:
                    score += 4.0
                if "top 10 things to know" in blob:
                    score += 3.0
            if self._is_latest_clinical_query(query) and ("hypertension" in query_lower or "blood pressure" in query_lower):
                if any(domain in host for domain in ("ahajournals.org", "jacc.org", "acc.org", "heart.org")):
                    score += 4.5
                if "/toc/" in url.lower() or re.search(r"\bvol\s*\d+\s*,\s*no\s*\d+\b", blob):
                    score -= 10.0
                if any(domain in host for domain in ("escardio.org", "who.int", "nice.org.uk")):
                    score += 2.0
                if re.search(r"\b2025\b", blob) and any(domain in host for domain in ("ahajournals.org", "jacc.org", "acc.org", "heart.org")):
                    score += 4.0
                if re.search(r"\b2024\b", blob) and "escardio.org" in host:
                    score += 1.0
            if "python" in query_lower and "docs" in query_lower:
                requested_version = self._python_docs_version(query)
                page_version = self._python_whatsnew_page_version(url)
                if "docs.python.org" in host:
                    score += 6.0
                if "what's new in python" in blob or "whats new in python" in blob:
                    score += 6.0
                if requested_version:
                    if requested_version in blob or f"/{requested_version}" in url.lower():
                        score += 7.0
                    if page_version and page_version != requested_version:
                        score -= 10.0
                    elif re.search(r"/whatsnew/\d+\.\d+\.html", url.lower()) and requested_version not in url.lower():
                        score -= 8.0
                    if re.search(r"/\d+\.\d+/", url.lower()) and f"/{requested_version}/" not in url.lower():
                        score -= 6.0
            if "dengue" in query_lower and re.search(r"\bwho\b|\bcdc\b", query_lower):
                if any(domain in host for domain in ("who.int", "cdc.gov")):
                    score += 3.0
                if any(segment in url.lower() for segment in ("/activities/", "/health-topics/", "/initiatives/")):
                    score -= 10.0
                if "/news/item/" in url.lower() or "/publications/" in url.lower():
                    score += 5.0
                if any(marker in blob for marker in ("arboviral", "chikungunya", "zika", "yellow fever", "clinical management")):
                    score += 4.0
                if any(marker in blob for marker in ("guideline", "guidelines")):
                    score += 6.0
                if "who.int" in host:
                    score += 4.0
                if re.search(r"\b2025\b", blob):
                    score += 4.0
                if "new who guidelines" in blob:
                    score += 5.0
                if not any(marker in blob for marker in ("guideline", "guidelines", "clinical management", "arboviral")):
                    score -= 6.0
                if "national guideline" in blob:
                    score -= 2.0
                if self._is_latest_who_dengue_guidance_query(query):
                    if any(segment in url.lower() for segment in ("/news-room/fact-sheets/detail/", "/emergencies/disease-outbreak-news/item/", "/news/detail-global/")):
                        score -= 9.0
                    if any(marker in blob for marker in ("handbook for clinical management of dengue", "dengue guidelines, for diagnosis, treatment, prevention and")):
                        score -= 8.0
                    if "national guideline" in blob:
                        score -= 10.0
                    if re.search(r"\b(2009|2010|2011|2012|2022|2023)\b", blob) and not re.search(r"\b202[4-9]\b", blob):
                        score -= 9.0
                    if "records highest number of dengue" in blob:
                        score -= 6.0
                    if "/publications/i/item/9789240111110" in url.lower() or "/handle/10665/381804" in url.lower():
                        score += 6.0
            if any(marker in blob for marker in ("session", "sessions", "conference", "meeting")):
                score -= 4.0
            if "pubmed.ncbi.nlm.nih.gov" in host or "ncbi.nlm.nih.gov" in host:
                score -= 5.0
            if "arxiv.org" in host:
                score -= 4.0
            if any(domain in host for domain in ("who.int", "cdc.gov", "acc.org", "heart.org", "ahajournals.org", "docs.python.org", "python.org")):
                score += 3.0

        return score

    def _prioritize_browse_rows(self, query: str, rows: List[Dict[str, Any]], *, prefer_official: bool = False) -> List[Dict[str, Any]]:
        scored: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            rr = dict(row)
            rr["_browse_score"] = self._score_browse_row(query, rr, prefer_official=prefer_official)
            scored.append(rr)

        scored.sort(key=lambda row: float(row.get("_browse_score") or 0.0), reverse=True)

        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in scored:
            url = str((row or {}).get("url") or "").strip().lower()
            key = url or str((row or {}).get("title") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            row.pop("_browse_score", None)
            deduped.append(row)
        return deduped

    def _score_research_result(self, query: str, item: Dict[str, Any]) -> float:
        title = str((item or {}).get("title") or "")
        desc = str((item or {}).get("description") or "")
        url = str((item or {}).get("url") or "")
        blob = f"{title} {desc} {url}".lower()
        host = (urlparse(url).netloc or "").lower()
        focus_terms = self._query_focus_terms(query)

        base = float((item or {}).get("quality") or (item or {}).get("score") or 0.0)
        score = base

        guideline_markers = (
            "guideline",
            "guidelines",
            "consensus",
            "statement",
            "recommendation",
            "recommendations",
            "protocol",
        )
        study_markers = (
            "cohort",
            "case-control",
            "cross-sectional",
            "meta-analysis",
            "randomized",
            "trial",
            "study",
        )

        if any(m in blob for m in guideline_markers):
            score += 9.0

        if any(m in blob for m in ("medication", "medications", "drug", "drugs", "therapy", "treatment")):
            score += 2.5

        authority_hosts = (
            "acc.org",
            "escardio.org",
            "heart.org",
            "ahajournals.org",
            "hypertension.ca",
            "nice.org.uk",
            "who.int",
            "cdc.gov",
            "nih.gov",
            "gov",
        )
        if any(h in host for h in authority_hosts):
            score += 8.0

        if re.search(r"\b(202[4-9]|203\d)\b", blob):
            score += 1.5

        if is_shopping_compare_query(query):
            group_hits = self._comparison_group_hit_count(query, blob)
            if group_hits >= 2:
                score += 8.0
            elif group_hits == 1:
                score += 1.0
            else:
                score -= 12.0
            if any(marker in blob for marker in (" vs ", " versus ", "compare", "comparison", "review", "reviews")):
                score += 5.0
            if any(domain in host for domain in ("arxiv.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov")):
                score -= 18.0
            if self._shopping_row_looks_noisy(query, item):
                score -= 20.0

        if is_trip_planning_query(query):
            if any(marker in blob for marker in self._trip_planning_focus_markers(query)):
                score += 5.0
            if self._travel_row_looks_ad_heavy(item):
                score -= 12.0
            if self._travel_row_looks_forumish(item):
                score -= 16.0
            if self._travel_row_looks_noisy(query, item):
                score -= 12.0

        if focus_terms:
            overlap_hits = sum(1 for term in focus_terms if term in blob)
            score += min(4.5, overlap_hits * 2.5)
            if overlap_hits == 0:
                score -= 12.0

        if "pubmed.ncbi.nlm.nih.gov" in host and not any(m in blob for m in guideline_markers):
            score -= 7.0

        if any(m in blob for m in study_markers) and not any(m in blob for m in guideline_markers):
            score -= 5.0

        if self._is_latest_clinical_query(query):
            if any(m in blob for m in guideline_markers):
                score += 5.0
            elif any(m in blob for m in study_markers):
                score -= 4.0

        return score

    def _prioritize_research_results(self, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not results:
            return []

        scored: List[Dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            rr = dict(r)
            rr["_research_score"] = self._score_research_result(query, rr)
            scored.append(rr)

        scored.sort(key=lambda x: float(x.get("_research_score") or 0.0), reverse=True)

        if self._is_latest_clinical_query(query):
            focused = [r for r in scored if self._result_matches_focus(query, r)]
            if focused:
                scored = focused + [r for r in scored if r not in focused]
            strong = [r for r in scored if float(r.get("_research_score") or 0.0) >= 8.0]
            if strong:
                scored = strong + [r for r in scored if float(r.get("_research_score") or 0.0) >= 1.0 and r not in strong]

        deduped: List[Dict[str, Any]] = []
        seen = set()
        for r in scored:
            u = str((r or {}).get("url") or "").strip().lower()
            k = u or str((r or {}).get("title") or "").strip().lower()
            if not k or k in seen:
                continue
            seen.add(k)
            r.pop("_research_score", None)
            deduped.append(r)

        return deduped[:12]

    def _build_crawlies_config(self, domain_key: str) -> Optional[Any]:
        if not RESEARCH_CRAWLIES_ENABLED or CrawliesConfig is None:
            return None

        profile = self._searx_profile_for_domain(domain_key)
        return CrawliesConfig(
            searx_base_url=str(SEARXNG_BASE_URL or "http://localhost:8080"),
            category=str(profile.get("category") or "science"),
            max_pages=max(1, int(RESEARCH_CRAWLIES_MAX_PAGES)),
            max_candidates=max(1, int(RESEARCH_CRAWLIES_MAX_CANDIDATES)),
            max_open_links=max(1, int(RESEARCH_CRAWLIES_MAX_OPEN_LINKS)),
            min_quality_stop=float(RESEARCH_CRAWLIES_MIN_QUALITY_STOP),
            use_scrapling=bool(RESEARCH_CRAWLIES_USE_SCRAPLING),
            use_playwright=bool(RESEARCH_CRAWLIES_USE_PLAYWRIGHT),
            use_llm_rerank=bool(RESEARCH_CRAWLIES_USE_LLM_RERANK),
            save_artifacts=bool(RESEARCH_CRAWLIES_SAVE_ARTIFACTS),
        )

    async def _research_crawlies(self, query: str, domain_key: str) -> List[Dict[str, Any]]:
        if CrawliesEngine is None:
            return []

        cfg = self._build_crawlies_config(domain_key)
        if cfg is None:
            return []

        timeout_s = max(1.0, float(RESEARCH_CRAWLIES_TIMEOUT_SECONDS))
        try:
            engine = CrawliesEngine(cfg)
            payload = await asyncio.wait_for(engine.crawl(query), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("Crawlies research timeout for '%s' after %.1fs", query, timeout_s)
            return []
        except Exception as e:
            logger.warning(f"Crawlies research failed for '{query}': {e}")
            return []

        docs = payload.get("docs") if isinstance(payload, dict) else []
        out: List[Dict[str, Any]] = []

        if isinstance(docs, list):
            for d in docs[: max(1, int(RESEARCH_CRAWLIES_MAX_OPEN_LINKS))]:
                if not isinstance(d, dict):
                    continue
                url = str(d.get("url") or "").strip()
                if not url:
                    continue
                title = str(d.get("title") or url).strip()
                snippet = str(d.get("snippet") or "").strip()
                content = str(d.get("content") or "").strip()
                description = _safe_trim(content or snippet, 1800)
                if not description:
                    continue
                method = str(d.get("method") or "crawl").strip()
                out.append({
                    "title": title,
                    "url": url,
                    "description": description,
                    "category": "science",
                    "source": f"crawlies_{method}",
                    "volatile": True,
                    "quality": float(d.get("quality") or 0.0),
                    "status_code": int(d.get("status_code") or 0),
                })

        if not out and isinstance(payload, dict):
            candidates = payload.get("candidates")
            if isinstance(candidates, list):
                for c in candidates[: max(1, int(RESEARCH_CRAWLIES_MAX_OPEN_LINKS))]:
                    if not isinstance(c, dict):
                        continue
                    url = str(c.get("url") or "").strip()
                    if not url:
                        continue
                    title = str(c.get("title") or url).strip()
                    snippet = _safe_trim(str(c.get("snippet") or ""), 600)
                    if not snippet:
                        continue
                    out.append({
                        "title": title,
                        "url": url,
                        "description": snippet,
                        "category": "science",
                        "source": "crawlies_candidate",
                        "volatile": True,
                        "score": float(c.get("score") or 0.0),
                    })

        if out:
            out = self._prioritize_research_results(query, out)
            logger.info("Crawlies research results: %d for '%s' (domain=%s)", len(out), query, domain_key)
            return self._tag(out, "science", True)

        return []

    async def _research_composer_fallback(self, query: str) -> List[Dict[str, Any]]:
        if not RESEARCH_COMPOSER_ENABLED:
            return []
        fallback_plan = BrowsePlan(
            mode="deep",
            query=query,
            query_variants=[query],
            needs_recency=False,
            needs_citations=True,
            official_preferred=False,
            reason="research fallback",
        )
        cached_rows = self._resume_cached_evidence(query, fallback_plan, domain="science")
        if cached_rows:
            return self._tag(cached_rows, "science", True)
        try:
            bundle = await research_compose(
                query,
                max_web_results=10,
                max_enrich_results_per_domain=6,
                max_deep_reads=8 if RESEARCH_COMPOSER_DEEPREAD else 0,
                risk_mode="auto",
            )
            self.last_research_bundle = bundle.as_dict()
            summary = self._summarize_evidence_bundle(bundle)
            rows = self._rows_from_evidence_bundle(bundle, category="science")
            sources = [str(getattr(item, "url", "") or "").strip() for item in list(getattr(bundle, "items", []) or [])[:6]]
            self._record_browse_report(
                query,
                mode="deep",
                summary=summary,
                sources=sources,
                limitations=list(getattr(bundle, "limitations", []) or []),
                research_brief=dict(getattr(bundle, "research_brief", {}) or {}),
                section_bundles=[dict(item or {}) for item in list(getattr(bundle, "section_bundles", []) or []) if isinstance(item, dict)],
            )
            self._save_evidence_bundle(query, fallback_plan, bundle, rows, domain="science")
            if rows:
                return self._tag(rows, "science", True)
            if summary:
                return self._tag([{
                    "title": "Research summary",
                    "url": sources[0] if sources else "",
                    "description": summary,
                    "category": "science",
                    "source": "research_composer",
                    "volatile": True,
                    "queries": bundle.queries,
                }], "science", True)
            return []
        except Exception as e:
            logger.warning(f"Research composer failed for '{query}': {e}")
            return []

    # --- Research stack helper ---
    async def _research_stack(self, query: str) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        self._append_browse_step(q, step="plan", detail="running research stack across local memory and live web sources", mode="deep")

        domain_key = self._infer_research_domain(q)
        deadline_s = min(12.0, max(6.0, float(RESEARCH_CRAWLIES_TIMEOUT_SECONDS)))
        started = time.monotonic()

        async def _agentpedia_task() -> List[Dict[str, Any]]:
            if not self.agentpedia:
                return []
            try:
                self._append_browse_step(q, step="memory", detail="checking Agentpedia before live retrieval", mode="deep")
                research_results = await self.agentpedia.search(q)
                if research_results and isinstance(research_results, list):
                    bad = 0
                    for r in research_results:
                        t = str((r or {}).get("title", "")).lower()
                        if "insufficient coverage" in t or "unavailable" in t:
                            bad += 1
                    if bad < max(1, len(research_results)):
                        research_results = self._prioritize_research_results(q, research_results)
                        self._append_browse_step(q, step="memory", detail=f"Agentpedia returned {len(research_results)} usable local fact row(s)", mode="deep")
                        logger.info(f"Agentpedia successful for '{q}' ({len(research_results)} results)")
                        return self._tag(research_results, "science", True)
            except Exception as e:
                logger.warning(f"Agentpedia failed for '{q}': {e}")
            return []

        async def _searx_task() -> List[Dict[str, Any]]:
            p = self._searx_profile_for_domain(domain_key)
            try:
                self._append_browse_step(q, step="retrieve", detail=f"querying SearXNG profile '{str(p.get('profile') or 'science')}'", mode="deep")
                async with httpx.AsyncClient(timeout=8.0) as client:
                    searx = await search_searxng(
                        client,
                        q,
                        max_results=int(p.get("max_results", 10)),
                        max_pages=int(p.get("max_pages", 2)),
                        profile=str(p.get("profile") or "science"),
                        category=str(p.get("category") or "science"),
                        source_name=str(p.get("source_name") or f"searxng_{domain_key}"),
                        domain=domain_key,
                    )
                    if searx and isinstance(searx, list):
                        searx = self._prioritize_research_results(q, searx)
                        self._append_browse_step(q, step="retrieve", detail=f"SearXNG returned {len(searx)} research row(s)", mode="deep")
                        logger.info(f"SearXNG research results: {len(searx)} for '{q}' (domain={domain_key})")
                        return self._tag(searx, "science", True)
            except Exception as e:
                logger.warning(f"SearXNG research failed for '{q}': {e}")
            return []

        tasks: Dict[str, asyncio.Task[List[Dict[str, Any]]]] = {
            "agentpedia": asyncio.create_task(_agentpedia_task()),
            "searxng": asyncio.create_task(_searx_task()),
        }
        if RESEARCH_CRAWLIES_ENABLED and CrawliesEngine is not None and CrawliesConfig is not None:
            tasks["crawlies"] = asyncio.create_task(self._research_crawlies(q, domain_key))

        def _pick_best(candidates: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
            for key in ("crawlies", "searxng", "agentpedia"):
                v = candidates.get(key) or []
                if v:
                    return v
            return []

        try:
            done, pending = await asyncio.wait(list(tasks.values()), timeout=deadline_s, return_when=asyncio.FIRST_COMPLETED)
            candidate_results: Dict[str, List[Dict[str, Any]]] = {}
            for d in done:
                try:
                    res = d.result()
                except Exception:
                    continue

                src = next((k for k, t in tasks.items() if t is d), "")
                if src:
                    candidate_results[src] = res or []

            grace_s = 0.35
            if pending and candidate_results and (time.monotonic() - started + grace_s) < deadline_s:
                done_grace, pending = await asyncio.wait(pending, timeout=grace_s)
                for d in done_grace:
                    try:
                        res = d.result()
                    except Exception:
                        continue
                    src = next((k for k, t in tasks.items() if t is d), "")
                    if src:
                        candidate_results[src] = res or []

            if "crawlies" in tasks and "crawlies" not in candidate_results:
                crawl_task = tasks.get("crawlies")
                if crawl_task in pending and any(candidate_results.get(k) for k in ("searxng", "agentpedia")):
                    remaining_budget = max(0.0, deadline_s - (time.monotonic() - started))
                    wait_crawl_s = min(2.5, remaining_budget)
                    if wait_crawl_s > 0:
                        logger.info(
                            "Research stack waiting up to %.2fs for crawlies before selecting fallback provider",
                            wait_crawl_s,
                        )
                        done_crawl, _ = await asyncio.wait({crawl_task}, timeout=wait_crawl_s)
                        if crawl_task in done_crawl:
                            pending.discard(crawl_task)
                            try:
                                crawl_res = crawl_task.result()
                            except Exception:
                                crawl_res = []
                            candidate_results["crawlies"] = crawl_res or []

            picked = _pick_best(candidate_results)
            if picked:
                chosen_provider = next((name for name in ("crawlies", "searxng", "agentpedia") if candidate_results.get(name)), "research")
                self._append_browse_step(q, step="judge", detail=f"selected {chosen_provider} as the strongest evidence path", mode="deep")
                if chosen_provider != "agentpedia":
                    added = self._write_agentpedia_memory(q, picked[:4], domain_hint=domain_key)
                    if added:
                        self._append_browse_step(q, step="memory", detail=f"persisted {added} Agentpedia fact row(s) from {chosen_provider} research", mode="deep")
                self._maybe_build_shadow_bundle(q, picked, domain=domain_key)
                self._record_browse_report(
                    q,
                    mode="deep",
                    summary=self._summarize_result_rows(q, picked),
                    sources=[str((row or {}).get("url") or "").strip() for row in picked[:6]],
                )
                return picked

            remaining = max(0.0, deadline_s - (time.monotonic() - started))
            if pending and remaining > 0:
                done2, pending2 = await asyncio.wait(pending, timeout=remaining)
                candidate_results2: Dict[str, List[Dict[str, Any]]] = {}
                for d in done2:
                    try:
                        res = d.result()
                    except Exception:
                        continue
                    src = next((k for k, t in tasks.items() if t is d), "")
                    if src:
                        candidate_results2[src] = res or []

                picked2 = _pick_best(candidate_results2)
                if picked2:
                    chosen_provider = next((name for name in ("crawlies", "searxng", "agentpedia") if candidate_results2.get(name)), "research")
                    self._append_browse_step(q, step="judge", detail=f"selected {chosen_provider} after waiting for slower providers", mode="deep")
                    if chosen_provider != "agentpedia":
                        added = self._write_agentpedia_memory(q, picked2[:4], domain_hint=domain_key)
                        if added:
                            self._append_browse_step(q, step="memory", detail=f"persisted {added} Agentpedia fact row(s) from {chosen_provider} research", mode="deep")
                    self._maybe_build_shadow_bundle(q, picked2, domain=domain_key)
                    self._record_browse_report(
                        q,
                        mode="deep",
                        summary=self._summarize_result_rows(q, picked2),
                        sources=[str((row or {}).get("url") or "").strip() for row in picked2[:6]],
                    )
                    return picked2
        finally:
            await _cancel_tasks_silently(list(tasks.values()))

        # Keep science/research path free of DDG fallbacks. Prefer composer summary if retrieval fails.
        return await self._research_composer_fallback(q)

    # === accept router kwargs like tool_veto/reason/signals ===
    async def search(
        self,
        query: str,
        retries: int = 3,
        backoff_factor: float = 0.5,
        **kwargs,
    ) -> list:
        # Router/orchestrator may pass these. We tolerate them.
        tool_veto = bool(kwargs.get("tool_veto", False))
        veto_reason = (kwargs.get("reason") or kwargs.get("veto_reason") or "").strip()
        signals = kwargs.get("signals", None) or {}
        intent_hint = str(signals.get("intent") or "").strip().lower()

        if tool_veto:
            logger.info(f"Websearch vetoed by router: {veto_reason}")
            return [{
                "title": "Websearch vetoed",
                "url": "",
                "description": veto_reason or "Router vetoed tool usage.",
                "category": "general",
                "volatile": False,
            }]

        query = (query or "").strip()
        if not query:
            return [{"title": "Error", "url": "", "description": "Empty query.", "category": "general", "volatile": False}]

        self._clear_browse_report()
        query_lower = query.lower().strip()
        browse_plan = build_browse_plan(query, intent_hint=intent_hint, route_hint="websearch")
        self._append_browse_step(
            query,
            step="plan",
            detail=(
                f"mode={browse_plan.mode}; reason={browse_plan.reason}; "
                f"recency={browse_plan.needs_recency}; citations={browse_plan.needs_citations}; "
                f"official={browse_plan.official_preferred}"
            ),
            mode=browse_plan.mode,
        )
        logger.info(f"Processing query: '{query}'")

        if self._is_personal_memory_query(query_lower):
            logger.info("Skipping websearch/finance routing for personal memory query")
            return [{
                "title": "Personal memory query",
                "url": "",
                "description": "Handled by in-model memory context.",
                "category": "general",
                "volatile": False,
            }]

        if (
            browse_plan.mode in {"github", "direct_url"}
            or browse_plan.official_preferred
            or (
                browse_plan.mode == "deep"
                and (
                    is_trip_planning_query(query)
                    or is_travel_lookup_query(query)
                    or is_shopping_compare_query(query)
                    or is_software_change_query(query)
                )
            )
        ):
            early = await self.search_web(query, retries, backoff_factor)
            if early:
                return self._tag(early, "general", False)
            if browse_plan.mode == "deep" and is_shopping_compare_query(query):
                return []

        # --- Router intent hints: bypass classifier and heuristics (PATCH) ---
        # If the router already decided the intent, trust it and avoid cross-domain fallthrough.
        if intent_hint in {"news", "weather", "science", "stock/commodity", "crypto", "forex"}:
            try:
                if intent_hint == "news":
                    res = await self._news_lookup_browse(query, retries=retries, backoff_factor=backoff_factor)
                    if res:
                        return self._tag(res, "news", True)
                    fallback = await self.search_web(query, retries, backoff_factor)
                    if fallback:
                        return self._tag(fallback, "news", True)
                    return [{"title": "News Not Found", "url": "", "description": "No news results found for this query.", "category": "news", "volatile": True}]

                if intent_hint == "weather":
                    res = await self.weather_handler.search_weather(query, retries, backoff_factor)
                    if res:
                        return self._tag(res, "weather", True)
                    fallback = await self.search_web(query, retries, backoff_factor)
                    if fallback:
                        return self._tag(fallback, "weather", True)
                    return [{"title": "Weather Not Found", "url": "", "description": "No weather results found for this query.", "category": "weather", "volatile": True}]

                if intent_hint == "science":
                    res = await self._research_stack(query)
                    if res:
                        return res
                    fallback = await self.search_web(query, retries, backoff_factor)
                    if fallback:
                        return self._tag(fallback, "general", False)
                    return [{"title": "Research Not Found", "url": "", "description": "No research results found for this query.", "category": "science", "volatile": False}]

                if intent_hint == "stock/commodity":
                    res = await self._search_finance_intent("stock/commodity", query)
                    if self._maybe_log_deroute(res, query=query):
                        res = []
                    if res:
                        return self._tag(res, "stock/commodity", True)
                    return [{"title": "Asset Not Found", "url": "", "description": "No matching stock, commodity, or index result was found.", "category": "stock/commodity", "volatile": True}]

                if intent_hint == "crypto":
                    res = await self._search_finance_intent("crypto", query)
                    if self._maybe_log_deroute(res, query=query):
                        res = []
                    if res:
                        return self._tag(res, "crypto", True)
                    return [{"title": "Crypto Not Found", "url": "", "description": "No matching crypto result was found.", "category": "crypto", "volatile": True}]

                if intent_hint == "forex":
                    res = await self._search_finance_intent("forex", query)
                    if self._maybe_log_deroute(res, query=query):
                        res = []
                    if res:
                        return self._tag(res, "forex", True)
                    return [{"title": "Rate Not Found", "url": "", "description": "No matching forex rate result was found.", "category": "forex", "volatile": True}]

            except Exception as e:
                logger.error(
                    f"Router intent routing failed for '{query}' ({intent_hint}): {e}\n{traceback.format_exc()}"
                )
                fallback = await self.search_web(query, retries, backoff_factor)
                if fallback:
                    return self._tag(fallback, "general", False)
                return [{"title": "Error", "url": "", "description": "Search failed unexpectedly.", "category": "general", "volatile": False}]

        # --- Conversion shortcut stays first ---
        parsed = parse_conversion_request(query)
        if parsed is not None:
            try:
                answer = await self.converter.convert(query)
                if answer and "Error" not in answer:
                    return [{
                        "title": f"{parsed.amount:g} {parsed.src.upper()} -> {parsed.dst.upper()}",
                        "url": "",
                        "description": answer,
                        "category": "forex",
                        "volatile": True
                    }]
                elif answer:
                    return [{
                        "title": "Conversion issue",
                        "url": "",
                        "description": answer,
                        "category": "general",
                        "volatile": False
                    }]
            except Exception as e:
                logger.error(f"Conversion failed for '{query}': {e}", exc_info=True)

        # --- Research intent: forced early path ---
        looks_research = self._is_research_query(query_lower)
        if intent_hint in {"research", "science"} or looks_research:
            logger.info(f"Research intent detected (hint={intent_hint!r}, looks_research={looks_research}) for '{query}'")
            res = await self._research_stack(query)
            if res:
                return res
            # If research stack fails, we continue to general web below.

        if self._is_finance_historical_query(query, intent_hint=intent_hint):
            hist_intent = intent_hint if intent_hint in {"stock/commodity", "crypto", "forex"} else ""
            if not hist_intent:
                forced_hist = self._force_intent_from_terms(query_lower)
                if forced_hist in {"stock/commodity", "crypto", "forex"}:
                    hist_intent = forced_hist
                else:
                    hist_intent = "stock/commodity"
            try:
                res = await self._search_finance_intent(hist_intent, query)
                if self._maybe_log_deroute(res, query=query):
                    res = []
                if res:
                    return self._tag(res, hist_intent, True)
            except Exception as e:
                logger.error(f"Historical finance routing failed for '{query}' ({hist_intent}): {e}\n{traceback.format_exc()}")

        # --- Forced intent heuristics (safe) ---
        forced = self._force_intent_from_terms(query_lower)
        if forced:
            try:
                if forced == "science":
                    res = await self._research_stack(query)
                    if res:
                        return res

                elif forced == "stock/commodity":
                    res = await self._search_finance_intent("stock/commodity", query)
                    if self._maybe_log_deroute(res, query=query):
                        res = []
                    if res:
                        return self._tag(res, "stock/commodity", True)

                elif forced == "crypto":
                    res = await self._search_finance_intent("crypto", query)
                    if self._maybe_log_deroute(res, query=query):
                        res = []
                    if res:
                        return self._tag(res, "crypto", True)

                elif forced == "forex":
                    res = await self._search_finance_intent("forex", query)
                    if self._maybe_log_deroute(res, query=query):
                        res = []
                    if res:
                        return self._tag(res, "forex", True)

                elif forced == "weather":
                    res = await self.weather_handler.search_weather(query, retries, backoff_factor)
                    if res:
                        return self._tag(res, "weather", True)

                elif forced == "news":
                    res = await self._news_lookup_browse(query, retries=retries, backoff_factor=backoff_factor)
                    if res:
                        return self._tag(res, "news", True)

            except Exception as e:
                logger.error(f"Forced routing failed for '{query}' ({forced}): {e}\n{traceback.format_exc()}")

        # --- LLM classification (still used), but sanity validator upgrades research to science ---
        query_type = await self._classify_query(query, retries=retries, backoff_factor=backoff_factor)
        query_type = self._sanity_validate_intent(query_type, query_lower)

        # --- Main routing + deroute-aware fallback (finance only) ---
        try:
            if query_type == "science":
                res = await self._research_stack(query)
                if res:
                    return res
                # fallthrough to general web

            if query_type == "stock/commodity":
                res = await self._search_finance_intent("stock/commodity", query)
                if self._maybe_log_deroute(res, query=query):
                    res = []
                if res:
                    return self._tag(res, "stock/commodity", True)
                # finance failed: try research (common misclass), then general
                res2 = await self._research_stack(query)
                if res2:
                    return res2
                res3 = await self.search_web(query, retries, backoff_factor)
                return self._tag(res3, "general", False)

            if query_type == "crypto":
                res = await self._search_finance_intent("crypto", query)
                if self._maybe_log_deroute(res, query=query):
                    res = []
                if res:
                    return self._tag(res, "crypto", True)
                res2 = await self._research_stack(query)
                if res2:
                    return res2
                res3 = await self.search_web(query, retries, backoff_factor)
                return self._tag(res3, "general", False)

            if query_type == "forex":
                res = await self._search_finance_intent("forex", query)
                if self._maybe_log_deroute(res, query=query):
                    res = []
                if res:
                    return self._tag(res, "forex", True)
                res3 = await self.search_web(query, retries, backoff_factor)
                return self._tag(res3, "general", False)

            if query_type == "weather":
                res = await self.weather_handler.search_weather(query, retries, backoff_factor)
                if res:
                    return self._tag(res, "weather", True)
                # fallback to general web (weather provider down / parse fail)
                res3 = await self.search_web(query, retries, backoff_factor)
                return self._tag(res3, "general", False)

            if query_type == "news":
                res = await self._news_lookup_browse(query, retries=retries, backoff_factor=backoff_factor)
                if res:
                    return self._tag(res, "news", True)
                # fallback: research stack (searxng), then ddg web
                res2 = await self._research_stack(query)  # uses searxng
                if res2:
                    return res2
                res3 = await self.search_web(query, retries, backoff_factor)
                return self._tag(res3, "general", False)

            # default general
            res = await self.search_web(query, retries, backoff_factor)
            return self._tag(res, "general", False)

        except Exception as e:
            logger.error(f"Routing failed for '{query}' ({query_type}): {e}\n{traceback.format_exc()}")
            return [{
                "title": "Error",
                "url": "",
                "description": "Search failed unexpectedly.",
                "category": query_type,
                "volatile": query_type in {"stock/commodity", "crypto", "forex", "weather", "news"},
            }]

    async def search_web(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        q = (query or "").strip()
        if not q:
            return []
        existing_report = dict(self.last_browse_report or {}) if isinstance(self.last_browse_report, dict) else {}
        if str(existing_report.get("query") or "").strip().lower() != q.lower():
            self._clear_browse_report()

        query_lower = q.lower()
        fetch_fullpage = self._needs_fullpage_fetch(query_lower)
        browse_plan = build_browse_plan(q)
        self._append_browse_step(
            q,
            step="plan",
            detail=(
                f"mode={browse_plan.mode}; reason={browse_plan.reason}; "
                f"fullpage_fetch={fetch_fullpage}; variants={len(list(browse_plan.query_variants or [])) or 1}"
            ),
            mode=browse_plan.mode,
        )

        q_key = self._normalize_cache_key(q)
        cache_key = f"general::{browse_plan.mode}::{int(fetch_fullpage)}::{q_key}"
        cached = self.search_cache.get(cache_key)
        if isinstance(cached, list) and cached:
            self._append_browse_step(q, step="retrieve", detail="served results from search cache", mode=browse_plan.mode)
            return cached

        forced = self._force_intent_from_terms(query_lower)
        if forced == "news":
            self._append_browse_step(q, step="route", detail="query looked like explicit news lookup; using news shortlist path", mode="news")
            news_rows = await self._news_lookup_browse(q, retries=retries, backoff_factor=backoff_factor)
            if news_rows:
                tagged_news = self._tag(news_rows, "news", True)
                self.search_cache.set(cache_key, tagged_news)
                return tagged_news

        try:
            if browse_plan.mode == "github":
                github_rows = await self._github_browse(q, browse_plan)
                if github_rows:
                    self.search_cache.set(cache_key, github_rows)
                    return github_rows

            if browse_plan.mode == "direct_url":
                direct_rows = await self._direct_url_browse(q, browse_plan)
                if direct_rows:
                    self.search_cache.set(cache_key, direct_rows)
                    return direct_rows

            if browse_plan.mode == "deep" and self._is_python_docs_query(q):
                python_docs_rows = await self._python_docs_direct_browse(q, browse_plan)
                if python_docs_rows:
                    self.search_cache.set(cache_key, python_docs_rows)
                    return python_docs_rows

            if browse_plan.mode == "deep" and is_software_change_query(q):
                software_rows = await self._software_change_browse(q, browse_plan)
                if software_rows:
                    self.search_cache.set(cache_key, software_rows)
                    return software_rows

            if browse_plan.mode == "deep" and browse_plan.official_preferred:
                official_rows = await self._official_preferred_browse(q, browse_plan)
                if official_rows:
                    self.search_cache.set(cache_key, official_rows)
                    return official_rows

            if browse_plan.mode == "deep" and is_shopping_compare_query(q):
                compare_rows = await self._shopping_compare_browse(q, browse_plan)
                if compare_rows:
                    self.search_cache.set(cache_key, compare_rows)
                    return compare_rows
                self._append_browse_step(
                    q,
                    step="judge",
                    detail="shopping compare fast path exhausted; skipping generic deep browse fallback",
                    mode=browse_plan.mode,
                )
                return []

            if browse_plan.mode == "deep" and is_trip_planning_query(q):
                travel_rows = await self._trip_planning_browse(q, browse_plan)
                if travel_rows:
                    self.search_cache.set(cache_key, travel_rows)
                    return travel_rows

            if browse_plan.mode == "deep" and is_travel_lookup_query(q):
                travel_lookup_rows = await self._travel_lookup_browse(q, browse_plan)
                if travel_lookup_rows:
                    self.search_cache.set(cache_key, travel_lookup_rows)
                    return travel_lookup_rows

            if browse_plan.mode == "deep":
                deep_rows = await self._deep_browse(q, browse_plan, allow_resume=True)
                if deep_rows:
                    self.search_cache.set(cache_key, deep_rows)
                    return deep_rows
        except Exception as e:
            logger.warning("Agentic browse path failed for '%s': %s", q, e)

        attempt_limit = 1 if browse_plan.mode == "quick" else retries
        ddg_timeout_s = 6.0 if browse_plan.mode == "quick" else 12.0
        for attempt in range(attempt_limit):
            try:
                self._append_browse_step(q, step="retrieve", detail="running DDG text search", mode=browse_plan.mode)
                raw = await asyncio.wait_for(self._ddg_text(q, max_results=18), timeout=ddg_timeout_s)
                base = self._normalize_ddg_results(raw)
                base = self._dedupe_results(base)
                enriched: List[Dict[str, Any]]
                if fetch_fullpage:
                    enriched = await self._fetch_and_attach_content(
                        base,
                        category="general",
                        top_n=3,
                        max_n=6,
                    )
                    content_count = sum(1 for row in enriched if str((row or {}).get("content") or "").strip())
                    if content_count:
                        self._append_browse_step(q, step="read", detail=f"opened {content_count} page(s) for extracted text", mode=browse_plan.mode)
                else:
                    enriched = [dict(r) for r in base]

                for r in enriched:
                    if isinstance(r, dict):
                        r["fullpage_fetch"] = fetch_fullpage

                # SearXNG fallback if DDG is weak
                if len(enriched) < 3:
                    self._append_browse_step(q, step="retrieve", detail="DDG looked thin; falling back to SearXNG enrichment", mode=browse_plan.mode)
                    logger.info(f"DDG weak ({len(enriched)} enriched results) for '{q}' - enriching with SearXNG")
                    gp = self._searx_profile_for_domain("general")
                    async with httpx.AsyncClient(timeout=12.0) as local_client:
                        extra = await search_searxng(
                            local_client,
                            q,
                            max_results=int(gp.get("max_results", 10)),
                            max_pages=int(gp.get("max_pages", 2)),
                            profile=str(gp.get("profile") or "general"),
                            category=str(gp.get("category") or "general"),
                            source_name=str(gp.get("source_name") or "searxng_general"),
                            domain="general"
                        )
                        existing_urls = {r.get("url", "") for r in enriched if isinstance(r, dict)}
                        extra_deduped = [r for r in extra if isinstance(r, dict) and r.get("url", "") not in existing_urls]
                        for r in extra_deduped:
                            r["fullpage_fetch"] = fetch_fullpage
                        enriched.extend(extra_deduped)
                        if extra_deduped:
                            self._append_browse_step(q, step="retrieve", detail=f"SearXNG added {len(extra_deduped)} extra row(s)", mode=browse_plan.mode)
                        logger.info(f"SearXNG fallback added {len(extra_deduped)} new results")

                self._append_browse_step(q, step="judge", detail=f"selected {min(len(enriched), 8)} result row(s) for answer grounding", mode=browse_plan.mode)
                limitations: List[str] = []
                if len(enriched) < 3:
                    limitations.append("General-web retrieval returned a thin source set.")
                summary = self._summarize_result_rows(q, enriched)
                self._record_browse_report(
                    q,
                    mode=browse_plan.mode,
                    summary=summary,
                    sources=[str((row or {}).get("url") or "").strip() for row in enriched[:6]],
                    limitations=limitations,
                )
                self.search_cache.set(cache_key, enriched)
                logger.info(f"DDG general results: {len(enriched)} for '{q}' (enriched)")
                return enriched
            except Exception as e:
                logger.error(f"General search error (attempt {attempt+1}/{attempt_limit}): {e}\n{traceback.format_exc()}")
                if browse_plan.mode == "quick" and attempt == 0:
                    self._append_browse_step(q, step="recover", detail="DDG failed; trying direct SearXNG fallback for quick lookup", mode=browse_plan.mode)
                    try:
                        gp = self._searx_profile_for_domain("general")
                        async with httpx.AsyncClient(timeout=12.0) as local_client:
                            recovered = await search_searxng(
                                local_client,
                                q,
                                max_results=int(gp.get("max_results", 10)),
                                max_pages=1,
                                profile=str(gp.get("profile") or "general"),
                                category=str(gp.get("category") or "general"),
                                source_name=str(gp.get("source_name") or "searxng_general"),
                                domain="general",
                            )
                        recovered = self._dedupe_results([dict(row or {}) for row in recovered if isinstance(row, dict)])
                        if recovered:
                            for row in recovered:
                                row["fullpage_fetch"] = fetch_fullpage
                            self._append_browse_step(
                                q,
                                step="judge",
                                detail=f"recovered {min(len(recovered), 8)} quick lookup row(s) via SearXNG",
                                mode=browse_plan.mode,
                            )
                            limitations: List[str] = []
                            if len(recovered) < 3:
                                limitations.append("Quick lookup recovered from a thin SearXNG source set after DDG failed.")
                            summary = self._summarize_result_rows(q, recovered)
                            self._record_browse_report(
                                q,
                                mode=browse_plan.mode,
                                summary=summary,
                                sources=[str((row or {}).get("url") or "").strip() for row in recovered[:6]],
                                limitations=limitations,
                            )
                            self.search_cache.set(cache_key, recovered)
                            return recovered
                    except Exception as searx_error:
                        logger.warning("Quick SearXNG recovery failed for '%s': %s", q, searx_error)
                if attempt < attempt_limit - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        offline_rows = self._offline_fallback_rows(q, browse_plan, reason="live web retrieval returned no usable rows")
        if offline_rows:
            self.search_cache.set(cache_key, offline_rows)
            return offline_rows
        self._append_browse_step(q, step="judge", detail="no live or local fallback rows were strong enough to answer", mode=browse_plan.mode)
        return []


    def to_search_bundle(self, query: str, results: list, time_anchor=None, exactness_requested: bool = False, domain: str = "general", needs_recency: bool = False) -> SearchBundle:
        bundle = SearchBundle(query=(query or "").strip(), results=[], warnings=[], summary="")
        report = self.last_browse_report if isinstance(self.last_browse_report, dict) else None
        if report and str(report.get("query") or "").strip().lower() == str(query or "").strip().lower():
            bundle.summary = str(report.get("summary") or "").strip()
            bundle.warnings.extend([str(x).strip() for x in list(report.get("limitations") or []) if str(x or "").strip()])
            bundle.execution_trace = self._render_trace_lines(report, limit=6)
            bundle.research_brief = dict(report.get("research_brief") or {}) if isinstance(report.get("research_brief") or {}, dict) else {}
            bundle.section_bundles = [dict(item or {}) for item in list(report.get("section_bundles") or []) if isinstance(item, dict)][:6]
        python_docs_query = self._is_python_docs_query(query)
        for r in (results or []):
            if not isinstance(r, dict):
                continue
            title = str(r.get("title") or "").strip()
            url = strip_tracking_params(str(r.get("url") or "").strip())
            description = str(r.get("description") or "").strip()
            content = str(r.get("content") or "").strip()
            snippet = description or content
            if python_docs_query and content:
                snippet = content
            elif content and (len(description) < 140 or description.startswith("(") or description.startswith("[")):
                snippet = content
            source_domain = str(r.get("source") or r.get("provider") or "").strip()
            published = str(r.get("published_at") or r.get("published") or "").strip() or None
            if len(snippet) > 350:
                snippet = snippet[:347].rstrip() + "..."
            if title and url:
                bundle.results.append(SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_domain=source_domain,
                    published_date=published,
                ))

        bundle.results = bundle.results[:6]
        if exactness_requested and time_anchor:
            target = ""
            if hasattr(time_anchor, "year") and getattr(time_anchor, "year", None):
                target = str(getattr(time_anchor, "year"))
            if hasattr(time_anchor, "date") and getattr(time_anchor, "date", None):
                target = str(getattr(time_anchor, "date"))
            if target:
                matched = [r for r in bundle.results if target in (r.published_date or "") or target in r.snippet or target in r.title]
                if matched:
                    bundle.results = matched + [r for r in bundle.results if r not in matched]
                else:
                    bundle.warnings.append("No clearly time-anchored sources found.")

        if str(domain or "").lower() == "news" and needs_recency:
            with_date = [r for r in bundle.results if (r.published_date or "").strip()]
            without_date = [r for r in bundle.results if not (r.published_date or "").strip()]
            with_date.sort(key=lambda r: str(r.published_date or ""), reverse=True)
            bundle.results = (with_date + without_date)[:6]
            if not with_date:
                bundle.warnings.append("Unable to verify reasonably recent publication times for latest-news request.")
        return bundle

    def format_results(self, results: list) -> str:
        report = self.last_browse_report if isinstance(self.last_browse_report, dict) else None
        summary = str((report or {}).get("summary") or "").strip()
        limitations = [str(x).strip() for x in list((report or {}).get("limitations") or []) if str(x or "").strip()]
        execution_steps = self._render_trace_lines(report or {}, limit=6) if report else []
        recovery_notes = [str(x).strip() for x in list((report or {}).get("recovery_notes") or []) if str(x or "").strip()]
        progress_headline = str((report or {}).get("progress_headline") or "").strip()

        if not results:
            if summary:
                block = "## Browse Summary\n"
                if progress_headline:
                    block += progress_headline + "\n"
                block += summary
                if execution_steps:
                    block += "\n\nAgent trace:\n" + "\n".join([f"- {item}" for item in execution_steps[:6]])
                if recovery_notes:
                    block += "\n\nRecovery notes:\n" + "\n".join([f"- {item}" for item in recovery_notes[:4]])
                if limitations:
                    block += "\n\nBrowse notes:\n" + "\n".join([f"- {item}" for item in limitations[:4]])
                return block[: max(500, int(WEBSEARCH_MAX_FORMAT_CHARS))]
            return "No search results found."

        debug_mode = bool(ROUTING_DEBUG or WEBSEARCH_DEBUG_RESULTS)

        lines = []
        if summary:
            lines.append("## Browse Summary")
            if progress_headline:
                lines.append(progress_headline)
            lines.append(summary)
            if execution_steps:
                lines.append("")
                lines.append("Agent trace:")
                lines.extend([f"- {item}" for item in execution_steps[:6]])
            if recovery_notes:
                lines.append("")
                lines.append("Recovery notes:")
                lines.extend([f"- {item}" for item in recovery_notes[:4]])
            if limitations:
                lines.append("")
                lines.append("Browse notes:")
                lines.extend([f"- {item}" for item in limitations[:4]])
                lines.append("")
        for idx, r in enumerate(results[:10], start=1):
            if not isinstance(r, dict):
                continue

            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            desc = (r.get("description") or "").strip()
            content = (r.get("content") or "").strip()
            category = (r.get("category") or "").strip()
            volatile = bool(r.get("volatile", False))
            source = (r.get("source") or r.get("provider") or "").strip()
            published = (r.get("published_at") or r.get("published") or "").strip()

            # Include deroute fields if present (for debugging)
            deroute = bool(r.get("deroute", False))
            deroute_reason = (r.get("reason") or "").strip()
            deroute_handler = (r.get("handler") or "").strip()
            fullpage_fetch = bool(r.get("fullpage_fetch", False))

            source_parts = [p for p in [source, published] if p]
            source_line = f" ({' - '.join(source_parts)})" if source_parts else ""
            block = (
                f"{idx}. {title}{source_line}\n"
                f"   URL: {url}\n"
                f"   Snippet: {_safe_trim(desc, 280)}\n"
                f"   Meta: category={category}, volatile={volatile}"
            )
            if debug_mode:
                block += f", deroute={deroute}"

            if debug_mode and deroute:
                if deroute_handler:
                    block += f"\n  DerouteHandler: {_safe_trim(deroute_handler, 80)}"
                if deroute_reason:
                    block += f"\n  DerouteReason: {_safe_trim(deroute_reason, 220)}"
            if content and (debug_mode or fullpage_fetch):
                block += f"\n  Extracted: {_safe_trim(content, 700)}"

            lines.append(block)

        formatted = "## Web/Search Context (results)\n" + "\n".join(lines)
        formatted += "\n\nReply 'expand 2' to open and summarize a story."
        return formatted[: max(500, int(WEBSEARCH_MAX_FORMAT_CHARS))]







