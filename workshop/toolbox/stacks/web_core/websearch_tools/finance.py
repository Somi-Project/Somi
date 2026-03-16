# handlers/websearch_tools/finance.py
import logging
import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
import re
import traceback

import yfinance as yf
from yahooquery import Ticker as YahooQueryTicker
import pytz

try:
    import config.settings as _settings
except Exception:
    _settings = None

SYSTEM_TIMEZONE = str(getattr(_settings, "SYSTEM_TIMEZONE", "America/New_York"))
DISABLE_MEMORY_FOR_FINANCIAL = bool(getattr(_settings, "DISABLE_MEMORY_FOR_FINANCIAL", False))
SEARXNG_BASE_URL = str(getattr(_settings, "SEARXNG_BASE_URL", "http://localhost:8080"))
FINANCE_HISTORICAL_CRAWLIES_ENABLED = bool(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_ENABLED", False))
FINANCE_HISTORICAL_CRAWLIES_TIMEOUT_SECONDS = float(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_TIMEOUT_SECONDS", 14.0))
FINANCE_HISTORICAL_CRAWLIES_MAX_PAGES = int(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_MAX_PAGES", 2))
FINANCE_HISTORICAL_CRAWLIES_MAX_CANDIDATES = int(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_MAX_CANDIDATES", 10))
FINANCE_HISTORICAL_CRAWLIES_MAX_OPEN_LINKS = int(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_MAX_OPEN_LINKS", 3))
FINANCE_HISTORICAL_CRAWLIES_MIN_QUALITY_STOP = float(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_MIN_QUALITY_STOP", 30.0))
FINANCE_HISTORICAL_CRAWLIES_USE_SCRAPLING = bool(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_USE_SCRAPLING", True))
FINANCE_HISTORICAL_CRAWLIES_USE_PLAYWRIGHT = bool(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_USE_PLAYWRIGHT", True))
FINANCE_HISTORICAL_CRAWLIES_USE_LLM_RERANK = bool(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_USE_LLM_RERANK", False))
FINANCE_HISTORICAL_CRAWLIES_SAVE_ARTIFACTS = bool(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_SAVE_ARTIFACTS", True))
FINANCE_HISTORICAL_CRAWLIES_CATEGORY = str(getattr(_settings, "FINANCE_HISTORICAL_CRAWLIES_CATEGORY", "general"))

from workshop.toolbox.stacks.web_core.websearch_tools.finance_data.compute_summary import compute_historical_summary

from .stickers import get_stock_ticker_suggestions
from .ftickers import get_forex_ticker_suggestions
from .itickers import get_index_ticker_suggestions
from .ctickers import get_commodity_ticker_suggestions
from .bcrypto import get_crypto_price
from .finance_historical_search import search_finance_historical, rewrite_historical_query, time_anchor

try:
    from workshop.tools.crawlies import CrawliesConfig, CrawliesEngine
except Exception:
    CrawliesConfig = None  # type: ignore
    CrawliesEngine = None  # type: ignore

logger = logging.getLogger(__name__)


def _scalar_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        pass

    iloc = getattr(value, "iloc", None)
    if iloc is not None:
        for idx in (-1, 0):
            try:
                candidate = iloc[idx]
                got = _scalar_float(candidate)
                if got is not None:
                    return got
            except Exception:
                continue

    for attr in ("item", "max", "min", "mean"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                got = _scalar_float(fn())
                if got is not None:
                    return got
            except Exception:
                continue
    return None

def _safe_trim(text: str, max_chars: int = 1600) -> str:
    s = str(text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 3)].rstrip() + "..."



class FinanceHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)

        # -----------------------------
        # De-route guardrails
        # -----------------------------
        # Strong research / academic markers
        self._non_finance_strong = {
            "pmid", "doi", "arxiv", "nct",
            "systematic review", "meta-analysis", "meta analysis",
            "randomized", "randomised", "rct", "trial", "cochrane",
            "guideline", "guidelines", "consensus",
            "pubmed", "europepmc", "crossref",
            "site:",  # site:edu style queries should not become ticker "SITE"
        }

        # High-signal finance cues (keep small and explicit)
        self._finance_cues = {
            "price", "quote", "ticker", "stock", "stocks", "share", "shares",
            "market cap", "marketcap", "dividend", "earnings", "yield",
            "fx", "forex", "exchange rate", "convert", "conversion",
            "crypto", "bitcoin", "btc", "ethereum", "eth", "sol", "solana", "usdt",
            "gold", "oil", "brent", "wti", "nasdaq", "dow", "s&p", "sp500", "dxy",
        }

        # Common false-positive "tickers" from NLP/search queries
        # (expand aggressively; these are frequent English tokens and medical acronyms)
        self._false_ticker_words = {
            "WHO", "WHEN", "WHAT", "WHERE", "WHY", "HOW",
            "SITE", "EDU", "ORG", "COM",
            "AND", "OR", "NOT", "THE", "A", "AN", "TO", "IN", "ON", "OF", "FOR",
            "THIS", "THAT", "THESE", "THOSE",
            "NEWS", "LATEST", "TODAY", "UPDATE",
            "GUIDE", "GUIDELINE", "GUIDELINES", "TRIAL", "RCT", "PMID", "DOI", "ARXIV", "NCT",
            # medical frequent tokens that should never be treated as tickers without explicit finance cues
            "BP", "DM", "HTN", "COPD", "CHF", "CAP", "PID", "MI", "CV", "CVA",
        }

        # Optional: if you still see random 3-letter codes being treated as tickers,
        # you can add more stopwords here.

    def get_system_time(self):
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")


    def _is_historical_query(self, query: str) -> bool:
        q = (query or "").lower()
        if not q:
            return False
        if re.search(r"\b(19|20)\d{2}\b", q):
            return True
        historical_terms = (
            "historical",
            "history",
            "previous close",
            "past year",
            "last year",
            "all-time",
            "all time",
            "52-week",
            "52 week",
            "year-to-date",
            "ytd",
            "what was",
            "how much was",
        )
        return any(term in q for term in historical_terms)


    def _historical_unavailable_result(self) -> list:
        return [{
            "title": "Historical Data Not Available",
            "url": "",
            "description": "Historical data is currently not available for this query.",
            "source": "finance_guardrail",
        }]


    def _extract_time_constraint(self, query: str) -> Dict[str, Any]:
        q = (query or "").strip().lower()
        if not q:
            return {}

        range_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\s+(?:to|through|until|-)\s+(\d{4}-\d{2}-\d{2})\b", q)
        if range_match:
            try:
                start = datetime.strptime(range_match.group(1), "%Y-%m-%d").date()
                end = datetime.strptime(range_match.group(2), "%Y-%m-%d").date()
                if start <= end:
                    return {"kind": "range", "start": start, "end": end}
            except Exception:
                pass

        date_match = re.search(r"\bon\s+(\d{4}-\d{2}-\d{2})\b", q)
        if date_match:
            try:
                dt = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
                return {"kind": "date", "start": dt, "end": dt}
            except Exception:
                pass

        month_match = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+((?:19|20)\d{2})\b",
            q,
            re.IGNORECASE,
        )
        if month_match:
            month_map = {
                "jan": 1,
                "feb": 2,
                "mar": 3,
                "apr": 4,
                "may": 5,
                "jun": 6,
                "jul": 7,
                "aug": 8,
                "sep": 9,
                "sept": 9,
                "oct": 10,
                "nov": 11,
                "dec": 12,
            }
            mon = month_match.group(1).lower()
            year = int(month_match.group(2))
            if mon.startswith("sept"):
                key = "sept"
            else:
                key = mon[:3]
            m = month_map.get(key, 0)
            if m:
                start = date(year, m, 1)
                if m == 12:
                    end = date(year, 12, 31)
                else:
                    end = date(year, m + 1, 1) - timedelta(days=1)
                return {"kind": "month", "year": year, "month": m, "start": start, "end": end}

        year_match = re.search(r"\b((?:19|20)\d{2})\b", q)
        if year_match:
            year = int(year_match.group(1))
            return {"kind": "year", "year": year, "start": date(year, 1, 1), "end": date(year, 12, 31)}

        return {}


    def _resolve_history_symbol(self, query: str, context_symbol: str | None = None) -> str | None:
        if context_symbol:
            return str(context_symbol).strip().upper()

        q = query or ""
        ql = q.lower()

        explicit = self._extract_explicit_ticker(q)
        if explicit:
            return explicit.upper()

        if self._looks_like_forex_pair(ql):
            pair = self._extract_fiat_pair(q)
            if pair:
                return f"{pair[0]}{pair[1]}=X"

        for cand in self._candidate_queries(q):
            for resolver in (
                get_stock_ticker_suggestions,
                get_commodity_ticker_suggestions,
                get_index_ticker_suggestions,
                get_forex_ticker_suggestions,
            ):
                try:
                    hits = resolver(cand)
                except Exception:
                    hits = []
                if hits:
                    return str(hits[0]).strip().upper()

        crypto_hint = self._normalize_crypto_lookup_query(q)
        crypto_map = {
            "bitcoin": "BTC-USD",
            "btc": "BTC-USD",
            "ethereum": "ETH-USD",
            "eth": "ETH-USD",
            "solana": "SOL-USD",
            "sol": "SOL-USD",
            "dogecoin": "DOGE-USD",
            "doge": "DOGE-USD",
            "ripple": "XRP-USD",
            "xrp": "XRP-USD",
            "cardano": "ADA-USD",
            "ada": "ADA-USD",
        }
        if crypto_hint in crypto_map:
            return crypto_map[crypto_hint]
        if any(k in ql for k in ("bitcoin", " btc ", "btc")):
            return "BTC-USD"
        if any(k in ql for k in ("ethereum", " eth ", "eth")):
            return "ETH-USD"
        if any(k in ql for k in ("solana", " sol ", "sol")):
            return "SOL-USD"
        if "gold" in ql:
            return "GC=F"
        if "brent" in ql:
            return "BZ=F"
        if any(k in ql for k in ("oil", "wti")):
            return "CL=F"

        return None


    def _infer_historical_symbol(self, query: str, context_symbol: str | None = None) -> str | None:
        return self._resolve_history_symbol(query, context_symbol=context_symbol)


    def _series_to_values(self, series: Any, max_points: int = 10000) -> List[Any]:
        if series is None:
            return []

        # pandas DataFrame-like: grab first column if multi-column selection.
        try:
            if hasattr(series, "shape") and hasattr(series, "iloc"):
                shape = getattr(series, "shape", None)
                if isinstance(shape, tuple) and len(shape) >= 2 and int(shape[1]) > 1:
                    series = series.iloc[:, 0]
        except Exception:
            pass

        for attr in ("tolist", "to_list"):
            fn = getattr(series, attr, None)
            if callable(fn):
                try:
                    vals = list(fn())
                    if vals:
                        return vals
                except Exception:
                    pass

        vals_attr = getattr(series, "values", None)
        if vals_attr is not None and not callable(vals_attr):
            try:
                vals = list(vals_attr)
                if vals:
                    return vals
            except Exception:
                pass

        raw_vals = getattr(series, "vals", None)
        if isinstance(raw_vals, list):
            return list(raw_vals)

        iloc = getattr(series, "iloc", None)
        if iloc is not None:
            vals = []
            for idx in range(max_points):
                try:
                    vals.append(iloc[idx])
                except Exception:
                    break
            if vals:
                return vals

        try:
            vals = list(series)
            if vals:
                return vals
        except Exception:
            pass

        return []


    def _history_to_candles(self, hist: Any) -> List[Dict[str, float]]:
        try:
            open_s = hist["Open"]
            high_s = hist["High"]
            low_s = hist["Low"]
            close_s = hist["Close"]
        except Exception:
            return []

        opens = [_scalar_float(v) for v in self._series_to_values(open_s)]
        highs = [_scalar_float(v) for v in self._series_to_values(high_s)]
        lows = [_scalar_float(v) for v in self._series_to_values(low_s)]
        closes = [_scalar_float(v) for v in self._series_to_values(close_s)]

        n = min(len(opens), len(highs), len(lows), len(closes))
        rows: List[Dict[str, float]] = []
        for i in range(n):
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]
            if None in (o, h, l, c):
                continue
            rows.append({"open": float(o), "high": float(h), "low": float(l), "close": float(c)})
        return rows


    async def _crawlies_historical(self, query: str, tc: Dict[str, Any]) -> list:
        if not FINANCE_HISTORICAL_CRAWLIES_ENABLED or CrawliesConfig is None or CrawliesEngine is None:
            return []

        try:
            cfg = CrawliesConfig(
                searx_base_url=str(SEARXNG_BASE_URL or "http://localhost:8080"),
                category=str(FINANCE_HISTORICAL_CRAWLIES_CATEGORY or "general"),
                max_pages=max(1, int(FINANCE_HISTORICAL_CRAWLIES_MAX_PAGES)),
                max_candidates=max(1, int(FINANCE_HISTORICAL_CRAWLIES_MAX_CANDIDATES)),
                max_open_links=max(1, int(FINANCE_HISTORICAL_CRAWLIES_MAX_OPEN_LINKS)),
                min_quality_stop=float(FINANCE_HISTORICAL_CRAWLIES_MIN_QUALITY_STOP),
                use_scrapling=bool(FINANCE_HISTORICAL_CRAWLIES_USE_SCRAPLING),
                use_playwright=bool(FINANCE_HISTORICAL_CRAWLIES_USE_PLAYWRIGHT),
                use_llm_rerank=bool(FINANCE_HISTORICAL_CRAWLIES_USE_LLM_RERANK),
                save_artifacts=bool(FINANCE_HISTORICAL_CRAWLIES_SAVE_ARTIFACTS),
            )
            engine = CrawliesEngine(cfg)
            payload = await asyncio.wait_for(
                engine.crawl(query),
                timeout=max(1.0, float(FINANCE_HISTORICAL_CRAWLIES_TIMEOUT_SECONDS)),
            )
        except Exception as e:
            logger.warning(f"Historical crawlies fallback failed for '{query}': {e}")
            return []

        docs = payload.get("docs") if isinstance(payload, dict) else []
        out: List[Dict[str, Any]] = []
        if isinstance(docs, list):
            for d in docs[: max(1, int(FINANCE_HISTORICAL_CRAWLIES_MAX_OPEN_LINKS))]:
                if not isinstance(d, dict):
                    continue
                url = str(d.get("url") or "").strip()
                if not url:
                    continue
                title = str(d.get("title") or url).strip()
                snippet = str(d.get("snippet") or "").strip()
                content = str(d.get("content") or "").strip()
                desc = _safe_trim(content or snippet, 1800)
                if not desc:
                    continue
                method = str(d.get("method") or "crawl").strip()
                out.append({
                    "title": title,
                    "url": url,
                    "description": desc,
                    "source": f"crawlies_{method}",
                    "quality": float(d.get("quality") or 0.0),
                })

        return out

    def _normalize_crypto_lookup_query(self, query: str) -> str:
        q = self._normalize_for_match(query)

        aliases = {
            "bitcoin": ("bitcoin", "btc"),
            "ethereum": ("ethereum", "eth"),
            "solana": ("solana", "sol"),
            "dogecoin": ("dogecoin", "doge"),
            "ripple": ("ripple", "xrp"),
            "cardano": ("cardano", "ada"),
        }
        for canonical, keys in aliases.items():
            if any(re.search(rf"\b{re.escape(k)}\b", q) for k in keys):
                return canonical

        q = re.sub(r"\b(what|whats|what's|the|price|of|now|current|for|quote|crypto)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q or (query or "").strip()



    async def search_historical_price(self, query: str, context_symbol: str | None = None) -> list:
        query = self._clean_query(query)
        tc = self._extract_time_constraint(query)
        symbol = self._resolve_history_symbol(query, context_symbol=context_symbol)

        if symbol:
            try:
                kwargs: Dict[str, Any] = {
                    "interval": "1d",
                    "progress": False,
                    "auto_adjust": False,
                    "threads": False,
                }
                start = tc.get("start") if isinstance(tc, dict) else None
                end = tc.get("end") if isinstance(tc, dict) else None
                if isinstance(start, date) and isinstance(end, date):
                    kwargs["start"] = start.isoformat()
                    kwargs["end"] = (end + timedelta(days=1)).isoformat()
                else:
                    kwargs["period"] = "max"

                hist = await asyncio.to_thread(yf.download, symbol, **kwargs)
                if hasattr(hist, "empty") and not getattr(hist, "empty"):
                    candles = self._history_to_candles(hist)
                    if candles:
                        summary = compute_historical_summary(candles)
                        min_low = summary.get("min_low")
                        max_high = summary.get("max_high")
                        first_close = summary.get("first_close")
                        last_close = summary.get("last_close")
                        ret_pct = summary.get("return_pct")

                        anchor = time_anchor(tc) if isinstance(tc, dict) else ""
                        anchor_suffix = f" for {anchor}" if anchor else ""
                        ret_text = ""
                        if ret_pct is not None:
                            ret_text = f" Return over window: {round(float(ret_pct), 2)}%."

                        return [{
                            "title": f"{symbol} Historical Price{anchor_suffix}",
                            "url": f"https://finance.yahoo.com/quote/{symbol}/history",
                            "description": (
                                f"Historical range{anchor_suffix}: low {min_low}, high {max_high}. "
                                f"Window started near {first_close}, latest close {last_close}.{ret_text}"
                            ),
                            "source": "yfinance_history",
                            "symbol": symbol,
                        }]
            except Exception as e:
                logger.warning(f"Historical yfinance query failed for '{symbol}': {e}")

        fallback_query = rewrite_historical_query(query, symbol_hint=symbol, tc=tc)

        crawlies_rows = await self._crawlies_historical(fallback_query, tc)
        if crawlies_rows:
            return crawlies_rows

        try:
            fallback = await search_finance_historical(fallback_query, min_results=3, tc=tc)
            if fallback:
                return fallback
        except Exception as e:
            logger.warning(f"Historical fallback search failed: {e}")

        return self._historical_unavailable_result()


    # -----------------------------
    # Query normalization helpers
    # -----------------------------
    def _clean_query(self, q: str) -> str:
        q = (q or "").strip()
        q = re.sub(r"\s+", " ", q)
        return q

    def _normalize_for_match(self, q: str) -> str:
        q = self._clean_query(q).lower()

        # common boilerplate removals
        q = re.sub(r"^(whats|what's)\s+the\s+", "", q)
        q = re.sub(r"^(price|rate|exchange rate|conversion rate)\s+(of|for)\s+", "", q)
        q = q.replace("?", "").strip()

        # normalize separators
        q = q.replace(" to ", "/")
        q = re.sub(r"\s*/\s*", "/", q)

        # normalize "eurusd" -> "eur/usd" (only if exactly 6 letters)
        m = re.fullmatch(r"([a-z]{3})([a-z]{3})", q)
        if m:
            q = f"{m.group(1)}/{m.group(2)}"

        return q

    def _has_finance_cues(self, q: str) -> bool:
        ql = (q or "").lower()
        return any(cue in ql for cue in self._finance_cues)

    def _extract_explicit_ticker(self, q: str) -> str | None:
        """
        Prefer explicit tickers typed by user:
        - AAPL, TSLA, BRK-B, BTCUSDT, EURUSD=X, ^GSPC, GC=F, DX-Y.NYB
        IMPORTANT:
          - Plain uppercase tokens (AAPL) are ONLY treated as explicit if finance cues exist.
          - Syntax-heavy tickers (^, =X, =F, USDT, -, ., digits) are always accepted.
        """
        s = (q or "").strip()
        if not s:
            return None

        # Syntax-heavy patterns (accept always)
        patterns_strong = [
            r"\b\^[A-Z]{1,6}\b",                 # ^GSPC
            r"\b[A-Z]{1,8}=X\b",                 # EURUSD=X
            r"\b[A-Z]{1,6}=F\b",                 # GC=F
            r"\b[A-Z0-9]{2,12}USDT\b",           # BTCUSDT, ETHUSDT, etc.
            r"\bDX-Y\.NYB\b",                    # DXY ticker
            r"\b\d{6}\.SS\b",                    # 000001.SS
            r"\b[A-Z]{1,6}[-.][A-Z0-9]{1,6}\b",  # BRK-B, RDS.A, etc.
        ]
        for pat in patterns_strong:
            m = re.search(pat, s)
            if m:
                return m.group(0)

        # Plain uppercase words (accept ONLY if finance cues exist)
        if self._has_finance_cues(s):
            m = re.search(r"\b[A-Z]{1,6}\b", s)
            if m:
                t = m.group(0).upper()
                if t in self._false_ticker_words:
                    return None
                return t

        return None

    def _candidate_queries(self, query: str) -> list[str]:
        """
        Generate multiple versions of the query for trying mappers.
        """
        raw = self._clean_query(query)
        norm = self._normalize_for_match(query)

        candidates = [raw, norm]

        stripped = norm
        stripped = stripped.replace("price", "").replace("rate", "").replace("exchange", "")
        stripped = stripped.replace("conversion", "").replace("value", "").strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

        m = re.search(r"\b([a-z]{3})/([a-z]{3})\b", norm)
        if m:
            pair = f"{m.group(1)}/{m.group(2)}"
            if pair not in candidates:
                candidates.insert(0, pair)

        out: list[str] = []
        seen = set()
        for c in candidates:
            c2 = (c or "").strip()
            if not c2:
                continue
            key = c2.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(c2)
        return out

    def _looks_like_forex_pair(self, query: str) -> bool:
        ql = (query or "").lower()
        if not ql:
            return False

        if re.search(r"\b([a-z]{3})\s*(?:/|to)\s*([a-z]{3})\b", ql):
            return True

        norm = self._normalize_for_match(ql)
        if re.fullmatch(r"[a-z]{6}", norm):
            return True

        return False

    def _extract_fiat_pair(self, query: str) -> tuple[str, str] | None:
        """
        Extracts a fiat pair from messy sentences like:
          - 'USD to EUR exchange rate today'
          - 'what is the usd eur rate'
          - 'exchange rate eur to usd'
          - 'usd/eur'
          - 'eurusd'
        Returns (BASE, QUOTE) or None.
        """
        s = self._normalize_for_match(query)

        m = re.search(r"\b([a-z]{3})/([a-z]{3})\b", s)
        if m:
            return (m.group(1).upper(), m.group(2).upper())

        m = re.fullmatch(r"([a-z]{3})([a-z]{3})", s)
        if m:
            return (m.group(1).upper(), m.group(2).upper())

        tokens = re.findall(r"\b[a-zA-Z]{3}\b", query)
        codes = [t.upper() for t in tokens]
        if len(codes) >= 2:
            return (codes[0], codes[1])

        return None

    # -----------------------------
    # De-route logic (deterministic)
    # -----------------------------
    def _should_deroute_from_finance(self, query: str, *, channel: str) -> tuple[bool, str]:
        """
        Finance-side guardrail to stop false-positive routing.
        Returns (True, reason) to signal caller to fall back.
        Key rule: strong non-finance cues only force deroute when finance cues are absent.
        """
        q = self._clean_query(query)
        ql = q.lower()

        if not ql:
            return True, "empty_query"

        has_finance_cue = self._has_finance_cues(ql)

        # Strong research/academic terms -> deroute UNLESS finance cues exist
        if any(k in ql for k in self._non_finance_strong):
            if not has_finance_cue:
                return True, "strong_non_finance_keywords"
            # finance cues exist -> allow finance to try (user may be mixing)
            # example: "price of PMID..." is weird but user intent is finance-like.
            # Let it proceed.

        # General question patterns -> deroute if no finance cues
        if (re.search(r"\bhow to\b", ql) or re.search(r"\bwhat is\b", ql)) and not has_finance_cue:
            return True, "general_question_what_is_how_to"

        # Explicit ticker syntax should NOT be derouted (except false ticker words)
        explicit = self._extract_explicit_ticker(q)
        if explicit:
            if explicit.upper() in self._false_ticker_words and not has_finance_cue:
                return True, "false_ticker_word"
            return False, ""

        # Shape checks
        has_dollar = "$" in q
        has_pair = bool(re.search(r"\b[a-z]{3}\s*(?:/|to)\s*[a-z]{3}\b", ql))
        has_tickerish = False

        # Ticker-ish uppercase tokens, but filter stopwords
        toks = re.findall(r"\b[A-Z]{1,5}\b", q)
        toks = [t for t in toks if t.upper() not in self._false_ticker_words]
        if toks and has_finance_cue:
            has_tickerish = True

        # If there are no finance cues and no finance shapes, deroute.
        if not has_finance_cue and not (has_dollar or has_pair):
            return True, f"no_finance_signals_{channel}"

        return False, ""

    def _deroute_payload(self, query: str, reason: str) -> list:
        return [{
            "deroute": True,
            "reason": reason,
            "handler": "finance",
            "title": "De-routed from finance",
            "url": "",
            "description": f"FinanceHandler declined this query: {reason}",
        }]

    # -----------------------------
    # Result formatting
    # -----------------------------
    def _format_crypto_result(self, crypto_response: str, query: str) -> dict:
        s = (crypto_response or "").strip()

        if not s or "Error" in s:
            logger.error(f"bcrypto error for '{query}': {s}")
            return {
                "title": "Price Not Found",
                "url": "",
                "description": f"Crypto price could not be retrieved: {s or 'empty response'}",
                "source": "binance",
            }

        m = re.search(
            r"^\s*(?P<name>.+?)\s*\((?P<symbol>[A-Z0-9]+)\)\s*:\s*\$(?P<price>[\d,]+(?:\.\d+)?)\s*$",
            s,
            flags=re.IGNORECASE,
        )

        if not m:
            logger.error(f"Invalid bcrypto response format for '{query}': {s}")
            return {
                "title": "Price Not Found",
                "url": "",
                "description": f"Crypto price retrieved but could not be parsed: {s}",
                "source": "binance",
            }

        name = (m.group("name") or "").strip()
        symbol = (m.group("symbol") or "").strip().upper()
        price_raw = (m.group("price") or "").strip()

        try:
            price_usd = float(price_raw.replace(",", ""))
        except Exception:
            price_usd = None

        return {
            "title": f"{name} ({symbol}) Price",
            "url": f"https://www.binance.com/en/trade/{symbol}",
            "description": (
                f"Current price: {price_raw} USD (Binance). "
                "Do not alter this number."
            ),
            "price_usd": price_usd,
            "source": "binance",
        }

    # -----------------------------
    # Stocks / Commodities / Indices
    # -----------------------------
    async def search_stocks_commodities(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        if DISABLE_MEMORY_FOR_FINANCIAL:
            logger.info("Memory usage disabled for stock/commodity/index query")

        query = self._clean_query(query)
        query_lower = query.lower().strip()
        logger.info(f"Processing stock/commodity query: '{query}' at {self.get_system_time()}")

        deroute, reason = self._should_deroute_from_finance(query, channel="stocks_commodities")
        if deroute:
            logger.info(f"De-routing stock/commodity query: reason={reason} query='{query}'")
            return self._deroute_payload(query, reason)

        ticker = None

        # 0) Explicit ticker wins immediately
        explicit = self._extract_explicit_ticker(query)
        if explicit:
            ticker = explicit
            logger.info(f"Using explicit ticker '{ticker}' from query '{query}'")

        # 1) Stocks/ETFs via dictionary suggestions
        if not ticker:
            for cand in self._candidate_queries(query):
                ticker_list = get_stock_ticker_suggestions(cand)
                if ticker_list:
                    ticker = ticker_list[0]
                    break

        # 2) Commodities
        if not ticker and not any(k in query_lower for k in ["ishares", "spdr", "etf", "trust"]):
            for cand in self._candidate_queries(query):
                ticker_list = get_commodity_ticker_suggestions(cand)
                if ticker_list:
                    ticker = ticker_list[0]
                    break

        # 3) Indices
        if not ticker:
            for cand in self._candidate_queries(query):
                ticker_list = get_index_ticker_suggestions(cand)
                if ticker_list:
                    ticker = ticker_list[0]
                    break

        if not ticker:
            logger.warning(f"No valid ticker found for query '{query}'")
            return [{
                "title": "Asset Not Found",
                "url": "",
                "description": "No matching stock, commodity, or index ticker found for the query.",
            }]

        # Guard: obvious false token
        if ticker.upper() in self._false_ticker_words and not self._has_finance_cues(query_lower):
            logger.info(f"De-routing due to false ticker word '{ticker}' from query '{query}'")
            return self._deroute_payload(query, "false_ticker_word_match")

        logger.info(f"Using ticker '{ticker}' for query '{query}'")

        # yfinance primary
        for attempt in range(retries):
            try:
                asset = yf.Ticker(ticker)
                info = asset.info
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = info.get("shortName", ticker)
                currency = info.get("currency", "USD")
                if price == "N/A":
                    raise ValueError("No valid price from yfinance")

                return [{
                    "title": f"{name} ({ticker}) Price",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Current price: {price} {currency} (Yahoo Finance). Do not alter this number.",
                    "source": "yfinance_exclusive",
                }]
            except Exception as e:
                logger.warning(
                    f"yfinance query failed for '{ticker}': {e}. Attempt {attempt + 1}/{retries}."
                )
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        logger.warning(f"All {retries} yfinance attempts failed for '{ticker}'. Falling back to yahooquery.")

        # yahooquery fallback
        for attempt in range(retries):
            try:
                asset = YahooQueryTicker(ticker)
                info = asset.summary_detail.get(ticker, {}) or {}
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = asset.quote_type.get(ticker, {}).get("shortName", ticker)
                currency = info.get("currency", "USD")
                if price == "N/A":
                    return [{
                        "title": "Price Not Found",
                        "url": "",
                        "description": "Price could not be retrieved at this time.",
                    }]

                return [{
                    "title": f"{name} ({ticker}) Price",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Current price: {price} {currency} (Yahoo Finance). Do not alter this number.",
                    "source": "yahooquery_fallback",
                }]
            except Exception as e:
                logger.error(f"yahooquery query failed for '{ticker}': {e}\n{traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        return [{
            "title": "Price Not Found",
            "url": "",
            "description": "Price could not be retrieved at this time.",
        }]

    # -----------------------------
    # Crypto (Binance via bcrypto)
    # -----------------------------
    async def search_crypto_yfinance(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        if DISABLE_MEMORY_FOR_FINANCIAL:
            logger.info("Memory usage disabled for crypto query")

        query = self._clean_query(query)
        ql = query.lower()

        deroute, reason = self._should_deroute_from_finance(query, channel="crypto")
        # allow crypto if explicit crypto cues exist
        if deroute and not any(k in ql for k in ("btc", "bitcoin", "eth", "ethereum", "crypto", "sol", "solana", "usdt")):
            logger.info(f"De-routing crypto query: reason={reason} query='{query}'")
            return self._deroute_payload(query, reason)

        for attempt in range(retries):
            try:
                explicit = self._extract_explicit_ticker(query)
                if explicit and explicit.upper().endswith("USDT"):
                    crypto_response = get_crypto_price(explicit)
                else:
                    normalized = self._normalize_crypto_lookup_query(query)
                    crypto_response = get_crypto_price(normalized)

                result = self._format_crypto_result(crypto_response, query)
                return [result]
            except Exception as e:
                logger.error(f"bcrypto query failed for '{query}': {e}\n{traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        return [{
            "title": "Price Not Found",
            "url": "",
            "description": "Crypto price could not be retrieved at this time.",
        }]

    # -----------------------------
    # Forex
    # -----------------------------
    async def search_forex_yfinance(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        if DISABLE_MEMORY_FOR_FINANCIAL:
            logger.info("Memory usage disabled for forex query")

        query = self._clean_query(query)
        ql = query.lower()
        logger.info(f"Processing forex query: '{query}' at {self.get_system_time()}")

        deroute, reason = self._should_deroute_from_finance(query, channel="forex")
        has_pair_shape = bool(re.search(r"\b[a-z]{3}\s*(?:/|to)\s*[a-z]{3}\b", ql)) or bool(
            re.fullmatch(r"[a-z]{6}", self._normalize_for_match(query))
        )
        if deroute and not has_pair_shape and not any(k in ql for k in ("fx", "forex", "exchange rate", "convert", "conversion")):
            logger.info(f"De-routing forex query: reason={reason} query='{query}'")
            return self._deroute_payload(query, reason)

        ticker = None

        # 0) Explicit Yahoo FX ticker wins (EURUSD=X etc.)
        explicit = self._extract_explicit_ticker(query)
        if explicit and explicit.upper().endswith("=X"):
            ticker = explicit
            logger.info(f"Using explicit forex ticker '{ticker}' from query '{query}'")
        else:
            # 1) Sentence-level extraction (USD to EUR exchange rate today -> USDEUR=X)
            pair = self._extract_fiat_pair(query)
            if pair:
                base, quote = pair
                ticker = f"{base}{quote}=X"
                logger.info(f"Extracted fiat pair {base}/{quote} -> '{ticker}' from query '{query}'")

            # 2) Dictionary-based suggestion fallback
            if not ticker:
                for cand in self._candidate_queries(query):
                    ticker_list = get_forex_ticker_suggestions(cand)
                    if ticker_list:
                        ticker = ticker_list[0]
                        break

        if not ticker:
            return [{
                "title": "Error",
                "url": "",
                "description": "No valid ticker found for the requested currency pair.",
            }]

        # yfinance primary
        for attempt in range(retries):
            try:
                forex = yf.Ticker(ticker)
                info = forex.info
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = info.get("shortName", ticker)
                currency = info.get("currency", "USD")
                if price == "N/A":
                    raise ValueError("No valid rate from yfinance")

                rate_val = None
                try:
                    rate_val = float(price)
                except Exception:
                    rate_val = None

                return [{
                    "title": f"{name} ({ticker}) Exchange Rate",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Current rate: {price} {currency} (Yahoo Finance). Do not alter this number.",
                    "rate": rate_val,
                    "source": "yfinance_exclusive",
                }]
            except Exception as e:
                logger.warning(
                    f"yfinance query failed for '{ticker}': {e}. Attempt {attempt + 1}/{retries}."
                )
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        # yahooquery fallback
        for attempt in range(retries):
            try:
                forex = YahooQueryTicker(ticker)
                info = forex.summary_detail.get(ticker, {}) or {}
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = forex.quote_type.get(ticker, {}).get("shortName", ticker)
                currency = info.get("currency", "USD")
                if price == "N/A":
                    return [{
                        "title": "Rate Not Found",
                        "url": "",
                        "description": "Rate could not be retrieved at this time.",
                    }]

                rate_val = None
                try:
                    rate_val = float(price)
                except Exception:
                    rate_val = None

                return [{
                    "title": f"{name} ({ticker}) Exchange Rate",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Current rate: {price} {currency} (Yahoo Finance). Do not alter this number.",
                    "rate": rate_val,
                    "source": "yahooquery_fallback",
                }]
            except Exception as e:
                logger.error(f"yahooquery query failed for '{ticker}': {e}\n{traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        return [{
            "title": "Rate Not Found",
            "url": "",
            "description": "Rate could not be retrieved at this time.",
        }]












