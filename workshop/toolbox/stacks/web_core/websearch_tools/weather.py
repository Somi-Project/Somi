# handlers/websearch_tools/weather.py
import logging
import asyncio
from datetime import datetime
import httpx
import pytz
import re
from urllib.parse import urljoin

# ----------------------------
# Config imports (no hardcoding)
# ----------------------------
try:
    from config.settings import SEARXNG_BASE_URL as _SEARXNG_BASE_URL
except Exception:
    _SEARXNG_BASE_URL = "http://localhost:8080"

try:
    from config.settings import SYSTEM_TIMEZONE as _SYSTEM_TIMEZONE
except Exception:
    _SYSTEM_TIMEZONE = "America/Port_of_Spain"

# Optional tuning knobs (not in your settings yet). Safe defaults if missing.
try:
    from config.settings import SEARXNG_TIMEOUT_S as _SEARXNG_TIMEOUT_S  # type: ignore
except Exception:
    _SEARXNG_TIMEOUT_S = 10.0

try:
    from config.settings import SEARXNG_MAX_RESULTS as _SEARXNG_MAX_RESULTS  # type: ignore
except Exception:
    _SEARXNG_MAX_RESULTS = 6

# ----------------------------
# Providers / constants
# ----------------------------
DEFAULT_CACHE_DURATION = 600  # seconds (10 minutes)

_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------
# Text hygiene
# ----------------------------
_TEMPORAL_TRASH = (
    "currently", "now", "right now", "today", "tonight",
    "tomorrow", "this morning", "this afternoon", "this evening",
    "this week", "this weekend", "at the moment",
)

_WEATHER_INTENT_TRASH = (
    "what's", "whats", "what is", "tell me", "show me", "check",
    "the", "a", "an",
    "weather", "forecast", "temperature", "rain", "humidity", "wind",
    "sunrise", "sunset", "moon phase", "moon cycle",
    "in", "for", "at", "around", "near",
)


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


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _clean_location_text(text: str) -> str:
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
    t = (q or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" \t\r\n.,;:!?")
    return t


def _build_searxng_weather_query(original_query: str, location: str) -> str:
    """
    Build a SearXNG query that preserves weather intent.
    Important: don't send just "Miami". Prefer "weather in miami" or a cleaned user query.
    """
    oq = (original_query or "").strip()
    oql = oq.lower()

    if any(k in oql for k in ("weather", "forecast", "sunrise", "sunset", "moon phase", "moon cycle", "temperature")):
        cleaned = oq
        for w in _TEMPORAL_TRASH:
            cleaned = re.sub(rf"\b{re.escape(w)}\b", " ", cleaned, flags=re.IGNORECASE)
        return _normalize_space(cleaned).strip()

    loc = (location or "").strip()
    if not loc:
        return oq if oq else "weather"
    return f"weather in {loc}"


