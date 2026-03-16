from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from executive.life_modeling.artifact_store import ArtifactStore
from .validators import passes_quality_gate


def _safe_zone(timezone: str):
    try:
        return ZoneInfo(str(timezone or "UTC"))
    except Exception:
        return dt_timezone.utc


class BriefGenerator:
    def __init__(self, store: ArtifactStore):
        self.store = store

    def weather_cues(self, weather: dict) -> list[str]:
        cues = []
        pop = float(weather.get("precip_probability", 0))
        precip = float(weather.get("precip_amount_mm", 0))
        uv = float(weather.get("uv_index", 0))
        heat = float(weather.get("heat_index_c", 0))
        wind = float(weather.get("wind_kph", 0))
        flood = float(weather.get("flood_risk", 0))
        if pop >= 0.5 or precip >= 2 or weather.get("thunderstorm_risk"):
            cues.append("Bring an umbrella for your likely out-of-home window.")
        if uv >= 7 or heat >= 32:
            cues.append("Plan sunscreen and hydration before midday exposure.")
        if wind >= 35 or flood >= 0.6:
            cues.append("Expect hazardous conditions; adjust travel timing.")
        return cues

    def generate(self, now: datetime, timezone: str, cards: list[dict], alerts: list[dict]) -> dict:
        filtered = [c for c in cards if passes_quality_gate(c)][:5]
        out = {
            "type": "daily_brief_v1",
            "date": (now.astimezone(_safe_zone(timezone)) if now.tzinfo else now.replace(tzinfo=_safe_zone(timezone))).date().isoformat(),
            "timezone": timezone,
            "cards": filtered,
            "alerts": alerts[:3],
            "no_autonomy": True,
        }
        return self.store.write("daily_brief_v1", out)

