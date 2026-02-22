from __future__ import annotations


def _on_off(v: bool) -> str:
    return "ON" if bool(v) else "OFF"


def build_policy_pack(settings) -> str:
    lines = [
        f"prompt_arch_version={getattr(settings, 'PROMPT_ARCH_VERSION', 'legacy')}",
        f"mode_gate={_on_off(getattr(settings, 'PROMPT_MODE_GATE_ENABLED', False))}",
        f"firewall={_on_off(getattr(settings, 'PROMPT_FIREWALL_ENABLED', False))}",
        f"action_protocol={_on_off(getattr(settings, 'PROMPT_ACTION_PROTOCOL_ENABLED', False))}",
        f"block_budgets={_on_off(getattr(settings, 'PROMPT_BLOCK_BUDGETS_ENABLED', False))}",
        f"snapshot_log={_on_off(getattr(settings, 'PROMPT_SNAPSHOT_LOG_ENABLED', False))}",
        "memory_write_posture=conservative",
    ]
    return "\n".join(lines)
