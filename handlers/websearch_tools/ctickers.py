import logging
import re

logger = logging.getLogger(__name__)

COMMODITY_TICKER_DICTIONARY = {
    # Metals
    "gold": "GC=F",
    "gold futures": "GC=F",
    "silver": "SI=F",
    "silver futures": "SI=F",
    "copper": "HG=F",
    "copper futures": "HG=F",
    "platinum": "PL=F",
    "platinum futures": "PL=F",
    "palladium": "PA=F",
    "palladium futures": "PA=F",

    # Energy
    "crude oil": "CL=F",
    "oil": "CL=F",
    "wti": "CL=F",
    "wti crude": "CL=F",
    "brent": "BZ=F",
    "brent crude": "BZ=F",
    "natural gas": "NG=F",
    "natural gas futures": "NG=F",
    "gasoline": "RB=F",
    "heating oil": "HO=F",

    # Ags
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
    "lumber": "LB=F",
    "lumber futures": "LB=F",
    "oats": "ZO=F",
    "oats futures": "ZO=F",

    # Livestock
    "live cattle": "LE=F",
    "cattle": "LE=F",
    "lean hogs": "HE=F",
    "hogs": "HE=F",

    # Popular miners (stocks)
    "barrick gold": "GOLD",
    "newmont": "NEM",
    "eldorado gold": "EGO",
    "freeport-mcmoran": "FCX",
}

def get_commodity_ticker_suggestions(query: str) -> list:
    q = (query or "").lower().strip()

    # If query smells like ETF/instrument request, let stock/ETF mapping handle it.
    etf_keywords = ["ishares", "spdr", "etf", "trust", "iau", "gld", "slv", "sgol", "bar"]
    if any(k in q for k in etf_keywords):
        return []

    suggestions = set()
    for synonym, ticker in COMMODITY_TICKER_DICTIONARY.items():
        if re.search(r"\b" + re.escape(synonym) + r"\b", q):
            suggestions.add(ticker)

    return list(suggestions)[:1]
