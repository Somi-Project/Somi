from __future__ import annotations


def lint_plan(plan: dict, mode: str, autonomy: bool = False) -> list[str]:
    errs: list[str] = []
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    text = "\n".join(steps) if isinstance(steps, list) else str(plan)
    low = text.lower()
    mode_up = str(mode).upper()

    if mode_up == "SAFE" or autonomy:
        if any(x in low for x in ["execute", "run", "install", "apply now"]):
            errs.append("attempts execution in SAFE/autonomy mode")
    if any(x in low for x in ["high risk", "critical", "delete", "system-wide"]) and "rollback" not in low:
        errs.append("high-risk plans must include rollback")
    if "bulk" in low and not all(x in low for x in ["criteria", "sample", "dry run", "checkpoint"]):
        errs.append("bulk actions require safeguards (criteria/sample/dry-run/checkpoint)")
    if "network" in low and "justification" not in low:
        errs.append("network enablement requires justification")
    return errs
