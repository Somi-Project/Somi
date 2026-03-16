from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import ScheduleSpec


DAY_MAP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def _parse_time_fragment(text: str) -> tuple[int, int]:
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", str(text or "").strip(), flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Unsupported schedule time: {text}")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    am_pm = str(match.group(3) or "").lower()
    if am_pm:
        if hour < 1 or hour > 12:
            raise ValueError(f"Unsupported schedule time: {text}")
        if am_pm == "pm" and hour < 12:
            hour += 12
        if am_pm == "am" and hour == 12:
            hour = 0
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Unsupported schedule time: {text}")
    return hour, minute


def compute_next_run(spec: ScheduleSpec, *, after_dt: datetime | None = None) -> str:
    local_tz = _tz(spec.timezone)
    now_local = (after_dt or datetime.now(timezone.utc)).astimezone(local_tz)

    if spec.kind == "interval":
        next_local = now_local + timedelta(hours=max(1, int(spec.interval_hours or 1)))
        return next_local.astimezone(timezone.utc).isoformat()

    target_time = time(hour=int(spec.hour or 0), minute=int(spec.minute or 0))
    if spec.kind == "daily":
        candidate = now_local.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc).isoformat()

    if spec.kind == "weekly":
        days = list(spec.days_of_week or [])
        if not days:
            raise ValueError("Weekly schedule requires days_of_week")
        for delta in range(0, 8):
            candidate = (now_local + timedelta(days=delta)).replace(
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0,
            )
            if candidate.weekday() not in days:
                continue
            if candidate <= now_local:
                continue
            return candidate.astimezone(timezone.utc).isoformat()
        fallback = (now_local + timedelta(days=7)).replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
        return fallback.astimezone(timezone.utc).isoformat()

    raise ValueError(f"Unsupported schedule kind: {spec.kind}")


def parse_schedule_text(schedule_text: str, *, timezone_name: str = "UTC", now: datetime | None = None) -> ScheduleSpec:
    text = " ".join(str(schedule_text or "").strip().lower().split())
    if not text:
        raise ValueError("Schedule text is required")

    interval_match = re.fullmatch(r"every\s+(\d+)\s+hours?", text)
    if interval_match:
        spec = ScheduleSpec(
            kind="interval",
            timezone=timezone_name,
            source_text=schedule_text,
            interval_hours=max(1, int(interval_match.group(1))),
        )
        return ScheduleSpec(**{**spec.to_record(), "next_run_at": compute_next_run(spec, after_dt=now)})

    if text.startswith("daily at ") or text.startswith("every day at "):
        time_text = text.split(" at ", 1)[1]
        hour, minute = _parse_time_fragment(time_text)
        spec = ScheduleSpec(
            kind="daily",
            timezone=timezone_name,
            source_text=schedule_text,
            hour=hour,
            minute=minute,
        )
        return ScheduleSpec(**{**spec.to_record(), "next_run_at": compute_next_run(spec, after_dt=now)})

    if text.startswith("weekdays at "):
        time_text = text.split(" at ", 1)[1]
        hour, minute = _parse_time_fragment(time_text)
        spec = ScheduleSpec(
            kind="weekly",
            timezone=timezone_name,
            source_text=schedule_text,
            days_of_week=[0, 1, 2, 3, 4],
            hour=hour,
            minute=minute,
        )
        return ScheduleSpec(**{**spec.to_record(), "next_run_at": compute_next_run(spec, after_dt=now)})

    weekly_match = re.fullmatch(r"([a-z,\s]+)\s+at\s+(.+)", text)
    if weekly_match:
        day_names = [part.strip() for part in weekly_match.group(1).split(",") if part.strip()]
        days = [DAY_MAP[name] for name in day_names if name in DAY_MAP]
        if days:
            hour, minute = _parse_time_fragment(weekly_match.group(2))
            spec = ScheduleSpec(
                kind="weekly",
                timezone=timezone_name,
                source_text=schedule_text,
                days_of_week=days,
                hour=hour,
                minute=minute,
            )
            return ScheduleSpec(**{**spec.to_record(), "next_run_at": compute_next_run(spec, after_dt=now)})

    raise ValueError(f"Unsupported schedule text: {schedule_text}")
