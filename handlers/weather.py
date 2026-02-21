import logging
import asyncio
from datetime import datetime
import httpx
import pytz
import re

# Configuration
DEFAULT_CACHE_DURATION = 600  # Cache duration in seconds (10 minutes)

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

    # Remove temporal junk phrases
    for w in _TEMPORAL_TRASH:
        t = t.replace(w, " ")

    # Drop lingering words like "currently" attached by punctuation
    t = re.sub(r"\b(currently|now|today|tonight)\b", " ", t)

    # Keep location-friendly chars
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


class WeatherHandler:
    def __init__(self, timezone: str = "America/Port_of_Spain"):
        """
        Initialize the WeatherHandler with a timezone and an empty cache.

        Args:
            timezone (str): The system timezone (e.g., "America/New_York").
        """
        self.timezone = pytz.timezone(timezone)
        self.cache = {}  # Cache format: {cache_key: (results, timestamp)}

    def get_system_time(self) -> str:
        """
        Get the current system time in the specified timezone.

        Returns:
            str: Formatted current time (e.g., "2023-10-25 14:30:00 EDT").
        """
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def extract_location(self, query: str) -> str:
        """
        Extract the location from the query using regex + cleaning.

        Supports:
        - "weather in miami currently" -> "miami"
        - "forecast for toronto ontario" -> "toronto ontario"
        - "sunrise in london uk" -> "london uk"

        Returns:
            cleaned location string or ""
        """
        q = (query or "").strip().lower()
        if not q:
            return ""

        # Primary regex: capture after "in|for"
        pattern = r"(?:\bin\b|\bfor\b)\s+(.*?)(?=\s*(?:weather|forecast|moon phase|moon cycle|sunrise|sunset|$))"
        match = re.search(pattern, q)
        if match:
            loc = match.group(1).strip()
            loc = _clean_location_text(loc)
            if loc:
                return loc

        # Fallback 1: if query starts with a location-like phrase and includes "weather/forecast"
        # e.g. "miami weather now" -> try removing intent words and keep what's left
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
        """
        Format the location for the wttr.in API by replacing spaces with '+'.
        """
        return (location or "").strip().replace(" ", "+")

    async def fetch_wttr_data(self, endpoint: str) -> dict:
        """
        Fetch data from wttr.in using the specified endpoint.
        """
        url = f"https://wttr.in/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
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
        """
        Process a weather-related query and return formatted results.
        """
        # Normalize query for cache key
        cache_key = _normalize_cache_key(query)

        # Check cache
        if cache_key in self.cache:
            results, timestamp = self.cache[cache_key]
            if (datetime.now(self.timezone) - timestamp).total_seconds() < cache_duration:
                logger.info(f"Returning cached results for query '{query}'")
                return results
            else:
                logger.info(f"Cache expired for query '{query}'")
                del self.cache[cache_key]

        query_lower = (query or "").lower()

        # Moon Phase Query
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

        # --- Extract Location for Other Queries ---
        location = self.extract_location(query)
        if not location:
            return [{
                "title": "Error",
                "url": "https://wttr.in/",
                "description": "Could not extract location from query."
            }]

        formatted_location = self.format_wttr_location(location)

        # Small retry loop (you had retries args but not implemented)
        last_err = None
        data = {}
        for attempt in range(max(1, int(retries))):
            try:
                data = await self.fetch_wttr_data(f"{formatted_location}?format=j1&u")
                if data and "current_condition" in data:
                    break
            except Exception as e:
                last_err = e
            if attempt < retries - 1:
                await asyncio.sleep(backoff_factor * (2 ** attempt))

        if not data or "current_condition" not in data:
            logger.error(f"No valid data returned for location '{location}'. last_err={last_err}")
            return [{
                "title": "Error",
                "url": f"https://wttr.in/{formatted_location}",
                "description": f"Could not retrieve weather information for {location}."
            }]

        # Extract resolved location from response
        nearest_area = data.get("nearest_area", [{}])[0]
        area_name = nearest_area.get("areaName", [{}])[0].get("value", "Unknown")
        country = nearest_area.get("country", [{}])[0].get("value", "Unknown")
        resolved_location = f"{area_name}, {country}"

        # Current conditions
        current = data["current_condition"][0]
        temp_f_raw = current.get("temp_F", "N/A")

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
            # wttr sometimes provides hourly chanceofrain in weather[0]["hourly"]
            hourly_data = data.get("weather", [{}])[0].get("hourly", [])
            if hourly_data:
                # pick first slot as a cheap proxy; better than failing hard
                chanceofrain = hourly_data[0].get("chanceofrain", "N/A")
        except Exception as e:
            logger.error(f"Error parsing chanceofrain for '{resolved_location}': {str(e)}")

        # --- Weather Query ---
        if "forecast" in query_lower or "tomorrow" in query_lower:
            # Tomorrow forecast: weather[1] if present
            weather_days = data.get("weather", [])
            if len(weather_days) > 1:
                forecast = weather_days[1]
            else:
                forecast = weather_days[0] if weather_days else {}

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
            # Default: current weather
            description = (
                f"The weather in {resolved_location} is:\n"
                f"Temperature: {temp_f:.1f}°F\n"
                f"Chance of Rain: {chanceofrain}%\n"
                f"Wind: {current.get('windspeedMiles', 'N/A')} mph {current.get('winddir16Point', 'N/A')}\n"
                f"Would you like greater details?"
            )
            formatted_results = [{
                "title": f"Weather in {resolved_location}",
                "url": f"https://wttr.in/{formatted_location}",
                "description": description,
                "needs_details": True
            }]

        # Cache and return results
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
