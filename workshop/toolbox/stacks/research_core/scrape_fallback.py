from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from config.settings import (
    SCRAPER_LLM_RERANK,
    SCRAPER_MAX_PAGE_OPENS,
    SCRAPER_MAX_RESULT_LINKS,
    SCRAPER_MODEL,
    SCRAPER_PAGE_TIMEOUT_MS,
    SCRAPER_TEMP_DIR,
    SCRAPER_USE_PLAYWRIGHT,
)
from workshop.toolbox.stacks.research_core.base import pack_result, safe_trim
from runtime.ollama_options import build_ollama_chat_options

try:
    import ollama
except Exception:  # pragma: no cover
    ollama = None  # type: ignore

logger = logging.getLogger(__name__)


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


def _is_pdf(url: str, content_type: str) -> bool:
    ul = str(url or "").lower()
    ct = str(content_type or "").lower()
    return ul.endswith(".pdf") or "application/pdf" in ct


async def _extract_pdf_excerpt(raw_bytes: bytes) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            chunks: List[str] = []
            for page in pdf.pages[:3]:
                txt = page.extract_text() or ""
                txt = txt.strip()
                if txt:
                    chunks.append(txt)
            return "\n\n".join(chunks).strip()
    except Exception:
        return ""


async def _fetch_page_excerpt(client: httpx.AsyncClient, url: str, *, timeout_s: float = 12.0) -> str:
    try:
        r = await client.get(url, timeout=timeout_s, follow_redirects=True)
        if r.status_code >= 400:
            return ""

        content = r.content[:1_500_000]
        ctype = str(r.headers.get("content-type") or "").lower()

        if _is_pdf(str(r.url), ctype):
            return safe_trim(await _extract_pdf_excerpt(content), 9000)

        if not ("text/html" in ctype or "application/xhtml+xml" in ctype or "text/plain" in ctype):
            return ""

        try:
            html = content.decode(r.encoding or "utf-8", errors="ignore")
        except Exception:
            html = content.decode("utf-8", errors="ignore")

        text = _extract_main_text(html)
        return safe_trim(text, 9000) if text else ""
    except Exception:
        return ""


def _tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", str(text or "").lower()) if t]


def _domain_boost(url: str) -> int:
    host = (urlparse(str(url or "")).netloc or "").lower()
    strong = (
        "who.int",
        "cdc.gov",
        "nih.gov",
        "heart.org",
        "escardio.org",
        "acc.org",
        "ahajournals.org",
        "hypertension.ca",
        "nice.org.uk",
    )
    if ".gov" in host:
        return 4
    for d in strong:
        if d in host:
            return 5
    return 0


def _heuristic_rank(query: str, row: Dict[str, Any]) -> int:
    q_tokens = set(_tokenize(query))
    title = str(row.get("title") or "")
    snippet = str(row.get("snippet") or "")
    content = str(row.get("content") or "")
    url = str(row.get("url") or "")
    blob = f"{title} {snippet} {content}".lower()

    score = 0
    if q_tokens:
        overlap = sum(1 for t in q_tokens if t in blob)
        score += overlap

    if any(k in blob for k in ("guideline", "consensus", "recommendation", "statement")):
        score += 4
    if re.search(r"\b(202[4-9]|203\d)\b", blob):
        score += 2

    score += _domain_boost(url)
    return score


def _parse_ranked_urls(raw: str) -> List[str]:
    text = str(raw or "").strip()
    if not text:
        return []

    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    candidate = text
    if "[" in text and "]" in text:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            candidate = text[start : end + 1]

    try:
        data = json.loads(candidate)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    out: List[str] = []
    for item in data:
        s = str(item or "").strip()
        if s.startswith("http") and s not in out:
            out.append(s)
    return out


async def _llm_rerank_urls(query: str, rows: List[Dict[str, Any]]) -> List[str]:
    if not rows or not SCRAPER_LLM_RERANK or ollama is None:
        return []

    payload = []
    for i, row in enumerate(rows[:12], 1):
        payload.append(
            {
                "idx": i,
                "title": str(row.get("title") or "")[:220],
                "url": str(row.get("url") or ""),
                "snippet": str(row.get("snippet") or "")[:320],
                "excerpt": str(row.get("content") or "")[:700],
            }
        )

    prompt = (
        "Rank these sources for answering the user query accurately. "
        "Prioritize official guidelines/consensus statements and recency. "
        "Return ONLY a JSON array of URLs in best-to-worst order.\n\n"
        f"Query: {query}\n\n"
        f"Candidates JSON:\n{json.dumps(payload, ensure_ascii=True)}"
    )

    def _chat() -> str:
        resp = ollama.chat(
            model=SCRAPER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options=build_ollama_chat_options(model=SCRAPER_MODEL, role="scraper", temperature=0.0, max_tokens=300),
        )
        return str((resp.get("message", {}) or {}).get("content", "") or "")

    try:
        raw = await asyncio.to_thread(_chat)
        return _parse_ranked_urls(raw)
    except Exception as e:
        logger.debug(f"Scraper LLM rerank failed: {e}")
        return []


