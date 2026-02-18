from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HeartbeatState:
    enabled: bool
    mode: str
    running: bool = False
    paused: bool = False
    last_tick_ts: str | None = None
    next_tick_ts: str | None = None
    last_event_ts: str | None = None
    last_error: str | None = None
    last_action: str | None = "Idle"
    warn_count: int = 0
    error_count: int = 0

    last_greeting_date: str | None = None
    last_greeting_ts: str | None = None

    last_weather_check_ts: str | None = None
    last_weather_warning_sig: str | None = None
    last_weather_warning_ts: str | None = None

    last_delight_ts: str | None = None
    last_delight_sig: str | None = None
    delight_count_week: int = 0
    delight_week_start_date: str | None = None

    last_sig_ts: dict[str, float] = field(default_factory=dict)
    task_last_run: dict[str, float] = field(default_factory=dict)

    last_agentpedia_run_ts: str | None = None
    last_agentpedia_topic: str | None = None
    agentpedia_facts_count: int = 0
    last_agentpedia_error: str | None = None
    last_agentpedia_role: str | None = None
    last_agentpedia_style: str | None = None
