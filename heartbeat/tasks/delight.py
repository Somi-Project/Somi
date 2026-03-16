from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext

_LOCAL_FACTS = [
    "Quick fact: Octopuses have three hearts. 🐙",
    "Quick fact: Honey never really spoils if sealed well.",
    "Quick fact: Your brain runs on about 20 watts.",
    "Quick fact: Bananas are berries; strawberries aren't.",
    "Quick fact: Some turtles can breathe through their shells.",
]

_LOCAL_JOKES = [
    "Joke: Why don't programmers like nature? Too many bugs.",
    "Joke: I would tell a UDP joke, but you might not get it.",
    "Joke: Why did the function break up? Too many arguments.",
    "Joke: I changed my password to 'incorrect'—now it's always a hint.",
]

_INTEREST_SNIPPETS = {
    "gaming": ["Tiny boost: one focused match or one focused task—same momentum."],
    "anime": ["Tiny boost: rewatch a favorite scene after your first completed task."],
    "cars": ["Tiny boost: smooth inputs beat aggressive ones—works for driving and focus."],
    "medicine": ["Tiny boost: checklists reduce cognitive load under pressure."],
}


class DelightTask:
    name = "delight"
    min_interval_seconds = 24 * 60 * 60
    enabled_flag_name = "HB_FEATURE_DELIGHT"

    def should_run(self, ctx: HeartbeatContext) -> bool:
        if not bool(ctx.settings.get("HB_FEATURE_DELIGHT", True)):
            return False

        freq = str(ctx.settings.get("HB_DELIGHT_FREQUENCY", "3_per_week"))
        if freq == "weekly":
            self.min_interval_seconds = 3 * 24 * 60 * 60
        else:
            self.min_interval_seconds = 24 * 60 * 60

        now = ctx.now_dt
        if self._respect_quiet_hours(ctx, now):
            return False

        if not self._respects_after_greeting_gap(ctx, now):
            return False

        if not self._quota_allows(ctx, now):
            return False

        cooldown_h = float(ctx.settings.get("HB_DELIGHT_COOLDOWN_HOURS", 24))
        if ctx.state.last_delight_ts:
            try:
                last_ts = datetime.fromisoformat(ctx.state.last_delight_ts)
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=ZoneInfo(str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC"))))
                if (now - last_ts).total_seconds() < cooldown_h * 3600:
                    return False
            except Exception:
                pass
        return True

    def _respect_quiet_hours(self, ctx: HeartbeatContext, now: datetime) -> bool:
        if not bool(ctx.settings.get("HB_DELIGHT_QUIET_HOURS_RESPECT", True)):
            return False
        quiet = ctx.settings.get("HEARTBEAT_QUIET_HOURS", ("22:00", "05:00"))
        try:
            sh, sm = [int(v) for v in str(quiet[0]).split(":", 1)]
            eh, em = [int(v) for v in str(quiet[1]).split(":", 1)]
        except Exception:
            return False
        cur = now.hour * 60 + now.minute
        s = sh * 60 + sm
        e = eh * 60 + em
        if s <= e:
            return s <= cur <= e
        return cur >= s or cur <= e

    def _respects_after_greeting_gap(self, ctx: HeartbeatContext, now: datetime) -> bool:
        gap_min = int(ctx.settings.get("HB_DELIGHT_AVOID_AFTER_GREETING_MINUTES", 60))
        if not ctx.state.last_greeting_ts:
            return True
        try:
            last = datetime.fromisoformat(ctx.state.last_greeting_ts)
            if last.tzinfo is None:
                last = last.replace(tzinfo=ZoneInfo(str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC"))))
            return (now - last) >= timedelta(minutes=gap_min)
        except Exception:
            return True

    def _week_start(self, d: date) -> date:
        return d - timedelta(days=d.weekday())

    def _quota_allows(self, ctx: HeartbeatContext, now: datetime) -> bool:
        freq = str(ctx.settings.get("HB_DELIGHT_FREQUENCY", "3_per_week"))
        today = now.date()

        if freq == "daily":
            if ctx.state.last_delight_ts is None:
                return True
            try:
                return datetime.fromisoformat(ctx.state.last_delight_ts).date() != today
            except Exception:
                return True

        week_start = self._week_start(today)
        week_start_iso = week_start.isoformat()
        if ctx.state.delight_week_start_date != week_start_iso:
            ctx.state.delight_week_start_date = week_start_iso
            ctx.state.delight_count_week = 0

        if freq == "weekly":
            return ctx.state.delight_count_week < 1
        return ctx.state.delight_count_week < 3

    def _make_signature(self, line: str, now: datetime) -> str:
        day = now.date().isoformat()
        raw = f"{day}|{line.strip().lower()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _pick_line(self, ctx: HeartbeatContext) -> str:
        ordered = list(ctx.settings.get("HB_DELIGHT_SOURCES", ["local_facts", "local_jokes"]))

        # A) agentpedia fact from cache
        if "agentpedia_fact" in ordered:
            fact = str(ctx.settings.get("HB_CACHED_AGENTPEDIA_FACT") or "").strip()
            if fact:
                return f"Quick spark: {fact}"

        # B) interest snippet from configured interests
        if "interest_snippet" in ordered:
            interests = ctx.settings.get("USER_INTERESTS") or []
            if isinstance(interests, (list, tuple)):
                for interest in interests:
                    options = _INTEREST_SNIPPETS.get(str(interest).lower())
                    if options:
                        return random.choice(options)

        # C) local facts
        if "local_facts" in ordered:
            return random.choice(_LOCAL_FACTS)

        # D) local jokes
        if "local_jokes" in ordered:
            return random.choice(_LOCAL_JOKES)

        return random.choice(_LOCAL_FACTS)

    def run(self, ctx: HeartbeatContext) -> list[dict[str, Any]]:
        now = ctx.now_dt
        line = self._pick_line(ctx)

        max_words = int(ctx.settings.get("HB_DELIGHT_MAX_WORDS", 50))
        words = line.split()
        if len(words) > max_words:
            line = " ".join(words[:max_words]).rstrip(".,;:") + "…"

        sig = self._make_signature(line, now)
        dedupe_hours = float(ctx.settings.get("HB_DELIGHT_COOLDOWN_HOURS", 24))
        last_ts = ctx.state.last_sig_ts.get(sig)
        if last_ts is not None and (now.timestamp() - last_ts) < dedupe_hours * 3600:
            return []

        ctx.state.last_sig_ts[sig] = now.timestamp()
        ctx.state.last_delight_sig = sig
        ctx.state.last_delight_ts = now.isoformat()
        ctx.state.delight_count_week = int(ctx.state.delight_count_week or 0) + 1
        if not ctx.state.delight_week_start_date:
            ctx.state.delight_week_start_date = self._week_start(now.date()).isoformat()
        ctx.state.last_action = "Delight shared"

        event = make_event(
            "INFO",
            "alert",
            "Quick spark",
            detail=line,
            meta={"kind": "delight"},
            timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
        )
        return [event]
