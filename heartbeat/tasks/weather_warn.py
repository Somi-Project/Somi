from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


class WeatherWarnTask:
    name = "weather_warn"
    min_interval_seconds = 45 * 60
    enabled_flag_name = "HB_FEATURE_WEATHER_WARN"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        enabled = bool(ctx.settings.get("HB_FEATURE_WEATHER_WARN", True))
        self.min_interval_seconds = int(ctx.settings.get("HB_WEATHER_CHECK_MINUTES", 45)) * 60
        return enabled

    def _normalize_payload(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload or not isinstance(payload, dict):
            return None

        precip_prob = payload.get("precip_prob")
        if precip_prob is None:
            precip_prob = payload.get("precipitation_probability")
        if precip_prob is None:
            precip_prob = payload.get("precip_probability")

        if isinstance(precip_prob, (int, float)) and precip_prob > 1:
            precip_prob = float(precip_prob) / 100.0
        else:
            precip_prob = _to_float(precip_prob)
            if precip_prob is not None and precip_prob > 1:
                precip_prob = precip_prob / 100.0

        rain_mm = _to_float(payload.get("rain_mm", payload.get("precipitation_mm")))
        wind_kph = _to_float(payload.get("wind_kph", payload.get("wind_speed_kph")))
        temp_c = _to_float(payload.get("temp_c", payload.get("temperature_c", payload.get("temp"))))
        desc = str(payload.get("description") or payload.get("line") or payload.get("summary") or "").strip()

        normalized = {
            "precip_prob": precip_prob,
            "rain_mm": rain_mm,
            "wind_kph": wind_kph,
            "temp_c": temp_c,
            "description": desc,
            "source": payload.get("source", "cached"),
        }
        return normalized

    def _get_weather_payload(self, ctx: HeartbeatContext) -> tuple[dict[str, Any] | None, str]:
        # Primary pathway: normalized payload if GUI/handler already cached it.
        primary = ctx.settings.get("HB_CACHED_WEATHER_PAYLOAD")
        normalized = self._normalize_payload(primary if isinstance(primary, dict) else None)
        if normalized:
            return normalized, "primary"

        # Fallback: cached text summary with freshness gate.
        freshness_limit_m = int(ctx.settings.get("HB_WEATHER_FRESHNESS_MINUTES", 180))
        cached_line = str(ctx.settings.get("HB_CACHED_WEATHER_LINE") or "").strip()
        cached_ts = str(ctx.settings.get("HB_CACHED_WEATHER_TS") or "").strip()
        if cached_line and cached_ts:
            try:
                now = ctx.now_dt
                ts = datetime.fromisoformat(cached_ts)
                if ts.tzinfo is None:
                    tz = ZoneInfo(str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")))
                    ts = ts.replace(tzinfo=tz)
                age_m = (now - ts).total_seconds() / 60.0
                if age_m <= freshness_limit_m:
                    parsed = {
                        "description": cached_line,
                        "temp_c": _to_float(cached_line),
                        "source": "cached_line",
                    }
                    return parsed, "fallback_cached"
            except Exception:
                return None, "fallback_invalid"

        return None, "failed"

    def _warning_signature(self, now: datetime, warning_types: list[str], payload: dict[str, Any]) -> str:
        def bucket(v: float | None, step: float) -> str:
            if v is None:
                return "na"
            return str(int(v / step))

        sig_struct = {
            "day": now.date().isoformat(),
            "types": sorted(set(warning_types)),
            "p": bucket(payload.get("precip_prob"), 0.1),
            "r": bucket(payload.get("rain_mm"), 5.0),
            "w": bucket(payload.get("wind_kph"), 10.0),
            "t": bucket(payload.get("temp_c"), 5.0),
        }
        raw = json.dumps(sig_struct, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def run(self, ctx: HeartbeatContext) -> list[dict[str, Any]]:
        now = ctx.now_dt
        ctx.state.last_weather_check_ts = now.isoformat()

        payload, source = self._get_weather_payload(ctx)
        if payload is None:
            return []

        thresholds = ctx.settings.get("HB_WEATHER_THRESHOLDS") or {}
        precip_th = float(thresholds.get("precip_prob", 0.70))
        rain_th = float(thresholds.get("rain_mm", 10))
        wind_th = float(thresholds.get("wind_kph", 45))
        heat_th = float(thresholds.get("heat_c", 35))
        cold_th = float(thresholds.get("cold_c", 5))
        storm_keywords = [str(k).lower() for k in thresholds.get("storm_keywords", [])]

        warnings: list[str] = []
        p = payload.get("precip_prob")
        r = payload.get("rain_mm")
        w = payload.get("wind_kph")
        t = payload.get("temp_c")
        desc = str(payload.get("description") or "")
        desc_lower = desc.lower()

        if isinstance(p, (int, float)) and p >= precip_th:
            warnings.append("heavy_rain_likely")
        if isinstance(r, (int, float)) and r >= rain_th:
            warnings.append("high_rain_volume")
        if isinstance(w, (int, float)) and w >= wind_th:
            warnings.append("strong_winds")
        if isinstance(t, (int, float)) and t >= heat_th:
            warnings.append("high_heat")
        if isinstance(t, (int, float)) and t <= cold_th:
            warnings.append("cold_risk")
        if desc_lower and any(k in desc_lower for k in storm_keywords):
            warnings.append("storm_signal")

        if not warnings:
            return []

        sig = self._warning_signature(now, warnings, payload)
        dedupe_hours = float(ctx.settings.get("HB_WEATHER_WARN_DEDUPE_HOURS", 8))
        dedupe_window_s = dedupe_hours * 3600.0
        last_ts = ctx.state.last_sig_ts.get(sig)
        if last_ts is not None and (now.timestamp() - last_ts) < dedupe_window_s:
            return []

        ctx.state.last_sig_ts[sig] = now.timestamp()
        ctx.state.last_weather_warning_sig = sig
        ctx.state.last_weather_warning_ts = now.isoformat()

        title_map = {
            "heavy_rain_likely": "Weather warning: heavy rain likely",
            "high_rain_volume": "Weather warning: heavy rainfall",
            "strong_winds": "Weather warning: strong winds likely",
            "high_heat": "Weather warning: high heat",
            "cold_risk": "Weather warning: cold conditions",
            "storm_signal": "Weather warning: storm conditions possible",
        }
        primary = warnings[0]
        title = title_map.get(primary, "Weather warning")
        detail = "Conditions today may need extra caution."
        if desc:
            detail = f"Today: {desc}"[:150]

        event = make_event(
            "WARN",
            "alert",
            title,
            detail=detail,
            actions=[{"label": "Show weather", "action": "open_weather_panel"}],
            meta={"kind": "weather_warn", "source": source, "warnings": warnings},
            timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
        )
        return [event]
