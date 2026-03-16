# handlers/websearch_tools/news.py
"""
NewsHandler (DDG news) with:
- recency hygiene (ensure "today" when appropriate)
- optional region bias for generic "current news" using DEFAULT_NEWS_REGION
- ambiguity handling (e.g., "Trinidad" â†’ person/sports noise)
- one deterministic rewrite retry, then a clarification prompt if still ambiguous
"""

import asyncio
import logging
import re
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import ollama
from duckduckgo_search import DDGS

from config.settings import WEBSEARCH_MODEL, SYSTEM_TIMEZONE, SEARXNG_DOMAIN_PROFILES
import pytz
from datetime import datetime

from runtime.ollama_options import build_ollama_chat_options

logger = logging.getLogger(__name__)

try:
    from config.settings import DEFAULT_NEWS_REGION as _DEFAULT_NEWS_REGION
except Exception:
    _DEFAULT_NEWS_REGION = ""


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


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
    timeout_s: float = 12.0,
    max_bytes: int = 1_500_000,
) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)"}
        r = await client.get(url, headers=headers, timeout=timeout_s, follow_redirects=True)
        if r.status_code >= 400:
            return ""
        ctype = (r.headers.get("content-type") or "").lower()
        if not ("text/html" in ctype or "application/xhtml+xml" in ctype or "text/plain" in ctype):
            return ""
        content = r.content[:max_bytes]
        try:
            html = content.decode(r.encoding or "utf-8", errors="ignore")
        except Exception:
            html = content.decode("utf-8", errors="ignore")
        extracted = _extract_main_text(html)
        return extracted.strip() if extracted else ""
    except Exception:
        return ""


