"""
Shared SearXNG searcher — free, local metasearch fallback/enrichment.
No auth/key required (self-hosted Docker).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import httpx

from config.settings import SEARXNG_BASE_URL
from handlers.research.base import pack_result, safe_trim
from handlers.websearch_tools.search_common import SearchProfile

logger = logging.getLogger(__name__)

_SEARXNG_SEM = asyncio.Semaphore(3)
_CAPABILITY_TTL_S = 900
_CAPABILITY_CACHE: Dict[str, Dict[str, Any]] = {}

# keep conservative; categories differ between instances and are optional anyway
_ALLOWED_CATEGORIES = {"general", "news", "science", "it", "files", "images", "videos", "finance"}

_PROFILES: Dict[str, SearchProfile] = {
    "general": SearchProfile(name="general", category="general", safe=0, domain="general"),
    "news": SearchProfile(name="news", category="news", time_range="day", safe=1, domain="news"),
    "science": SearchProfile(name="science", category="science", engines=["arxiv", "pubmed", "semantic_scholar"], safe=0, domain="science"),
    "finance_current": SearchProfile(name="finance_current", category="finance", time_range="day", safe=0, domain="finance_current"),
    "finance_historical": SearchProfile(name="finance_historical", category="general", time_range="year", safe=1, domain="finance_historical"),
    "weather": SearchProfile(name="weather", category="general", safe=0, domain="weather"),
    # Research domain-specialized profiles
    "science_biomed": SearchProfile(name="science_biomed", category="science", engines=["pubmed", "semantic_scholar"], safe=0, domain="biomed"),
    "science_engineering": SearchProfile(name="science_engineering", category="science", engines=["arxiv", "semantic_scholar"], safe=0, domain="engineering"),
    "science_nutrition": SearchProfile(name="science_nutrition", category="science", engines=["pubmed", "semantic_scholar"], safe=0, domain="nutrition"),
    "science_religion": SearchProfile(name="science_religion", category="general", engines=["wikipedia", "duckduckgo"], safe=1, domain="religion"),
    "science_entertainment": SearchProfile(name="science_entertainment", category="general", engines=["wikipedia", "duckduckgo"], safe=1, domain="entertainment"),
    "science_business_administrator": SearchProfile(name="science_business_administrator", category="general", engines=["duckduckgo"], safe=1, domain="business_administrator"),
    "science_journalism_communication": SearchProfile(name="science_journalism_communication", category="news", engines=["duckduckgo"], safe=1, domain="journalism_communication"),
}

_DOMAIN_TO_PROFILE: Dict[str, str] = {
    "biomed": "science_biomed",
    "engineering": "science_engineering",
    "nutrition": "science_nutrition",
    "religion": "science_religion",
    "entertainment": "science_entertainment",
    "business_administrator": "science_business_administrator",
    "journalism_communication": "science_journalism_communication",
}


def _pick(res: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _cache_key(base: str) -> str:
    return (base or "").strip().rstrip("/")


async def _detect_capabilities(client: httpx.AsyncClient, base: str) -> Dict[str, Any]:
    """
    Best-effort runtime capability matrix.
    We probe /config (if available) and gracefully fallback to permissive defaults.
    """
    k = _cache_key(base)
    now = time.time()
    cached = _CAPABILITY_CACHE.get(k)
    if cached and (now - float(cached.get("at", 0))) <= _CAPABILITY_TTL_S:
        return dict(cached.get("caps") or {})

    caps = {
        "categories": set(_ALLOWED_CATEGORIES),
        "engines": set(),
        "supports_time_range": True,
        "supports_language": True,
        "supports_safesearch": True,
    }

    cfg_url = urljoin(base + "/", "config")
    try:
        r = await client.get(cfg_url, timeout=3.0)
        if r.status_code == 200:
            js = r.json() if "json" in (r.headers.get("content-type") or "").lower() else {}
            if isinstance(js, dict):
                cats = js.get("categories")
                if isinstance(cats, list) and cats:
                    caps["categories"] = {str(c).strip().lower() for c in cats if str(c).strip()}
                eng = js.get("engines")
                if isinstance(eng, list):
                    names = set()
                    for e in eng:
                        if isinstance(e, dict):
                            n = str(e.get("name") or "").strip()
                            if n:
                                names.add(n)
                        elif isinstance(e, str) and e.strip():
                            names.add(e.strip())
                    caps["engines"] = names
    except Exception:
        pass

    _CAPABILITY_CACHE[k] = {"at": now, "caps": caps}
    return caps


async def search_searxng(
    client: httpx.AsyncClient,
    query: str,
    *,
    max_results: int = 8,
    profile: str = "general",
    category: Optional[str] = None,
    engines: Optional[List[str]] = None,
    time_range: Optional[str] = None,
    language: Optional[str] = None,
    safe: Optional[int | str] = None,
    domain: Optional[str] = None,
    source_name: str = "searxng",
) -> List[Dict[str, Any]]:
    """
    Shared async SearXNG search — returns pack_result-compatible dicts.
    """
    q = (query or "").strip()
    if not q:
        return []

    base = (SEARXNG_BASE_URL or "").strip().rstrip("/")
    if not base:
        logger.debug("SEARXNG_BASE_URL not set; skipping searxng search")
        return []

    p = _PROFILES.get((profile or "").strip(), _PROFILES["general"])
    # If caller passes domain but no explicit profile, auto-pick specialized research profile.
    if (profile or "general").strip() == "general" and domain:
        mapped = _DOMAIN_TO_PROFILE.get(str(domain).strip().lower())
        if mapped:
            p = _PROFILES.get(mapped, p)
    chosen_cat = str(category or p.category or "general").strip().lower()
    chosen_engines = engines if engines is not None else list(p.engines)
    chosen_time_range = time_range if time_range is not None else p.time_range
    chosen_language = language if language is not None else p.language
    chosen_safe = safe if safe is not None else p.safe
    chosen_domain = str(domain or p.domain or profile or "general")

    caps = await _detect_capabilities(client, base)
    allowed_cats = set(caps.get("categories") or _ALLOWED_CATEGORIES)
    if chosen_cat not in allowed_cats:
        chosen_cat = "general"

    allowed_engines = set(caps.get("engines") or set())
    if chosen_engines and allowed_engines:
        chosen_engines = [e for e in chosen_engines if str(e) in allowed_engines]

    search_url = urljoin(base + "/", "search")

    params = {
        "q": q,
        "format": "json",
        "pageno": 1,
        "categories": chosen_cat,
    }
    if chosen_engines:
        if isinstance(chosen_engines, (list, tuple, set)):
            joined = ",".join(str(e).strip() for e in chosen_engines if str(e).strip())
            if joined:
                params["engines"] = joined
        elif isinstance(chosen_engines, str):
            params["engines"] = chosen_engines
    if chosen_time_range and bool(caps.get("supports_time_range", True)):
        params["time_range"] = str(chosen_time_range)
    if chosen_language and bool(caps.get("supports_language", True)):
        params["language"] = str(chosen_language)
    if chosen_safe is not None and bool(caps.get("supports_safesearch", True)):
        params["safesearch"] = str(chosen_safe)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)",
        "Accept": "application/json",
    }

    async with _SEARXNG_SEM:
        try:
            r = await client.get(search_url, params=params, headers=headers, timeout=10.0)
            if r.status_code != 200:
                logger.debug(f"SearXNG error {r.status_code} for '{q}'")
                return []
            js = r.json()
        except Exception as e:
            logger.debug(f"SearXNG request failed for '{q}': {e}")
            return []

    raw_results = js.get("results", []) or []
    if not isinstance(raw_results, list):
        return []

    out: List[Dict[str, Any]] = []
    for res in raw_results[: max_results]:
        if not isinstance(res, dict):
            continue

        title = _pick(res, "title") or "SearXNG Result"
        url2 = _pick(res, "url")
        content = _pick(res, "content", "snippet", "description")
        published = _pick(res, "publishedDate", "pubdate", "published_at", "date")

        if not url2:
            continue

        desc = content
        if published:
            desc = f"[{published}] {desc}" if desc else f"[{published}]"

        spans = [safe_trim(desc, 300)] if desc else []

        r_dict = pack_result(
            title=title,
            url=url2,
            description=safe_trim(desc, 800),
            source=source_name,
            domain=chosen_domain,
            id_type="url",
            id=url2,
            published=published,
            evidence_level="web_search",
            evidence_spans=spans[:6],
        )
        r_dict["volatile"] = True
        r_dict["provider"] = "searxng"
        out.append(r_dict)

    logger.info("SearXNG returned %d results for '%s' (category=%s, profile=%s)", len(out), q, chosen_cat, profile)
    return out
