# handlers/websearch_tools/finance.py
import logging
import asyncio
from config.settings import SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL, FINANCE_YAHOO_BACKEND
import pytz
from datetime import datetime, date, timedelta
import re

from .stickers import get_stock_ticker_suggestions
from .ftickers import get_forex_ticker_suggestions
from .itickers import get_index_ticker_suggestions
from .ctickers import get_commodity_ticker_suggestions
from handlers.finance.compute_summary import compute_historical_summary
from handlers.finance.format_query import normalize_query_spec
from handlers.finance.vendors.binance_client import BinanceClient, NoDataError as BinanceNoDataError, UnsupportedSymbolError
from handlers.finance.vendors.yahoo_yfinance_client import YahooYFinanceClient, NoDataError as YFinanceNoDataError
from handlers.finance.vendors.yahoo_yahooquery_client import YahooYahooQueryClient, NoDataError as YahooQueryNoDataError

logger = logging.getLogger(__name__)




def _scalar_float(value, default: float = 0.0) -> float:
    """Convert pandas/numpy scalars or 1-item Series/arrays to float safely."""
    try:
        if hasattr(value, "iloc"):
            value = value.iloc[0]
        elif hasattr(value, "item"):
            value = value.item()
        return float(value)
    except Exception:
        return float(default)
class FinanceHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)
        self._binance = BinanceClient()
        self._yahoo_backend = (FINANCE_YAHOO_BACKEND or "yfinance").strip().lower()
        self._yahoo_yf = YahooYFinanceClient()
        self._yahoo_yq = YahooYahooQueryClient()

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

    # -----------------------------
    # Query normalization helpers
    # -----------------------------
    def _clean_query(self, q: str) -> str:
        q = (q or "").strip()
        q = re.sub(r"\s+", " ", q)
        return q

    def _normalize_asset_phrase(self, q: str) -> str:
        t = self._clean_query(q).lower()
        t = re.sub(r"^[\s\W]*(what'?s|what is|tell me|give me|show me)\s+", "", t)
        t = re.sub(r"^the\s+", "", t)
        t = re.sub(r"\b(current\s+)?(price|quote|rate|value|market\s+price)\b", "", t)
        t = re.sub(r"\b(of|for|on|now|today|please)\b", "", t)
        t = re.sub(r"\s+", " ", t).strip(" ?!.,")
        return t or self._clean_query(q)

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


    def _build_endpoint_candidates(self, query: str) -> list[str]:
        """
        Build endpoint-compatible candidate strings (asset-focused, low boilerplate).
        Keeps free API wrappers fed with minimal normalized tokens.
        """
        raw = self._clean_query(query)
        norm_asset = self._normalize_asset_phrase(raw)
        candidates = [norm_asset]
        for cand in self._candidate_queries(raw):
            cl = cand.lower()
            if any(tok in cl for tok in ("what", "whats", "what's", "price of", "tell me", "show me")):
                continue
            candidates.append(cand)

        out: list[str] = []
        seen = set()
        for c in candidates:
            c2 = re.sub(r"\s+", " ", str(c or "")).strip(" ?!.,")
            if not c2:
                continue
            k = c2.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(c2)
        return out

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

    def _get_yahoo_clients_in_order(self):
        if self._yahoo_backend == "yahooquery":
            return [self._yahoo_yq, self._yahoo_yf]
        return [self._yahoo_yf, self._yahoo_yq]

    @staticmethod
    def _interval_to_yahoo(interval: str) -> str:
        mapping = {
            "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m",
            "60m": "60m", "90m": "90m", "1h": "60m", "1d": "1d", "5d": "5d",
            "1wk": "1wk", "1mo": "1mo", "3mo": "3mo",
        }
        return mapping.get((interval or "1d").lower(), "1d")

    @staticmethod
    def _interval_to_binance(interval: str) -> str:
        mapping = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d", "1wk": "1w", "1mo": "1M"}
        return mapping.get((interval or "1d").lower(), "1d")


    def _extract_interval_constraint(self, query: str) -> str | None:
        q = (query or "").lower()
        m = re.search(r"\b(1m|2m|5m|15m|30m|60m|90m|1h|1d|5d|1wk|1mo|3mo)\b", q)
        if m:
            val = m.group(1)
            return "1h" if val == "60m" else val
        if "minute" in q:
            return "1m"
        if "hour" in q or "hourly" in q:
            return "1h"
        if "week" in q or "weekly" in q:
            return "1wk"
        if "month" in q or "monthly" in q:
            return "1mo"
        if "day" in q or "daily" in q:
            return "1d"
        return None

    def _upgrade_yahoo_interval_for_range(self, interval: str, start: date, end: date) -> str:
        span_days = max(1, (end - start).days + 1)
        iv = (interval or "1d").lower()
        if iv == "1m" and span_days > 7:
            return "1d"
        if iv in {"2m", "5m", "15m", "30m", "60m", "90m", "1h"} and span_days > 60:
            return "1d"
        return iv

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

        candidates = self._build_endpoint_candidates(query)
        norm_asset = candidates[0] if candidates else self._normalize_asset_phrase(query)
        logger.info(f"Endpoint-compatible candidates for finance lookup: {candidates[:4]}")

        # 1) Commodities first to avoid false stock matches like "NOW" from phrases such as "price of oil now".
        if not ticker and not any(k in query_lower for k in ["ishares", "spdr", "etf", "trust"]):
            for cand in candidates:
                ticker_list = get_commodity_ticker_suggestions(cand)
                if ticker_list:
                    ticker = ticker_list[0]
                    break

        # 2) Stocks/ETFs via dictionary suggestions
        if not ticker:
            stock_candidates = [norm_asset]
            # Include broader candidates only if they don't contain temporal/current-price filler tokens.
            for cand in candidates:
                cl = cand.lower()
                if cand == norm_asset:
                    continue
                if any(tok in cl for tok in (" now", " today", " current", " latest")):
                    continue
                stock_candidates.append(cand)
            for cand in stock_candidates:
                ticker_list = get_stock_ticker_suggestions(cand)
                if ticker_list:
                    ticker = ticker_list[0]
                    break

        # 3) Indices
        if not ticker:
            for cand in candidates:
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
        # Deterministic vendor execution with one-step backend fallback
        spec = normalize_query_spec(asset_class="equity", symbol=ticker, query_type="spot")
        for client in self._get_yahoo_clients_in_order():
            try:
                quote = client.get_spot_price(spec.symbol)
                price = quote.get("price")
                currency = quote.get("currency", "USD")
                return [{
                    "title": f"{spec.symbol} Price",
                    "url": f"https://finance.yahoo.com/quote/{spec.symbol}",
                    "description": f"Current price: {price} {currency} (Yahoo Finance). Do not alter this number.",
                    "source": client.__class__.__name__,
                    "price": price,
                    "timestamp": quote.get("timestamp"),
                }]
            except (YFinanceNoDataError, YahooQueryNoDataError) as e:
                logger.warning(f"Yahoo spot query failed for '{spec.symbol}' via {client.__class__.__name__}: {e}")
            except Exception as e:
                logger.warning(f"Yahoo spot query failed for '{spec.symbol}' via {client.__class__.__name__}: {e}")

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
        explicit = self._extract_explicit_ticker(query)
        if explicit and explicit.upper().endswith("USDT"):
            symbol = explicit.upper()
        else:
            normalized = self._normalize_asset_phrase(query)
            symbol = (normalized.replace("/", "").replace("-", "").replace(" ", "").upper())
            if not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"

        spec = normalize_query_spec(asset_class="crypto", symbol=symbol, query_type="spot")
        try:
            quote = self._binance.get_spot_price(spec.symbol)
            return [{
                "title": f"{spec.symbol} Price",
                "url": f"https://www.binance.com/en/trade/{spec.symbol}",
                "description": f"Current price: {quote['price']} USD (Binance). Do not alter this number.",
                "price_usd": quote["price"],
                "source": "binance",
                "timestamp": quote.get("timestamp"),
            }]
        except UnsupportedSymbolError as e:
            return [{"title": "Price Not Found", "url": "", "description": str(e), "source": "binance"}]
        except Exception as e:
            logger.error(f"Binance spot query failed for '{spec.symbol}': {e}")
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

        explicit = self._extract_explicit_ticker(query)
        if explicit and explicit.upper().endswith("=X"):
            ticker = explicit.upper()
            logger.info(f"Using explicit forex ticker '{ticker}' from query '{query}'")
        else:
            pair = self._extract_fiat_pair(query)
            if pair:
                base, quote = pair
                ticker = f"{base}{quote}=X"
                logger.info(f"Extracted fiat pair {base}/{quote} -> '{ticker}' from query '{query}'")

            if not ticker:
                for cand in self._candidate_queries(query):
                    ticker_list = get_forex_ticker_suggestions(cand)
                    if ticker_list:
                        ticker = ticker_list[0].upper()
                        break

        if not ticker:
            return [{
                "title": "Error",
                "url": "",
                "description": "No valid ticker found for the requested currency pair.",
            }]

        spec = normalize_query_spec(asset_class="fx", symbol=ticker, query_type="spot")
        for attempt in range(retries):
            for client in self._get_yahoo_clients_in_order():
                try:
                    quote = client.get_spot_price(spec.symbol)
                    rate = quote.get("price")
                    currency = quote.get("currency", "USD")
                    return [{
                        "title": f"{spec.symbol} Exchange Rate",
                        "url": f"https://finance.yahoo.com/quote/{spec.symbol}",
                        "description": f"Current rate: {rate} {currency} (Yahoo Finance). Do not alter this number.",
                        "rate": rate,
                        "source": client.__class__.__name__,
                        "timestamp": quote.get("timestamp"),
                    }]
                except (YFinanceNoDataError, YahooQueryNoDataError) as e:
                    logger.warning(f"Yahoo forex query failed for '{spec.symbol}' via {client.__class__.__name__}: {e}")
                except Exception as e:
                    logger.warning(f"Yahoo forex query failed for '{spec.symbol}' via {client.__class__.__name__}: {e}")

            if attempt < retries - 1:
                await asyncio.sleep(backoff_factor * (2 ** attempt))

        return [{
            "title": "Rate Not Found",
            "url": "",
            "description": "Rate could not be retrieved at this time.",
        }]


    def _extract_time_constraint(self, query: str) -> dict | None:
        q = (query or "").lower()
        month_map = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
            "october": 10, "oct": 10, "november": 11, "novemeber": 11, "nov": 11, "december": 12, "dec": 12,
        }
        md_text = re.search(r"\b(" + "|".join(month_map.keys()) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2}|19\d{2})\b", q)
        if md_text:
            m = month_map[md_text.group(1)]
            d = int(md_text.group(2))
            y = int(md_text.group(3))
            dt = date(y, m, d)
            return {"kind": "date", "start": dt, "end": dt}

        mm = re.search(r"\b(" + "|".join(month_map.keys()) + r")\s+(20\d{2}|19\d{2})\b", q)
        if mm:
            m = month_map[mm.group(1)]
            y = int(mm.group(2))
            start = date(y, m, 1)
            end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
            return {"kind": "month", "year": y, "month": m, "start": start, "end": end}

        mr = re.search(r"\bbetween\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})\b", q)
        if mr:
            return {"kind": "range", "start": date.fromisoformat(mr.group(1)), "end": date.fromisoformat(mr.group(2))}

        md = re.search(r"\bon\s+(\d{4}-\d{2}-\d{2})\b", q)
        if md:
            d = date.fromisoformat(md.group(1))
            return {"kind": "date", "start": d, "end": d}

        y = re.search(r"\bin\s+(20\d{2}|19\d{2})\b", q)
        if y:
            yy = int(y.group(1))
            return {"kind": "year", "year": yy, "start": date(yy, 1, 1), "end": date(yy, 12, 31)}

        if "last year" in q:
            yy = datetime.utcnow().year - 1
            return {"kind": "year", "year": yy, "start": date(yy, 1, 1), "end": date(yy, 12, 31)}

        return None

    def _resolve_history_symbol(self, query: str, context_symbol: str | None = None) -> str | None:
        q = (query or "").upper()
        if context_symbol:
            return context_symbol
        if "BTCUSDT" in q or "BTC" in q or "BITCOIN" in q:
            return "BTCUSDT"
        if "ETHUSDT" in q or "ETH" in q or "ETHEREUM" in q:
            return "ETHUSDT"
        explicit = self._extract_explicit_ticker(query)
        if explicit and explicit.endswith("USDT"):
            return explicit
        return explicit or None
    async def search_historical_price(self, query: str, *, context_symbol: str | None = None) -> list:
        tc = self._extract_time_constraint(query)
        if not tc:
            return []

        symbol = self._resolve_history_symbol(query, context_symbol=context_symbol)
        if not symbol:
            return [{
                "title": "Historical price unavailable",
                "url": "",
                "description": "No symbol detected for the requested historical range.",
                "source": "history_error",
            }]

        asset_class = "crypto" if symbol.upper().endswith("USDT") else "equity"
        spec = normalize_query_spec(
            asset_class=asset_class,
            symbol=symbol,
            query_type="historical",
            interval=(self._extract_interval_constraint(query) or "1d"),
            start=tc["start"],
            end=tc["end"],
        )

        try:
            if spec.asset_class == "crypto":
                start_ms = int(datetime.combine(spec.start, datetime.min.time()).timestamp() * 1000)
                end_ms = int(datetime.combine(spec.end + timedelta(days=1), datetime.min.time()).timestamp() * 1000)
                candles = self._binance.get_historical_candles(spec.symbol, self._interval_to_binance(spec.interval or "1d"), start_ms, end_ms)
            else:
                start_s = spec.start.isoformat()
                end_s = (spec.end + timedelta(days=1)).isoformat()
                candles = None
                requested_interval = self._upgrade_yahoo_interval_for_range(spec.interval or "1d", spec.start, spec.end)
                yahoo_interval = self._interval_to_yahoo(requested_interval)
                for client in self._get_yahoo_clients_in_order():
                    try:
                        candles = client.get_historical_candles(spec.symbol, start_s, end_s, yahoo_interval)
                        break
                    except (YFinanceNoDataError, YahooQueryNoDataError):
                        continue
                if not candles:
                    raise ValueError(f"No data returned for {spec.symbol} in requested range.")

            summary = compute_historical_summary(candles)
            return [{
                "title": f"{spec.symbol} historical price ({spec.start} to {spec.end})",
                "url": f"https://finance.yahoo.com/quote/{spec.symbol}/history",
                "description": (
                    f"Historical {spec.symbol} for {spec.start} to {spec.end}: "
                    f"first close {summary['first_close']:,.2f}, last close {summary['last_close']:,.2f}, "
                    f"low {summary['min_low']:,.2f}, high {summary['max_high']:,.2f}, "
                    f"return {summary['return_pct']:.2f}%."
                ),
                "source": "historical_candles",
                "candles": candles,
                **summary,
            }]
        except (BinanceNoDataError, UnsupportedSymbolError, ValueError) as e:
            return [{
                "title": "Historical price unavailable",
                "url": "",
                "description": str(e),
                "source": "history_error",
            }]
        except Exception:
            return [{
                "title": "Historical price unavailable",
                "url": "",
                "description": f"No data returned for {symbol} in requested range.",
                "source": "history_error",
            }]
