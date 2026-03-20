from __future__ import annotations

from pathlib import Path
from typing import Any


_HIGH_RISK_NAMES = {"pyproject.toml", "package.json", "requirements.txt", "setup.py", "poetry.lock", "package-lock.json"}
_CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def score_edit_risk(
    *,
    relative_path: str,
    preview: dict[str, Any] | None = None,
    repo_map: dict[str, Any] | None = None,
    mode: str = "overwrite",
) -> dict[str, Any]:
    rel = str(relative_path or "").replace("\\", "/").strip()
    repo = dict(repo_map or {})
    preview_payload = dict(preview or {})
    file_name = Path(rel).name.lower()
    suffix = Path(rel).suffix.lower()
    score = 12
    reasons: list[str] = []

    if not bool(preview_payload.get("exists")):
        score += 8
        reasons.append("new_file")
    if str(mode or "overwrite").strip().lower() == "overwrite":
        score += 8
        reasons.append("full_overwrite")
    if abs(int(preview_payload.get("delta_chars") or 0)) >= 1200:
        score += 16
        reasons.append("large_delta")
    if bool(preview_payload.get("requires_preview")):
        score += 10
        reasons.append("large_preview")
    if file_name in _HIGH_RISK_NAMES:
        score += 35
        reasons.append("dependency_manifest")
    elif suffix in _CONFIG_SUFFIXES:
        score += 18
        reasons.append("config_file")
    if rel in {str(item) for item in list(repo.get("entrypoints") or [])}:
        score += 20
        reasons.append("entrypoint")
    if any(str(row.get("path") or "") == rel for row in list(repo.get("hotspot_files") or []) if isinstance(row, dict)):
        score += 14
        reasons.append("hotspot")
    if "/tests/" in f"/{rel.lower()}/" or Path(rel).name.startswith("test_"):
        score = max(8, score - 8)
        reasons.append("test_only")

    score = max(0, min(100, score))
    level = _risk_level(score)
    return {
        "path": rel,
        "risk_score": score,
        "risk_level": level,
        "reasons": reasons,
        "verify_required": level in {"medium", "high", "critical"},
        "rollback_advised": level in {"high", "critical"},
        "publish_requires_confirmation": bool(
            level in {"high", "critical"} or "dependency_manifest" in reasons or "config_file" in reasons
        ),
    }


def build_change_plan(
    *,
    objective: str,
    repo_map: dict[str, Any] | None = None,
    relative_paths: list[str] | None = None,
    verify_command: str = "",
    run_command: str = "",
) -> dict[str, Any]:
    repo = dict(repo_map or {})
    targets = [str(item).strip() for item in list(relative_paths or []) if str(item).strip()]
    if not targets:
        targets = [str(item).strip() for item in list(repo.get("focus_files") or []) if str(item).strip()]
    targets = targets[:5]

    symbol_lookup = {
        str(row.get("path") or ""): [str(item).strip() for item in list(row.get("symbols") or []) if str(item).strip()]
        for row in list(repo.get("focus_symbols") or [])
        if isinstance(row, dict)
    }
    focus_symbols = [{"path": path, "symbols": symbol_lookup.get(path, [])[:4]} for path in targets if symbol_lookup.get(path)]

    steps = [f"Inspect {' and '.join(targets[:2]) or 'the current focus files'} before patching."]
    if targets:
        steps.append(f"Apply bounded edits to {', '.join(targets[:3])}.")
    if verify_command:
        steps.append(f"Run verification: {verify_command}.")
    elif run_command:
        steps.append(f"Smoke-check with: {run_command}.")
    steps.append("Review the diff, summarize the change, and capture rollback if risk is elevated.")

    return {
        "objective": str(objective or "").strip(),
        "targets": targets,
        "focus_symbols": focus_symbols,
        "steps": steps,
        "verify_command": str(verify_command or "").strip(),
        "run_command": str(run_command or "").strip(),
        "summary": " | ".join(
            [
                f"targets={', '.join(targets[:3])}" if targets else "targets=repo focus",
                f"verify={verify_command}" if verify_command else ("run=" + run_command if run_command else ""),
                "bounded patch loop",
            ]
        ).strip(" |"),
    }
