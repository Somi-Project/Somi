from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from executive.life_modeling.artifact_store import ArtifactStore
from config import settings

DEFAULT_PREFS = {
    "topics": {
        "weather": "notify",
        "news": "brief_only",
        "markets": "brief_only",
        "tasks": "notify",
        "strategic_signals": "notify",
        "alerts": "notify",
    },
    "brief_windows": {"morning": "08:00", "evening": "18:00"},
    "quiet_hours": {"start": "22:00", "end": "07:00"},
    "limits": {"max_notifications_per_day": int(getattr(settings, "PROACTIVITY_MAX_NOTIFICATIONS_PER_DAY", 1)), "max_messages_per_day": int(getattr(settings, "PROACTIVITY_MAX_MESSAGES_PER_DAY", 3)), "daily_interrupt_budget": int(getattr(settings, "PROACTIVITY_DAILY_INTERRUPT_BUDGET", 100))},
    "thresholds": {"notify": 72, "brief": 45},
}

TOPICS = {"strategic_signals", "weather", "news", "markets", "tasks", "alerts", "morning_brief", "evening_brief"}


@dataclass
class PreferenceManager:
    store: ArtifactStore

    def iter_updates(self, days: int = 60):
        cutoff = datetime.now(dt_timezone.utc) - timedelta(days=max(1, days))
        for row in self.store.iter_all("preference_update_v1") or []:
            ts = _parse_ts(row.get("timestamp"))
            if ts and ts >= cutoff:
                yield row


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=dt_timezone.utc)
    except Exception:
        return None


def _expiry(update: dict, tz: ZoneInfo) -> datetime | None:
    now = datetime.now(dt_timezone.utc)
    dur = str(update.get("duration") or "forever")
    ts = _parse_ts(update.get("timestamp")) or now
    base_local = ts.astimezone(tz)
    if dur == "once":
        return ts + timedelta(hours=1)
    if dur == "today":
        return base_local.replace(hour=23, minute=59, second=59, microsecond=0)
    if dur == "days":
        days = max(1, int(update.get("ttl_days") or 1))
        return ts + timedelta(days=days)
    ttl_days = int(update.get("ttl_days") or 0)
    if ttl_days > 0:
        return ts + timedelta(days=ttl_days)
    return None


def _active(update: dict, now: datetime, tz: ZoneInfo) -> bool:
    expires = _expiry(update, tz)
    return True if expires is None else now <= expires


def write_preference_update(store: ArtifactStore, payload: dict) -> dict:
    row = {
        "type": "preference_update_v1",
        "artifact_id": payload.get("artifact_id") or f"pu_{uuid.uuid4().hex[:10]}",
        "timestamp": payload.get("timestamp") or datetime.now(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "topic": payload.get("topic", "strategic_signals"),
        "scope": payload.get("scope", "global"),
        "mode": payload.get("mode", "disable"),
        "time": payload.get("time"),
        "duration": payload.get("duration", "forever"),
        "ttl_days": int(payload.get("ttl_days") or 0),
        "source_text": payload.get("source_text", ""),
        "no_autonomy": True,
    }
    if row["topic"] not in TOPICS:
        row["topic"] = "strategic_signals"
    return store.write("preference_update_v1", row)


def compile_effective_preferences(now: datetime, timezone: str, updates: list[dict] | None = None) -> dict:
    tz = ZoneInfo(timezone)
    local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    utc_now = local_now.astimezone(dt_timezone.utc)
    prefs = {
        "topics": dict(DEFAULT_PREFS["topics"]),
        "brief_windows": dict(DEFAULT_PREFS["brief_windows"]),
        "quiet_hours": dict(DEFAULT_PREFS["quiet_hours"]),
        "limits": dict(DEFAULT_PREFS["limits"]),
        "thresholds": dict(DEFAULT_PREFS["thresholds"]),
    }
    updates = sorted(list(updates or []), key=lambda r: str(r.get("timestamp") or ""))
    active = [u for u in updates if _active(u, utc_now, tz)]

    def apply(rows: list[dict], allowed_modes: set[str]):
        for row in rows:
            mode = str(row.get("mode") or "")
            if mode not in allowed_modes:
                continue
            topic = str(row.get("topic") or "")
            if topic in {"morning_brief", "evening_brief"}:
                key = "morning" if topic == "morning_brief" else "evening"
                if mode in {"disable", "snooze"} or row.get("time") is None:
                    prefs["brief_windows"][key] = None
                elif mode == "update_time":
                    prefs["brief_windows"][key] = row.get("time")
                elif mode == "enable":
                    prefs["brief_windows"][key] = prefs["brief_windows"].get(key) or DEFAULT_PREFS["brief_windows"][key]
                continue
            if topic in prefs["topics"]:
                if mode in {"disable", "snooze"}:
                    prefs["topics"][topic] = "off"
                elif mode in {"alerts_only", "brief_only", "notify"}:
                    prefs["topics"][topic] = mode
                elif mode == "enable":
                    prefs["topics"][topic] = "notify"

    temporary = [u for u in active if str(u.get("duration")) in {"once", "today", "days"} or str(u.get("mode")) == "snooze"]
    disables = [u for u in active if str(u.get("mode")) == "disable" and u not in temporary]
    explicit = [u for u in active if u not in temporary and u not in disables]

    apply(explicit, {"alerts_only", "brief_only", "notify", "enable", "update_time"})
    apply(disables, {"disable"})
    apply(temporary, {"disable", "alerts_only", "brief_only", "notify", "update_time", "snooze", "enable"})
    return prefs
