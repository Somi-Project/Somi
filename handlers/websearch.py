import logging
import asyncio
import ollama
import traceback
import re
from duckduckgo_search import DDGS
from config.settings import DEFAULT_MODEL, INSTRUCT_MODEL, SYSTEM_TIMEZONE
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

        # Fallback for index, currency code, forex, crypto, weather, and news term detection
        index_terms = ['dxy', 's&p 500', 'sp500', 'dow jones', 'nasdaq', 'nasdaq 100', 'vix', 'ftse', 'nikkei', 'hang seng', 'dax', 'cac', 'shanghai', 'sensex', 'asx', 'kospi']
        currency_codes = ['usd', 'eur', 'gbp', 'jpy', 'ttd', 'cad', 'aud', 'chf', 'nzd']
        forex_terms = [
            'exchange rate', 'conversion rate', 'forex', 'currency', 'exchange', 'convert', 'rate',
            'currency conversion', 'dollar yen', 'yen', 'euro dollar', 'pound dollar', 'aussie dollar',
            'kiwi dollar', 'loonie', 'swissie', 'yuan', 'rupee', 'peso', 'real', 'rand'
        ]
        crypto_terms = ['bitcoin', 'ethereum', 'solana', 'crypto', 'coin', 'cryptocurrency']
        weather_terms = ['weather', 'forecast', 'temperature', 'sunrise', 'sunset', 'moon phase', 'moon cycle']
        news_terms = ['news', 'headlines', 'current events', 'latest news', 'bbc', 'cnn', 'breaking news']

        # Strict LLM prompt for single-word output
        prompt = f"""
You are a text classifier. Output EXACTLY ONE WORD from the following categories: stock/commodity, crypto, forex, weather, news, general. Do NOT use thinking mode, reasoning, explanations, or tags like <think> or **Answer**. Do NOT output anything other than the category name.

Categories:
- stock/commodity: Stock prices, commodities (gold, oil), or indices (S&P 500, DXY). Examples: "Apple stock", "gold price", "Nasdaq 100".
- crypto: Cryptocurrencies. Examples: "Bitcoin price", "Ethereum value", "whats the price of sol".
- forex: Currency exchange rates. Examples: "USD to EUR", "usdjpy rate", "currency conversion".
- weather: Weather conditions or forecasts. Examples: "New York weather", "London forecast", "sunrise time".
- news: News or current events. Examples: "latest news", "BBC news", "Ukraine headlines".
- general: Other topics. Examples: "history of Rome", "best restaurants".

Query: {query}
"""
        for attempt in range(retries):
            try:
                response = ollama.chat(
                    model=INSTRUCT_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.0, "think": False}  # Disable thinking mode
                )
                raw_output = response.get("message", {}).get("content", "general").strip()
                logger.debug(f"Raw LLM output for '{query}' using {INSTRUCT_MODEL}: {raw_output}")

                # Extract category from potentially verbose output
                query_type = raw_output
                # Try to match "Answer: crypto" or similar
                match = re.search(r'\b(?:Answer|Category)\s*:\s*(\w+(?:/\w+)?)\b', raw_output, re.IGNORECASE)
                if match:
                    query_type = match.group(1).strip()
                else:
                    # Take the last word as fallback
                    words = raw_output.split()
                    query_type = words[-1].strip('"').strip("'") if words else "general"

                # Validate query_type
                valid_categories = ["stock/commodity", "crypto", "forex", "weather", "news", "general"]
                if query_type not in valid_categories:
                    logger.warning(f"Invalid category '{query_type}' for query '{query}'. Defaulting to 'general'.")
                    query_type = "general"

                logger.info(f"Classified query '{query}' as '{query_type}' using {INSTRUCT_MODEL}")
                break
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(f"LLM classification attempt {attempt + 1} failed for '{query}' using {INSTRUCT_MODEL}: {str(e)}. Retrying...")
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                else:
                    logger.error(f"All {retries} LLM classification attempts failed for '{query}' using {INSTRUCT_MODEL}: {str(e)}\nStack trace: {traceback.format_exc()}")
                    return [{"title": "Error", "url": "", "description": "errors"}]
        else:
            logger.error(f"All {retries} LLM classification attempts exhausted for '{query}' using {INSTRUCT_MODEL}")
            return [{"title": "Error", "url": "", "description": "errors"}]

        # Normalize query for forex check
        normalized_query = query_lower.replace('/', '').replace(' to ', '').replace(' ', '')
        logger.debug(f"Normalized query for forex check: '{normalized_query}'")
        logger.debug(f"Forex check for '{query_lower}': forex_terms={any(term in query_lower for term in forex_terms)}, currency_codes={any(code in normalized_query for code in currency_codes)}, query_type={query_type}")

        # Check for index terms
        if any(term in query_lower for term in index_terms):
            logger.info(f"Query '{query}' contains index terms: routing to stocks/commodities")
            return await self.finance_handler.search_stocks_commodities(query_lower)

        # Force crypto routing if crypto terms are present and classification is not financial
        if query_type not in ["stock/commodity", "crypto", "forex"] and any(term in query_lower for term in crypto_terms):
            logger.info(f"Overriding classification '{query_type}' for '{query}' to 'crypto' due to crypto terms")
            query_type = "crypto"

        # Force weather routing if weather terms are present and classification is not weather
        if query_type != "weather" and any(term in query_lower for term in weather_terms):
            logger.info(f"Overriding classification '{query_type}' for '{query}' to 'weather' due to weather terms")
            query_type = "weather"

        # Force news routing if news terms are present and classification is not news
        if query_type != "news" and any(term in query_lower for term in news_terms):
            logger.info(f"Overriding classification '{query_type}' for '{query}' to 'news' due to news terms")
            query_type = "news"

        # Force forex routing
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

        # Route based on LLM classification
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