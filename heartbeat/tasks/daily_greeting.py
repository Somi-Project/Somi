from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


_QUOTES = [
    "Start gentle. Consistency beats intensity.",
    "Small steps still move your life forward.",
    "Breathe first, then choose your first easy win.",
    "Clarity grows when you begin, not before.",
    "Kind progress is still progress.",
    "One focused hour can change the whole day.",
    "Do the next simple thing well.",
    "Less rush, more rhythm.",
    "A calm start can carry the whole morning.",
    "Make it lighter than yesterday.",
    "Show up first; polish later.",
    "Protect your attention like it's oxygen.",
    "Momentum loves a tiny beginning.",
    "Quiet effort compounds.",
    "Keep it simple, keep it moving.",
    "Energy follows direction.",
    "Finish one thing before chasing five.",
    "Today's tiny win counts.",
    "Start where you are, not where you wish you were.",
    "A steady pace beats a perfect plan.",
    "Begin with what's already in reach.",
    "You don't need pressure to make progress.",
    "Less noise, more signal.",
]


class DailyGreetingTask:
    name = "daily_greeting"
    min_interval_seconds = 60
    enabled_flag_name = "HB_FEATURE_DAILY_GREETING"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        if not bool(ctx.settings.get("HB_FEATURE_DAILY_GREETING", True)):
            return False

        now = ctx.now_dt
        tz_name = ctx.settings.get("SYSTEM_TIMEZONE", "UTC")
        tz = ZoneInfo(tz_name)
        if now.tzinfo is None:
            now = now.replace(tzinfo=tz)

        greeting_time = str(ctx.settings.get("HEARTBEAT_DAILY_GREETING_TIME", "05:00"))
        try:
            hour, minute = [int(v) for v in greeting_time.split(":", maxsplit=1)]
        except Exception:
            hour, minute = 5, 0

        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < scheduled:
            return False

        today = now.date().isoformat()
        return ctx.state.last_greeting_date != today

    def run(self, ctx: HeartbeatContext) -> list[dict]:
        now = ctx.now_dt
        tz_name = ctx.settings.get("SYSTEM_TIMEZONE", "UTC")
        tz = ZoneInfo(tz_name)
        if now.tzinfo is None:
            now = now.replace(tzinfo=tz)

        include_quote = bool(ctx.settings.get("HB_GREETING_INCLUDE_QUOTE", True))
        include_weather = bool(ctx.settings.get("HB_GREETING_INCLUDE_WEATHER", True))
        include_news_urgent = bool(ctx.settings.get("HB_GREETING_INCLUDE_NEWS_URGENT", False))
        if bool(ctx.settings.get("HB_NEWS_DISABLED", False)):
            include_news_urgent = False
        max_words = int(ctx.settings.get("HB_GREETING_MAX_WORDS", 80))

        segments = ["Good morning. Let's make today easy: one small win first."]

        if include_weather:
            weather_line = str(ctx.settings.get("HB_CACHED_WEATHER_LINE") or "").strip()
            if weather_line:
                segments.append(f"Weather: {weather_line}")

        if include_news_urgent:
            urgent_headline = str(ctx.settings.get("HB_CACHED_URGENT_HEADLINE") or "").strip()
            if urgent_headline:
                segments.append(f"Urgent: {urgent_headline}")

        if include_quote:
            segments.append(f"\"{random.choice(_QUOTES)}\"")

        detail = "\n".join(segments)
        words = detail.split()
        if len(words) > max_words:
            detail = " ".join(words[:max_words]).rstrip(".,;:") + "…"

        event = make_event(
            "INFO",
            "alert",
            "Good morning",
            detail=detail,
            meta={"channel": ctx.settings.get("HB_GREETING_CHANNEL", "activity"), "kind": "daily_greeting"},
            timezone=tz_name,
        )

        ctx.state.last_greeting_date = now.date().isoformat()
        ctx.state.last_greeting_ts = now.isoformat()
        ctx.state.last_action = "Daily greeting sent"
        return [event]
