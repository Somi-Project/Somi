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
import ollama
from duckduckgo_search import DDGS

from config.settings import INSTRUCT_MODEL, SYSTEM_TIMEZONE

from handlers.websearch_tools.finance import FinanceHandler
from handlers.websearch_tools.news import NewsHandler
from handlers.websearch_tools.weather import WeatherHandler

from handlers.websearch_tools.conversion import parse_conversion_request, Converter

import pytz
from datetime import datetime

# NEW: SearXNG import
from handlers.research.searxng import search_searxng

logger = logging.getLogger(__name__)

# --- RESEARCH (Agentpedia) safe import ---
try:
    from handlers.research.agentpedia import Agentpedia
    agentpedia_available = True
except Exception as e:
    logger.warning(f"Agentpedia not available: {e}")
    agentpedia_available = False
    Agentpedia = None


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
    NOTE: This will treat DNS failures as unsafe (returns True).
    """
    try:
        # FIXED: syntax error here (your code had "None." and missed a closing paren)
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

        # IMPORTANT: disallow odd ports
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
    return t[:limit].rstrip() + "…"


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

        # FIX: you returned category="science" but it was not in valid_categories
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
            "consensus", "consensuses",
            "practice guideline", "practice guidelines",
            "recommendation", "recommendations",
            "recommended", "recommend",
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

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def _is_research_query(self, query_lower: str) -> bool:
        return any(t in query_lower for t in self.research_terms)

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
        matches = set()

        if self._looks_like_forex_pair(query_lower):
            matches.add("forex")
        if any(t in query_lower for t in self.crypto_terms):
            matches.add("crypto")
        if any(t in query_lower for t in self.index_terms):
            matches.add("stock/commodity")

        stock_keywords = ["stock", "stocks", "share price", "shares", "ticker", "price of"]
        if any(k in query_lower for k in stock_keywords):
            matches.add("stock/commodity")
        if re.search(r"\b[A-Z]{3,5}\b", query_lower.upper()):
            matches.add("stock/commodity")

        if any(t in query_lower for t in self.weather_terms):
            matches.add("weather")
        if any(t in query_lower for t in self.news_terms):
            matches.add("news")

        if len(matches) == 1:
            return next(iter(matches))
        return None

    def _sanity_validate_intent(self, intent: str, ql: str) -> str:
        intent = intent if intent in self.valid_categories else "general"

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

        # NOTE: "science" only comes from Agentpedia path, not LLM classifier
        if intent == "science":
            return "science"

        return intent

    # FIXED: your signature had "retries: int HISTORY = 3" which is invalid syntax
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
                    model=INSTRUCT_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.0, "think": False},
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

    async def search(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        query = (query or "").strip()
        if not query:
            return [{"title": "Error", "url": "", "description": "Empty query.", "category": "general", "volatile": False}]

        query_lower = query.lower().strip()
        logger.info(f"Processing query: '{query}'")

        parsed = parse_conversion_request(query)
        if parsed is not None:
            try:
                answer = await self.converter.convert(query)
                if answer and "Error" not in answer:
                    return [{
                        "title": f"{parsed.amount:g} {parsed.src.upper()} → {parsed.dst.upper()}",
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

        forced = self._force_intent_from_terms(query_lower)
        if forced:
            try:
                if forced == "stock/commodity":
                    res = await self.finance_handler.search_stocks_commodities(query_lower)
                    return self._tag(res, "stock/commodity", True)
                if forced == "crypto":
                    res = await self.finance_handler.search_crypto_yfinance(query)
                    return self._tag(res, "crypto", True)
                if forced == "forex":
                    res = await self.finance_handler.search_forex_yfinance(query_lower)
                    return self._tag(res, "forex", True)
                if forced == "weather":
                    res = await self.weather_handler.search_weather(query, retries, backoff_factor)
                    return self._tag(res, "weather", True)
                if forced == "news":
                    res = await self.news_handler.search_news(query, retries, backoff_factor)
                    return self._tag(res, "news", True)
            except Exception as e:
                logger.error(f"Forced routing failed for '{query}' ({forced}): {e}\n{traceback.format_exc()}")

        # Research/science path (Agentpedia) - only if strong research keywords
        if self._is_research_query(query_lower):
            if self.agentpedia:
                try:
                    research_results = await self.agentpedia.search(query)
                    if research_results and not any(
                        "insufficient coverage" in str(r.get("title", "")).lower()
                        or "unavailable" in str(r.get("title", "")).lower()
                        for r in research_results
                    ):
                        logger.info(f"Agentpedia successful for '{query}' ({len(research_results)} results)")
                        return self._tag(research_results, "science", True)
                except Exception as e:
                    logger.warning(f"Agentpedia failed for '{query}': {e}")

            logger.info(f"Agentpedia unavailable or insufficient → falling back for '{query}'")

        query_type = await self._classify_query(query, retries=retries, backoff_factor=backoff_factor)
        query_type = self._sanity_validate_intent(query_type, query_lower)

        try:
            if query_type == "stock/commodity":
                res = await self.finance_handler.search_stocks_commodities(query)
                return self._tag(res, "stock/commodity", True)
            if query_type == "crypto":
                res = await self.finance_handler.search_crypto_yfinance(query)
                return self._tag(res, "crypto", True)
            if query_type == "forex":
                res = await self.finance_handler.search_forex_yfinance(query_lower)
                return self._tag(res, "forex", True)
            if query_type == "weather":
                res = await self.weather_handler.search_weather(query, retries, backoff_factor)
                return self._tag(res, "weather", True)
            if query_type == "news":
                res = await self.news_handler.search_news(query, retries, backoff_factor)
                return self._tag(res, "news", True)

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

        q_key = self._normalize_cache_key(q)
        cache_key = f"general::{q_key}"
        cached = self.search_cache.get(cache_key)
        if isinstance(cached, list) and cached:
            return cached

        for attempt in range(retries):
            try:
                raw = await self._ddg_text(q, max_results=18)
                base = self._normalize_ddg_results(raw)
                base = self._dedupe_results(base)

                enriched = await self._fetch_and_attach_content(
                    base,
                    category="general",
                    top_n=3,
                    max_n=6,
                )

                # SearXNG fallback if DDG is weak
                if len(enriched) < 3:
                    logger.info(f"DDG weak ({len(enriched)} enriched results) for '{q}' — enriching with SearXNG")
                    async with httpx.AsyncClient(timeout=12.0) as local_client:
                        extra = await search_searxng(
                            local_client,
                            q,
                            max_results=8,
                            category="general",
                            source_name="searxng_fallback",
                            domain="general"
                        )
                        existing_urls = {r.get("url", "") for r in enriched}
                        extra_deduped = [r for r in extra if r.get("url", "") not in existing_urls]
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

    def format_results(self, results: list) -> str:
        if not results:
            return "No search results found."

        lines = []
        for r in results[:10]:
            if not isinstance(r, dict):
                continue

            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            desc = (r.get("description") or "").strip()
            content = (r.get("content") or "").strip()
            category = (r.get("category") or "").strip()
            volatile = bool(r.get("volatile", False))

            block = (
                f"- Title: {title}\n"
                f"  URL: {url}\n"
                f"  Snippet: {_safe_trim(desc, 280)}\n"
                f"  Meta: category={category}, volatile={volatile}"
            )
            if content:
                block += f"\n  Extracted: {_safe_trim(content, 700)}"

            lines.append(block)

        return "## Web/Search Context (results)\n" + "\n".join(lines)