def _normalize_space(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _contains_any(text: str, needles: List[str]) -> bool:
    tl = (text or "").lower()
    return any(n.lower() in tl for n in needles)


_GENERIC_NEWS_TRIGGERS = (
    "current news",
    "latest news",
    "headlines",
    "breaking news",
    "news today",
    "what's new",
    "whats new",
    "what is happening",
)


def _apply_region_bias_if_generic(query: str) -> str:
    q = _normalize_space(query)
    ql = q.lower()

    if not _DEFAULT_NEWS_REGION:
        return q

    generic = any(k in ql for k in _GENERIC_NEWS_TRIGGERS)
    if not generic:
        return q

    mentions_world = any(k in ql for k in ["world", "global", "international"])
    mentions_us = any(k in ql for k in [" usa", " us ", "united states", "america", "american"])
    mentions_specific_place = bool(re.search(r"\b(in|for|from)\s+[a-zA-Z]", ql))

    if mentions_world or mentions_us or mentions_specific_place:
        return q

    return f"{_DEFAULT_NEWS_REGION} {q}".strip()


@dataclass
class AmbiguityRule:
    term: str
    place_rewrite: str
    wrong_sense_keywords: List[str]
    user_override_keywords: List[str]


AMBIGUITY_RULES: List[AmbiguityRule] = [
    AmbiguityRule(
        term="trinidad",
        place_rewrite="trinidad and tobago",
        wrong_sense_keywords=[
            "chambliss", "ncaa", "ole miss", "qb", "quarterback", "rebels",
            "touchdown", "sec", "injunction", "eligibility", "lawsuit",
        ],
        user_override_keywords=[
            "chambliss", "ncaa", "ole miss", "qb", "quarterback",
        ],
    ),
]


def _apply_ambiguity_hygiene(user_query: str) -> Tuple[str, Optional[str]]:
    q = _normalize_space(user_query)
    ql = q.lower()

    for rule in AMBIGUITY_RULES:
        if re.search(rf"\b{re.escape(rule.term)}\b", ql):
            if _contains_any(ql, rule.user_override_keywords):
                return q, None
            if rule.place_rewrite in ql:
                return q, None
            rewritten = re.sub(
                rf"\b{re.escape(rule.term)}\b", rule.place_rewrite, q, flags=re.IGNORECASE
            )
            return rewritten, rule.term

    return q, None


def _results_look_wrong_for_rule(results: List[Dict[str, Any]], rule: AmbiguityRule, top_n: int = 5) -> bool:
    if not results or not rule:
        return False

    score = 0
    checked = 0
    term_lower = rule.term.lower()

    for r in results[:max(1, int(top_n))]:
        title = str(r.get("title", "") or "").lower()
        desc = str(r.get("description", "") or "").lower()
        blob = f"{title} {desc}"

        has_term = term_lower in blob
        has_wrong = any(k.lower() in blob for k in rule.wrong_sense_keywords)

        if has_term and has_wrong:
            score += 1
        checked += 1

    return checked >= 3 and score >= 3 and (score / checked) >= 0.60


def _build_clarification(rule: AmbiguityRule) -> Dict[str, Any]:
    if rule.term == "trinidad":
        msg = (
            "Iâ€™m not sure what you mean by â€œTrinidadâ€.\n"
            "- Do you mean **Trinidad & Tobago (local news)**?\n"
            "- Or **Trinidad (a person/name/topic)**?\n"
            "Reply with either **â€œTrinidad & Tobagoâ€** or **â€œTrinidad (person)â€** and Iâ€™ll rerun the search."
        )
    else:
        msg = f"Iâ€™m not sure what you mean by â€œ{rule.term}â€. Can you clarify the place/meaning you intend?"

    return {
        "title": "Clarification needed",
        "url": "",
        "description": msg,
        "source": "somi_disambiguation",
    }


class NewsHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)
        self._fetch_sem = asyncio.Semaphore(3)

        self._cache: Dict[str, Any] = {}
        self._cache_exp: Dict[str, float] = {}
        self._ttl = 600  # 10 min

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def _cache_get(self, key: str) -> Optional[Any]:
        exp = self._cache_exp.get(key)
        loop_time = asyncio.get_event_loop().time()
        if not exp or exp < loop_time:
            self._cache.pop(key, None)
            self._cache_exp.pop(key, None)
            return None
        return self._cache.get(key)

    def _cache_set(self, key: str, val: Any) -> None:
        self._cache[key] = val
        self._cache_exp[key] = asyncio.get_event_loop().time() + self._ttl

    def _clean_refined_query(self, raw: str, fallback: str) -> str:
        try:
            text = (raw or "").strip()
            if not text:
                return fallback

            text = re.sub(r"<[^>]+>", " ", text)
            text = text.replace("**", " ").replace("`", " ")
            text = re.sub(r"[\r\n\t]+", "\n", text).strip()

            m = re.search(r"^\s*(?:answer|refined)\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            if m:
                text = m.group(1).strip()

            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            text = lines[-1] if lines else fallback

            if len(text) > 140:
                text = text[:140].rstrip()

            bad = [
                "think",
                "reasoning",
                "category",
                "output exactly",
                "note:",
                "output above",
                "actual output may vary",
                "just an example",
            ]
            if any(b in text.lower() for b in bad):
                return fallback

            # Reject sentence-like meta responses; keep concise query-like strings only.
            if re.search(r"[.!?]{2,}", text):
                return fallback
            if len(re.findall(r"\w+", text)) > 20:
                return fallback

            return text
        except Exception:
            return fallback

    async def _bounded_fetch(self, client: httpx.AsyncClient, url: str) -> str:
        async with self._fetch_sem:
            return await _fetch_url_text(client, url)

    async def _enrich_top_pages(self, results: List[Dict[str, Any]], top_n: int = 2) -> List[Dict[str, Any]]:
        if not results:
            return results
        pick = [r for r in results[: max(1, int(top_n))] if isinstance(r, dict) and r.get("url")]
        if not pick:
            return results

        try:
            async with httpx.AsyncClient() as client:
                tasks = [self._bounded_fetch(client, r["url"]) for r in pick]
                fetched = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            return results

        url_to_text: Dict[str, str] = {}
        for r, txt in zip(pick, fetched):
            if isinstance(txt, str) and txt.strip():
                url_to_text[r["url"]] = txt.strip()

        out: List[Dict[str, Any]] = []
        for r in results:
            rr = dict(r)
            txt = url_to_text.get(str(r.get("url") or ""))
            if txt:
                rr["content"] = _safe_trim(txt, 6000)
            out.append(rr)
        return out
    def _refine_query_llm(self, q: str) -> Tuple[str, str]:
        raw_q = _normalize_space(q)
        fallback_refined = raw_q

        if "today" not in fallback_refined.lower() and not re.search(r"\b(202\d|201\d)\b", fallback_refined):
            if not any(k in fallback_refined.lower() for k in ["yesterday", "last week", "last month"]):
                fallback_refined = fallback_refined.strip() + " today"

        prompt = f"""
Output EXACTLY a refined DuckDuckGo news query string. Use "today" for recency when appropriate.
Do NOT output anything else.
Query: {raw_q}
""".strip()

        refined = fallback_refined
        try:
            resp = ollama.chat(
                model=WEBSEARCH_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options=build_ollama_chat_options(model=WEBSEARCH_MODEL, role="websearch", temperature=0.2),
            )
            raw_out = (resp.get("message", {}) or {}).get("content", "") or ""
            refined = self._clean_refined_query(raw_out, fallback_refined)
        except Exception:
            refined = fallback_refined

        return refined, fallback_refined
    async def _searx_news(self, query: str, max_results: int = 15) -> List[Dict[str, Any]]:
        try:
            from workshop.toolbox.stacks.research_core.searxng import search_searxng
        except Exception:
            return []

        p = (SEARXNG_DOMAIN_PROFILES or {}).get("news", {}) if isinstance(SEARXNG_DOMAIN_PROFILES, dict) else {}
        prof = str(p.get("profile") or "news")
        cat = str(p.get("category") or "news")
        src = str(p.get("source_name") or "searxng_news")
        pages = int(p.get("max_pages", 2))
        cap = int(p.get("max_results", max_results))

        attempts = [
            (prof, cat, src),
            ("general", "general", "searxng_news_general"),
        ]

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for prof_i, cat_i, src_i in attempts:
                    rows = await search_searxng(
                        client,
                        query,
                        max_results=min(max_results, cap),
                        max_pages=pages,
                        profile=prof_i,
                        category=cat_i,
                        source_name=src_i,
                        domain="news",
                    )
                    norm = self._normalize_searx_news(rows)
                    if norm:
                        return norm
            return []
        except Exception as e:
            logger.debug(f"SearXNG news failed: {e}")
            return []

    async def _ddg_news(self, query: str, max_results: int = 15) -> List[Dict[str, Any]]:
        def _run():
            with DDGS() as ddgs:
                return list(ddgs.news(query, max_results=max_results))

        try:
            return await asyncio.to_thread(_run)
        except Exception as e:
            logger.warning(f"DDG news failed: {e}")
            return []

    def _normalize_ddg_news(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            url = (r.get("url") or r.get("href") or r.get("link") or "").strip()
            if not url:
                continue
            published = r.get("date") or r.get("published") or r.get("published_at") or ""
            out.append(
                {
                    "title": (r.get("title") or "").strip(),
                    "url": url,
                    "description": (r.get("snippet") or r.get("description") or "").strip(),
                    "source": "ddg_news",
                    "provider": "ddg",
                    "published_at": published,
                }
            )
        return out

    def _normalize_searx_news(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            url = (r.get("url") or r.get("href") or r.get("link") or "").strip()
            if not url:
                continue
            out.append(
                {
                    "title": (r.get("title") or "").strip(),
                    "url": url,
                    "description": (r.get("description") or r.get("snippet") or "").strip(),
                    "source": str(r.get("source") or "searxng"),
                    "provider": "searxng",
                    "published_at": r.get("publishedDate") or r.get("date") or "",
                }
            )
        return out

    def _query_relevance_score(self, query: str, rows: List[Dict[str, Any]]) -> int:
        tokens = {t for t in re.findall(r"[a-z0-9]{3,}", (query or "").lower())}
        stop = {"news", "latest", "today", "about", "what", "whats", "the", "and", "for", "from"}
        tokens = {t for t in tokens if t not in stop}
        if not tokens:
            return 0

        best = 0
        for r in rows[:5]:
            blob = f"{r.get('title', '')} {r.get('description', '')}".lower()
            score = sum(1 for t in tokens if t in blob)
            if score > best:
                best = score
        return best

    def _prefer_ddg_over_searx(self, query: str, searx_rows: List[Dict[str, Any]], ddg_rows: List[Dict[str, Any]]) -> bool:
        if not ddg_rows:
            return False
        if not searx_rows:
            return True

        searx_score = self._query_relevance_score(query, searx_rows)
        ddg_score = self._query_relevance_score(query, ddg_rows)

        if ddg_score > searx_score:
            return True
        if searx_score == 0 and ddg_score >= 1:
            return True
        return False

    async def _search_once(self, refined_query: str, retries: int, backoff_factor: float) -> List[Dict[str, Any]]:
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                raw = await self._ddg_news(refined_query, max_results=15)
                base = self._normalize_ddg_news(raw)
                enriched = await self._enrich_top_pages(base, top_n=2)
                return enriched
            except Exception as e:
                last_err = e
                logger.error(f"DDG news error (attempt {attempt+1}/{retries}): {e}\n{traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
        if last_err:
            logger.warning(f"News search failed: {last_err}")
        return []

    async def search_news(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        q = _normalize_space(query)
        if not q:
            return [{"title": "Error", "url": "", "description": "Empty query.", "source": "ddg_news", "provider": "ddg"}]

        cache_key = f"news::{q.lower()}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, list) and cached:
            return cached

        q = _apply_region_bias_if_generic(q)
        q_hyg, applied_term = _apply_ambiguity_hygiene(q)

        # Keep searx aligned to original user wording (before LLM refinement).
        searx_results = await self._searx_news(q_hyg, max_results=15)

        refined_query, _ = await asyncio.to_thread(self._refine_query_llm, q_hyg)
        ddg_results = await self._search_once(refined_query, retries=retries, backoff_factor=backoff_factor)

        if self._prefer_ddg_over_searx(q_hyg, searx_results, ddg_results):
            results = ddg_results or searx_results
        else:
            results = searx_results or ddg_results

        if applied_term:
            rule = next((r for r in AMBIGUITY_RULES if r.term == applied_term), None)
            if rule and _results_look_wrong_for_rule(results, rule, top_n=5):
                forced = re.sub(
                    rf"\b{re.escape(rule.term)}\b", rule.place_rewrite, q, flags=re.IGNORECASE
                ).strip()

                if "today" not in forced.lower() and "news" not in forced.lower():
                    forced = forced + " news today"

                forced_ddg = await self._search_once(forced, retries=2, backoff_factor=backoff_factor)
                forced_searx = await self._searx_news(forced, max_results=15)

                if self._prefer_ddg_over_searx(forced, forced_searx, forced_ddg):
                    forced_results = forced_ddg or forced_searx
                else:
                    forced_results = forced_searx or forced_ddg

                if forced_results and not _results_look_wrong_for_rule(forced_results, rule, top_n=5):
                    results = forced_results
                else:
                    results = [_build_clarification(rule)]

        if not results:
            broader = q.replace("today", "").strip() + " news"
            broader_searx = await self._searx_news(broader, max_results=15)
            broader_ddg = await self._search_once(broader, retries=2, backoff_factor=backoff_factor)
            if self._prefer_ddg_over_searx(broader, broader_searx, broader_ddg):
                results = broader_ddg or broader_searx
            else:
                results = broader_searx or broader_ddg

        self._cache_set(cache_key, results)
        return results







