from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from handlers.research.agentpedia import Agentpedia
from handlers.research.role_overlay import resolve_role_context
from heartbeat.events import make_event
from heartbeat.tasks.base import HeartbeatContext


class AgentpediaGrowthTask:
    name = "agentpedia_growth"
    min_interval_seconds = 7 * 24 * 60 * 60
    enabled_flag_name = "HB_FEATURE_AGENTPEDIA_GROWTH"

    def __init__(self):
        self.agentpedia = Agentpedia(write_back=False)

    def should_run(self, ctx: HeartbeatContext) -> bool:
        if not bool(ctx.settings.get("HB_FEATURE_AGENTPEDIA_GROWTH", False)):
            return False

        freq_mode = str(ctx.settings.get("HB_AGENTPEDIA_GROWTH_FREQUENCY_MODE", "explicit"))
        role = ctx.settings.get("CAREER_ROLE") if bool(ctx.settings.get("HB_FEATURE_CAREER_ROLE", True)) else None
        interests = ctx.settings.get("USER_INTERESTS") if bool(ctx.settings.get("HB_FEATURE_CAREER_ROLE", True)) else []
        role_ctx = resolve_role_context(role, interests if isinstance(interests, list) else [])
        freq = str(ctx.settings.get("HB_AGENTPEDIA_GROWTH_FREQUENCY", "weekly"))
        if freq_mode == "role_default" and role_ctx.growth_frequency_default:
            freq = str(role_ctx.growth_frequency_default)

        if freq == "daily":
            self.min_interval_seconds = 24 * 60 * 60
        elif freq == "3_per_week":
            self.min_interval_seconds = 24 * 60 * 60
        else:
            self.min_interval_seconds = 7 * 24 * 60 * 60

        # extra guard for 3/week quota from stateful timestamp map
        if freq == "3_per_week":
            week_key = f"agentpedia_week:{ctx.now_dt.date().isocalendar().week}"
            count = int(ctx.state.last_sig_ts.get(week_key, 0))
            if count >= 3:
                return False
        return True

    def run(self, ctx: HeartbeatContext) -> list[dict[str, Any]]:
        role = ctx.settings.get("CAREER_ROLE") if bool(ctx.settings.get("HB_FEATURE_CAREER_ROLE", True)) else None
        interests = ctx.settings.get("USER_INTERESTS") if bool(ctx.settings.get("HB_FEATURE_CAREER_ROLE", True)) else []
        max_facts = int(ctx.settings.get("HB_AGENTPEDIA_FACTS_PER_RUN", 2))
        announce = bool(ctx.settings.get("HB_AGENTPEDIA_ANNOUNCE_UPDATES", False))

        try:
            result = self.agentpedia.grow(role=role, interests=interests, max_facts=max_facts, mode="safe")
            stats = self.agentpedia.get_agentpedia_stats()
            ctx.state.last_agentpedia_run_ts = stats.get("last_run_ts")
            ctx.state.last_agentpedia_topic = stats.get("last_topic_run")
            ctx.state.agentpedia_facts_count = int(stats.get("facts_count") or 0)
            ctx.state.last_action = f"Agentpedia updated (+{int(result.get('added_facts_count') or 0)})"
            ctx.state.last_agentpedia_role = str(stats.get("last_role") or role or "General")
            ctx.state.last_agentpedia_style = str(stats.get("last_nugget_style") or "fun_fact")

            # 3/week weekly counter
            freq = str(ctx.settings.get("HB_AGENTPEDIA_GROWTH_FREQUENCY", "weekly"))
            if freq == "3_per_week" and int(result.get("added_facts_count") or 0) > 0:
                week_key = f"agentpedia_week:{ctx.now_dt.date().isocalendar().week}"
                ctx.state.last_sig_ts[week_key] = float(int(ctx.state.last_sig_ts.get(week_key, 0)) + 1)

            if int(result.get("added_facts_count") or 0) > 0 and announce:
                topic_txt = ", ".join(result.get("updated_topics") or [])
                return [
                    make_event(
                        "INFO",
                        "status",
                        "Agentpedia updated",
                        detail=f"Updated: {topic_txt}" if topic_txt else "Agentpedia knowledge updated",
                        meta={"kind": "agentpedia_growth"},
                        timezone=str(ctx.settings.get("SYSTEM_TIMEZONE", "UTC")),
                    )
                ]
            return []
        except Exception as exc:
            ctx.state.last_agentpedia_error = str(exc)
            # fail-silent for UI
            return []
