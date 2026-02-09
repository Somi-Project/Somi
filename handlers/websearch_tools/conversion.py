# handlers/websearch_tools/conversion.py
import re
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict

# Import your existing mappers / helpers
from .ftickers import get_forex_ticker_suggestions
from .ctickers import get_commodity_ticker_suggestions
from .stickers import get_stock_ticker_suggestions
# bcrypto is called indirectly via search_crypto_yfinance

logger = logging.getLogger(__name__)


@dataclass
class ConversionRequest:
    amount: float
    src: str      # e.g. "AUD", "ETH", "GOLD"
    dst: str


# Spoken/phrase → canonical code (expand as needed)
SPOKEN_TO_CODE = {
    # Fiat
    "australian dollar": "AUD", "aud": "AUD", "aussie": "AUD", "australian dollars": "AUD",
    "trinidad dollar": "TTD", "ttd": "TTD", "trinidad and tobago dollar": "TTD", "trinidad dollars": "TTD",
    "us dollar": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "american dollar": "USD",
    "euro": "EUR", "eur": "EUR", "euros": "EUR",
    "pound": "GBP", "gbp": "GBP", "british pound": "GBP", "sterling": "GBP",
    "yen": "JPY", "jpy": "JPY", "japanese yen": "JPY",
    "canadian dollar": "CAD", "cad": "CAD",
    # Crypto
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "solana": "SOL", "sol": "SOL",
    # Commodities
    "gold": "GOLD", "ounce of gold": "GOLD", "xau": "GOLD",
}


_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_conversion_request(query: str) -> Optional[ConversionRequest]:
    """
    Extract amount, src, dst from natural language.
    Uses spoken-to-code mapping + regex patterns.
    """
    q = (query or "").lower().strip()
    if not q:
        return None

    m_amt = _AMOUNT_RE.search(q)
    if not m_amt:
        return None
    amount_str = m_amt.group(1)
    amount = float(amount_str)

    # Patterns (tuned for your examples)
    patterns = [
        # "100 aud to ttd" / "100 australian dollars to trinidad dollars"
        rf"\b{re.escape(amount_str)}\s+([a-z ]+)\s+(?:to|in|for)\s+([a-z ]+)\b",
        # "how much ttd is 100 aud" / "how many trinidad dollars for 100 australian dollars"
        r"\bhow\s+(?:much|many)\s+([a-z ]+)\s+(?:is|for|in)\s+" + re.escape(amount_str) + r"\s+([a-z ]+)\b",
        # "tTD is 100 aud"
        r"\b([a-z ]+)\s+is\s+" + re.escape(amount_str) + r"\s+([a-z ]+)\b",
    ]

    for pat in patterns:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            # Determine src/dst based on pattern structure
            if "how" in pat:
                dst_raw, src_raw = m.group(1).strip(), m.group(2).strip()
            else:
                src_raw, dst_raw = m.group(1).strip(), m.group(2).strip()

            src = SPOKEN_TO_CODE.get(src_raw, src_raw.upper().replace(" ", ""))
            dst = SPOKEN_TO_CODE.get(dst_raw, dst_raw.upper().replace(" ", ""))

            if not src or not dst or src == dst:
                continue

            return ConversionRequest(amount=amount, src=src, dst=dst)

    logger.debug(f"No match for query: {query}")
    return None


class Converter:
    def __init__(self, websearch_router):
        self.ws = websearch_router

    def _extract_price(self, result: Dict) -> Optional[float]:
        """Extract numeric USD value from any finance result dict"""
        if not isinstance(result, dict):
            return None

        # Try common keys
        for key in ["price_usd", "rate", "price", "regularMarketPrice", "previousClose"]:
            v = result.get(key)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    continue

        # Fallback: parse description (e.g. "Current price: 2845.20 USD")
        desc = result.get("description", "") or ""
        m = re.search(r"[\d,]+\.?\d*", desc)
        if m:
            try:
                return float(m.group(0).replace(",", ""))
            except:
                pass

        return None

    async def _get_usd_value(self, asset: str, amount: float = 1.0) -> Optional[float]:
        asset = asset.strip().upper()
        if not asset:
            return None

        logger.info(f"→ Resolving {amount} {asset} to USD")

        # 1. USD shortcut
        if asset == "USD":
            return amount

        # 2. Try crypto first (uses bcrypto mapping via search_crypto_yfinance)
        try:
            query = f"{asset} price" if not asset.endswith("USDT") else asset
            res = await asyncio.wait_for(
                self.ws.finance_handler.search_crypto_yfinance(query),
                timeout=10.0
            )
            if res and res[0] and "price_usd" in res[0]:
                v = float(res[0]["price_usd"])
                logger.info(f"   Crypto success → {asset} = {v:.2f} USD")
                return amount * v
        except asyncio.TimeoutError:
            logger.debug(f"   Crypto timeout for {asset}")
        except Exception as e:
            logger.debug(f"   Crypto path skipped/failed for {asset}: {e}")

        # 3. Try forex (uses ftickers mapping via search_forex_yfinance)
        if len(asset) == 3 and asset.isalpha():
            try:
                res = await asyncio.wait_for(
                    self.ws.finance_handler.search_forex_yfinance(f"{asset} to USD"),
                    timeout=12.0
                )
                if res and res[0]:
                    v = self._extract_price(res[0])
                    if v is not None:
                        logger.info(f"   Forex success → {asset} = {v:.6f} USD")
                        return amount * v
            except asyncio.TimeoutError:
                logger.debug(f"   Forex timeout for {asset}")
            except Exception as e:
                logger.debug(f"   Forex path skipped/failed for {asset}: {e}")

        # 4. Try commodity / stock (uses ctickers/stickers via search_stocks_commodities)
        try:
            query = f"price of {asset}" if asset != "GOLD" else "GC=F"  # force gold futures
            res = await asyncio.wait_for(
                self.ws.finance_handler.search_stocks_commodities(query),
                timeout=12.0
            )
            if res and res[0]:
                v = self._extract_price(res[0])
                if v is not None:
                    logger.info(f"   Commodity/stock success → {asset} = {v:.2f} USD")
                    return amount * v
        except asyncio.TimeoutError:
            logger.debug(f"   Commodity timeout for {asset}")
        except Exception as e:
            logger.debug(f"   Commodity/stock path failed for {asset}: {e}")

        logger.error(f"   Failed to resolve {asset} to USD")
        return None

    async def convert(self, query: str) -> str:
        parsed = parse_conversion_request(query)
        if not parsed:
            return "Error: Could not understand the conversion request."

        try:
            src_usd = await self._get_usd_value(parsed.src, parsed.amount)
            if src_usd is None:
                return f"Error: Could not fetch price for {parsed.src}."

            dst_usd_per_1 = await self._get_usd_value(parsed.dst, 1.0)
            if dst_usd_per_1 is None or dst_usd_per_1 == 0:
                return f"Error: Could not fetch price for {parsed.dst}."

            result = src_usd / dst_usd_per_1

            amt_str = f"{parsed.amount:g}"
            conv_str = f"{result:,.6f}".rstrip("0").rstrip(".")

            return f"{amt_str} {parsed.src.upper()} ≈ {conv_str} {parsed.dst.upper()}"

        except asyncio.TimeoutError:
            return "Error: Conversion timed out (data source slow or rate limited)."
        except Exception as e:
            logger.error(f"Conversion failed: {e}", exc_info=True)
            return "Error during conversion."