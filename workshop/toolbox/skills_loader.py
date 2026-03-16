from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from config import toolboxsettings as tbs


@dataclass
class SkillSpec:
    name: str
    version: str
    input_schema: str
    output_schema: str
    required_capabilities: list[str]
    safe_mode_behavior: str
    risk_notes: str
    path: str


REQUIRED_KEYS = {
    "name",
    "version",
    "input schema",
    "output schema",
    "required capabilities",
    "safe mode behavior",
    "risk notes",
}

FORBIDDEN_CAPS_BY_DEFAULT = {"external_apps", "system_wide", "network", "delete"}


def _parse_skills_md(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip().lower()] = v.strip()
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"skills.md missing required metadata: {', '.join(missing)}")
    return data


def _validate_tool_contract(tool_py: Path) -> None:
    source = tool_py.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            args = [a.arg for a in node.args.args]
            if len(args) >= 2 and args[0] == "args" and args[1] == "ctx":
                return
    raise ValueError("tool must implement run(args, ctx)")


def load_skill(path: str | Path) -> SkillSpec:
    root = Path(path)
    meta = _parse_skills_md(root / "skills.md")
    required_caps = [x.strip() for x in meta["required capabilities"].split(",") if x.strip()]

    mode = tbs.normalized_mode()
    if mode == tbs.MODE_SAFE and meta["safe mode behavior"].lower() not in {"plan-only", "patch-only"}:
        raise ValueError("SAFE mode only permits plan/patch-only skills")

    for cap in required_caps:
        if cap in FORBIDDEN_CAPS_BY_DEFAULT:
            allow = {
                "external_apps": tbs.ALLOW_EXTERNAL_APPS,
                "system_wide": tbs.ALLOW_SYSTEM_WIDE_ACTIONS,
                "network": tbs.ALLOW_NETWORK,
                "delete": tbs.ALLOW_DELETE_ACTIONS,
            }[cap]
            if not allow:
                raise ValueError(f"Skill rejected due to forbidden capability: {cap}")

    _validate_tool_contract(root / "tool.py")
    return SkillSpec(
        name=meta["name"],
        version=meta["version"],
        input_schema=meta["input schema"],
        output_schema=meta["output schema"],
        required_capabilities=required_caps,
        safe_mode_behavior=meta["safe mode behavior"],
        risk_notes=meta["risk notes"],
        path=str(root),
    )


def register_verified_skills(skills_root: str | Path) -> list[SkillSpec]:
    root = Path(skills_root)
    registered: list[SkillSpec] = []
    for candidate in root.iterdir() if root.exists() else []:
        if not candidate.is_dir() or not (candidate / "skills.md").exists():
            continue
        registered.append(load_skill(candidate))
    return registered
