import logging
import asyncio
from datetime import datetime
import httpx
import pytz
import re
from urllib.parse import urljoin

# Configuration
DEFAULT_CACHE_DURATION = 600  # Cache duration in seconds (10 minutes)

_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# NEW: local SearXNG (JSON) fallback
_SEARXNG_BASE_URL = "http://localhost:8080"
_SEARXNG_TIMEOUT_S = 10.0
_SEARXNG_MAX_RESULTS = 6


def _open_meteo_weather_desc(code) -> str:
    code_map = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers",
        81: "Rain showers",
        82: "Violent rain showers",
        85: "Snow showers",
        86: "Snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with hail",
    }
    return code_map.get(code, "Unknown")


# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Words/phrases that frequently contaminate location strings (e.g., "miami currently")
_TEMPORAL_TRASH = (
    "currently", "now", "right now", "today", "tonight",
    "tomorrow", "this morning", "this afternoon", "this evening",
    "this week", "this weekend", "at the moment",
)

# Common lead-ins and weather intent terms to remove when trying to infer a location
_WEATHER_INTENT_TRASH = (
    "what's", "whats", "what is", "tell me", "show me", "check",
    "the", "a", "an",
    "weather", "forecast", "temperature", "rain", "humidity", "wind",
    "sunrise", "sunset", "moon phase", "moon cycle",
    "in", "for", "at", "around", "near",
)


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _clean_location_text(text: str) -> str:
    """
    Aggressively clean a location candidate:
    - remove temporal modifiers ("currently", "now", etc.)
    - remove junk punctuation
    - keep alnum/space/hyphen/comma only
    """
    t = (text or "").strip().lower()
    if not t:
        return ""

    for w in _TEMPORAL_TRASH:
        t = t.replace(w, " ")

    t = re.sub(r"\b(currently|now|today|tonight)\b", " ", t)

    t = re.sub(r"[^a-z0-9\s,\-]", " ", t)
    t = _normalize_space(t).strip(" ,.;:!?")
    return t


def _normalize_cache_key(q: str) -> str:
    """
    Normalize query for caching so trivial variants don't explode cache keys.
    """
    t = (q or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" \t\r\n.,;:!?")
    return t


