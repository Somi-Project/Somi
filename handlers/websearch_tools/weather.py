# handlers/websearch_tools/weather.py
"""
WeatherHandler with:
- intent routing (quick / action / time / full / moon)
- default location fallback via DEFAULT_LOCATION
- Open-Meteo (geocoding + forecast) as primary source
- wttr.in moon fallback
- concise responses; detailed only when asked
- 24h caching for moon & solar times
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytz

from config.settings import SYSTEM_TIMEZONE

logger = logging.getLogger(__name__)

# Optional defaults
try:
    from config.settings import DEFAULT_LOCATION as _DEFAULT_LOCATION
except Exception:
    _DEFAULT_LOCATION = ""

DEFAULT_CACHE_DURATION = 600  # 10 minutes


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class GeoResult:
    name: str
    country: str
    admin1: str
    latitude: float
    longitude: float
    timezone: str


@dataclass
class WeatherSnapshot:
    location_label: str
    timezone: str
    now_iso: str

    temp_c: Optional[float] = None
    feels_c: Optional[float] = None
    humidity: Optional[float] = None
    wind_kmh: Optional[float] = None
    wind_dir_deg: Optional[float] = None
    precip_mm: Optional[float] = None
    weather_code: Optional[int] = None

    today_max_c: Optional[float] = None
    today_min_c: Optional[float] = None
    today_rain_prob: Optional[float] = None
    today_uv_max: Optional[float] = None
    sunrise_iso: Optional[str] = None
    sunset_iso: Optional[str] = None

    tom_max_c: Optional[float] = None
    tom_min_c: Optional[float] = None
    tom_rain_prob: Optional[float] = None
    tom_uv_max: Optional[float] = None
    tom_sunrise_iso: Optional[str] = None
    tom_sunset_iso: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _safe_trim(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "…"

def _normalize_space(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _round1(x: Optional[float]) -> Optional[float]:
    if x is None: return None
    try: return round(float(x), 1)
    except: return None

def _round0(x: Optional[float]) -> Optional[float]:
    if x is None: return None
    try: return round(float(x), 0)
    except: return None

def _uv_label(uv: float) -> str:
    if uv < 3: return "low"
    if uv < 6: return "moderate"
    if uv < 8: return "high"
    if uv < 11: return "very high"
    return "extreme"

def _wind_dir_16(deg: Optional[float]) -> str:
    if deg is None: return "?"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    try:
        i = int((deg + 11.25) // 22.5) % 16
        return dirs[i]
    except:
        return "?"

_WEATHER_CODE_TEXT = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle (light)", 57: "Freezing drizzle (dense)",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Freezing rain (light)", 67: "Freezing rain (heavy)",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Rain showers (slight)", 81: "Rain showers (moderate)", 82: "Rain showers (violent)",
    85: "Snow showers (slight)", 86: "Snow showers (heavy)",
    95: "Thunderstorm", 96: "Thunderstorm w/ slight hail", 99: "Thunderstorm w/ heavy hail",
}

_INTENT_FULL  = ["full", "all details", "everything", "detailed", "in-depth", "report"]
_INTENT_TIME  = ["sunrise", "sunset", "dawn", "dusk", "fajr", "prayer", "zenith", "time of"]
_INTENT_MOON  = ["moon phase", "moon cycle", "lunar phase", "lunar cycle", "moon day"]
_INTENT_RAIN  = ["rain", "umbrella", "precip", "shower", "storm", "drizzle"]
_INTENT_UV    = ["uv", "sunburn", "sunscreen"]
_INTENT_WIND  = ["wind", "breeze", "gust"]
_INTENT_HUM   = ["humidity", "humid"]
_INTENT_TEMP  = ["temperature", "temp", "hot", "cold", "feels like", "chilly"]


def _infer_intent(q: str) -> str:
    ql = (q or "").lower()

    if any(k in ql for k in _INTENT_FULL):   return "full"
    if any(k in ql for k in _INTENT_MOON):   return "moon"
    if any(k in ql for k in _INTENT_TIME):   return "time"
    if any(k in ql for k in _INTENT_UV):     return "action_uv"
    if any(k in ql for k in _INTENT_RAIN):   return "action_rain"
    if any(k in ql for k in _INTENT_WIND):   return "action_wind"
    if any(k in ql for k in _INTENT_HUM):    return "action_humidity"
    if any(k in ql for k in _INTENT_TEMP):   return "action_temp"

    return "quick"


def _extract_location_from_query(query: str) -> str:
    """
    Improved version that strips common time-related prefixes first
    so "sunrise time in X" or "what time is sunset in Y" still extracts X/Y correctly.
    """
    q = _normalize_space(query)
    if not q:
        return ""

    # Remove leading time-related words/phrases
    q = re.sub(
        r"\b(?:sunrise|sunset|dawn|dusk|when is|what time is|time of|fajr|prayer|zenith)\b\s*",
        "", q, flags=re.IGNORECASE
    ).strip()
    ql = q.lower()

    # If "in/for/at" present, capture after it
    m = re.search(
        r"\b(?:in|for|at)\s+(.+?)(?=\b(?:today|tomorrow|now|weather|forecast|sunrise|sunset|dawn|dusk|uv|rain|humidity|wind)\b|$)",
        ql
    )
    if m:
        loc = m.group(1).strip()
        loc = re.sub(r"[^a-zA-Z0-9\s\-,']", "", loc)
        return _normalize_space(loc)

    # If starts with time word + location
    m2 = re.search(
        r"^(?:sunrise|sunset|dawn|dusk|weather|forecast)\s+(.+)$",
        ql
    )
    if m2:
        loc = m2.group(1).strip()
        loc = re.sub(r"[^a-zA-Z0-9\s\-,']", "", loc)
        loc = re.sub(r"\b(?:today|tomorrow|now)\b", "", loc).strip()
        return _normalize_space(loc)

    return ""


# ── Core Handler ────────────────────────────────────────────────────────────

class WeatherHandler:
    def __init__(
        self,
        timezone: str = SYSTEM_TIMEZONE,
        cache_duration: int = DEFAULT_CACHE_DURATION,
        http_timeout: float = 10.0,
    ):
        self.timezone = pytz.timezone(timezone)
        self._cache_ttl = int(cache_duration)
        self._http_timeout = float(http_timeout)

        self._cache: Dict[str, Tuple[Any, float]] = {}

        # Long-lived moon cache (global)
        self.MOON_CACHE_KEY = "moon::global::daily"
        self.MOON_CACHE_TTL = 86400  # 24 hours

    def get_system_time(self) -> str:
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    def _cache_get(self, key: str) -> Optional[Any]:
        item = self._cache.get(key)
        if not item:
            return None
        val, ts = item
        if time.time() > ts:
            self._cache.pop(key, None)
            return None
        return val

    def _cache_set(self, key: str, val: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._cache_ttl
        self._cache[key] = (val, time.time() + effective_ttl)

    async def _geocode(self, name: str) -> Optional[GeoResult]:
        name = _normalize_space(name)
        if not name:
            return None

        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": name, "count": 1, "language": "en", "format": "json"}

        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.warning(f"Geocode failed for '{name}': {e}")
            return None

        results = data.get("results")
        if not results or not isinstance(results, list):
            return None

        top = results[0]
        if not isinstance(top, dict):
            return None

        try:
            return GeoResult(
                name=str(top.get("name") or name),
                country=str(top.get("country") or ""),
                admin1=str(top.get("admin1") or ""),
                latitude=float(top.get("latitude")),
                longitude=float(top.get("longitude")),
                timezone=str(top.get("timezone") or "auto"),
            )
        except Exception:
            return None

    async def _fetch_open_meteo(self, geo: GeoResult) -> Optional[WeatherSnapshot]:
        url = "https://api.open-meteo.com/v1/forecast"

        params = {
            "latitude": geo.latitude,
            "longitude": geo.longitude,
            "timezone": "auto",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
        }

        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.warning(f"Open-Meteo fetch failed for '{geo.name}': {e}")
            return None

        if not isinstance(data, dict):
            return None

        tz = str(data.get("timezone") or geo.timezone or "auto")
        now_iso = (data.get("current") or {}).get("time", "")

        parts = [geo.name]
        if geo.admin1: parts.append(geo.admin1)
        if geo.country: parts.append(geo.country)
        location_label = ", ".join(p for p in parts if p)

        snap = WeatherSnapshot(location_label=location_label, timezone=tz, now_iso=now_iso)

        cur = data.get("current") or {}
        snap.temp_c     = _round1(cur.get("temperature_2m"))
        snap.humidity   = _round0(cur.get("relative_humidity_2m"))
        snap.feels_c    = _round1(cur.get("apparent_temperature"))
        snap.precip_mm  = _round1(cur.get("precipitation"))
        snap.weather_code = int(cur["weather_code"]) if cur.get("weather_code") is not None else None
        snap.wind_kmh   = _round1(cur.get("wind_speed_10m"))
        snap.wind_dir_deg = _round0(cur.get("wind_direction_10m"))

        daily = data.get("daily") or {}
        def pick(field: str, idx: int) -> Optional[float]:
            arr = daily.get(field)
            if isinstance(arr, list) and len(arr) > idx:
                try: return float(arr[idx])
                except: return None
            return None

        def pick_str(field: str, idx: int) -> Optional[str]:
            arr = daily.get(field)
            if isinstance(arr, list) and len(arr) > idx:
                try: return str(arr[idx])
                except: return None
            return None

        snap.today_max_c      = _round1(pick("temperature_2m_max", 0))
        snap.today_min_c      = _round1(pick("temperature_2m_min", 0))
        snap.today_rain_prob  = _round0(pick("precipitation_probability_max", 0))
        snap.today_uv_max     = _round0(pick("uv_index_max", 0))
        snap.sunrise_iso      = pick_str("sunrise", 0)
        snap.sunset_iso       = pick_str("sunset", 0)

        snap.tom_max_c        = _round1(pick("temperature_2m_max", 1))
        snap.tom_min_c        = _round1(pick("temperature_2m_min", 1))
        snap.tom_rain_prob    = _round0(pick("precipitation_probability_max", 1))
        snap.tom_uv_max       = _round0(pick("uv_index_max", 1))
        snap.tom_sunrise_iso  = pick_str("sunrise", 1)
        snap.tom_sunset_iso   = pick_str("sunset", 1)

        return snap

    async def _fetch_wttr_moon(self) -> Dict[str, Any]:
        base = "https://www.wttr.in/moon"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SomiBot/1.1)"}

        async def get_json():
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                r = await client.get(f"{base}?format=j1", headers=headers)
                r.raise_for_status()
                return r.json()

        async def get_text():
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                r = await client.get(f"{base}?F", headers=headers)
                r.raise_for_status()
                return r.text.strip()

        for _ in range(3):
            try:
                data = await get_json()
                if isinstance(data, dict) and data:
                    return data
            except Exception as e:
                await asyncio.sleep(0.4)

        for _ in range(2):
            try:
                text = await get_text()
                if not text:
                    continue
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                keep = [ln for ln in lines if any(p in ln for p in ["Full Moon", "New Moon", "First Quarter", "Last Quarter", "Moon Phase", "Moon Age"])]
                return {
                    "_source": "wttr_text",
                    "lines": keep[:8] or lines[:8],
                    "raw": "\n".join(lines[:40]),
                }
            except Exception:
                await asyncio.sleep(0.4)

        return {}

    def _format_time_local(self, iso_str: Optional[str], tz_name: str) -> str:
        if not iso_str:
            return "N/A"
        try:
            dt = datetime.fromisoformat(iso_str)
            tz = pytz.timezone(tz_name) if tz_name and tz_name != "auto" else self.timezone
            dt_local = tz.localize(dt) if dt.tzinfo is None else dt.astimezone(tz)
            return dt_local.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return iso_str or "N/A"

    def _condition_text(self, code: Optional[int]) -> str:
        if code is None:
            return "Weather"
        return _WEATHER_CODE_TEXT.get(int(code), f"Weather (code {code})")

    def _resolve_location(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        loc = _extract_location_from_query(query)
        if loc:
            return loc, None

        if _DEFAULT_LOCATION:
            return _DEFAULT_LOCATION, None

        return None, "No location found. Try: 'weather in Port of Spain' or set DEFAULT_LOCATION in settings.py."

    def _render_quick(self, snap: WeatherSnapshot) -> str:
        cond = self._condition_text(snap.weather_code)
        temp = f"{snap.temp_c}°C" if snap.temp_c is not None else "N/A"
        feels = f"{snap.feels_c}°C" if snap.feels_c is not None else None

        rain = f"{int(snap.today_rain_prob)}%" if snap.today_rain_prob is not None else None

        wind_line = ""
        if snap.wind_kmh is not None and snap.wind_kmh >= 25:
            wind_line = f"\n💨 Wind: {snap.wind_kmh:g} km/h {_wind_dir_16(snap.wind_dir_deg)}"

        feels_part = f" (feels like {feels})" if feels and feels != temp else ""
        rain_part = f"\n🌧️ Rain chance (today): {rain}" if rain else ""

        return f"🌤️ {snap.location_label}\n{cond}\nTemp: {temp}{feels_part}{rain_part}{wind_line}"

    def _render_action_rain(self, snap: WeatherSnapshot, query: str) -> str:
        ql = query.lower()
        is_tom = "tomorrow" in ql
        prob = snap.tom_rain_prob if is_tom else snap.today_rain_prob
        day = "tomorrow" if is_tom else "today"

        if prob is None:
            return f"🌧️ Rain probability {day} in {snap.location_label}: N/A"

        p = int(prob)
        advice = "Low — no umbrella needed" if p <= 25 else \
                 "Moderate — consider umbrella" if p <= 60 else \
                 "High — umbrella recommended"

        return f"🌧️ Rain chance {day} in {snap.location_label}: {p}%\n{advice}"

    def _render_action_uv(self, snap: WeatherSnapshot, query: str) -> str:
        ql = query.lower()
        is_tom = "tomorrow" in ql
        uv = snap.tom_uv_max if is_tom else snap.today_uv_max
        day = "tomorrow" if is_tom else "today"

        if uv is None:
            return f"🌞 UV index {day} in {snap.location_label}: N/A"

        label = _uv_label(float(uv))
        advice = "Sunscreen + shade recommended (late morning–afternoon)" if label in ("high", "very high", "extreme") else \
                 "Low sunburn risk — still be sensible"

        return f"🌞 UV index {day} in {snap.location_label}: {int(uv)} ({label})\n{advice}"

    def _render_action_wind(self, snap: WeatherSnapshot) -> str:
        if snap.wind_kmh is None:
            return f"💨 Wind in {snap.location_label}: N/A"
        d = _wind_dir_16(snap.wind_dir_deg)
        w = snap.wind_kmh
        note = "Light breeze" if w < 15 else "Noticeable wind" if w < 30 else "Strong wind — be careful outdoors"
        return f"💨 Wind in {snap.location_label}: {w:g} km/h {d}\n{note}"

    def _render_action_humidity(self, snap: WeatherSnapshot) -> str:
        if snap.humidity is None:
            return f"💧 Humidity in {snap.location_label}: N/A"
        h = int(snap.humidity)
        note = "Dry" if h < 40 else "Comfortable to mildly humid" if h < 70 else "Humid — may feel sticky"
        return f"💧 Humidity in {snap.location_label}: {h}%\n{note}"

    def _render_action_temp(self, snap: WeatherSnapshot) -> str:
        if snap.temp_c is None:
            return f"🌡️ Temperature in {snap.location_label}: N/A"
        t = snap.temp_c
        feels = snap.feels_c
        line = f"🌡️ Temperature now in {snap.location_label}: {t:g}°C"
        if feels is not None and abs(feels - t) >= 2:
            line += f" (feels like {feels:g}°C)"
        return line

    def _render_time(self, snap: WeatherSnapshot, query: str) -> str:
        ql = query.lower()
        tz = snap.timezone if snap.timezone and snap.timezone != "auto" else SYSTEM_TIMEZONE

        sunrise = self._format_time_local(snap.sunrise_iso, tz)
        sunset  = self._format_time_local(snap.sunset_iso, tz)

        dawn = dusk = None
        try:
            if snap.sunrise_iso:
                dt = datetime.fromisoformat(snap.sunrise_iso)
                dawn = (dt - timedelta(minutes=30)).strftime("%I:%M %p").lstrip("0")
            if snap.sunset_iso:
                dt = datetime.fromisoformat(snap.sunset_iso)
                dusk = (dt + timedelta(minutes=30)).strftime("%I:%M %p").lstrip("0")
        except:
            pass

        lines = [f"⏰ Times for {snap.location_label} ({tz})"]

        if any(w in ql for w in ["sunrise", "dawn", "fajr", "prayer"]):
            if any(w in ql for w in ["dawn", "fajr", "prayer"]):
                lines.append(f"Dawn (approx): {dawn or 'N/A'}")
            lines.append(f"Sunrise: {sunrise}")

        if any(w in ql for w in ["sunset", "dusk"]):
            lines.append(f"Sunset: {sunset}")
            if "dusk" in ql:
                lines.append(f"Dusk (approx): {dusk or 'N/A'}")

        if len(lines) == 1:
            lines += [f"Sunrise: {sunrise}", f"Sunset: {sunset}"]

        return "\n".join(lines)

    def _render_full(self, snap: WeatherSnapshot) -> str:
        tz = snap.timezone if snap.timezone and snap.timezone != "auto" else SYSTEM_TIMEZONE
        cond = self._condition_text(snap.weather_code)
        wind_dir = _wind_dir_16(snap.wind_dir_deg)

        lines = [
            f"📍 {snap.location_label}",
            f"Condition: {cond}",
            f"Now: {snap.temp_c if snap.temp_c is not None else 'N/A'}°C"
                 f"{f' (feels like {snap.feels_c:g}°C)' if snap.feels_c is not None else ''}",
            f"Humidity: {int(snap.humidity)}%" if snap.humidity is not None else "Humidity: N/A",
            f"Wind: {snap.wind_kmh:g} km/h {wind_dir}" if snap.wind_kmh is not None else "Wind: N/A",
            f"Precip now: {snap.precip_mm:g} mm" if snap.precip_mm is not None else "Precip now: N/A",
            "",
            "Today:",
            f"- Max/Min: {snap.today_max_c if snap.today_max_c is not None else 'N/A'}°C / {snap.today_min_c if snap.today_min_c is not None else 'N/A'}°C",
            f"- Rain chance (max): {int(snap.today_rain_prob)}%" if snap.today_rain_prob is not None else "- Rain chance: N/A",
            f"- UV max: {int(snap.today_uv_max)} ({_uv_label(float(snap.today_uv_max))})" if snap.today_uv_max is not None else "- UV max: N/A",
            f"- Sunrise: {self._format_time_local(snap.sunrise_iso, tz)}",
            f"- Sunset:  {self._format_time_local(snap.sunset_iso, tz)}",
        ]

        if any(v is not None for v in [snap.tom_max_c, snap.tom_min_c, snap.tom_rain_prob]):
            lines += [
                "",
                "Tomorrow:",
                f"- Max/Min: {snap.tom_max_c if snap.tom_max_c is not None else 'N/A'}°C / {snap.tom_min_c if snap.tom_min_c is not None else 'N/A'}°C",
                f"- Rain chance (max): {int(snap.tom_rain_prob)}%" if snap.tom_rain_prob is not None else "- Rain chance: N/A",
                f"- UV max: {int(snap.tom_uv_max)} ({_uv_label(float(snap.tom_uv_max))})" if snap.tom_uv_max is not None else "- UV max: N/A",
            ]
            if snap.tom_sunrise_iso:
                lines.append(f"- Sunrise: {self._format_time_local(snap.tom_sunrise_iso, tz)}")
            if snap.tom_sunset_iso:
                lines.append(f"- Sunset:  {self._format_time_local(snap.tom_sunset_iso, tz)}")

        return "\n".join(lines)

    async def _build_snapshot(self, location: str) -> Tuple[Optional[WeatherSnapshot], Optional[str]]:
        geo = await self._geocode(location)
        if not geo:
            return None, f"Could not resolve location '{location}'. Try a more specific place (e.g., 'Port of Spain, Trinidad')."
        snap = await self._fetch_open_meteo(geo)
        if not snap:
            return None, f"Weather provider failed for '{location}'. Try again."
        return snap, None

    async def search_weather(
        self,
        query: str,
        retries: int = 1,
        backoff_factor: float = 0.5,
        cache_duration: int = DEFAULT_CACHE_DURATION,
    ) -> list:
        q = _normalize_space(query)
        if not q:
            return [{"title": "Error", "url": "", "description": "Empty query."}]

        intent = _infer_intent(q)
        loc, err = self._resolve_location(q)
        if err:
            return [{"title": "Error", "url": "https://open-meteo.com/", "description": err}]

        # ── Moon ────────────────────────────────────────────────────────────
        if intent == "moon":
            cached = self._cache_get(self.MOON_CACHE_KEY)
            if cached and isinstance(cached, list) and cached:
                return cached

            data = await self._fetch_wttr_moon()

            if data and "weather" in data:
                try:
                    astro = data["weather"][0]["astronomy"][0]
                    desc = f"Moon Phase: {astro.get('moon_phase', 'N/A')}\nMoon Day: {astro.get('moon_day', 'N/A')}"
                    out = [{"title": "Moon Phase", "url": "https://www.wttr.in/moon", "description": desc, "source": "wttr"}]
                except:
                    out = []
            else:
                if data and data.get("_source") == "wttr_text":
                    lines = data.get("lines") or (data.get("raw") or "").splitlines()[:10]
                    desc = "Moon cycle:\n" + "\n".join(lines)
                    out = [{"title": "Moon Cycle", "url": "https://www.wttr.in/moon", "description": desc, "source": "wttr"}]
                else:
                    out = [{"title": "Error", "url": "https://www.wttr.in/moon", "description": "Could not retrieve moon data.", "source": "wttr"}]

            self._cache_set(self.MOON_CACHE_KEY, out, ttl=self.MOON_CACHE_TTL)
            return out

        # ── Daily cache for time/full intents ───────────────────────────────
        use_daily_cache = intent in ("time", "full")
        daily_cache_key = None
        if use_daily_cache and not err:
            today_str = datetime.now(self.timezone).strftime("%Y-%m-%d")
            daily_cache_key = f"wx::daily::{today_str}::{loc.lower() if loc else 'default'}"
            cached_daily = self._cache_get(daily_cache_key)
            if cached_daily:
                return cached_daily

        # ── Normal short cache ──────────────────────────────────────────────
        ql = q.lower()
        day_key = "tomorrow" if "tomorrow" in ql else "today"
        cache_key = f"wx::{intent}::{day_key}::{loc.lower() if loc else 'default'}"

        cached = self._cache_get(cache_key)
        if isinstance(cached, list) and cached:
            return cached

        # Fetch
        last_err: Optional[str] = None
        snap: Optional[WeatherSnapshot] = None
        for attempt in range(max(1, retries)):
            snap, last_err = await self._build_snapshot(loc)
            if snap:
                break
            await asyncio.sleep(backoff_factor * (2 ** attempt))

        if not snap:
            return [{"title": "Error", "url": "https://open-meteo.com/", "description": last_err or "Weather unavailable."}]

        # Render
        if intent == "quick":
            desc = self._render_quick(snap)
            out = [{"title": f"Weather in {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "time":
            desc = self._render_time(snap, q)
            out = [{"title": f"Solar times in {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "full":
            desc = self._render_full(snap)
            out = [{"title": f"Full weather report for {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "action_rain":
            desc = self._render_action_rain(snap, q)
            out = [{"title": f"Rain chance for {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "action_uv":
            desc = self._render_action_uv(snap, q)
            out = [{"title": f"UV index for {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "action_wind":
            desc = self._render_action_wind(snap)
            out = [{"title": f"Wind in {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "action_humidity":
            desc = self._render_action_humidity(snap)
            out = [{"title": f"Humidity in {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        elif intent == "action_temp":
            desc = self._render_action_temp(snap)
            out = [{"title": f"Temperature in {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]
        else:
            desc = self._render_quick(snap)
            out = [{"title": f"Weather in {snap.location_label}", "url": "https://open-meteo.com/", "description": desc, "source": "open-meteo"}]

        # Store caches
        if use_daily_cache and daily_cache_key:
            self._cache_set(daily_cache_key, out, ttl=86400)  # 24h

        self._cache_set(cache_key, out)
        return out