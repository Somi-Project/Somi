import logging
import asyncio
import ollama
import traceback
from duckduckgo_search import DDGS
from config.settings import DEFAULT_MODEL, SYSTEM_TIMEZONE
from .finance import FinanceHandler
from .news import NewsHandler
from .weather import WeatherHandler
import pytz
from datetime import datetime

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class WebSearchHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)
        self.finance_handler = FinanceHandler()
        self.news_handler = NewsHandler()
        self.weather_handler = WeatherHandler()

    def get_system_time(self):
        """Get the current system time in the configured timezone."""
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    async def search(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        """Route the query to the appropriate search method based on LLM classification."""
        query_lower = query.lower().strip()
        logger.info(f"Processing query: '{query}'")

        # Fallback for index, currency code, and forex term detection
        index_terms = ['dxy', 's&p 500', 'sp500', 'dow jones', 'nasdaq', 'nasdaq 100', 'vix', 'ftse', 'nikkei', 'hang seng', 'dax', 'cac', 'shanghai', 'sensex', 'asx', 'kospi']
        currency_codes = ['usd', 'eur', 'gbp', 'jpy', 'ttd', 'cad', 'aud', 'chf', 'nzd']
        forex_terms = [
            'exchange rate', 'conversion rate', 'forex', 'currency', 'exchange', 'convert', 'rate',
            'currency conversion', 'dollar yen', 'yen', 'euro dollar', 'pound dollar', 'aussie dollar',
            'kiwi dollar', 'loonie', 'swissie', 'yuan', 'rupee', 'peso', 'real', 'rand'
        ]

        # LLM prompt for classification
        prompt = f"""
Classify the following query into one of these categories: "stock/commodity", "crypto", "forex", "weather", "news", or "general".
- "stock/commodity": Queries about stock prices, company shares, commodities (e.g., gold, oil), or market indices (e.g., S&P 500, DXY, Nasdaq 100). Prioritize terms like "stock", "price", "ticker", "shares", "market", "index", "dxy", "nasdaq", "dow jones". Examples: "Apple stock price", "gold price today", "NVIDIA ticker", "crude oil market", "whats the price of DXY", "Nasdaq 100 price".
- "crypto": Queries about cryptocurrencies. Prioritize terms like "crypto", "price", "coin", "sol", "bitcoin", "ethereum". Examples: "Bitcoin price", "Ethereum value", "Solana market cap", "whats the price of sol".
- "forex": Queries about currency exchange rates or forex. Prioritize terms like "exchange rate", "conversion rate", "currency", "forex", "exchange", "convert", "rate", "currency conversion", "dollar yen", "yen", "euro dollar", "pound dollar", or currency pairs (e.g., USD/EUR, GBP to USD, TTD to USD, usdjpy, eurusd). Examples: "USD to EUR rate", "EUR/USD exchange", "whats the conversion rate of usdjpy", "whats the price of usdjpy", "TTD to USD exchange rate", "gbpusd rate", "euro conversion rate", "convert USD to JPY", "what's the exchange for usdjpy", "currency conversion USD to EUR", "dollar yen price", "yen exchange rate".
- "weather": Queries about weather conditions. Examples: "New York weather", "London forecast", "temperature today".
- "news": Queries about news or current events. Examples: "latest news", "Ukraine headlines", "BBC news today".
- "general": Any query not fitting the above categories. Examples: "history of Rome", "best restaurants".
Return **only** the category name (e.g., "stock/commodity", "crypto", "forex", "weather", "news", "general") with no additional text or explanation.

Query: {query}
"""
        for attempt in range(retries):
            try:
                response = ollama.chat(
                    model=DEFAULT_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.0}  # Lower temperature for consistency
                )
                query_type = response.get("message", {}).get("content", "general").strip()
                query_type = query_type.strip('"').strip("'")
                logger.info(f"Classified query '{query}' as '{query_type}'")
                break
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(f"LLM classification attempt {attempt + 1} failed for '{query}': {str(e)}. Retrying...")
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                else:
                    logger.error(f"All {retries} LLM classification attempts failed for '{query}': {str(e)}\nStack trace: {traceback.format_exc()}")
                    return [{"title": "Error", "url": "", "description": "errors"}]
        else:
            logger.error(f"All {retries} LLM classification attempts exhausted for '{query}'")
            return [{"title": "Error", "url": "", "description": "errors"}]

        # Normalize query for forex check (e.g., "usdjpy" -> "usdjpy", "usd/jpy" -> "usdjpy", "usd to jpy" -> "usdjpy")
        normalized_query = query_lower.replace('/', '').replace(' to ', '').replace(' ', '')
        logger.debug(f"Normalized query for forex check: '{normalized_query}'")
        logger.debug(f"Forex check for '{query_lower}': forex_terms={any(term in query_lower for term in forex_terms)}, currency_codes={any(code in normalized_query for code in currency_codes)}, query_type={query_type}")

        # Check for index terms to avoid misclassification
        if any(term in query_lower for term in index_terms):
            logger.info(f"Query '{query}' contains index terms: routing to stocks/commodities")
            return await self.finance_handler.search_stocks_commodities(query_lower)

        # Force forex routing if forex terms or currency codes are present, regardless of LLM classification
        is_forex_query = (
            any(term in query_lower for term in forex_terms) or
            any(code in normalized_query for code in currency_codes)
        )
        if is_forex_query:
            logger.info(f"Query '{query}' contains currency codes or forex terms: forcing routing to forex")
            return await self.finance_handler.search_forex_yfinance(query_lower)

        # Skip memory retrieval for financial queries
        if query_type in ["stock/commodity", "crypto", "forex"]:
            logger.info(f"Skipping memory retrieval for financial query type '{query_type}'")
        else:
            logger.info(f"Memory retrieval allowed for non-financial query type '{query_type}'")

        # Route based on LLM classification (if not already routed to forex)
        if query_type == "stock/commodity":
            logger.info(f"Query '{query}' routed to finance (Stocks/Commodities)")
            return await self.finance_handler.search_stocks_commodities(query)
        elif query_type == "crypto":
            logger.info(f"Query '{query}' routed to finance (Crypto)")
            return await self.finance_handler.search_crypto_yfinance(query)
        elif query_type == "forex":
            logger.info(f"Query '{query}' routed to finance (Forex)")
            return await self.finance_handler.search_forex_yfinance(query_lower)
        elif query_type == "weather":
            logger.info(f"Query '{query}' routed to weather search")
            return await self.weather_handler.search_weather(query, retries, backoff_factor)
        elif query_type == "news":
            logger.info(f"Query '{query}' routed to news search")
            return await self.news_handler.search_news(query, retries, backoff_factor)
        else:
            logger.info(f"Query '{query}' routed to general web search")
            return await self.search_web(query, retries, backoff_factor)

    async def search_web(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        """Perform a DuckDuckGo search for general queries."""
        for attempt in range(retries):
            try:
                with DDGS() as ddgs:
                    results = ddgs.text(query, max_results=15)
                logger.info(f"Successfully retrieved {len(results)} results for query '{query}'")
                formatted_results = [
                    {
                        "title": result.get("title", ""),
                        "url": result.get("href", ""),
                        "description": result.get("body", "")
                    }
                    for result in results
                ]
                return formatted_results
            except Exception as e:
                logger.error(f"Error during DuckDuckGo search (attempt {attempt + 1}/{retries}): {str(e)}\nStack trace: {traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.error(f"All {retries} attempts failed for query '{query}'")
        return []

    def format_results(self, results: list) -> str:
        """Format search results as a string."""
        if not results:
            return "No search results found."
        formatted = [
            f"Title: {r['title']}\nURL: {r['url']}\nDescription: {r['description']}\n"
            for r in results
        ]
        formatted_text = "\n".join(formatted)
        logger.info(f"Complete formatted web search results: {formatted_text}")
        return formatted_text