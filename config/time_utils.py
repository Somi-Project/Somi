# config/time_utils.py
import spacy
import pytz
from datetime import datetime
import logging
from typing import Optional

# Set up logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration from settings
from .settings import SYSTEM_TIMEZONE

class TimeQueryHandler:
    """Handles detection and processing of date/time queries."""
    
    def __init__(self, ollama_client=None, model: str = "default_model"):
        self.ollama_client = ollama_client  # Optional LLM client for fallback
        self.model = model
        # Load spaCy model
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except Exception as e:
            logger.error(f"Failed to load spaCy model: {str(e)}")
            self.nlp = None

    def is_date_time_query(self, prompt: str) -> bool:
        """
        Determine if the prompt is a date/time query using spaCy and optional LLM fallback.
        Returns True for queries like 'time in London' or 'today's date', False otherwise.
        """
        prompt_lower = prompt.lower().strip()
        
        # Step 1: spaCy check
        if self.nlp:
            try:
                doc = self.nlp(prompt)
                # Check for time-related keywords
                has_time_keyword = any(token.text.lower() in {"time", "date", "day", "now", "today", "current"} for token in doc)
                # Check for location entities (GPE = Geopolitical Entity)
                has_location = any(ent.label_ == "GPE" for ent in doc.ents)
                # Consider it a time query if it has time keywords and either a location or explicit time modifiers
                has_time_intent = has_time_keyword and (has_location or any(token.text.lower() in {"current", "now", "today"} for token in doc))
                
                if has_time_intent:
                    logger.info(f"spaCy detected time/date query: '{prompt}'")
                    return True
            except Exception as e:
                logger.error(f"Error in spaCy processing for '{prompt}': {str(e)}")
        
        # Step 2: Fallback to LLM if available
        if self.ollama_client:
            try:
                classification_prompt = f"""
                Determine if the prompt is explicitly asking for the current date, time, or day (including location-specific queries like 'time in London'). 
                Return 'True' if it is a date/time query, 'False' otherwise. Focus on intent, not just keywords.
                Prompt: "{prompt}"
                Examples:
                - "what's the time" -> True
                - "time in London" -> True
                - "time to cook dinner" -> False
                - "date of the moon landing" -> False
                Return only 'True' or 'False'.
                """
                response = self.ollama_client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a query classifier."},
                        {"role": "user", "content": classification_prompt}
                    ],
                    options={"temperature": 0.3, "max_tokens": 10}
                )
                result = response.get("message", {}).get("content", "").strip().lower()
                logger.info(f"LLM classified '{prompt}' as time/date query: {result}")
                return result == "true"
            except Exception as e:
                logger.error(f"Error in LLM classification for '{prompt}': {str(e)}")
        
        # Default to False if no clear time/date intent
        return False

    def get_system_date_time(self, prompt: str = "") -> str:
        """Get the current date and time, handling location-specific queries if provided."""
        prompt_lower = prompt.lower().strip()
        # Check for location-specific time query (e.g., "time in London")
        if self.nlp:
            try:
                doc = self.nlp(prompt)
                # Look for location entities
                for ent in doc.ents:
                    if ent.label_ == "GPE":
                        location = ent.text.capitalize()
                        try:
                            tz = pytz.timezone(location)
                            now = datetime.now(tz)
                            day_suffix = {1: "st", 2: "nd", 3: "rd"}.get(now.day % 10 if now.day % 10 in [1, 2, 3] and not 11 <= now.day % 100 <= 13 else 0, "th")
                            return now.strftime(f"It's %I:%M %p %Z %A, %d{day_suffix} %B %Y")
                        except pytz.exceptions.UnknownTimeZoneError:
                            return f"Sorry, I don't know the timezone for {location}. Try another city!"
            except Exception as e:
                logger.error(f"Error in spaCy location extraction for '{prompt}': {str(e)}")
        
        # Default to system timezone
        tz = pytz.timezone(SYSTEM_TIMEZONE)
        now = datetime.now(tz)
        day_suffix = {1: "st", 2: "nd", 3: "rd"}.get(now.day % 10 if now.day % 10 in [1, 2, 3] and not 11 <= now.day % 100 <= 13 else 0, "th")
        formatted_date = now.strftime(f"It's %I:%M %p %Z %A, %d{day_suffix} %B %Y")
        return formatted_date