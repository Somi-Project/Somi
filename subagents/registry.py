from __future__ import annotations

from typing import Any, Iterable

from subagents.specs import SubagentProfile, SubagentRunSpec, new_subagent_run_id


DEFAULT_SUBAGENT_PROFILES: tuple[SubagentProfile, ...] = (
    SubagentProfile(
        key="research_scout",
        display_name="Research Scout",
        description="Gathers current evidence from web and research surfaces without polluting the parent turn.",
        default_allowed_tools=("web_intelligence_stack", "research_artifact_agentpedia", "browser.runtime"),
        default_max_turns=2,
        default_timeout_seconds=120,
        default_budget_tokens=4500,
        toolsets=("research", "safe-chat"),
    ),
    SubagentProfile(
        key="data_gatherer",
        display_name="Data Gatherer",
        description="Pulls structured facts from OCR, image, and lightweight evidence tools for the parent thread.",
        default_allowed_tools=("ocr_stack", "image_tooling_stack", "web_intelligence_stack", "browser.runtime"),
        default_max_turns=2,
        default_timeout_seconds=120,
        default_budget_tokens=3500,
        toolsets=("field", "research", "safe-chat"),
    ),
    SubagentProfile(
        key="coding_worker",
        display_name="Coding Worker",
        description="Handles bounded engineering tasks and only touches CLI when the parent explicitly approves and supplies an allowlist.",
        default_allowed_tools=("coding.workspace", "coding.fs", "coding.python", "coding.runtime", "coding.scaffold", "cli.exec", "browser.runtime", "browser.action"),
        default_max_turns=2,
        default_timeout_seconds=90,
        default_budget_tokens=3000,
        toolsets=("developer", "ops"),
        metadata={"requires_explicit_cli_approval": True},
    ),
)


class SubagentRegistry:
    def __init__(self, profiles: Iterable[SubagentProfile] | None = None) -> None:
        self._profiles: dict[str, SubagentProfile] = {}
        for profile in profiles or DEFAULT_SUBAGENT_PROFILES:
            self.register(profile)

    def register(self, profile: SubagentProfile) -> None:
        self._profiles[str(profile.key)] = profile

    def get(self, key: str) -> SubagentProfile | None:
        return self._profiles.get(str(key or "").strip().lower())

    def keys(self) -> list[str]:
        return sorted(self._profiles.keys())

    def list_profiles(self) -> list[dict[str, Any]]:
        return [self._profiles[key].to_dict() for key in self.keys()]

    def build_spec(
        self,
        *,
        profile_key: str,
        objective: str,
        user_id: str,
        thread_id: str,
        allowed_tools: list[str] | None = None,
        max_turns: int | None = None,
        backend: str | None = None,
        timeout_seconds: int | None = None,
        budget_tokens: int | None = None,
        parent_turn_id: int | None = None,
        parent_session_id: str = "",
        artifact_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> SubagentRunSpec:
        profile = self.get(profile_key)
        if profile is None:
            raise KeyError(f"Unknown subagent profile: {profile_key}")

        return SubagentRunSpec(
            run_id=str(run_id or new_subagent_run_id(profile.key)),
            profile_key=profile.key,
            objective=objective,
            user_id=user_id,
            thread_id=thread_id,
            allowed_tools=list(allowed_tools or profile.default_allowed_tools),
            max_turns=int(max_turns or profile.default_max_turns),
            backend=str(backend or profile.default_backend),
            timeout_seconds=int(timeout_seconds or profile.default_timeout_seconds),
            budget_tokens=int(budget_tokens or profile.default_budget_tokens),
            parent_turn_id=parent_turn_id,
            parent_session_id=str(parent_session_id or ""),
            artifact_refs=list(artifact_refs or []),
            metadata=dict(metadata or {}),
        )
