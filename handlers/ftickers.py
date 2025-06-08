import logging
import re

# Configure basic logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

FOREX_TICKER_DICTIONARY = {
    # EUR/USD (Euro vs. US Dollar)
    "eur/usd": "EURUSD=X",
    "usd/eur": "EURUSD=X",
    "eur usd": "EURUSD=X",
    "euro": "EURUSD=X",
    "euro dollar": "EURUSD=X",
    "euro us dollar": "EURUSD=X",
    "euro/dollar": "EURUSD=X",
    "eurusd": "EURUSD=X",
    "eur/usd pair": "EURUSD=X",
    "euro vs dollar": "EURUSD=X",
    "euro vs us dollar": "EURUSD=X",
    "eur dollar": "EURUSD=X",

    # USD/JPY (US Dollar vs. Japanese Yen)
    "usd/jpy": "JPY=X",
    "jpy/usd": "JPY=X",
    "usd jpy": "JPY=X",
    "yen": "JPY=X",
    "japanese yen": "JPY=X",
    "us dollar yen": "JPY=X",
    "dollar yen": "JPY=X",
    "usd/yen": "JPY=X",
    "jpy usd": "JPY=X",
    "usdjpy": "JPY=X",
    "usd/jpy pair": "JPY=X",
    "dollar vs yen": "JPY=X",
    "us dollar vs japanese yen": "JPY=X",
    # Typo variations for USD/JPY
    "usd jpt": "JPY=X",
    "usdjpt": "JPY=X",
    "usd/jpt": "JPY=X",

    # GBP/USD (British Pound vs. US Dollar)
    "gbp/usd": "GBPUSD=X",
    "usd/gbp": "GBPUSD=X",
    "gbp usd": "GBPUSD=X",
    "pound": "GBPUSD=X",
    "british pound": "GBPUSD=X",
    "sterling": "GBPUSD=X",
    "pound sterling": "GBPUSD=X",
    "gbp/usd pair": "GBPUSD=X",
    "pound dollar": "GBPUSD=X",
    "british pound dollar": "GBPUSD=X",
    "gbpusd": "GBPUSD=X",
    "pound vs dollar": "GBPUSD=X",
    "gbp vs usd": "GBPUSD=X",

    # USD/CAD (US Dollar vs. Canadian Dollar)
    "usd/cad": "CAD=X",
    "cad/usd": "CAD=X",
    "usd cad": "CAD=X",
    "canadian dollar": "CAD=X",
    "loonie": "CAD=X",
    "canada dollar": "CAD=X",
    "us dollar canadian dollar": "CAD=X",
    "usdcad": "CAD=X",
    "usd/cad pair": "CAD=X",
    "dollar vs loonie": "CAD=X",
    "us dollar vs canadian dollar": "CAD=X",

    # USD/CHF (US Dollar vs. Swiss Franc)
    "usd/chf": "CHF=X",
    "chf/usd": "CHF=X",
    "usd chf": "CHF=X",
    "swiss franc": "CHF=X",
    "swissie": "CHF=X",
    "swiss dollar": "CHF=X",
    "us dollar swiss franc": "CHF=X",
    "usdchf": "CHF=X",
    "usd/chf pair": "CHF=X",
    "dollar vs swiss franc": "CHF=X",
    "us dollar vs swiss franc": "CHF=X",

    # AUD/USD (Australian Dollar vs. US Dollar)
    "aud/usd": "AUDUSD=X",
    "usd/aud": "AUDUSD=X",
    "aud usd": "AUDUSD=X",
    "aussie": "AUDUSD=X",
    "australian dollar": "AUDUSD=X",
    "aussie dollar": "AUDUSD=X",
    "aud/usd pair": "AUDUSD=X",
    "australian dollar us dollar": "AUDUSD=X",
    "audusd": "AUDUSD=X",
    "aussie vs dollar": "AUDUSD=X",
    "aud vs usd": "AUDUSD=X",

    # NZD/USD (New Zealand Dollar vs. US Dollar)
    "nzd/usd": "NZDUSD=X",
    "usd/nzd": "NZDUSD=X",
    "nzd usd": "NZDUSD=X",
    "kiwi": "NZDUSD=X",
    "new zealand dollar": "NZDUSD=X",
    "kiwi dollar": "NZDUSD=X",
    "nzd/usd pair": "NZDUSD=X",
    "new zealand dollar us dollar": "NZDUSD=X",
    "nzdusd": "NZDUSD=X",
    "kiwi vs dollar": "NZDUSD=X",
    "nzd vs usd": "NZDUSD=X",

    # USD/CNY (US Dollar vs. Chinese Yuan)
    "usd/cny": "CNY=X",
    "cny/usd": "CNY=X",
    "usd cny": "CNY=X",
    "chinese yuan": "CNY=X",
    "yuan": "CNY=X",
    "renminbi": "CNY=X",
    "us dollar yuan": "CNY=X",
    "usdcny": "CNY=X",
    "usd/cny pair": "CNY=X",
    "dollar vs yuan": "CNY=X",
    "us dollar vs chinese yuan": "CNY=X",

    # USD/INR (US Dollar vs. Indian Rupee)
    "usd/inr": "INR=X",
    "inr/usd": "INR=X",
    "usd inr": "INR=X",
    "indian rupee": "INR=X",
    "rupee": "INR=X",
    "india rupee": "INR=X",
    "usdinr": "INR=X",
    "usd/inr pair": "INR=X",
    "dollar vs rupee": "INR=X",
    "us dollar vs indian rupee": "INR=X",

    # USD/MXN (US Dollar vs. Mexican Peso)
    "usd/mxn": "MXN=X",
    "mxn/usd": "MXN=X",
    "usd mxn": "MXN=X",
    "mexican peso": "MXN=X",
    "peso": "MXN=X",
    "mexico peso": "MXN=X",
    "usdmxn": "MXN=X",
    "usd/mxn pair": "MXN=X",
    "dollar vs peso": "MXN=X",
    "us dollar vs mexican peso": "MXN=X",

    # USD/BRL (US Dollar vs. Brazilian Real)
    "usd/brl": "BRL=X",
    "brl/usd": "BRL=X",
    "usd brl": "BRL=X",
    "brazilian real": "BRL=X",
    "real": "BRL=X",
    "brazil real": "BRL=X",
    "usdbrl": "BRL=X",
    "usd/brl pair": "BRL=X",
    "dollar vs real": "BRL=X",
    "us dollar vs brazilian real": "BRL=X",

    # USD/ZAR (US Dollar vs. South African Rand)
    "usd/zar": "ZAR=X",
    "zar/usd": "ZAR=X",
    "usd zar": "ZAR=X",
    "south african rand": "ZAR=X",
    "rand": "ZAR=X",
    "south africa rand": "ZAR=X",
    "usdzar": "ZAR=X",
    "usd/zar pair": "ZAR=X",
    "dollar vs rand": "ZAR=X",
    "us dollar vs south african rand": "ZAR=X",

    # USD/SGD (US Dollar vs. Singapore Dollar)
    "usd/sgd": "SGD=X",
    "sgd/usd": "SGD=X",
    "usd sgd": "SGD=X",
    "singapore dollar": "SGD=X",
    "sing dollar": "SGD=X",
    "sgd dollar": "SGD=X",
    "usdsgd": "SGD=X",
    "usd/sgd pair": "SGD=X",
    "dollar vs singapore dollar": "SGD=X",
    "us dollar vs singapore dollar": "SGD=X",

    # USD/HKD (US Dollar vs. Hong Kong Dollar)
    "usd/hkd": "HKD=X",
    "hkd/usd": "HKD=X",
    "usd hkd": "HKD=X",
    "hong kong dollar": "HKD=X",
    "hk dollar": "HKD=X",
    "hkd dollar": "HKD=X",
    "usdhkd": "HKD=X",
    "usd/hkd pair": "HKD=X",
    "dollar vs hong kong dollar": "HKD=X",
    "us dollar vs hong kong dollar": "HKD=X",

    # USD/KRW (US Dollar vs. Korean Won)
    "usd/krw": "KRW=X",
    "krw/usd": "KRW=X",
    "usd krw": "KRW=X",
    "korean won": "KRW=X",
    "won": "KRW=X",
    "south korea won": "KRW=X",
    "usdkrw": "KRW=X",
    "usd/krw pair": "KRW=X",
    "dollar vs won": "KRW=X",
    "us dollar vs korean won": "KRW=X",

    # USD/TRY (US Dollar vs. Turkish Lira)
    "usd/try": "TRY=X",
    "try/usd": "TRY=X",
    "usd try": "TRY=X",
    "turkish lira": "TRY=X",
    "lira": "TRY=X",
    "turkey lira": "TRY=X",
    "usdtry": "TRY=X",
    "usd/try pair": "TRY=X",
    "dollar vs lira": "TRY=X",
    "us dollar vs turkish lira": "TRY=X",

    # USD/RUB (US Dollar vs. Russian Ruble)
    "usd/rub": "RUB=X",
    "rub/usd": "RUB=X",
    "usd rub": "RUB=X",
    "russian ruble": "RUB=X",
    "ruble": "RUB=X",
    "russia ruble": "RUB=X",
    "usdrub": "RUB=X",
    "usd/rub pair": "RUB=X",
    "dollar vs ruble": "RUB=X",
    "us dollar vs russian ruble": "RUB=X",

    # USD/PLN (US Dollar vs. Polish Zloty)
    "usd/pln": "PLN=X",
    "pln/usd": "PLN=X",
    "usd pln": "PLN=X",
    "polish zloty": "PLN=X",
    "zloty": "PLN=X",
    "poland zloty": "PLN=X",
    "usdpln": "PLN=X",
    "usd/pln pair": "PLN=X",
    "dollar vs zloty": "PLN=X",
    "us dollar vs polish zloty": "PLN=X",

    # USD/THB (US Dollar vs. Thai Baht)
    "usd/thb": "THB=X",
    "thb/usd": "THB=X",
    "usd thb": "THB=X",
    "thai baht": "THB=X",
    "baht": "THB=X",
    "thailand baht": "THB=X",
    "usdthb": "THB=X",
    "usd/thb pair": "THB=X",
    "dollar vs baht": "THB=X",
    "us dollar vs thai baht": "THB=X",

    # USD/MYR (US Dollar vs. Malaysian Ringgit)
    "usd/myr": "MYR=X",
    "myr/usd": "MYR=X",
    "usd myr": "MYR=X",
    "malaysian ringgit": "MYR=X",
    "ringgit": "MYR=X",
    "malaysia ringgit": "MYR=X",
    "usdmyr": "MYR=X",
    "usd/myr pair": "MYR=X",
    "dollar vs ringgit": "MYR=X",
    "us dollar vs malaysian ringgit": "MYR=X",

    # USD/IDR (US Dollar vs. Indonesian Rupiah)
    "usd/idr": "IDR=X",
    "idr/usd": "IDR=X",
    "usd idr": "IDR=X",
    "indonesian rupiah": "IDR=X",
    "rupiah": "IDR=X",
    "indonesia rupiah": "IDR=X",
    "usdidr": "IDR=X",
    "usd/idr pair": "IDR=X",
    "dollar vs rupiah": "IDR=X",
    "us dollar vs indonesian rupiah": "IDR=X",

    # USD/PHP (US Dollar vs. Philippine Peso)
    "usd/php": "PHP=X",
    "php/usd": "PHP=X",
    "usd php": "PHP=X",
    "philippine peso": "PHP=X",
    "philippines peso": "PHP=X",
    "ph peso": "PHP=X",
    "usdphp": "PHP=X",
    "usd/php pair": "PHP=X",
    "dollar vs philippine peso": "PHP=X",
    "us dollar vs philippine peso": "PHP=X",

    # USD/VND (US Dollar vs. Vietnamese Dong)
    "usd/vnd": "VND=X",
    "vnd/usd": "VND=X",
    "usd vnd": "VND=X",
    "vietnamese dong": "VND=X",
    "dong": "VND=X",
    "vietnam dong": "VND=X",
    "usdvnd": "VND=X",
    "usd/vnd pair": "VND=X",
    "dollar vs dong": "VND=X",
    "us dollar vs vietnamese dong": "VND=X",

    # EUR/JPY (Euro vs. Japanese Yen)
    "eur/jpy": "EURJPY=X",
    "jpy/eur": "EURJPY=X",
    "eur jpy": "EURJPY=X",
    "euro yen": "EURJPY=X",
    "euro japanese yen": "EURJPY=X",
    "eurjpy": "EURJPY=X",
    "eur/jpy pair": "EURJPY=X",
    "euro vs yen": "EURJPY=X",
    "euro vs japanese yen": "EURJPY=X",

    # GBP/JPY (British Pound vs. Japanese Yen)
    "gbp/jpy": "GBPJPY=X",
    "jpy/gbp": "GBPJPY=X",
    "gbp jpy": "GBPJPY=X",
    "pound yen": "GBPJPY=X",
    "british pound yen": "GBPJPY=X",
    "gbpjpy": "GBPJPY=X",
    "gbp/jpy pair": "GBPJPY=X",
    "pound vs yen": "GBPJPY=X",
    "british pound vs japanese yen": "GBPJPY=X",

    # AUD/JPY (Australian Dollar vs. Japanese Yen)
    "aud/jpy": "AUDJPY=X",
    "jpy/aud": "AUDJPY=X",
    "aud jpy": "AUDJPY=X",
    "aussie yen": "AUDJPY=X",
    "australian dollar yen": "AUDJPY=X",
    "audjpy": "AUDJPY=X",
    "aud/jpy pair": "AUDJPY=X",
    "aussie vs yen": "AUDJPY=X",
    "australian dollar vs japanese yen": "AUDJPY=X",

    # NZD/JPY (New Zealand Dollar vs. Japanese Yen)
    "nzd/jpy": "NZDJPY=X",
    "jpy/nzd": "NZDJPY=X",
    "nzd jpy": "NZDJPY=X",
    "kiwi yen": "NZDJPY=X",
    "new zealand dollar yen": "NZDJPY=X",
    "nzdjpy": "NZDJPY=X",
    "nzd/jpy pair": "NZDJPY=X",
    "kiwi vs yen": "NZDJPY=X",
    "new zealand dollar vs japanese yen": "NZDJPY=X",

    # CHF/JPY (Swiss Franc vs. Japanese Yen)
    "chf/jpy": "CHFJPY=X",
    "jpy/chf": "CHFJPY=X",
    "chf jpy": "CHFJPY=X",
    "swiss yen": "CHFJPY=X",
    "swiss franc yen": "CHFJPY=X",
    "chfjpy": "CHFJPY=X",
    "chf/jpy pair": "CHFJPY=X",
    "swiss franc vs yen": "CHFJPY=X",
    "swiss franc vs japanese yen": "CHFJPY=X",

    # CAD/JPY (Canadian Dollar vs. Japanese Yen)
    "cad/jpy": "CADJPY=X",
    "jpy/cad": "CADJPY=X",
    "cad jpy": "CADJPY=X",
    "canadian yen": "CADJPY=X",
    "canadian dollar yen": "CADJPY=X",
    "cadjpy": "CADJPY=X",
    "cad/jpy pair": "CADJPY=X",
    "loonie vs yen": "CADJPY=X",
    "canadian dollar vs japanese yen": "CADJPY=X",
}

