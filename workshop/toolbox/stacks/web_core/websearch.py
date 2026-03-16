# handlers/websearch.py
import asyncio
import logging
import re
import time
import traceback
import socket
import ipaddress
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx
try:
    import ollama
except Exception:  # pragma: no cover
    ollama = None  # type: ignore
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
from workshop.toolbox.stacks.web_core.search_bundle import SearchBundle, SearchResult, strip_tracking_params

import pytz
from datetime import datetime

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
    return t[:limit].rstrip() + "â€¦"


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
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
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


class WebSearchHandler:
    def __init__(self):
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

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

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

        # Hard signals
        if self._re_pmid.search(ql) or self._re_doi.search(ql) or self._re_nct.search(ql) or self._re_arxiv.search(ql):
            return True

        # Common research operators / patterns
        if "site:" in ql:
            # not always research, but it is definitely "not finance"
            # and is often academic/web-research
            return True

        return any(t in ql for t in self.research_terms)

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

            for cat in self.valid_categories:
                if re.search(rf"\b{re.escape(cat)}\b", cleaned):
                    return cat

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
        if any(t in ql for t in self.crypto_terms):
            matches.add("crypto")
        if any(t in ql for t in self.index_terms):
            matches.add("stock/commodity")

        stock_keywords = ["stock", "stocks", "share price", "shares", "ticker", "price of", "market cap", "quote"]
        if any(k in ql for k in stock_keywords):
            matches.add("stock/commodity")

        # NOTE: removed this bug source:
        # if re.search(r"\b[A-Z]{3,5}\b", query_lower.upper()):
        #     matches.add("stock/commodity")

        if any(t in ql for t in self.weather_terms):
            matches.add("weather")
        if any(t in ql for t in self.news_terms):
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
            if not any(t in ql for t in self.weather_terms):
                return "general"

        if intent == "news":
            if not any(t in ql for t in self.news_terms) and not any(x in ql for x in ["breaking", "headline", "reuters", "bbc"]):
                return "general"

        if intent == "crypto":
            has_crypto = any(t in ql for t in self.crypto_terms)
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

    def _score_research_result(self, query: str, item: Dict[str, Any]) -> float:
        title = str((item or {}).get("title") or "")
        desc = str((item or {}).get("description") or "")
        url = str((item or {}).get("url") or "")
        blob = f"{title} {desc} {url}".lower()
        host = (urlparse(url).netloc or "").lower()

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
        try:
            bundle = await research_compose(
                query,
                max_web_results=10,
                max_enrich_results_per_domain=6,
                max_deep_reads=8 if RESEARCH_COMPOSER_DEEPREAD else 0,
                risk_mode="auto",
            )
            self.last_research_bundle = bundle.as_dict()
            if not (bundle.answer or "").strip():
                return []
            item: Dict[str, Any] = {
                "title": "Research composer answer" if bundle.items else "Research composer insufficient evidence",
                "url": "",
                "description": bundle.answer,
                "category": "science",
                "source": "research_composer",
                "volatile": True,
                "queries": bundle.queries,
            }
            if bundle.items:
                item["conflicts"] = bundle.conflicts
            return self._tag([item], "science", True)
        except Exception as e:
            logger.warning(f"Research composer failed for '{query}': {e}")
            return []

    # --- Research stack helper ---
    async def _research_stack(self, query: str) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        domain_key = self._infer_research_domain(q)
        deadline_s = min(12.0, max(6.0, float(RESEARCH_CRAWLIES_TIMEOUT_SECONDS)))
        started = time.monotonic()

        async def _agentpedia_task() -> List[Dict[str, Any]]:
            if not self.agentpedia:
                return []
            try:
                research_results = await self.agentpedia.search(q)
                if research_results and isinstance(research_results, list):
                    bad = 0
                    for r in research_results:
                        t = str((r or {}).get("title", "")).lower()
                        if "insufficient coverage" in t or "unavailable" in t:
                            bad += 1
                    if bad < max(1, len(research_results)):
                        research_results = self._prioritize_research_results(q, research_results)
                        logger.info(f"Agentpedia successful for '{q}' ({len(research_results)} results)")
                        return self._tag(research_results, "science", True)
            except Exception as e:
                logger.warning(f"Agentpedia failed for '{q}': {e}")
            return []

        async def _searx_task() -> List[Dict[str, Any]]:
            p = self._searx_profile_for_domain(domain_key)
            try:
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
                self._maybe_build_shadow_bundle(q, picked, domain=domain_key)
                for p in pending:
                    p.cancel()
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
                    self._maybe_build_shadow_bundle(q, picked2, domain=domain_key)
                    for p in pending2:
                        p.cancel()
                    return picked2
                for p in pending2:
                    p.cancel()
        finally:
            for t in tasks.values():
                if not t.done():
                    t.cancel()

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

        query_lower = query.lower().strip()
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

        # --- Router intent hints: bypass classifier and heuristics (PATCH) ---
        # If the router already decided the intent, trust it and avoid cross-domain fallthrough.
        if intent_hint in {"news", "weather", "science", "stock/commodity", "crypto", "forex"}:
            try:
                if intent_hint == "news":
                    res = await self.news_handler.search_news(query, retries, backoff_factor)
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
                        "title": f"{parsed.amount:g} {parsed.src.upper()} â†’ {parsed.dst.upper()}",
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
                    res = await self.news_handler.search_news(query, retries, backoff_factor)
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
                res = await self.news_handler.search_news(query, retries, backoff_factor)
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

        composer_fallback: Optional[List[Dict[str, Any]]] = None

        query_lower = q.lower()
        fetch_fullpage = self._needs_fullpage_fetch(query_lower)

        q_key = self._normalize_cache_key(q)
        cache_key = f"general::{int(fetch_fullpage)}::{q_key}"
        cached = self.search_cache.get(cache_key)
        if isinstance(cached, list) and cached:
            return cached

        for attempt in range(retries):
            try:
                raw = await self._ddg_text(q, max_results=18)
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
                else:
                    enriched = [dict(r) for r in base]

                for r in enriched:
                    if isinstance(r, dict):
                        r["fullpage_fetch"] = fetch_fullpage

                # SearXNG fallback if DDG is weak
                if len(enriched) < 3:
                    logger.info(f"DDG weak ({len(enriched)} enriched results) for '{q}' â€” enriching with SearXNG")
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
                        logger.info(f"SearXNG fallback added {len(extra_deduped)} new results")

                self.search_cache.set(cache_key, enriched)
                logger.info(f"DDG general results: {len(enriched)} for '{q}' (enriched)")
                return enriched
            except Exception as e:
                logger.error(f"General search error (attempt {attempt+1}/{retries}): {e}\n{traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        return []


    def to_search_bundle(self, query: str, results: list, time_anchor=None, exactness_requested: bool = False, domain: str = "general", needs_recency: bool = False) -> SearchBundle:
        bundle = SearchBundle(query=(query or "").strip(), results=[], warnings=[])
        for r in (results or []):
            if not isinstance(r, dict):
                continue
            title = str(r.get("title") or "").strip()
            url = strip_tracking_params(str(r.get("url") or "").strip())
            snippet = str(r.get("description") or r.get("content") or "").strip()
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
        if not results:
            return "No search results found."

        debug_mode = bool(ROUTING_DEBUG or WEBSEARCH_DEBUG_RESULTS)

        lines = []
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
            source_line = f" ({' â€” '.join(source_parts)})" if source_parts else ""
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







