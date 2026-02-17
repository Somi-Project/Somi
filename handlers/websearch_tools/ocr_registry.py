import logging
import re

# Configure basic logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

COMMODITY_TICKER_DICTIONARY = {
    "gold": "GC=F",
    "gold futures": "GC=F",
    "silver": "SI=F",
    "silver futures": "SI=F",
    "crude oil": "CL=F",
    "oil": "CL=F",
    "crude oil futures": "CL=F",
    "natural gas": "NG=F",
    "natural gas futures": "NG=F",
    "copper": "HG=F",
    "copper futures": "HG=F",
    "platinum": "PL=F",
    "platinum futures": "PL=F",
    "palladium": "PA=F",
    "palladium futures": "PA=F",
    "wheat": "ZW=F",
    "wheat futures": "ZW=F",
    "corn": "ZC=F",
    "corn futures": "ZC=F",
    "soybeans": "ZS=F",
    "soybean futures": "ZS=F",
    "coffee": "KC=F",
    "coffee futures": "KC=F",
    "sugar": "SB=F",
    "sugar futures": "SB=F",
    "cocoa": "CC=F",
    "cocoa futures": "CC=F",
    "cotton": "CT=F",
    "cotton futures": "CT=F",
    "live cattle": "LE=F",
    "cattle": "LE=F",
    "lean hogs": "HE=F",
    "hogs": "HE=F",
    "lumber": "LB=F",
    "lumber futures": "LB=F",
    "oats": "ZO=F",
    "oats futures": "ZO=F",
    "soybean oil": "ZL=F",
    "soybean oil futures": "ZL=F",
    "barrick gold": "GOLD",
    "newmont": "NEM",
    "nem": "NEM",
    "eldorado gold": "EGO",
    "ego": "EGO",
    "freeport-mcmoran": "FCX",
    "fcx": "FCX",
}


def get_commodity_ticker_suggestions(query: str) -> list:
    """
    Return a list of Yahoo Finance tickers that match the query for commodities.
    Args:
        query (str): Asset name (e.g., "gold", "crude oil").
    Returns:
        list: List of matching tickers (e.g., ["GC=F"]). Returns empty list if no match.
    """
    query_lower = (query or "").lower().strip()
    logger.debug(f"Processing commodity ticker query: '{query_lower}'")

    # Skip commodity futures for ETF-related queries
    etf_keywords = ["ishares", "spdr", "etf", "trust", "iau", "gld", "slv"]
    if any(keyword in query_lower for keyword in etf_keywords):
        logger.debug(f"Skipping commodity futures for ETF-related query: '{query}'")
        return []

    suggestions = set()
    for synonym, ticker in COMMODITY_TICKER_DICTIONARY.items():
        if re.search(r"\b" + re.escape(synonym.lower()) + r"\b", query_lower):
            suggestions.add(ticker)

    result = list(suggestions)[:1]
    logger.info(f"Commodity ticker suggestions for '{query}': {result}")
    return result
