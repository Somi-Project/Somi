import logging
import re

logger = logging.getLogger(__name__)

# Canonical: BASE/QUOTE -> Yahoo ticker BASEQUOTE=X
# e.g. USD/JPY -> USDJPY=X
FOREX_TICKER_DICTIONARY = {
    # Majors
    "eur/usd": "EURUSD=X",
    "gbp/usd": "GBPUSD=X",
    "aud/usd": "AUDUSD=X",
    "nzd/usd": "NZDUSD=X",
    "usd/jpy": "USDJPY=X",
    "usd/cad": "USDCAD=X",
    "usd/chf": "USDCHF=X",

    # Common crosses
    "eur/jpy": "EURJPY=X",
    "gbp/jpy": "GBPJPY=X",
    "aud/jpy": "AUDJPY=X",
    "nzd/jpy": "NZDJPY=X",
    "chf/jpy": "CHFJPY=X",
    "cad/jpy": "CADJPY=X",

    # Common EM / Asia
    "usd/cny": "USDCNY=X",
    "usd/inr": "USDINR=X",
    "usd/mxn": "USDMXN=X",
    "usd/brl": "USDBRL=X",
    "usd/zar": "USDZAR=X",
    "usd/sgd": "USDSGD=X",
    "usd/hkd": "USDHKD=X",
    "usd/krw": "USDKRW=X",
    "usd/try": "USDTRY=X",
    "usd/rub": "USDRUB=X",
    "usd/pln": "USDPLN=X",
    "usd/thb": "USDTHB=X",
    "usd/myr": "USDMYR=X",
    "usd/idr": "USDIDR=X",
    "usd/php": "USDPHP=X",
    "usd/vnd": "USDVND=X",
}

# Extra synonyms / user phrasing -> canonical pair keys above
FOREX_SYNONYMS = {
    # EURUSD
    "euro": "eur/usd",
    "eurusd": "eur/usd",
    "euro dollar": "eur/usd",
    "euro vs dollar": "eur/usd",
    "eur usd": "eur/usd",

    # USDJPY
    "yen": "usd/jpy",
    "jpy": "usd/jpy",
    "usdjpy": "usd/jpy",
    "usd jpy": "usd/jpy",
    "dollar yen": "usd/jpy",
    "dollar to yen": "usd/jpy",
    "usd to jpy": "usd/jpy",
    "us dollar yen": "usd/jpy",

    # GBPUSD
    "pound": "gbp/usd",
    "sterling": "gbp/usd",
    "gbpusd": "gbp/usd",
    "pound dollar": "gbp/usd",
    "gbp usd": "gbp/usd",

    # USDCAD
    "cad": "usd/cad",
    "loonie": "usd/cad",
    "usdcad": "usd/cad",
    "usd cad": "usd/cad",
    "usd to cad": "usd/cad",
    "dollar to cad": "usd/cad",

    # USDCHF
    "chf": "usd/chf",
    "swiss franc": "usd/chf",
    "usdchf": "usd/chf",
    "usd chf": "usd/chf",

    # AUDUSD / NZDUSD
    "aussie": "aud/usd",
    "audusd": "aud/usd",
    "kiwi": "nzd/usd",
    "nzdusd": "nzd/usd",

    # USDCNY
    "yuan": "usd/cny",
    "renminbi": "usd/cny",
    "usdcny": "usd/cny",

    # USDINR
    "rupee": "usd/inr",
    "usd inr": "usd/inr",
    "usdinr": "usd/inr",
}

def _normalize_forex_query(q: str) -> str:
    q = (q or "").lower().strip()

    # remove common boilerplate
    q = re.sub(r"^(whats|what's)\s+the\s+(conversion\s+rate|exchange\s+rate|rate)\s+of\s+", "", q)
    q = re.sub(r"^(convert|conversion)\s+", "", q)

    # normalize separators: "usd to jpy", "usd/jpy", "usd jpy", "usdjpy"
    q = q.replace(" to ", "/").replace("-", "/")
    q = re.sub(r"\s+", " ", q).strip()

    # convert usdjpy -> usd/jpy
    m = re.fullmatch(r"([a-z]{3})([a-z]{3})", q)
    if m:
        q = f"{m.group(1)}/{m.group(2)}"

    # keep "usd jpy" -> "usd/jpy"
    m = re.fullmatch(r"([a-z]{3})\s+([a-z]{3})", q)
    if m:
        q = f"{m.group(1)}/{m.group(2)}"

    return q

def get_forex_ticker_suggestions(query: str) -> list:
    q = _normalize_forex_query(query)

    # direct canonical match
    if q in FOREX_TICKER_DICTIONARY:
        return [FOREX_TICKER_DICTIONARY[q]]

    # synonym match (exact)
    if q in FOREX_SYNONYMS:
        canon = FOREX_SYNONYMS[q]
        return [FOREX_TICKER_DICTIONARY[canon]]

    # synonym match (contains)
    for syn, canon in FOREX_SYNONYMS.items():
        if syn in q:
            return [FOREX_TICKER_DICTIONARY[canon]]

    # parse any embedded pair like "usd/jpy" in a longer sentence
    m = re.search(r"\b([a-z]{3})\s*/\s*([a-z]{3})\b", q)
    if m:
        pair = f"{m.group(1)}/{m.group(2)}"
        if pair in FOREX_TICKER_DICTIONARY:
            return [FOREX_TICKER_DICTIONARY[pair]]

    return []
