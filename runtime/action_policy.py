from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.autonomy_profiles import evaluate_autonomy_request
from runtime.security_guard import (
    normalize_delivery_channel,
    normalize_execution_backend,
    normalize_risk_tier,
    risk_exceeds,
    tool_allows_backend,
    tool_allows_channel,
)


ACTION_CLASSES = {
    "read",
    "write",
    "destructive",
    "financial",
    "external_message",
    "system_change",
    "plugin_exec",
}


def _text_set(values: list[Any] | tuple[Any, ...] | set[Any] | None) -> set[str]:
    return {str(item or "").strip().lower() for item in list(values or []) if str(item or "").strip()}


def classify_action_class(tool_name: str, entry: dict[str, Any] | None = None) -> str:
    name = str(tool_name or "").strip().lower()
    entry = dict(entry or {})
    policy = dict(entry.get("policy") or {})
    capabilities = _text_set(entry.get("capabilities"))
    toolsets = _text_set(entry.get("toolsets"))
    tags = _text_set(entry.get("tags"))
    merged = capabilities | toolsets | tags

    if any(token in name for token in ("delete", "destroy", "wipe", "purge", "remove")):
        return "destructive"
    if any(token in merged for token in ("financial", "billing", "payments", "commerce", "purchase")):
        return "financial"
    if any(token in name for token in ("payment", "billing", "purchase", "checkout")):
        return "financial"
    if any(token in merged for token in ("plugin", "skill", "extension", "marketplace")):
        if any(token in name for token in ("install", "enable", "disable", "update", "import", "execute", "run")):
            return "plugin_exec"
    if any(
        token in name
        for token in (
            "email.send",
            "mail.send",
            "message.send",
            "telegram.send",
            "discord.send",
            "sms.send",
            "post",
            "publish",
            "tweet",
            "upload",
            "push",
        )
    ):
        return "external_message"
    if any(token in merged for token in ("messaging", "social", "publish", "upload")):
        return "external_message"
    if any(token in name for token in ("cli.exec", "shell", "exec", "install", "service", "system", "git.push", "git.commit")):
        return "system_change"
    if any(token in merged for token in ("execute", "shell", "system", "admin", "install")):
        return "system_change"
    if bool(policy.get("mutates_state", False)) or not bool(policy.get("read_only", True)):
        return "write"
    return "read"


def confirmation_requirement_for(action_class: str, risk_tier: str) -> str:
    action = str(action_class or "read").strip().lower()
    tier = normalize_risk_tier(risk_tier)
    if action in {"financial", "destructive"} or tier == "CRITICAL":
        return "typed_phrase"
    if action in {"external_message", "system_change", "plugin_exec"} or tier == "HIGH":
        return "typed"
    if action == "write" or tier == "MEDIUM":
        return "double_confirm"
    return "single_click"


@dataclass(frozen=True)
class ActionPolicyDecision:
    allowed: bool
    blocked_reason: str
    approval_required: bool
    confirmation_requirement: str
    action_class: str
    risk_tier: str
    max_risk_tier: str
    approved: bool
    read_only: bool
    mutates_state: bool
    requires_approval: bool
    preview_required: bool
    rollback_advised: bool
    backend: str
    channel: str
    background_task: bool
    autonomy_profile: str
    autonomy_check: dict[str, Any]
    availability: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "blocked_reason": str(self.blocked_reason or ""),
            "approval_required": bool(self.approval_required),
            "confirmation_requirement": str(self.confirmation_requirement or "single_click"),
            "action_class": str(self.action_class or "read"),
            "risk_tier": str(self.risk_tier or "LOW"),
            "max_risk_tier": str(self.max_risk_tier or "CRITICAL"),
            "approved": bool(self.approved),
            "read_only": bool(self.read_only),
            "mutates_state": bool(self.mutates_state),
            "requires_approval": bool(self.requires_approval),
            "preview_required": bool(self.preview_required),
            "rollback_advised": bool(self.rollback_advised),
            "backend": str(self.backend or "local"),
            "channel": str(self.channel or "chat"),
            "background_task": bool(self.background_task),
            "autonomy_profile": str(self.autonomy_profile or "balanced"),
            "autonomy_check": dict(self.autonomy_check or {}),
            "availability": dict(self.availability or {"ok": True, "issues": []}),
        }


