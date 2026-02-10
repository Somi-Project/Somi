# handlers/time_handler.py
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

import pytz
import httpx
from timezonefinder import TimezoneFinder 

logger = logging.getLogger(__name__)


# -----------------------------
# Small TTL cache (in-memory)
# -----------------------------
@dataclass
class _CacheItem:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int = 30 * 86400, max_items: int = 512):
        self.ttl = int(ttl_seconds)
        self.max_items = int(max_items)
        self._store: Dict[str, _CacheItem] = {}

    def get(self, key: str) -> Optional[Any]:
        it = self._store.get(key)
        if not it:
            return None
        if time.time() > it.expires_at:
            self._store.pop(key, None)
            return None
        return it.value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = _CacheItem(value=value, expires_at=time.time() + self.ttl)
        if len(self._store) > self.max_items:
            # evict oldest expiry first
            items = sorted(self._store.items(), key=lambda kv: kv[1].expires_at)
            for k, _ in items[: max(1, len(items) - self.max_items)]:
                self._store.pop(k, None)


class TimeHandler:
    """
    World-time helper.
    - If prompt contains "time in <location>", returns local time at that location.
    - Otherwise returns time in default_timezone.

    Internals:
    - Geocodes using Nominatim (rate-limited; we cache results aggressively).
    - Resolves timezone using timezonefinder (offline).
    """

    def __init__(self, default_timezone: str = "UTC"):
        self.default_timezone = default_timezone

        # Offline timezone resolver
        self._tzf = TimezoneFinder()

        # Cache:
        #   - geocode results and timezone resolution for the same location string
        #   - store only (lat, lon, tz_name, display_name) so it's fast next time
        self._loc_cache = TTLCache(ttl_seconds=30 * 86400, max_items=512)

        # Optional hardcoded aliases for very common city queries (fast path)
        # (Keys should be lowercased)
        self._aliases = {
            "port of spain": "America/Port_of_Spain",
            "pos": "America/Port_of_Spain",
            "trinidad": "America/Port_of_Spain",
            "trinidad and tobago": "America/Port_of_Spain",

            "new york": "America/New_York",
            "nyc": "America/New_York",
            "london": "Europe/London",
            "paris": "Europe/Paris",
            "tokyo": "Asia/Tokyo",
            "kingston": "America/Jamaica",
        }

    # ---------- Public API ----------

    def get_system_date_time(self, prompt: str = "") -> str:
        """
        Returns formatted time.
        - If prompt includes a location query, returns time in that location.
        - Else returns time in self.default_timezone.
        """
        prompt = (prompt or "").strip()
        location = self._extract_location(prompt)

        if not location:
            tz = self._safe_tz(self.default_timezone)
            return self._format_now(tz, label=None)

        # Fast-path alias
        loc_key = self._norm_loc(location)
        alias_tz = self._aliases.get(loc_key)
        if alias_tz:
            tz = self._safe_tz(alias_tz)
            return self._format_now(tz, label=location)

        # Resolve via geocode + timezonefinder
        resolved = self._resolve_location_to_timezone(location)
        if not resolved:
            # Graceful fallback
            tz = self._safe_tz(self.default_timezone)
            return f"Sorry, I couldn't resolve a timezone for '{location}'. {self._format_now(tz, label=None)}"

        tz_name, display_name = resolved
        tz = self._safe_tz(tz_name)
        return self._format_now(tz, label=display_name or location)

    # ---------- Internals ----------

    def _safe_tz(self, tz_name: str) -> pytz.BaseTzInfo:
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.UTC

    def _format_now(self, tz: pytz.BaseTzInfo, label: Optional[str]) -> str:
        now = datetime.now(tz)
        day_suffix = self._day_suffix(now.day)
        where = f"in {label}" if label else f"in {tz.zone}"
        # Example: It's 02:14 PM AST Sunday, 08th February 2026 in Port of Spain, Trinidad and Tobago
        return now.strftime(f"It's %I:%M %p %Z %A, %d{day_suffix} %B %Y {where}")

    def _day_suffix(self, day: int) -> str:
        if 11 <= day % 100 <= 13:
            return "th"
        return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    def _norm_loc(self, s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    def _extract_location(self, prompt: str) -> str:
        """
        Supports:
          - "time in Port of Spain"
          - "what time is it in New York"
          - "current time in tokyo?"
          - "time for london"
        """
        if not prompt:
            return ""

        p = prompt.strip()

        patterns = [
            r"\btime\s+in\s+(.+?)\s*$",
            r"\btime\s+for\s+(.+?)\s*$",
            r"\bwhat\s+time\s+is\s+it\s+in\s+(.+?)\s*$",
            r"\bcurrent\s+time\s+in\s+(.+?)\s*$",
            r"\bthe\s+time\s+in\s+(.+?)\s*$",
        ]

        for pat in patterns:
            m = re.search(pat, p, flags=re.IGNORECASE)
            if m:
                loc = m.group(1).strip()
                # Strip trailing punctuation
                loc = re.sub(r"[?.!,;:]+$", "", loc).strip()
                # Avoid swallowing entire prompt if malformed
                if 1 <= len(loc) <= 80:
                    return loc

        return ""

    def _resolve_location_to_timezone(self, location: str) -> Optional[Tuple[str, str]]:
        """
        Returns (tz_name, display_name) or None.
        Cached for 30 days.
        """
        loc_key = self._norm_loc(location)
        cache_key = f"loc::{loc_key}"
        cached = self._loc_cache.get(cache_key)
        if isinstance(cached, tuple) and len(cached) == 4:
            _, _, tz_name, display_name = cached
            if tz_name:
                return (tz_name, display_name or location)

        geo = self._geocode(location)
        if not geo:
            return None

        lat, lon, display_name = geo
        tz_name = self._tzf.timezone_at(lat=lat, lng=lon) or ""

        # timezonefinder can return None for some edge ocean coords; try a nearby fallback
        if not tz_name:
            tz_name = self._tzf.closest_timezone_at(lat=lat, lng=lon) or ""

        if not tz_name:
            return None

        self._loc_cache.set(cache_key, (lat, lon, tz_name, display_name))
        return (tz_name, display_name or location)

    def _geocode(self, location: str) -> Optional[Tuple[float, float, str]]:
        """
        Nominatim geocode.
        We intentionally keep this lean and cache heavily (rate limits exist).
        """
        loc = (location or "").strip()
        if not loc:
            return None

        cache_key = f"geo::{self._norm_loc(loc)}"
        cached = self._loc_cache.get(cache_key)
        if isinstance(cached, tuple) and len(cached) == 4:
            lat, lon, _, display_name = cached
            return (float(lat), float(lon), str(display_name))

        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": loc, "format": "json", "limit": 1}

        try:
            with httpx.Client(timeout=8.0) as client:
                r = client.get(
                    url,
                    params=params,
                    headers={"User-Agent": "SomiBot/1.1 (world-time; contact: local-user)"},
                )
                if r.status_code >= 400:
                    logger.warning(f"Nominatim geocode HTTP {r.status_code} for '{loc}'")
                    return None
                data = r.json()
        except Exception as e:
            logger.warning(f"Nominatim geocode failed for '{loc}': {e}")
            return None

        if not data:
            return None

        try:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            display = str(data[0].get("display_name", loc))
        except Exception:
            return None

        # Store partial in cache: lat/lon + display, timezone resolved later
        self._loc_cache.set(cache_key, (lat, lon, "", display))
        return (lat, lon, display)