class WeatherHandler:
    def __init__(self, timezone: str | None = None):
        # Timezone defaults to settings, but caller can override.
        tz_name = timezone or _SYSTEM_TIMEZONE or "America/Port_of_Spain"
        self.timezone = pytz.timezone(tz_name)

        # Cache format: {cache_key: (results, timestamp)}
        self.cache: dict[str, tuple[list, datetime]] = {}

        # wttr hard caps: 1 attempt, 1 endpoint.
        self.WTTR_MAX_RETRIES = 1
        self.WTTR_BACKOFF_FACTOR = 0.3

        # SearXNG config normalized once (avoid module-level hardcoding)
        self.searxng_base_url = (_SEARXNG_BASE_URL or "").rstrip("/")
        self.searxng_timeout_s = float(_SEARXNG_TIMEOUT_S)
        self.searxng_max_results = int(_SEARXNG_MAX_RESULTS)

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def extract_location(self, query: str) -> str:
        q = (query or "").strip().lower()
        if not q:
            return ""

        pattern = r"(?:\bin\b|\bfor\b)\s+(.*?)(?=\s*(?:weather|forecast|moon phase|moon cycle|sunrise|sunset|$))"
        match = re.search(pattern, q)
        if match:
            loc = _clean_location_text(match.group(1).strip())
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
            logger.error(f"Error fetching Open-Meteo geocode for '{location}': {e}")
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
            logger.error(f"Error fetching Open-Meteo forecast for lat={latitude}, lon={longitude}: {e}")
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
                "description": f"The solar times in {resolved_location} are:\nSunrise: {sunrise}\nSunset: {sunset}",
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
                    f"Average Temperature: {avg_f}Â°F\n"
                    f"Max Temperature: {max_f}Â°F\n"
                    f"Min Temperature: {min_f}Â°F\n"
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
                f"Temperature: {float(temp_f):.1f}Â°F ({temp_c:.1f}Â°C)\n"
                f"Chance of Rain: {chance_rain}%\n"
                f"Wind: {wind_mph} mph ({wind_kmh} km/h) {wind_dir}\n"
                f"Would you like greater details?"
            ),
            "needs_details": True,
        }]

    async def _searxng_fallback(self, original_query: str, location: str) -> list:
        """
        Third-tier fallback: SearXNG returns SOURCES, not structured weather fields.
        We synthesize a query like "weather in <location>" (or keep the user's weather intent).
        """
        if not self.searxng_base_url:
            return []

        q = _build_searxng_weather_query(original_query, location)
        if not q:
            return []

        url = urljoin(self.searxng_base_url + "/", "search")
        params = {"q": q, "format": "json", "language": "en"}
        headers = {"User-Agent": "SomiWeather/1.0", "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self.searxng_timeout_s, follow_redirects=True) as client:
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
            out.append({"title": title or "Weather source", "url": link, "description": snippet[:500]})
            if len(out) >= self.searxng_max_results:
                break

        if not out:
            return []

        lines = [f"Structured weather providers failed. Here are sources for: {q}"]
        for i, r0 in enumerate(out[:5], 1):
            lines.append(f"{i}. {r0['title']} â€” {r0['url']}")

        return [{
            "title": "Weather sources via SearXNG",
            "url": self.searxng_base_url,
            "description": "\n".join(lines),
            "volatile": True,
        }]

    async def fetch_wttr_data(self, endpoint: str) -> dict:
        url = f"https://wttr.in/{endpoint}"
        try:
            headers = {"User-Agent": "SomiWeather/1.0 (+https://wttr.in)", "Accept": "application/json"}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching wttr.in data for '{endpoint}': {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching wttr.in data for '{endpoint}': {e}")
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

        # Moon Phase (wttr)
        if "moon phase" in query_lower or "moon cycle" in query_lower:
            data = await self.fetch_wttr_data("moon?format=j1")
            if data and "weather" in data:
                astronomy = data["weather"][0]["astronomy"][0]
                description = (
                    "The moon phase is:\n"
                    f"Moon Phase: {astronomy.get('moon_phase', 'N/A')}\n"
                    f"Moon Day: {astronomy.get('moon_day', 'N/A')}"
                )
                formatted_results = [{"title": "Moon Phase", "url": "https://wttr.in/moon", "description": description}]
                self.cache[cache_key] = (formatted_results, datetime.now(self.timezone))
                return formatted_results

            return [{"title": "Error", "url": "https://wttr.in/moon", "description": "Could not retrieve moon phase information."}]

        # Extract location
        location = self.extract_location(query)
        if not location:
            # if we can't extract location, try searxng with raw query as last resort
            searx = await self._searxng_fallback(query, "")
            if searx:
                self.cache[cache_key] = (searx, datetime.now(self.timezone))
                return searx
            return [{"title": "Error", "url": "https://wttr.in/", "description": "Could not extract location from query."}]

        # Provider order: Open-Meteo -> wttr.in -> SearXNG
        open_meteo_results = await self._open_meteo_fallback(location, query_lower)
        if open_meteo_results:
            self.cache[cache_key] = (open_meteo_results, datetime.now(self.timezone))
            return open_meteo_results

        formatted_location = self.format_wttr_location(location)

        # wttr: hard-cap to 1 attempt, 1 endpoint
        wttr_retries = min(self.WTTR_MAX_RETRIES, max(1, int(retries)))
        wttr_backoff = float(backoff_factor)

        data = {}
        last_err = None
        endpoint = f"{formatted_location}?format=j1"

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

        # wttr failed -> SearXNG
        if not data or "current_condition" not in data:
            logger.error(f"No valid wttr data for '{location}'. last_err={last_err}. Trying SearXNG fallback.")
            searx = await self._searxng_fallback(query, location)
            if searx:
                self.cache[cache_key] = (searx, datetime.now(self.timezone))
                return searx

            return [{"title": "Error", "url": f"https://wttr.in/{formatted_location}", "description": f"Could not retrieve weather information for {location}."}]

        # Resolve location from wttr
        nearest_area = data.get("nearest_area", [{}])[0]
        area_name = nearest_area.get("areaName", [{}])[0].get("value", "Unknown")
        country = nearest_area.get("country", [{}])[0].get("value", "Unknown")
        resolved_location = f"{area_name}, {country}"

        current = data["current_condition"][0]
        temp_f_raw = current.get("temp_F", "N/A")
        temp_c_raw = current.get("temp_C", "N/A")
        condition = current.get("weatherDesc", [{}])[0].get("value", "N/A")

        # sanity check temp
        try:
            temp_f = float(temp_f_raw)
            if not 32 <= temp_f <= 122:
                return [{"title": "Error", "url": f"https://wttr.in/{formatted_location}", "description": f"Implausible weather data for {resolved_location}."}]
        except ValueError:
            return [{"title": "Error", "url": f"https://wttr.in/{formatted_location}", "description": f"Invalid weather data for {resolved_location}."}]

        # chance of rain best-effort
        chanceofrain = "N/A"
        try:
            hourly_data = data.get("weather", [{}])[0].get("hourly", [])
            if hourly_data:
                chanceofrain = hourly_data[0].get("chanceofrain", "N/A")
        except Exception:
            pass

        # Build response
        if "forecast" in query_lower or "tomorrow" in query_lower:
            weather_days = data.get("weather", [])
            forecast = weather_days[1] if len(weather_days) > 1 else (weather_days[0] if weather_days else {})
            description = (
                f"The weather forecast for {resolved_location} tomorrow is:\n"
                f"Average Temperature: {forecast.get('avgtempF', 'N/A')}Â°F\n"
                f"Max Temperature: {forecast.get('maxtempF', 'N/A')}Â°F\n"
                f"Min Temperature: {forecast.get('mintempF', 'N/A')}Â°F\n"
                f"Chance of Rain: {forecast.get('hourly', [{}])[0].get('chanceofrain', 'N/A')}%"
            )
            formatted_results = [{"title": f"Weather Forecast for {resolved_location}", "url": f"https://wttr.in/{formatted_location}", "description": description}]
        elif "sunrise" in query_lower or "sunset" in query_lower:
            astronomy = data.get("weather", [{}])[0].get("astronomy", [{}])[0]
            description = (
                f"The solar times in {resolved_location} are:\n"
                f"Sunrise: {astronomy.get('sunrise', 'N/A')}\n"
                f"Sunset: {astronomy.get('sunset', 'N/A')}\n"
                f"Moonrise: {astronomy.get('moonrise', 'N/A')}\n"
                f"Moonset: {astronomy.get('moonset', 'N/A')}"
            )
            formatted_results = [{"title": f"Solar Times in {resolved_location}", "url": f"https://wttr.in/{formatted_location}", "description": description}]
        else:
            description = (
                f"The weather in {resolved_location} is:\n"
                f"Condition: {condition}\n"
                f"Temperature: {temp_f:.1f}Â°F ({temp_c_raw}Â°C)\n"
                f"Chance of Rain: {chanceofrain}%\n"
                f"Wind: {current.get('windspeedMiles', 'N/A')} mph ({current.get('windspeedKmph', 'N/A')} km/h) {current.get('winddir16Point', 'N/A')}\n"
                f"Would you like greater details?"
            )
            formatted_results = [{
                "title": f"Weather in {resolved_location}",
                "url": f"https://wttr.in/{formatted_location}",
                "description": description,
                "needs_details": True,
            }]

        self.cache[cache_key] = (formatted_results, datetime.now(self.timezone))
        return formatted_results


# Example usage
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


