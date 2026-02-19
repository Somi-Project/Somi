# handlers/websearch_tools/finance.py
import logging
import asyncio
import yfinance as yf
from yahooquery import Ticker as YahooQueryTicker
import traceback
from config.settings import SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL
import pytz
from datetime import datetime
import re

from .stickers import get_stock_ticker_suggestions
from .ftickers import get_forex_ticker_suggestions
from .itickers import get_index_ticker_suggestions
from .ctickers import get_commodity_ticker_suggestions
from .bcrypto import get_crypto_price

logger = logging.getLogger(__name__)


class FinanceHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)

    def get_system_time(self):
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

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

    def _extract_explicit_ticker(self, q: str) -> str | None:
        """
        Prefer explicit tickers typed by user:
        - AAPL, TSLA, BRK-B, BTCUSDT, EURUSD=X, ^GSPC, GC=F, DX-Y.NYB
        """
        s = (q or "").strip()

        patterns = [
            r"\b\^[A-Z]{1,6}\b",                       # ^GSPC
            r"\b[A-Z]{1,8}=X\b",                       # EURUSD=X
            r"\b[A-Z]{1,6}=F\b",                       # GC=F
            r"\b[A-Z0-9]{5,12}USDT\b",                 # BTCUSDT
            r"\bDX-Y\.NYB\b",                          # DXY ticker
            r"\b000001\.SS\b",                         # Shanghai composite style
            r"\b[A-Z]{1,6}(?:[-.][A-Z]{1,4})?\b",       # AAPL, BRK-B (keep last so others win first)
        ]
        for pat in patterns:
            m = re.search(pat, s)
            if m:
                return m.group(0)
        return None

    def _candidate_queries(self, query: str) -> list[str]:
        """
        Generate multiple versions of the query for trying mappers.
        """
        raw = self._clean_query(query)
        norm = self._normalize_for_match(query)

        candidates = [raw, norm]

        # stripped variants (sometimes the dictionaries are strict)
        stripped = norm
        stripped = stripped.replace("price", "").replace("rate", "").replace("exchange", "")
        stripped = stripped.replace("conversion", "").replace("value", "").strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

        # Try extracting "xxx/yyy" inside longer text
        m = re.search(r"\b([a-z]{3})/([a-z]{3})\b", norm)
        if m:
            pair = f"{m.group(1)}/{m.group(2)}"
            if pair not in candidates:
                candidates.insert(0, pair)  # strongest

        # Remove empties / duplicates while preserving order
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

    # -----------------------------
    # NEW: sentence forex pair extractor
    # -----------------------------
    def _extract_fiat_pair(self, query: str) -> tuple[str, str] | None:
        """
        Extracts a fiat pair from messy sentences like:
          - 'USD to EUR exchange rate today'
          - 'what is the usd eur rate'
          - 'exchange rate eur to usd'
          - 'usd/eur'
          - 'eurusd'
        Returns (BASE, QUOTE) or None.

        Intentional: only supports 3-letter codes.
        """
        s = self._normalize_for_match(query)

        # already normalized to xxx/yyy
        m = re.search(r"\b([a-z]{3})/([a-z]{3})\b", s)
        if m:
            return (m.group(1).upper(), m.group(2).upper())

        # bare 6-letter pair
        m = re.fullmatch(r"([a-z]{3})([a-z]{3})", s)
        if m:
            return (m.group(1).upper(), m.group(2).upper())

        # token scan (first two 3-letter codes)
        tokens = re.findall(r"\b[a-zA-Z]{3}\b", query)
        codes = [t.upper() for t in tokens]
        if len(codes) >= 2:
            return (codes[0], codes[1])

        return None

    # -----------------------------
    # Result formatting
    # -----------------------------
    def _format_crypto_result(self, crypto_response: str, query: str) -> dict:
        """
        Expected bcrypto response (examples):
          - "Bitcoin (BTCUSDT): $69,310.36"
          - "btc (BTCUSDT): $69310.36"
        We parse robustly and return:
          - description with the exact number
          - price_usd numeric field (helps debugging + downstream)
        """
        s = (crypto_response or "").strip()

        if not s or "Error" in s:
            logger.error(f"bcrypto error for '{query}': {s}")
            return {
                "title": "Price Not Found",
                "url": "",
                "description": f"Crypto price could not be retrieved: {s or 'empty response'}",
                "source": "binance",
            }

        # name (SYMBOL): $123,456.78
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

        ticker = None

        # 0) Explicit ticker wins immediately (user typed AAPL, ^GSPC, GC=F, etc.)
        explicit = self._extract_explicit_ticker(query)
        if explicit:
            ticker = explicit
            logger.info(f"Using explicit ticker '{ticker}' from query '{query}'")

        # 1) Stocks/ETFs via dictionary suggestions (multiple candidate strings)
        if not ticker:
            for cand in self._candidate_queries(query):
                ticker_list = get_stock_ticker_suggestions(cand)
                if ticker_list:
                    ticker = ticker_list[0]
                    break

        # 2) Commodities (skip futures for ETF-ish queries)
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

        for attempt in range(retries):
            try:
                explicit = self._extract_explicit_ticker(query)
                if explicit and explicit.upper().endswith("USDT"):
                    crypto_response = get_crypto_price(explicit)
                else:
                    crypto_response = get_crypto_price(query)

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
        logger.info(f"Processing forex query: '{query}' at {self.get_system_time()}")

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

            # 2) Your existing dictionary-based suggestion fallback
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

                # numeric rate for downstream calculation
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
