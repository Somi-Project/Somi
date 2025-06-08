import logging
import asyncio
from datetime import datetime, timedelta
import httpx
import pytz
import re
import json
import traceback

# Configuration (adjust as per your project structure)
SYSTEM_TIMEZONE = "America/New_York"  # Replace with your desired timezone
DEFAULT_CACHE_DURATION = 600  # Cache duration in seconds (10 minutes)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeatherHandler:
    def __init__(self, timezone: str = SYSTEM_TIMEZONE):
        """
        Initialize the WeatherHandler with a timezone and an empty cache.
        
        Args:
            timezone (str): The system timezone (e.g., "America/New_York").
        """
        self.timezone = pytz.timezone(timezone)
        self.cache = {}  # Cache format: {query: (results, timestamp)}

    def get_system_time(self) -> str:
        """
        Get the current system time in the specified timezone.
        
        Returns:
            str: Formatted current time (e.g., "2023-10-25 14:30:00 EDT").
        """
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def extract_location(self, query: str) -> str:
        """
        Extract the location from the query using regex.
        
        Args:
            query (str): The user query (e.g., "whats the weather in san fernando trinidad").
            
        Returns:
            str: The extracted and cleaned location (e.g., "san fernando trinidad"), or empty string if not found.
        """
        pattern = r"(?:in|for)\s+(.*?)(?=\s*(?:weather|forecast|moon phase|sunrise|sunset|$))"
        match = re.search(pattern, query.lower())
        if match:
            location = match.group(1).strip()
            # Clean location: keep only alphanumeric characters, spaces, and hyphens
            location = re.sub(r'[^a-zA-Z0-9\s-]', '', location)
            return location
        logger.warning(f"No location found in query: '{query}'")
        return ""

    def format_wttr_location(self, location: str) -> str:
        """
        Format the location for the wttr.in API by replacing spaces with '+'.
        
        Args:
            location (str): The location string (e.g., "san fernando trinidad").
            
        Returns:
            str: Formatted location (e.g., "san+fernando+trinidad").
        """
        return location.strip().replace(" ", "+")

    async def fetch_wttr_data(self, endpoint: str) -> dict:
        """
        Fetch data from wttr.in using the specified endpoint.
        
        Args:
            endpoint (str): The wttr.in endpoint (e.g., "san+fernando+trinidad?format=j1&u" or "moon?format=j1").
            
        Returns:
            dict: Parsed JSON response from wttr.in, or empty dict on failure.
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

    async def search_weather(self, query: str, retries: int = 1, backoff_factor: float = 0.5, cache_duration: int = DEFAULT_CACHE_DURATION) -> list:
        """
        Process a weather-related query and return formatted results.
        
        Args:
            query (str): The user query (e.g., "whats the weather in san fernando trinidad").
            retries (int): Number of retry attempts (not implemented in this version).
            backoff_factor (float): Delay factor for retries (not implemented in this version).
            cache_duration (int): Cache validity duration in seconds.
            
        Returns:
            list: List of result dictionaries with title, url, and description.
        """
        # Normalize query for cache key
        cache_key = query.lower().strip()

        # Check cache
        if cache_key in self.cache:
            results, timestamp = self.cache[cache_key]
            if (datetime.now(self.timezone) - timestamp).total_seconds() < cache_duration:
                logger.info(f"Returning cached results for query '{query}'")
                return results
            else:
                logger.info(f"Cache expired for query '{query}'")
                del self.cache[cache_key]

        query_lower = query.lower()

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
                "url": "https://www.accuweather.com",
                "description": "Could not retrieve moon phase information."
            }]

        # --- Extract Location for Other Queries ---
        location = self.extract_location(query)
        if not location:
            return [{
                "title": "Error",
                "url": "https://www.accuweather.com",
                "description": "Could not extract location from query."
            }]

        formatted_location = self.format_wttr_location(location)
        data = await self.fetch_wttr_data(f"{formatted_location}?format=j1&u")

        if not data or "current_condition" not in data:
            logger.error(f"No valid data returned for location '{location}'")
            return [{
                "title": "Error",
                "url": "https://www.accuweather.com",
                "description": f"Could not retrieve weather information for {location}."
            }]

        # Extract resolved location from response
        nearest_area = data.get("nearest_area", [{}])[0]
        area_name = nearest_area.get("areaName", [{}])[0].get("value", "Unknown")
        country = nearest_area.get("country", [{}])[0].get("value", "Unknown")
        resolved_location = f"{area_name}, {country}"

        # Current conditions
        current = data["current_condition"][0]
        temp_f = current.get("temp_F", "N/A")

        # Temperature validation
        try:
            temp_f = float(temp_f)
            if not 32 <= temp_f <= 122:
                logger.warning(f"Implausible temperature {temp_f}°F for '{resolved_location}'")
                return [{
                    "title": "Error",
                    "url": "https://www.accuweather.com",
                    "description": f"Implausible weather data for {resolved_location}."
                }]
        except ValueError:
            logger.warning(f"Invalid temperature format '{temp_f}' for '{resolved_location}'")
            return [{
                "title": "Error",
                "url": "https://www.accuweather.com",
                "description": f"Invalid weather data for {resolved_location}."
            }]

        # Select chance of rain based on local time
        local_time_str = current.get("localObsDateTime", "")
        chanceofrain = "N/A"
        if local_time_str:
            try:
                local_time = datetime.strptime(local_time_str, "%Y-%m-%d %H:%M %p")
                current_hour = local_time.hour
                hourly_data = data["weather"][0]["hourly"]
                # Convert time strings (e.g., "000", "300") to hours and find closest
                closest_slot = min(
                    hourly_data,
                    key=lambda x: abs(int(x["time"]) // 100 - current_hour)
                )
                chanceofrain = closest_slot.get("chanceofrain", "N/A")
            except Exception as e:
                logger.error(f"Error parsing chanceofrain for '{resolved_location}': {str(e)}")

        # --- Weather Query ---
        if "weather" in query_lower or "whats the weather" in query_lower:
            description = (
                f"The weather in {resolved_location} is:\n"
                f"Temperature: {temp_f}°F\n"
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

        # --- Forecast Query ---
        elif "forecast" in query_lower or "tomorrow" in query_lower:
            forecast = data["weather"][1]  # Day 1 (tomorrow)
            description = (
                f"The weather forecast for {resolved_location} tomorrow is:\n"
                f"Average Temperature: {forecast.get('avgtempF', 'N/A')}°F\n"
                f"Max Temperature: {forecast.get('maxtempF', 'N/A')}°F\n"
                f"Min Temperature: {forecast.get('mintempF', 'N/A')}°F\n"
                f"Chance of Rain: {forecast['hourly'][0].get('chanceofrain', 'N/A')}%"
            )
            formatted_results = [{
                "title": f"Weather Forecast for {resolved_location}",
                "url": f"https://wttr.in/{formatted_location}",
                "description": description
            }]

        # --- Solar Times Query ---
        elif "sunrise" in query_lower or "sunset" in query_lower:
            astronomy = data["weather"][0]["astronomy"][0]
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
            # Default to current weather if query type is unclear
            description = (
                f"The weather in {resolved_location} is:\n"
                f"Temperature: {temp_f}°F\n"
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

# Example usage
async def main():
    handler = WeatherHandler()
    
    # Test queries
    queries = [
        "whats the weather in san fernando trinidad",
        "whats the forecast for toronto ontario",
        "what is the moon phase",
        "whats the sunrise time in london uk"
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