import pytz
import re
from datetime import datetime
import logging

# Set up logger
logger = logging.getLogger(__name__)

class TimeHandler:
    def __init__(self, default_timezone="UTC"):
        self.default_timezone = default_timezone

    def get_system_date_time(self, prompt: str = "") -> str:
        """Get the current date and time, handling location-specific queries if provided."""
        prompt_lower = prompt.lower().strip()
        location_match = re.search(r"time in (\w+)", prompt_lower)
        
        # Map common city names to their timezone
        timezone_mapping = {
            "london": "Europe/London",
            "paris": "Europe/Paris",
            "newyork": "America/New_York",
            "tokyo": "Asia/Tokyo",
            # Add more mappings as needed
        }
        
        if location_match:
            location = location_match.group(1).lower()
            # Check if the location is in the timezone mapping
            if location in timezone_mapping:
                tz = pytz.timezone(timezone_mapping[location])
            else:
                try:
                    tz = pytz.timezone(location.capitalize())
                except pytz.exceptions.UnknownTimeZoneError:
                    return f"Sorry, I don't know the timezone for {location.capitalize()}. Try another city!"
        else:
            tz = pytz.timezone(self.default_timezone)

        now = datetime.now(tz)
        logger.info(f"System time in timezone '{tz}': {now}")
        day_suffix = {1: "st", 2: "nd", 3: "rd"}.get(now.day % 10 if now.day % 10 in [1, 2, 3] and not 11 <= now.day % 100 <= 13 else 0, "th")
        formatted_date = now.strftime(f"It's %I:%M %p %Z %A, %d{day_suffix} %B %Y")
        return formatted_date