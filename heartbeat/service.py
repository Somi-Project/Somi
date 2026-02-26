from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from heartbeat.events import EventQueue, EventRingBuffer, event_signature, make_event
from heartbeat.policy import HeartbeatPolicy
from heartbeat.state import HeartbeatState
from heartbeat.tasks import AgentpediaGrowthTask, DailyGreetingTask, DelightTask, GoalNudgeTask, ReminderCheckTask, WeatherWarnTask
from heartbeat.tasks.base import HeartbeatContext, TaskRegistry


class HeartbeatService:
    """Calm background heartbeat runtime with strict monitor-only behavior."""

    # FUTURE (1B+): Task plugins (DailyGreeting, WeatherWarn, UrgentNews, ResearchNugget)
    # FUTURE: ASSIST mode may propose actions but requires user confirmation for side effects
    # FUTURE: Codex-like plugin integration point for “propose plan/patch” (no auto-apply)
    # SAFETY: Any external side effect must be gated behind explicit user opt-in
    # Heartbeat does NOT do autonomous news.
    # Rationale: news is high-noise, low-actionability, and causes spam.
    # Only fetch news on explicit user request.

    def __init__(self, settings_module=None):
        if settings_module is None:
            try:
                from config import heartbeatsettings as runtime_settings

                settings_module = runtime_settings
            except Exception:
                settings_module = SimpleNamespace()

        self.settings_module = settings_module
        self.timezone = getattr(settings_module, "SYSTEM_TIMEZONE", "UTC")
        self.tick_seconds = int(getattr(settings_module, "HEARTBEAT_TICK_SECONDS", 10))
        self.max_ui_drain = int(getattr(settings_module, "HB_MAX_UI_EVENTS_PER_DRAIN", 25))
        self.quiet_hours = getattr(settings_module, "HEARTBEAT_QUIET_HOURS", ("22:00", "05:00"))

        self.state = HeartbeatState(
            enabled=bool(getattr(settings_module, "HEARTBEAT_ENABLED", True)),
            mode=str(getattr(settings_module, "HEARTBEAT_MODE", "MONITOR")),
        )

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._ring = EventRingBuffer(maxlen=int(getattr(settings_module, "HB_MAX_EVENTS_BUFFER", 200)))
        self._ui_queue = EventQueue()
        self._registry = TaskRegistry()
        self._policy = HeartbeatPolicy(
            breadcrumb_minutes=int(getattr(settings_module, "HB_ALIVE_BREADCRUMB_MINUTES", 30)),
            dedupe_cooldown_seconds=int(getattr(settings_module, "HB_EVENT_DEDUPE_COOLDOWN_SECONDS", 300)),
        )
        self._logger = self._build_logger()
        self._inject_test_error_once = False
        self._shared_context: dict[str, Any] = {}

        self._registry.register(DailyGreetingTask())
        self._registry.register(WeatherWarnTask())
        self._registry.register(DelightTask())
        self._registry.register(AgentpediaGrowthTask())
        self._registry.register(ReminderCheckTask())
        self._registry.register(GoalNudgeTask())

    def _build_logger(self) -> logging.Logger:
        logs_path = Path(getattr(self.settings_module, "HB_LOG_PATH", "sessions/logs/heartbeat.log"))
        logs_path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("heartbeat.service")
        logger.setLevel(logging.INFO)
        has_handler = any(
            isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "").endswith(str(logs_path))
            for h in logger.handlers
        )
        if not has_handler:
            handler = RotatingFileHandler(logs_path, maxBytes=512_000, backupCount=3, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def _settings_snapshot(self) -> dict[str, Any]:
        keys = [
            "SYSTEM_TIMEZONE",
            "HEARTBEAT_ENABLED",
            "HEARTBEAT_MODE",
            "HEARTBEAT_TICK_SECONDS",
            "HEARTBEAT_QUIET_HOURS",
            "HB_ALIVE_BREADCRUMB_MINUTES",
            "HB_EVENT_DEDUPE_COOLDOWN_SECONDS",
            "HB_MAX_EVENTS_BUFFER",
            "HB_FEATURE_DAILY_GREETING",
            "HEARTBEAT_DAILY_GREETING_TIME",
            "HB_GREETING_INCLUDE_QUOTE",
            "HB_GREETING_INCLUDE_WEATHER",
            "HB_GREETING_INCLUDE_NEWS_URGENT",
            "HB_GREETING_MAX_WORDS",
            "HB_GREETING_CHANNEL",
            "HB_FEATURE_WEATHER_WARN",
            "HB_WEATHER_CHECK_MINUTES",
            "HB_WEATHER_WARN_DEDUPE_HOURS",
            "HB_WEATHER_FRESHNESS_MINUTES",
            "HB_WEATHER_THRESHOLDS",
            "HB_WEATHER_FAIL_SILENT",
            "HB_FEATURE_DELIGHT",
            "HB_DELIGHT_FREQUENCY",
            "HB_DELIGHT_QUIET_HOURS_RESPECT",
            "HB_DELIGHT_COOLDOWN_HOURS",
            "HB_DELIGHT_AVOID_AFTER_GREETING_MINUTES",
            "HB_DELIGHT_MAX_WORDS",
            "HB_DELIGHT_SOURCES",
            "USER_INTERESTS",
            "HB_NEWS_DISABLED",
            "HB_FEATURE_NEWS_URGENT",
            "HB_FEATURE_AGENTPEDIA_GROWTH",
            "HB_AGENTPEDIA_GROWTH_FREQUENCY",
            "HB_AGENTPEDIA_GROWTH_FREQUENCY_MODE",
            "HB_AGENTPEDIA_FACTS_PER_RUN",
            "HB_AGENTPEDIA_ANNOUNCE_UPDATES",
            "HB_AGENTPEDIA_MIN_CONFIDENCE_TO_COMMIT",
            "HB_AGENTPEDIA_FAIL_SILENT",
            "CAREER_ROLE",
            "USER_INTERESTS",
            "HB_FEATURE_CAREER_ROLE",
            "HB_FEATURE_REMINDERS",
            "HB_FEATURE_GOAL_NUDGES",
            "HB_GOAL_NUDGE_INTERVAL_MINUTES",
        ]
        snapshot = {k: getattr(self.settings_module, k, None) for k in keys}
        with self._lock:
            snapshot.update(self._shared_context)
        return snapshot

    def set_shared_context(self, **kwargs: Any) -> None:
        with self._lock:
            self._shared_context.update(kwargs)

    def _in_quiet_hours(self, now: datetime) -> bool:
        try:
            start_raw, end_raw = self.quiet_hours
            start_t = time.fromisoformat(start_raw)
            end_t = time.fromisoformat(end_raw)
        except Exception:
            return False
        n = now.timetz().replace(tzinfo=None)
        if start_t <= end_t:
            return start_t <= n <= end_t
        return n >= start_t or n <= end_t

    def _record_event(self, event: dict[str, Any], for_ui: bool = False) -> None:
        with self._lock:
            self.state.last_event_ts = event.get("ts")
            level = event.get("level")
            if level == "WARN":
                self.state.warn_count += 1
            elif level == "ERROR":
                self.state.error_count += 1
                self.state.last_error = event.get("detail") or event.get("title")
        self._ring.append(event)
        if for_ui:
            self._ui_queue.put(event)

    def _emit_lifecycle(self, title: str) -> None:
        event = make_event("INFO", "lifecycle", title, timezone=self.timezone)
        self._record_event(event, for_ui=True)
        self._logger.info(title)

    def _run_tasks(self, now: datetime) -> None:
        settings_snapshot = self._settings_snapshot()
        for task in self._registry.list_tasks():
            last_run = self.state.task_last_run.get(task.name, 0.0)
            if (now.timestamp() - last_run) < int(getattr(task, "min_interval_seconds", 60)):
                continue

            ctx = HeartbeatContext(now_dt=now, settings=settings_snapshot, state=self.state)
            should_run = False
            try:
                should_run = task.should_run(ctx)
            except Exception as exc:
                self._logger.debug("Task should_run failed for %s: %s", task.name, exc)
            finally:
                self.state.task_last_run[task.name] = now.timestamp()

            if not should_run:
                continue

            try:
                events = task.run(ctx)
            except Exception as exc:
                self._logger.debug("Task run failed for %s: %s", task.name, exc)
                continue

            if task.name == "weather_warn" and not events:
                # 1C fail-silent weather behavior.
                self._logger.debug("weather_warn: no user-facing output (insufficient/failing data)")

            for event in events:
                self._record_event(event, for_ui=True)
                self._logger.info("%s: %s", task.name, event.get("title", "event"))

    def start(self) -> None:
        if not self.state.enabled or self.state.mode == "OFF":
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        with self._lock:
            self.state.running = True
            self.state.paused = False
            self.state.last_action = "Started"
        self._emit_lifecycle("Heartbeat started")
        self._thread = threading.Thread(target=self._run_loop, name="HeartbeatService", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        with self._lock:
            self.state.running = False
            self.state.last_action = "Stopped"
        self._emit_lifecycle("Heartbeat stopped")

    def pause(self) -> None:
        with self._lock:
            self.state.paused = True
            self.state.last_action = "Paused"
        self._emit_lifecycle("Heartbeat paused")

    def resume(self) -> None:
        with self._lock:
            self.state.paused = False
            self.state.last_action = "Resumed"
        self._emit_lifecycle("Heartbeat resumed")

    def register_task(self, task) -> None:
        self._registry.register(task)

    def inject_test_error_once(self) -> None:
        """Testing hook: raise one controlled loop exception on the next tick."""
        self._inject_test_error_once = True

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            state_snapshot = {
                "enabled": self.state.enabled,
                "mode": self.state.mode,
                "running": self.state.running,
                "paused": self.state.paused,
                "last_tick_ts": self.state.last_tick_ts,
                "next_tick_ts": self.state.next_tick_ts,
                "last_event_ts": self.state.last_event_ts,
                "last_error": self.state.last_error,
                "last_action": self.state.last_action,
                "warn_count": self.state.warn_count,
                "error_count": self.state.error_count,
                "last_greeting_date": self.state.last_greeting_date,
                "last_greeting_ts": self.state.last_greeting_ts,
                "last_weather_check_ts": self.state.last_weather_check_ts,
                "last_weather_warning_sig": self.state.last_weather_warning_sig,
                "last_weather_warning_ts": self.state.last_weather_warning_ts,
                "last_delight_ts": self.state.last_delight_ts,
                "last_delight_sig": self.state.last_delight_sig,
                "delight_count_week": self.state.delight_count_week,
                "delight_week_start_date": self.state.delight_week_start_date,
                "last_agentpedia_run_ts": self.state.last_agentpedia_run_ts,
                "last_agentpedia_topic": self.state.last_agentpedia_topic,
                "agentpedia_facts_count": self.state.agentpedia_facts_count,
                "last_agentpedia_error": self.state.last_agentpedia_error,
                "last_agentpedia_role": self.state.last_agentpedia_role,
                "last_agentpedia_style": self.state.last_agentpedia_style,
            }
        return {"state": state_snapshot, "events": self._ring.get_last(20)}

    def drain_events(self, max_n: int | None = None) -> list[dict[str, Any]]:
        max_n = self.max_ui_drain if max_n is None else max_n
        return self._ui_queue.drain(max_n=max_n)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = self._now()
            try:
                if self._inject_test_error_once:
                    self._inject_test_error_once = False
                    raise RuntimeError("Injected heartbeat test error")

                next_tick = now + timedelta(seconds=self.tick_seconds)
                with self._lock:
                    self.state.last_tick_ts = now.isoformat()
                    self.state.next_tick_ts = next_tick.isoformat()

                tick_event = make_event("DEBUG", "tick", "Heartbeat tick", timezone=self.timezone)
                self._record_event(tick_event, for_ui=False)

                with self._lock:
                    paused = self.state.paused

                status_event = make_event(
                    "INFO",
                    "status",
                    "Heartbeat paused" if paused else "Heartbeat steady",
                    detail="Monitoring in background" if not paused else "Paused by user",
                    meta={"paused": paused},
                    timezone=self.timezone,
                )
                self._record_event(status_event, for_ui=False)

                if self._policy.should_emit_ui_event(status_event, now):
                    self._ui_queue.put(status_event)

                if (not paused) and (not self._in_quiet_hours(now)) and self._policy.allow_breadcrumb(now):
                    breadcrumb = make_event(
                        "INFO",
                        "status",
                        "Heartbeat steady",
                        detail="Monitoring in background",
                        timezone=self.timezone,
                    )
                    self._record_event(breadcrumb, for_ui=True)

                if not paused:
                    self._run_tasks(now)

            except Exception as exc:
                msg = str(exc)
                with self._lock:
                    self.state.last_error = msg
                err_event = make_event(
                    "ERROR",
                    "error",
                    "Heartbeat runtime error",
                    detail=msg,
                    timezone=self.timezone,
                )
                sig = event_signature(err_event)
                if self._policy.dedupe_ok(sig, now):
                    self._record_event(err_event, for_ui=True)
                    self._logger.error("Heartbeat runtime error: %s", msg)

            self._stop_event.wait(self.tick_seconds)