def _build_searxng_weather_query(original_query: str, location: str) -> str:
    """
    Build a sensible SearXNG query.
    We do NOT want to pass only 'miami' — we want 'weather in miami' (or similar).
    Prefer the original query if it already contains weather intent; otherwise synthesize.
    """
    oq = (original_query or "").strip()
    oql = oq.lower()

    # If user already asked weather-ish, keep their intent (but clean out temporal junk)
    if any(k in oql for k in ("weather", "forecast", "sunrise", "sunset", "moon phase", "moon cycle", "temperature")):
        # Remove temporal trash to avoid weird ranking ("miami currently")
        cleaned = oq
        for w in _TEMPORAL_TRASH:
            cleaned = re.sub(rf"\b{re.escape(w)}\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = _normalize_space(cleaned)
        return cleaned.strip()

    loc = (location or "").strip()
    if not loc:
        return oq if oq else "weather"
    return f"weather in {loc}"


class WeatherHandler:
    def __init__(self, timezone: str = "America/Port_of_Spain"):
        self.timezone = pytz.timezone(timezone)
        self.cache = {}  # Cache format: {cache_key: (results, timestamp)}

        # Hard caps for wttr: at most 1 retry (i.e., 1 attempt total) and 1 endpoint total.
        self.WTTR_MAX_RETRIES = 1
        self.WTTR_BACKOFF_FACTOR = 0.3  # irrelevant with 1 retry, but kept for future

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def extract_location(self, query: str) -> str:
        q = (query or "").strip().lower()
        if not q:
            return ""

        pattern = r"(?:\bin\b|\bfor\b)\s+(.*?)(?=\s*(?:weather|forecast|moon phase|moon cycle|sunrise|sunset|$))"
        match = re.search(pattern, q)
        if match:
            loc = match.group(1).strip()
            loc = _clean_location_text(loc)
            if loc:
                return loc

        if any(k in q for k in ("weather", "forecast", "sunrise", "sunset", "moon phase", "moon cycle")):
            t = q
            for w in _WEATHER_INTENT_TRASH:
                t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
            t = _clean_location_text(t)
            if t:
                return t

        logger.warning(f"No location found in query: '{query}'")
        return ""

    def format_wttr_location(self, location: str) -> str:
        return (location or "").strip().replace(" ", "+")

    async def fetch_open_meteo_geocode(self, location: str) -> dict:
        try:
            params = {"name": location, "count": 1, "language": "en", "format": "json"}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(_OPEN_METEO_GEOCODE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json() or {}
                results = payload.get("results") or []
                return results[0] if results else {}
        except Exception as e:
            logger.error(f"Error fetching Open-Meteo geocode for '{location}': {str(e)}")
            return {}

    async def fetch_open_meteo_forecast(self, latitude: float, longitude: float) -> dict:
        try:
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code,wind_speed_10m,wind_direction_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 3,
            }
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(_OPEN_METEO_FORECAST_URL, params=params)
                resp.raise_for_status()
                return resp.json() or {}
        except Exception as e:
            logger.error(f"Error fetching Open-Meteo forecast for lat={latitude}, lon={longitude}: {str(e)}")
            return {}

    async def _open_meteo_fallback(self, location: str, query_lower: str):
        geocode = await self.fetch_open_meteo_geocode(location)
        if not geocode:
            return None

        lat = geocode.get("latitude")
        lon = geocode.get("longitude")
        if lat is None or lon is None:
            return None

        data = await self.fetch_open_meteo_forecast(lat, lon)
        if not data:
            return None

        resolved_location = ", ".join([v for v in [geocode.get("name"), geocode.get("country")] if v]) or location.title()
        src_url = f"https://open-meteo.com/en/docs?latitude={lat}&longitude={lon}"

        if "sunrise" in query_lower or "sunset" in query_lower:
            daily = data.get("daily", {})
            sunrise = (daily.get("sunrise") or ["N/A"])[0]
            sunset = (daily.get("sunset") or ["N/A"])[0]
            return [{
                "title": f"Solar Times in {resolved_location}",
                "url": src_url,
                "description": (
                    f"The solar times in {resolved_location} are:\n"
                    f"Sunrise: {sunrise}\n"
                    f"Sunset: {sunset}"
                ),
            }]

        if "forecast" in query_lower or "tomorrow" in query_lower:
            daily = data.get("daily", {})
            idx = 1 if len(daily.get("temperature_2m_max") or []) > 1 else 0
            max_f = (daily.get("temperature_2m_max") or ["N/A"])[idx]
            min_f = (daily.get("temperature_2m_min") or ["N/A"])[idx]
            rain = (daily.get("precipitation_probability_max") or ["N/A"])[idx]
            avg_f = "N/A"
            try:
                avg_f = f"{(float(max_f) + float(min_f)) / 2:.1f}"
            except Exception:
                pass
            return [{
                "title": f"Weather Forecast for {resolved_location}",
                "url": src_url,
                "description": (
                    f"The weather forecast for {resolved_location} tomorrow is:\n"
                    f"Average Temperature: {avg_f}°F\n"
                    f"Max Temperature: {max_f}°F\n"
                    f"Min Temperature: {min_f}°F\n"
                    f"Chance of Rain: {rain}%"
                ),
            }]

        current = data.get("current", {})
        temp_f = current.get("temperature_2m")
        wind_mph = current.get("wind_speed_10m", "N/A")
        wind_dir = current.get("wind_direction_10m", "N/A")
        code = current.get("weather_code")
        condition = _open_meteo_weather_desc(code)
        daily = data.get("daily", {})
        chance_rain = (daily.get("precipitation_probability_max") or ["N/A"])[0]

        if temp_f is None:
            return None

        temp_c = (float(temp_f) - 32.0) * 5.0 / 9.0
        wind_kmh = "N/A"
        try:
            wind_kmh = f"{float(wind_mph) * 1.60934:.1f}"
        except Exception:
            pass

        return [{
            "title": f"Weather in {resolved_location}",
            "url": src_url,
            "description": (
                f"The weather in {resolved_location} is:\n"
                f"Condition: {condition}\n"
                f"Temperature: {float(temp_f):.1f}°F ({temp_c:.1f}°C)\n"
                f"Chance of Rain: {chance_rain}%\n"
                f"Wind: {wind_mph} mph ({wind_kmh} km/h) {wind_dir}\n"
                f"Would you like greater details?"
            ),
            "needs_details": True,
        }]

    async def _searxng_fallback(self, original_query: str, location: str) -> list:
        """
        Third-tier fallback: SearXNG (local) returns SOURCES, not structured weather fields.
        We synthesize a good query like 'weather in <location>' (or keep original weather intent).
        """
        q = _build_searxng_weather_query(original_query, location)
        if not q:
            return []

        url = urljoin(_SEARXNG_BASE_URL.rstrip("/") + "/", "search")
        params = {"q": q, "format": "json", "language": "en"}
        headers = {"User-Agent": "SomiWeather/1.0", "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=_SEARXNG_TIMEOUT_S, follow_redirects=True) as client:
                r = await client.get(url, params=params, headers=headers)
                r.raise_for_status()
                data = r.json() or {}
        except Exception as e:
            logger.error(f"SearXNG fallback failed for q='{q}': {e}")
            return []

        items = data.get("results") or data.get("items") or []
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            title = (it.get("title") or "").strip()
            link = (it.get("url") or it.get("link") or "").strip()
            snippet = (it.get("content") or it.get("description") or it.get("snippet") or "").strip()
            if not link.startswith("http"):
                continue
            out.append({
                "title": title or "Weather source",
                "url": link,
                "description": snippet[:500],
                "note": "SearXNG fallback (links only; structured provider unavailable).",
            })
            if len(out) >= _SEARXNG_MAX_RESULTS:
                break

        if not out:
            return []

        # Present as a single consolidated result card (cleaner UX) OR return many results.
        # Here we return one summary card + top links embedded.
        lines = [f"Structured weather providers failed. Here are sources for: {q}"]
        for i, r in enumerate(out[:5], 1):
            lines.append(f"{i}. {r['title']} — {r['url']}")
        return [{
            "title": f"Weather sources via SearXNG",
            "url": _SEARXNG_BASE_URL,
            "description": "\n".join(lines),
            "volatile": True,
        }]

    async def fetch_wttr_data(self, endpoint: str) -> dict:
        url = f"https://wttr.in/{endpoint}"
        try:
            headers = {
                "User-Agent": "SomiWeather/1.0 (+https://wttr.in)",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching wttr.in data for '{endpoint}': {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching wttr.in data for '{endpoint}': {str(e)}")
        return {}

    async def search_weather(
        self,
        query: str,
        retries: int = 1,
        backoff_factor: float = 0.5,
        cache_duration: int = DEFAULT_CACHE_DURATION,
    ) -> list:
        cache_key = _normalize_cache_key(query)

        # Cache
        if cache_key in self.cache:
            results, timestamp = self.cache[cache_key]
            if (datetime.now(self.timezone) - timestamp).total_seconds() < cache_duration:
                logger.info(f"Returning cached results for query '{query}'")
                return results
            logger.info(f"Cache expired for query '{query}'")
            del self.cache[cache_key]

        query_lower = (query or "").lower()

        # Moon Phase Query (wttr moon endpoint only)
        if "moon phase" in query_lower or "moon cycle" in query_lower:
            data = await self.fetch_wttr_data("moon?format=j1")
            if data and "weather" in data:
                astronomy = data["weather"][0]["astronomy"][0]
                description = (
                    f"The moon phase is:\n"
                    f"Moon Phase: {astronomy.get('moon_phase', 'N/A')}\n"
                    f"Moon Day: {astronomy.get('moon_day', 'N/A')}"
                )
                formatted_results = [{
                    "title": "Moon Phase",
                    "url": "https://wttr.in/moon",
                    "description": description
                }]
                self.cache[cache_key] = (formatted_results, datetime.now(self.timezone))
                logger.info(f"Moon phase retrieved for query '{query}'")
                return formatted_results

            return [{
                "title": "Error",
                "url": "https://wttr.in/moon",
                "description": "Could not retrieve moon phase information."
            }]

        # Extract location (needed for wttr + open-meteo; also used to synthesize searxng query)
        location = self.extract_location(query)
        if not location:
            # If location can't be extracted, still try searxng with the raw query as last resort
            searx = await self._searxng_fallback(query, "")
            return searx if searx else [{
                "title": "Error",
                "url": "https://wttr.in/",
                "description": "Could not extract location from query."
            }]

        formatted_location = self.format_wttr_location(location)

        # --- wttr: hard-cap to 1 attempt and 1 endpoint ---
        wttr_retries = min(self.WTTR_MAX_RETRIES, max(1, int(retries)))
        wttr_backoff = float(backoff_factor)

        data = {}
        last_err = None
        endpoint = f"{formatted_location}?format=j1"  # single endpoint only

        for attempt in range(wttr_retries):
            try:
                data = await self.fetch_wttr_data(endpoint)
                if data and "current_condition" in data:
                    break
                last_err = f"missing current_condition endpoint={endpoint}"
            except Exception as e:
                last_err = e
                data = {}

            if attempt < wttr_retries - 1:
                await asyncio.sleep(wttr_backoff * (2 ** attempt))

        # wttr failed -> Open-Meteo fallback
        if not data or "current_condition" not in data:
            logger.error(
                f"No valid wttr data for location '{location}'. last_err={last_err}. "
                f"Trying Open-Meteo fallback."
            )
            fallback_results = await self._open_meteo_fallback(location, query_lower)
            if fallback_results:
                self.cache[cache_key] = (fallback_results, datetime.now(self.timezone))
                logger.info(f"Open-Meteo fallback succeeded for '{location}'")
                return fallback_results

            # Open-Meteo failed -> SearXNG fallback (links)
            logger.error(f"Open-Meteo fallback failed for '{location}'. Trying SearXNG fallback.")
            searx = await self._searxng_fallback(query, location)
            if searx:
                self.cache[cache_key] = (searx, datetime.now(self.timezone))
                return searx

            return [{
                "title": "Error",
                "url": f"https://wttr.in/{formatted_location}",
                "description": f"Could not retrieve weather information for {location}."
            }]

        # Resolve location from wttr response
        nearest_area = data.get("nearest_area", [{}])[0]
        area_name = nearest_area.get("areaName", [{}])[0].get("value", "Unknown")
        country = nearest_area.get("country", [{}])[0].get("value", "Unknown")
        resolved_location = f"{area_name}, {country}"

        # Current conditions
        current = data["current_condition"][0]
        temp_f_raw = current.get("temp_F", "N/A")
        temp_c_raw = current.get("temp_C", "N/A")
        condition = current.get("weatherDesc", [{}])[0].get("value", "N/A")

        # Temperature validation
        try:
            temp_f = float(temp_f_raw)
            if not 32 <= temp_f <= 122:
                logger.warning(f"Implausible temperature {temp_f}°F for '{resolved_location}'")
                return [{
                    "title": "Error",
                    "url": f"https://wttr.in/{formatted_location}",
                    "description": f"Implausible weather data for {resolved_location}."
                }]
        except ValueError:
            logger.warning(f"Invalid temperature format '{temp_f_raw}' for '{resolved_location}'")
            return [{
                "title": "Error",
                "url": f"https://wttr.in/{formatted_location}",
                "description": f"Invalid weather data for {resolved_location}."
            }]

        # Chance of rain (best-effort; wttr fields vary)
        chanceofrain = "N/A"
        try:
            hourly_data = data.get("weather", [{}])[0].get("hourly", [])
            if hourly_data:
                chanceofrain = hourly_data[0].get("chanceofrain", "N/A")
        except Exception as e:
            logger.error(f"Error parsing chanceofrain for '{resolved_location}': {str(e)}")

        # Build response
        if "forecast" in query_lower or "tomorrow" in query_lower:
            weather_days = data.get("weather", [])
            forecast = weather_days[1] if len(weather_days) > 1 else (weather_days[0] if weather_days else {})

            description = (
                f"The weather forecast for {resolved_location} tomorrow is:\n"
                f"Average Temperature: {forecast.get('avgtempF', 'N/A')}°F\n"
                f"Max Temperature: {forecast.get('maxtempF', 'N/A')}°F\n"
                f"Min Temperature: {forecast.get('mintempF', 'N/A')}°F\n"
                f"Chance of Rain: {forecast.get('hourly', [{}])[0].get('chanceofrain', 'N/A')}%"
            )
            formatted_results = [{
                "title": f"Weather Forecast for {resolved_location}",
                "url": f"https://wttr.in/{formatted_location}",
                "description": description
            }]

        elif "sunrise" in query_lower or "sunset" in query_lower:
            astronomy = data.get("weather", [{}])[0].get("astronomy", [{}])[0]
            description = (
                f"The solar times in {resolved_location} are:\n"
                f"Sunrise: {astronomy.get('sunrise', 'N/A')}\n"
                f"Sunset: {astronomy.get('sunset', 'N/A')}\n"
                f"Moonrise: {astronomy.get('moonrise', 'N/A')}\n"
                f"Moonset: {astronomy.get('moonset', 'N/A')}"
            )
            formatted_results = [{
                "title": f"Solar Times in {resolved_location}",
                "url": f"https://wttr.in/{formatted_location}",
                "description": description
            }]

        else:
            description = (
                f"The weather in {resolved_location} is:\n"
                f"Condition: {condition}\n"
                f"Temperature: {temp_f:.1f}°F ({temp_c_raw}°C)\n"
                f"Chance of Rain: {chanceofrain}%\n"
                f"Wind: {current.get('windspeedMiles', 'N/A')} mph ({current.get('windspeedKmph', 'N/A')} km/h) {current.get('winddir16Point', 'N/A')}\n"
                f"Would you like greater details?"
            )
            formatted_results = [{
                "title": f"Weather in {resolved_location}",
                "url": f"https://wttr.in/{formatted_location}",
                "description": description,
                "needs_details": True
            }]

        # Cache and return
        self.cache[cache_key] = (formatted_results, datetime.now(self.timezone))
        logger.info(f"Weather data retrieved for '{resolved_location}' from query '{query}'")
        return formatted_results


# Example usage (optional)
async def main():
    handler = WeatherHandler()

    queries = [
        "whats the weather in miami currently",
        "miami weather now",
        "whats the weather in san fernando trinidad",
        "whats the forecast for toronto ontario",
        "what is the moon phase",
        "whats the sunrise time in london uk",
    ]

    for q in queries:
        results = await handler.search_weather(q)
        print(f"\nQuery: {q}")
        for result in results:
            print(f"Title: {result['title']}")
            print(f"URL: {result['url']}")
            print(f"Description:\n{result['description']}")
            print("-" * 50)


if __name__ == "__main__":
    asyncio.run(main())
