import logging
import asyncio
import ollama
import traceback
import re
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
Output EXACTLY the refined query string for a DuckDuckGo news search, using "today" for recency. Do NOT use thinking mode, reasoning, explanations, or tags like <think> or **Answer**. Do NOT output anything other than the refined query string.

Examples:
- Input: latest news -> news today
- Input: Ukraine news -> Ukraine news today
- Input: whats the latest bbc news today -> BBC news today

Query: {query}
"""
        try:
            response = ollama.chat(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.2, "think": False}  # Disable thinking mode
            )
            raw_output = response.get("message", {}).get("content", query).strip()
            logger.debug(f"Raw LLM output for query refinement '{query}': {raw_output}")

            # Extract refined query from potentially verbose output
            refined_query = raw_output
            # Match "Answer: New York news today" or similar
            match = re.search(r'\b(?:Answer|Refined)\s*:\s*(.+)', raw_output, re.IGNORECASE)
            if match:
                refined_query = match.group(1).strip()
            else:
                # Take the last line as fallback
                lines = [line.strip() for line in raw_output.split('\n') if line.strip()]
                refined_query = lines[-1] if lines else query

            # Clean and validate refined query
            refined_query = re.sub(r'<[^>]+>', '', refined_query).strip()  # Remove tags
            invalid_terms = ['think', 'answer', 'reasoning', 'category']
            if not refined_query or any(term in refined_query.lower() for term in invalid_terms) or len(refined_query) > 100:
                logger.warning(f"Invalid refined query '{refined_query}' for '{query}'. Using default.")
                refined_query = f"{query.replace('whats the latest', '').strip()} today"

            logger.info(f"Refined news query: '{refined_query}'")
        except Exception as e:
            logger.error(f"Error refining news query '{query}': {str(e)}\nStack trace: {traceback.format_exc()}")
            refined_query = f"{query.replace('whats the latest', '').strip()} today"
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