def get_forex_ticker_suggestions(query: str) -> list:
    """
    Return a list of Yahoo Finance tickers that match the query for forex pairs.
    Args:
        query (str): Currency pair or name (e.g., "eur/usd", "yen").
    Returns:
        list: List of matching tickers (e.g., ["EURUSD=X"]). Returns empty list if no match.
    """
    query_lower = query.lower().strip()
    logger.debug(f"Processing forex query: '{query_lower}'")

    # Clean query to remove common prefixes
    cleaned_query = re.sub(r'^(whats\s+the\s+price\s+of|price\s+of|rate\s+of|exchange\s+rate\s+of)\s+', '', query_lower).strip()
    logger.debug(f"Cleaned query: '{cleaned_query}'")

    suggestions = set()

    # Try exact match first
    if cleaned_query in FOREX_TICKER_DICTIONARY:
        ticker = FOREX_TICKER_DICTIONARY[cleaned_query]
        logger.debug(f"Exact match found: '{cleaned_query}' -> '{ticker}'")
        suggestions.add(ticker)

    # Try partial matching with dictionary keys
    for synonym, ticker in FOREX_TICKER_DICTIONARY.items():
        if re.search(r'\b' + re.escape(synonym.lower()) + r'\b', cleaned_query):
            logger.debug(f"Matched synonym '{synonym}' in '{cleaned_query}' -> '{ticker}'")
            suggestions.add(ticker)

    # Fallback: Try to extract currency pair or name
    if not suggestions:
        # Extract potential currency pair (e.g., "usd/jpy", "eur usd")
        pair_match = re.search(r'(\b[a-z]{3}\b\s*(?:/|\s+)\s*\b[a-z]{3}\b)', cleaned_query)
        if pair_match:
            pair = pair_match.group(1).replace(' ', '/')
            if pair in FOREX_TICKER_DICTIONARY:
                ticker = FOREX_TICKER_DICTIONARY[pair]
                logger.debug(f"Fallback: Matched currency pair '{pair}' -> '{ticker}'")
                suggestions.add(ticker)

        # Extract single currency name (e.g., "euro", "yen")
        for synonym, ticker in FOREX_TICKER_DICTIONARY.items():
            if synonym in cleaned_query.split():
                logger.debug(f"Fallback: Matched currency name '{synonym}' in '{cleaned_query}' -> '{ticker}'")
                suggestions.add(ticker)

    result = list(suggestions)[:1]
    if not result:
        logger.warning(f"No ticker matches found for query '{query}' (cleaned: '{cleaned_query}')")
    else:
        logger.info(f"Forex ticker suggestions for '{query}': {result}")
    return result