def evaluate_action_policy(
    *,
    tool_name: str,
    entry: dict[str, Any] | None,
    runtime_ctx: dict[str, Any] | None = None,
    availability: dict[str, Any] | None = None,
) -> ActionPolicyDecision:
    runtime_ctx = dict(runtime_ctx or {})
    entry = dict(entry or {})
    policy = dict(entry.get("policy") or {})
    availability = dict(availability or {"ok": True, "issues": []})

    read_only = bool(policy.get("read_only", False))
    mutates_state = bool(policy.get("mutates_state", not read_only))
    requires_approval = bool(policy.get("requires_approval", False))
    risk_tier = normalize_risk_tier(policy.get("risk_tier", "LOW"))
    max_risk_tier = normalize_risk_tier(runtime_ctx.get("max_risk_tier", "CRITICAL"))
    approved = bool(runtime_ctx.get("approved", False))
    backend = normalize_execution_backend(runtime_ctx.get("backend") or runtime_ctx.get("execution_backend") or "local")
    channel = normalize_delivery_channel(runtime_ctx.get("channel") or runtime_ctx.get("delivery_channel") or runtime_ctx.get("source") or "chat")
    requested_mode = str(runtime_ctx.get("operation_mode") or "").strip().lower()
    background_task = bool(runtime_ctx.get("background_task", False))
    action_class = classify_action_class(tool_name, entry=entry)
    autonomy_profile = str(runtime_ctx.get("autonomy_profile") or runtime_ctx.get("active_autonomy_profile") or "balanced").strip().lower() or "balanced"
    explicit_external_effect = bool(runtime_ctx.get("external_effect", False))

    autonomy_check = evaluate_autonomy_request(
        autonomy_profile,
        risk_tier=risk_tier,
        mutates_state=mutates_state,
        external_effect=explicit_external_effect,
        background_task=background_task,
        step_index=int(runtime_ctx.get("autonomy_step_index") or runtime_ctx.get("step_index") or 0),
        elapsed_seconds=int(runtime_ctx.get("autonomy_elapsed_seconds") or runtime_ctx.get("elapsed_seconds") or 0),
        retry_count=int(runtime_ctx.get("autonomy_retry_count") or runtime_ctx.get("retry_count") or 0),
        load_level=str(runtime_ctx.get("load_level") or runtime_ctx.get("runtime_load_level") or "normal"),
        requested_parallel_tools=int(runtime_ctx.get("requested_parallel_tools") or runtime_ctx.get("parallel_tools") or 1),
    )

    blocked_reason = ""
    if not bool(availability.get("ok", True)):
        issues = ", ".join(str(item) for item in list(availability.get("issues") or [])[:4])
        blocked_reason = f"unavailable:{issues or 'unknown'}"
    elif not tool_allows_backend(entry, backend):
        blocked_reason = f"backend:{backend}"
    elif not tool_allows_channel(entry, channel):
        blocked_reason = f"channel:{channel}"
    elif risk_exceeds(risk_tier, max_risk_tier):
        blocked_reason = f"risk:{risk_tier}>{max_risk_tier}"
    elif read_only and requested_mode in {"write", "mutate", "delete", "execute"}:
        blocked_reason = f"mode:{requested_mode}"
    elif not bool(autonomy_check.get("allowed", True)):
        reasons = list(autonomy_check.get("reasons") or [])
        blocked_reason = str(reasons[0] if reasons else "autonomy_blocked")

    confirmation_requirement = confirmation_requirement_for(action_class, risk_tier)
    preview_required = action_class in {"write", "destructive", "financial", "external_message", "system_change", "plugin_exec"} or mutates_state
    rollback_advised = action_class in {"write", "destructive", "system_change", "plugin_exec"} or mutates_state
    approval_required = bool(requires_approval or autonomy_check.get("requires_confirmation", False))
    if action_class in {"destructive", "financial", "external_message", "system_change", "plugin_exec"}:
        approval_required = True

    if not blocked_reason and approval_required and not approved:
        blocked_reason = "approval_required"

    return ActionPolicyDecision(
        allowed=not bool(blocked_reason),
        blocked_reason=str(blocked_reason or ""),
        approval_required=bool(approval_required),
        confirmation_requirement=confirmation_requirement,
        action_class=action_class if action_class in ACTION_CLASSES else "read",
        risk_tier=risk_tier,
        max_risk_tier=max_risk_tier,
        approved=approved,
        read_only=read_only,
        mutates_state=mutates_state,
        requires_approval=requires_approval,
        preview_required=preview_required,
        rollback_advised=rollback_advised,
        backend=backend,
        channel=channel,
        background_task=background_task,
        autonomy_profile=autonomy_profile,
        autonomy_check=dict(autonomy_check or {}),
        availability=availability,
    )
