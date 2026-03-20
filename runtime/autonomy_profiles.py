from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_LOAD_ORDER = {"normal": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class AutonomyProfile:
    profile_id: str
    display_name: str
    description: str
    max_risk_tier: str
    max_auto_steps: int
    max_elapsed_seconds: int
    max_retry_count: int
    max_parallel_tools: int
    confirm_on_mutation: bool
    allow_background_tasks: bool
    allow_external_effects: bool
    background_load_ceiling: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "description": self.description,
            "max_risk_tier": self.max_risk_tier,
            "max_auto_steps": self.max_auto_steps,
            "max_elapsed_seconds": self.max_elapsed_seconds,
            "max_retry_count": self.max_retry_count,
            "max_parallel_tools": self.max_parallel_tools,
            "confirm_on_mutation": self.confirm_on_mutation,
            "allow_background_tasks": self.allow_background_tasks,
            "allow_external_effects": self.allow_external_effects,
            "background_load_ceiling": self.background_load_ceiling,
        }


DEFAULT_AUTONOMY_PROFILES: tuple[AutonomyProfile, ...] = (
    AutonomyProfile(
        profile_id="ask_first",
        display_name="Ask First",
        description="Always confirm before mutating local state or starting background work.",
        max_risk_tier="LOW",
        max_auto_steps=1,
        max_elapsed_seconds=120,
        max_retry_count=0,
        max_parallel_tools=1,
        confirm_on_mutation=True,
        allow_background_tasks=False,
        allow_external_effects=False,
        background_load_ceiling="normal",
    ),
    AutonomyProfile(
        profile_id="balanced",
        display_name="Balanced",
        description="Allow bounded local research and background work, but still confirm before meaningful mutations.",
        max_risk_tier="MEDIUM",
        max_auto_steps=4,
        max_elapsed_seconds=600,
        max_retry_count=1,
        max_parallel_tools=2,
        confirm_on_mutation=True,
        allow_background_tasks=True,
        allow_external_effects=False,
        background_load_ceiling="high",
    ),
    AutonomyProfile(
        profile_id="hands_off_safe",
        display_name="Hands-Off Safe",
        description="Let Somi handle low-risk local steps and background work autonomously while still blocking external consequences.",
        max_risk_tier="LOW",
        max_auto_steps=6,
        max_elapsed_seconds=900,
        max_retry_count=2,
        max_parallel_tools=2,
        confirm_on_mutation=False,
        allow_background_tasks=True,
        allow_external_effects=False,
        background_load_ceiling="medium",
    ),
)


def list_autonomy_profiles() -> list[AutonomyProfile]:
    return list(DEFAULT_AUTONOMY_PROFILES)


def get_autonomy_profile(profile_id: str) -> AutonomyProfile | None:
    target = str(profile_id or "").strip().lower()
    for profile in DEFAULT_AUTONOMY_PROFILES:
        if profile.profile_id == target:
            return profile
    return None


def _risk_allowed(profile: AutonomyProfile, risk_tier: str) -> bool:
    requested = _RISK_ORDER.get(str(risk_tier or "LOW").strip().upper(), 1)
    allowed = _RISK_ORDER.get(str(profile.max_risk_tier or "LOW").strip().upper(), 1)
    return requested <= allowed


def _load_exceeds(ceiling: str, load_level: str) -> bool:
    requested = _LOAD_ORDER.get(str(load_level or "normal").strip().lower(), 1)
    allowed = _LOAD_ORDER.get(str(ceiling or "normal").strip().lower(), 1)
    return requested > allowed


