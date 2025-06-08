import logging
import asyncio
import yfinance as yf
from yahooquery import Ticker as YahooQueryTicker
import traceback
from config.settings import SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL
import pytz
from datetime import datetime
from handlers.stickers import get_stock_ticker_suggestions
from handlers.ftickers import get_forex_ticker_suggestions
from handlers.itickers import get_index_ticker_suggestions
from handlers.ctickers import get_commodity_ticker_suggestions
from handlers.bcrypto import get_crypto_price
import re

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class FinanceHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)

    def get_system_time(self):
        """Get the current system time in the configured timezone."""
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def _format_crypto_result(self, crypto_response: str, query: str) -> dict:
        """Convert bcrypto.py string response to the expected dictionary format."""
        if "Error" in crypto_response:
            logger.error(f"bcrypto error for '{query}': {crypto_response}")
            return {
                "title": "Price Not Found",
                "url": "",
                "description": f"The price of the requested cryptocurrency could not be retrieved: {crypto_response}",
                "source": "binance"
            }
        
        match = re.match(r"(.+?)\s*\((.+?)\):\s*\$([\d,.]+)", crypto_response)
        if not match:
            logger.error(f"Invalid bcrypto response format for '{query}': {crypto_response}")
            return {
                "title": "Price Not Found",
                "url": "",
                "description": "The price of the requested cryptocurrency could not be retrieved due to an invalid response format.",
                "source": "binance"
            }
        
        name, symbol, price = match.groups()
        return {
            "title": f"{name.strip()} ({symbol}) Price",
            "url": f"https://www.binance.com/en/trade/{symbol}",
            "description": f"Current price: {price} USD. This Binance data is the most accurate and up-to-date. The price must not be altered, as changing it could mislead the user and cause financial harm.",
            "source": "binance"
        }

    async def search_stocks_commodities(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        """Search stock, commodity, or index prices using yfinance with ticker mapping, falling back to yahooquery."""
        if DISABLE_MEMORY_FOR_FINANCIAL:
            logger.info("Memory usage disabled for stock/commodity/index query")

        query_lower = query.lower().strip()
        logger.info(f"Processing stock/commodity query: '{query}' at {self.get_system_time()}")

        ticker_list = get_stock_ticker_suggestions(query)
        ticker = ticker_list[0] if ticker_list else None

        if not ticker and not any(k in query_lower for k in ["ishares", "spdr", "etf", "trust"]):
            ticker_list = get_commodity_ticker_suggestions(query)
            ticker = ticker_list[0] if ticker_list else None

        if not ticker:
            ticker_list = get_index_ticker_suggestions(query)
            ticker = ticker_list[0] if ticker_list else None
        
        if not ticker:
            potential_ticker = query_lower.replace("whats the price of", "").replace("stock", "").strip()
            if potential_ticker.upper() in ["IAU", "GLD", "AAPL", "SLV"]:
                ticker = potential_ticker.upper()
                logger.info(f"Using query as ticker: '{ticker}' for query '{query}'")

        if not ticker:
            logger.warning(f"No valid ticker found for query '{query}'")
            return [{"title": "Asset Not Found", "url": "", "description": "No matching stock or commodity ticker found for the query."}]
        
        logger.info(f"Using ticker '{ticker}' for query '{query}'")

        for attempt in range(retries):
            try:
                logger.info(f"Attempting yfinance query for ticker '{ticker}' (attempt {attempt + 1}/{retries})")
                asset = yf.Ticker(ticker)
                info = asset.info
                logger.info(f"Successfully retrieved yfinance data for '{ticker}'")
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = info.get("shortName", ticker)
                currency = info.get("currency", "USD")
                logger.info(f"yfinance data for '{ticker}': name='{name}', price={price}, currency={currency}")
                if price == "N/A":
                    logger.info(f"No valid price for '{ticker}'")
                    raise ValueError("No valid price from yfinance")
                return [{
                    "title": f"{name} ({ticker}) Price",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Current price: {price} {currency}. This Yahoo Finance data is the most accurate and up-to-date. The price must not be altered, as changing it could mislead the user and cause financial harm.",
                    "source": "yfinance_exclusive"
                }]
            except Exception as e:
                logger.warning(f"yfinance query failed for '{ticker}': {str(e)}. Attempt {attempt + 1}/{retries}.")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.warning(f"All {retries} yfinance attempts failed for '{ticker}'. Falling back to yahooquery.")

        for attempt in range(retries):
            try:
                logger.info(f"Attempting yahooquery query for ticker '{ticker}' (attempt {attempt + 1}/{retries})")
                asset = YahooQueryTicker(ticker)
                info = asset.summary_detail.get(ticker, {})
                logger.info(f"Successfully retrieved yahooquery data for '{ticker}'")
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = asset.quote_type.get(ticker, {}).get("shortName", ticker)
                currency = info.get("currency", "USD")
                logger.info(f"yahooquery data for '{ticker}': name='{name}', price={price}, currency={currency}")
                if price == "N/A":
                    logger.info(f"No valid price for '{ticker}'")
                    return [{"title": "Price Not Found", "url": "", "description": "The price of the requested asset could not be retrieved at this time."}]
                return [{
                    "title": f"{name} ({ticker}) Price",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Current price: {price} {currency}. This Yahoo Finance data is the most accurate and up-to-date. The price must not be altered, as changing it could mislead the user and cause financial harm.",
                    "source": "yahooquery_fallback"
                }]
            except Exception as e:
                logger.error(f"yahooquery query failed for '{ticker}': {str(e)}\nStack trace: {traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.error(f"All {retries} yahooquery attempts failed for '{ticker}'")
        return [{"title": "Price Not Found", "url": "", "description": "The price of the requested asset could not be retrieved at this time."}]

    async def search_crypto_yfinance(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        """Search cryptocurrency prices using bcrypto handler."""
        if DISABLE_MEMORY_FOR_FINANCIAL:
            logger.info("Memory usage disabled for crypto query")

        logger.info(f"Attempting crypto price fetch for query '{query}' using bcrypto")
        for attempt in range(retries):
            try:
                crypto_response = get_crypto_price(query)
                result = self._format_crypto_result(crypto_response, query)
                logger.info(f"Successfully retrieved crypto data for '{query}': {result}")
                return [result]
            except Exception as e:
                logger.error(f"bcrypto query failed for '{query}': {str(e)}\nStack trace: {traceback.format_exc()}")
                if attempt < retries - 1:
                    logger.info(f"Retrying crypto query (attempt {attempt + 1}/{retries})")
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.error(f"All {retries} bcrypto attempts failed for '{query}'")
        return [{"title": "Price Not Found", "url": "", "description": "The price of the requested cryptocurrency could not be retrieved at this time."}]

    async def search_forex_yfinance(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        """Search forex exchange rates using yfinance with ticker mapping, falling back to yahooquery."""
        if DISABLE_MEMORY_FOR_FINANCIAL:
            logger.info("Memory usage disabled for forex query")

        query_lower = query.lower().strip()
        logger.info(f"Processing forex query: '{query}' at {self.get_system_time()}")

        # Normalize query for forex pair (e.g., "usdjpy" -> "usd/jpy")
        normalized_query = re.sub(r'^(whats\s+the\s+(?:conversion\s+rate|exchange\s+rate|rate)\s+of)\s+', '', query_lower).strip()
        normalized_query = re.sub(r'\b([a-z]{3})([a-z]{3})\b', r'\1/\2', normalized_query)  # Convert "usdjpy" to "usd/jpy"
        logger.debug(f"Normalized forex query: '{normalized_query}'")

        ticker_list = get_forex_ticker_suggestions(normalized_query)
        ticker = ticker_list[0] if ticker_list else None

        # Fallback: Try original query if normalized query fails
        if not ticker:
            ticker_list = get_forex_ticker_suggestions(query_lower)
            ticker = ticker_list[0] if ticker_list else None

        if not ticker:
            logger.warning(f"No valid forex ticker found for query '{query}' (normalized: '{normalized_query}')")
            return [{"title": "Error", "url": "", "description": "No valid ticker found for the requested currency pair."}]
        
        logger.info(f"Valid forex ticker '{ticker}' extracted for query '{query}'")

        for attempt in range(retries):
            try:
                logger.info(f"Attempting yfinance query for ticker '{ticker}' (attempt {attempt + 1}/{retries})")
                forex = yf.Ticker(ticker)
                info = forex.info
                logger.info(f"Successfully retrieved yfinance data for '{ticker}'")
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = info.get("shortName", ticker)
                currency = info.get("currency", "USD")
                logger.info(f"yfinance data for '{ticker}': name='{name}', price={price}, currency={currency}")
                if price == "N/A":
                    logger.info(f"No valid rate for '{ticker}'")
                    raise ValueError("No valid rate from yfinance")
                return [{
                    "title": f"{name} ({ticker}) Exchange Rate",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Asset is currently {price} {currency}. This Yahoo Finance data is the most accurate and up-to-date. The rate must not be altered, as changing it could mislead the user and cause financial harm.",
                    "source": "yfinance_exclusive"
                }]
            except Exception as e:
                logger.warning(f"yfinance query failed for '{ticker}': {str(e)}. Attempt {attempt + 1}/{retries}.")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.warning(f"All {retries} yfinance attempts failed for '{ticker}'. Falling back to yahooquery.")

        for attempt in range(retries):
            try:
                logger.info(f"Attempting yahooquery query for ticker '{ticker}' (attempt {attempt + 1}/{retries})")
                forex = YahooQueryTicker(ticker)
                info = forex.summary_detail.get(ticker, {})
                logger.info(f"Successfully retrieved yahooquery data for '{ticker}'")
                price = info.get("regularMarketPrice", info.get("previousClose", "N/A"))
                name = forex.quote_type.get(ticker, {}).get("shortName", ticker)
                currency = info.get("currency", "USD")
                logger.info(f"yahooquery data for '{ticker}': name='{name}', price={price}, currency={currency}")
                if price == "N/A":
                    logger.info(f"No valid rate for '{ticker}'")
                    return [{"title": "Rate Not Found", "url": "", "description": "The exchange rate for the requested currency pair could not be retrieved at this time."}]
                return [{
                    "title": f"{name} ({ticker}) Exchange Rate",
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "description": f"Asset is currently {price} {currency}. This Yahoo Finance data is the most accurate and up-to-date. The rate must not be altered, as changing it could mislead the user and cause financial harm.",
                    "source": "yahooquery_fallback"
                }]
            except Exception as e:
                logger.error(f"yahooquery query failed for '{ticker}': {str(e)}\nStack trace: {traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.error(f"All {retries} yahooquery attempts failed for '{ticker}'")
        return [{"title": "Rate Not Found", "url": "", "description": "The exchange rate for the requested currency pair could not be retrieved at this time."}]