import logging
import asyncio
import ollama
import traceback
from duckduckgo_search import DDGS
from config.settings import DEFAULT_MODEL, SYSTEM_TIMEZONE
import pytz
from datetime import datetime

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class NewsHandler:
    def __init__(self):
        self.timezone = pytz.timezone(SYSTEM_TIMEZONE)

    def get_system_time(self):
        """Get the current system time in the configured timezone."""
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    async def search_news(self, query: str, retries: int = 3, backoff_factor: float = 0.5) -> list:
        """Search news using DuckDuckGo news search with LLM query refinement."""
        current_time = self.get_system_time()
        prompt = f"""
You are part of the SomiAgent AI framework, a versatile system with capabilities including web search, time awareness, and memory storage. The current time and date is {current_time}. Your internal knowledge and memories are outdated for this news query. You must rely solely on the web search results provided to generate an accurate response. Do not conflict your internal knowledge or memories with the search results. If no web search results are found, do not generate news headlines; instead, report that no results are available.

Refine the following news query to make it specific and suitable for a DuckDuckGo news search. Focus on recent news (e.g., today, this week) and include any specific topic or source (e.g., BBC) mentioned. Use the term 'today' to ensure recency instead of a specific date. Return only the refined query string with no additional text, explanation, or quotation marks.

Examples:
- Input: "latest news" -> news today
- Input: "Ukraine news" -> Ukraine news today
- Input: "whats the latest bbc news today" -> BBC news today

Query: {query}
"""
        try:
            response = ollama.chat(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.2}
            )
            refined_query = response.get("message", {}).get("content", query).strip()
            logger.info(f"Refined news query: '{refined_query}'")
        except Exception as e:
            logger.error(f"Error refining news query '{query}': {str(e)}")
            refined_query = f"{query} today"
            logger.info(f"Falling back to default news query: '{refined_query}'")

        for attempt in range(retries):
            try:
                with DDGS() as ddgs:
                    results = ddgs.news(refined_query, max_results=15)
                logger.info(f"Successfully retrieved {len(results)} news results for query '{refined_query}'")
                if not results and attempt == retries - 1:
                    broader_query = query.replace("today", "").strip() + " news"
                    logger.info(f"No results for '{refined_query}', falling back to '{broader_query}'")
                    with DDGS() as ddgs:
                        results = ddgs.news(broader_query, max_results=15)
                    logger.info(f"Retrieved {len(results)} news results for fallback query '{broader_query}'")
                formatted_results = [
                    {
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "description": result.get("snippet", "")
                    }
                    for result in results
                ]
                return formatted_results
            except Exception as e:
                logger.error(f"Error during DuckDuckGo news search (attempt {attempt + 1}/{retries}): {str(e)}\nStack trace: {traceback.format_exc()}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                continue
        logger.error(f"All {retries} attempts failed for news query '{refined_query}'")
        return []