def build_autonomy_budget(profile: AutonomyProfile | dict[str, Any] | str, *, load_level: str = "normal") -> dict[str, Any]:
    if isinstance(profile, AutonomyProfile):
        selected = profile
    elif isinstance(profile, dict):
        selected = AutonomyProfile(
            profile_id=str(profile.get("profile_id") or "profile"),
            display_name=str(profile.get("display_name") or profile.get("profile_id") or "Profile"),
            description=str(profile.get("description") or ""),
            max_risk_tier=str(profile.get("max_risk_tier") or "LOW"),
            max_auto_steps=int(profile.get("max_auto_steps") or 1),
            max_elapsed_seconds=int(profile.get("max_elapsed_seconds") or 120),
            max_retry_count=int(profile.get("max_retry_count") or 0),
            max_parallel_tools=int(profile.get("max_parallel_tools") or 1),
            confirm_on_mutation=bool(profile.get("confirm_on_mutation", True)),
            allow_background_tasks=bool(profile.get("allow_background_tasks", False)),
            allow_external_effects=bool(profile.get("allow_external_effects", False)),
            background_load_ceiling=str(profile.get("background_load_ceiling") or "normal"),
        )
    else:
        selected = get_autonomy_profile(str(profile or "")) or get_autonomy_profile("ask_first")  # type: ignore[assignment]

    level = str(load_level or "normal").strip().lower() or "normal"
    step_budget = int(selected.max_auto_steps)
    elapsed_budget = int(selected.max_elapsed_seconds)
    retry_budget = int(selected.max_retry_count)
    parallel_budget = int(selected.max_parallel_tools)
    if level == "critical":
        step_budget = min(step_budget, 1)
        elapsed_budget = min(elapsed_budget, 90)
        parallel_budget = 1
    elif level == "high":
        step_budget = min(step_budget, max(1, step_budget - 1))
        elapsed_budget = min(elapsed_budget, max(120, int(selected.max_elapsed_seconds * 0.75)))
        parallel_budget = min(parallel_budget, 1)
    elif level == "medium":
        elapsed_budget = min(elapsed_budget, max(120, int(selected.max_elapsed_seconds * 0.9)))
        parallel_budget = min(parallel_budget, max(1, selected.max_parallel_tools))
    return {
        "profile_id": selected.profile_id,
        "load_level": level,
        "max_auto_steps": max(1, step_budget),
        "max_elapsed_seconds": max(60, elapsed_budget),
        "max_retry_count": max(0, retry_budget),
        "max_parallel_tools": max(1, parallel_budget),
        "background_load_ceiling": str(selected.background_load_ceiling or "normal"),
    }


def evaluate_autonomy_request(
    profile: AutonomyProfile | dict[str, Any] | str,
    *,
    risk_tier: str = "LOW",
    mutates_state: bool = False,
    external_effect: bool = False,
    background_task: bool = False,
    step_index: int = 0,
    elapsed_seconds: int = 0,
    retry_count: int = 0,
    load_level: str = "normal",
    requested_parallel_tools: int = 1,
) -> dict[str, Any]:
    if isinstance(profile, AutonomyProfile):
        selected = profile
    elif isinstance(profile, dict):
        selected = AutonomyProfile(
            profile_id=str(profile.get("profile_id") or "profile"),
            display_name=str(profile.get("display_name") or profile.get("profile_id") or "Profile"),
            description=str(profile.get("description") or ""),
            max_risk_tier=str(profile.get("max_risk_tier") or "LOW"),
            max_auto_steps=int(profile.get("max_auto_steps") or 1),
            max_elapsed_seconds=int(profile.get("max_elapsed_seconds") or 120),
            max_retry_count=int(profile.get("max_retry_count") or 0),
            max_parallel_tools=int(profile.get("max_parallel_tools") or 1),
            confirm_on_mutation=bool(profile.get("confirm_on_mutation", True)),
            allow_background_tasks=bool(profile.get("allow_background_tasks", False)),
            allow_external_effects=bool(profile.get("allow_external_effects", False)),
            background_load_ceiling=str(profile.get("background_load_ceiling") or "normal"),
        )
    else:
        selected = get_autonomy_profile(str(profile or "")) or get_autonomy_profile("ask_first")  # type: ignore[assignment]

    reasons: list[str] = []
    allowed = True
    requires_confirmation = False
    budget = build_autonomy_budget(selected, load_level=load_level)

    if not _risk_allowed(selected, risk_tier):
        allowed = False
        reasons.append(f"risk_tier_exceeds_profile:{str(risk_tier or 'LOW').upper()}")
    if external_effect and not bool(selected.allow_external_effects):
        allowed = False
        reasons.append("external_effect_blocked")
    if background_task and not bool(selected.allow_background_tasks):
        requires_confirmation = True
        reasons.append("background_task_requires_confirmation")
    if int(step_index or 0) >= int(budget.get("max_auto_steps") or 1):
        allowed = False
        reasons.append("step_budget_exhausted")
    if int(elapsed_seconds or 0) > int(budget.get("max_elapsed_seconds") or 120):
        allowed = False
        reasons.append("time_budget_exhausted")
    if int(retry_count or 0) > int(budget.get("max_retry_count") or 0):
        allowed = False
        reasons.append("retry_budget_exhausted")
    if int(requested_parallel_tools or 1) > int(budget.get("max_parallel_tools") or 1):
        allowed = False
        reasons.append("parallel_budget_exhausted")
    if background_task and _load_exceeds(str(budget.get("background_load_ceiling") or "normal"), load_level):
        if str(load_level or "").strip().lower() == "critical":
            allowed = False
            reasons.append("background_load_blocked")
        else:
            requires_confirmation = True
            reasons.append("background_load_requires_confirmation")
    if mutates_state and bool(selected.confirm_on_mutation):
        requires_confirmation = True
        reasons.append("mutation_requires_confirmation")
    if not allowed:
        requires_confirmation = False

    return {
        "profile": selected.to_dict(),
        "allowed": bool(allowed),
        "requires_confirmation": bool(requires_confirmation),
        "reasons": reasons,
        "budget": budget,
    }
