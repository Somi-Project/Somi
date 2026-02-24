from __future__ import annotations


def lint_plan(plan: dict, mode: str, autonomy: bool = False) -> list[str]:
    errs: list[str] = []
    text = (
        "\n".join(plan.get("steps", []))
        if isinstance(plan.get("steps"), list)
        else str(plan)
    )
    low = text.lower()
    if mode == "safe" or autonomy:
        if any(
            x in low for x in ["execute", "run tests", "pip install", "npm install"]
        ):
            errs.append("execution is not allowed in safe/autonomy modes")
    if "bulk" in low and "targetset" not in low:
        errs.append("bulk plans must include TargetSet")
    if any(x in low for x in ["delete", "rm "]) and "typed confirm" not in low:
        errs.append("delete actions require typed confirmation")
    if "network" in low and "justification:" not in low:
        errs.append("network enablement requires justification line")
    if any(x in low for x in ["high", "critical"]) and "rollback" not in low:
        errs.append("high/critical plans must include rollback")
    return errs