def _write_temp_artifact(query: str, rows: List[Dict[str, Any]]) -> str:
    try:
        os.makedirs(SCRAPER_TEMP_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        digest = hashlib.sha1(f"{query}|{stamp}".encode("utf-8", errors="ignore")).hexdigest()[:10]
        path = os.path.join(SCRAPER_TEMP_DIR, f"scrape_{stamp}_{digest}.json")
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "count": len(rows),
            "rows": rows,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return path
    except Exception:
        return ""


async def _scrape_searx_results(query: str, *, base_url: str, max_links: int, timeout_ms: int) -> List[Dict[str, str]]:
    if not SCRAPER_USE_PLAYWRIGHT:
        return []

    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        logger.debug(f"Playwright unavailable for scraper fallback: {e}")
        return []

    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return []

    search_url = urljoin(base + "/", f"search?q={quote_plus(query)}&language=auto&categories=general&safesearch=0")

    browser = None
    context = None
    page = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(search_url, wait_until="domcontentloaded", timeout=int(timeout_ms))
            await page.wait_for_timeout(350)

            rows = await page.evaluate(
                """
                (maxLinks) => {
                  const out = [];
                  const seen = new Set();
                  const nodes = Array.from(document.querySelectorAll('article.result, #urls article, .result'));
                  for (const node of nodes) {
                    const a = node.querySelector('h3 a, h4 a, a[href]');
                    if (!a) continue;
                    const href = a.href || a.getAttribute('href') || '';
                    if (!href || !href.startsWith('http') || seen.has(href)) continue;
                    seen.add(href);
                    const title = (a.textContent || '').trim();
                    const sn = node.querySelector('p.content, .content, .result-content, .description, p');
                    const snippet = sn ? (sn.textContent || '').trim() : '';
                    out.push({ title, url: href, snippet });
                    if (out.length >= maxLinks) break;
                  }

                  if (!out.length) {
                    const links = Array.from(document.querySelectorAll('a[href]'));
                    for (const a of links) {
                      const href = a.href || a.getAttribute('href') || '';
                      const title = (a.textContent || '').trim();
                      if (!href || !href.startsWith('http') || !title) continue;
                      if (seen.has(href)) continue;
                      seen.add(href);
                      out.push({ title, url: href, snippet: '' });
                      if (out.length >= maxLinks) break;
                    }
                  }

                  return out;
                }
                """,
                int(max_links),
            )

            clean_rows: List[Dict[str, str]] = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                title = str(row.get("title") or "").strip()
                snippet = str(row.get("snippet") or "").strip()
                if not url or not url.startswith("http"):
                    continue
                clean_rows.append({"url": url, "title": title, "snippet": snippet})
            return clean_rows
    except Exception as e:
        logger.debug(f"Playwright SearX scrape failed for '{query}': {e}")
        return []
    finally:
        try:
            if page is not None:
                await page.close()
        except Exception:
            pass
        try:
            if context is not None:
                await context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                await browser.close()
        except Exception:
            pass


async def scrape_searx_with_playwright(
    *,
    query: str,
    base_url: str,
    domain: str = "general",
    source_name: str = "searxng_scrape",
    max_results: int = 8,
    max_links: int | None = None,
    max_page_opens: int | None = None,
    timeout_ms: int | None = None,
) -> List[Dict[str, Any]]:
    q = str(query or "").strip()
    if not q:
        return []

    max_links_effective = int(max_links or SCRAPER_MAX_RESULT_LINKS or 8)
    max_pages_effective = int(max_page_opens or SCRAPER_MAX_PAGE_OPENS or 3)
    timeout_effective = int(timeout_ms or SCRAPER_PAGE_TIMEOUT_MS or 12000)

    searx_rows = await _scrape_searx_results(
        q,
        base_url=base_url,
        max_links=max_links_effective,
        timeout_ms=timeout_effective,
    )
    if not searx_rows:
        return []

    picked = searx_rows[: max(1, max_pages_effective)]
    sem = asyncio.Semaphore(3)

    async with httpx.AsyncClient(
        timeout=12.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)"},
    ) as client:

        async def _enrich(row: Dict[str, str]) -> Dict[str, Any]:
            async with sem:
                content = await _fetch_page_excerpt(client, str(row.get("url") or ""), timeout_s=12.0)
            return {
                "title": str(row.get("title") or "").strip() or "Web Result",
                "url": str(row.get("url") or "").strip(),
                "snippet": str(row.get("snippet") or "").strip(),
                "content": content,
            }

        enriched = await asyncio.gather(*[_enrich(r) for r in picked], return_exceptions=True)

    rows: List[Dict[str, Any]] = []
    for r in enriched:
        if isinstance(r, dict) and str(r.get("url") or "").startswith("http"):
            rows.append(r)

    if not rows:
        return []

    artifact_path = _write_temp_artifact(q, rows)

    ranked_urls = await _llm_rerank_urls(q, rows)
    if ranked_urls:
        order = {u: i for i, u in enumerate(ranked_urls)}
        rows.sort(key=lambda x: order.get(str(x.get("url") or ""), 10_000))
    else:
        rows.sort(key=lambda x: _heuristic_rank(q, x), reverse=True)

    out: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        title = str(row.get("title") or "Web Result").strip() or "Web Result"
        snippet = str(row.get("snippet") or "").strip()
        content = str(row.get("content") or "").strip()
        desc = snippet or safe_trim(content, 700)

        spans: List[str] = []
        if snippet:
            spans.append(safe_trim(snippet, 280))
        if content:
            spans.append(safe_trim(content, 280))

        packed = pack_result(
            title=title,
            url=url,
            description=safe_trim(desc, 900),
            source=source_name,
            domain=str(domain or "general"),
            id_type="url",
            id=url,
            published="",
            evidence_level="web_search",
            evidence_spans=spans[:4],
        )
        packed["provider"] = "searxng_playwright"
        packed["volatile"] = True
        if content:
            packed["content"] = safe_trim(content, 9000)
        if artifact_path:
            packed["scrape_artifact"] = artifact_path

        out.append(packed)
        if len(out) >= int(max_results):
            break

    return out

