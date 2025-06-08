import logging
import re

# Configure basic logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

INDEX_TICKER_DICTIONARY = {
    "dxy": "DX-Y.NYB",
    "dollar index": "DX-Y.NYB",
    "us dollar index": "DX-Y.NYB",
    "usd index": "DX-Y.NYB",
    "s&p 500": "^GSPC",
    "sp500": "^GSPC",
    "s&p": "^GSPC",
    "s and p 500": "^GSPC",
    "spx": "^GSPC",
    "s&p500": "^GSPC",
    "dow jones": "^DJI",
    "dow": "^DJI",
    "djia": "^DJI",
    "dow jones industrial": "^DJI",
    "nasdaq": "^IXIC",
    "nasdaq composite": "^IXIC",
    "nasdaq 100": "^NDX",
    "ndx": "^NDX",
    "nasdaq 100 futures": "NQ=F",
    "vix": "^VIX",
    "volatility index": "^VIX",
    "vix index": "^VIX",
    "ftse 100": "^FTSE",
    "ftse": "^FTSE",
    "uk 100": "^FTSE",
    "nikkei 225": "^N225",
    "nikkei": "^N225",
    "hang seng": "^HSI",
    "hsi": "^HSI",
    "dax": "^GDAXI",
    "cac 40": "^FCHI",
    "cac": "^FCHI",
    "shanghai composite": "000001.SS",
    "shanghai": "000001.SS",
    "bse sensex": "^BSESN",
    "sensex": "^BSESN",
    "asx 200": "^AXJO",
    "asx": "^AXJO",
    "kospi": "^KS11"
}

def get_index_ticker_suggestions(query: str) -> list:
    """
    Return a list of Yahoo Finance tickers that match the query for indices.
    Args:
        query (str): Index name (e.g., "s&p 500", "dow jones").
    Returns:
        list: List of matching tickers (e.g., ["^GSPC"]). Returns empty list if no match.
    """
    query_lower = query.lower().strip()
    logger.debug(f"Processing index query: '{query_lower}'")

    # Clean query to remove common prefixes
    cleaned_query = re.sub(r'^(whats\s+the\s+(?:price|value|level)\s+of)\s+', '', query_lower).strip()
    logger.debug(f"Cleaned query: '{cleaned_query}'")

    suggestions = set()

    # Try exact match
    if cleaned_query in INDEX_TICKER_DICTIONARY:
        ticker = INDEX_TICKER_DICTIONARY[cleaned_query]
        logger.debug(f"Exact match found: '{cleaned_query}' -> '{ticker}'")
        suggestions.add(ticker)

    # Try partial matching with dictionary keys
    for synonym, ticker in INDEX_TICKER_DICTIONARY.items():
        if re.search(r'\b' + re.escape(synonym.lower()) + r'\b', cleaned_query):
            logger.debug(f"Matched synonym '{synonym}' in '{cleaned_query}' -> '{ticker}'")
            suggestions.add(ticker)

    result = list(suggestions)[:1]
    if not result:
        logger.warning(f"No ticker matches found for query '{query}' (cleaned: '{cleaned_query}')")
    else:
        logger.info(f"Index ticker suggestions for '{query}': {result}")
    return result