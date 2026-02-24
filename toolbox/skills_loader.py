from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from config import toolboxsettings as tbs


@dataclass
class SkillSpec:
    name: str
    version: str
    description: str
    capabilities_required: list[str]
    risk_notes: str
    inputs_schema: dict
    outputs_schema: dict
    example_calls: list[str]
    safe_mode_behavior: str
    body: str
    file_hash: str


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        raise ValueError("skills.md requires frontmatter")
    lines = raw.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("skills.md frontmatter not closed")
    meta = {}
    for line in lines[1:end]:
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, "\n".join(lines[end + 1 :]).strip()


def load_skill_spec(path: str | Path) -> SkillSpec:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    required = [
        x.strip()
        for x in str(meta.get("capabilities_required", "")).split(",")
        if x.strip()
    ]
    if (
        tbs.TOOLBOX_MODE == "safe"
        and str(meta.get("safe_mode_behavior", "")).strip().lower() != "patch-only"
    ):
        raise ValueError("SAFE mode skills must declare safe_mode_behavior: patch-only")
    if any(x in {"external_apps", "system_wide"} for x in required):
        if not tbs.ALLOW_EXTERNAL_APPS or not tbs.ALLOW_SYSTEM_WIDE_ACTIONS:
            raise ValueError(
                "Skill requires capabilities above current toolbox settings"
            )

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return SkillSpec(
        name=meta["name"],
        version=meta["version"],
        description=meta["description"],
        capabilities_required=required,
        risk_notes=meta.get("risk_notes", ""),
        inputs_schema=json.loads(meta.get("inputs", "{}")),
        outputs_schema=json.loads(meta.get("outputs", "{}")),
        example_calls=[
            x.strip()
            for x in str(meta.get("example_calls", "")).split(";")
            if x.strip()
        ],
        safe_mode_behavior=meta.get("safe_mode_behavior", ""),
        body=body,
        file_hash=digest,
    )


class SkillsRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        self._items[f"{spec.name}@{spec.version}"] = spec

    def get(self, ref: str) -> SkillSpec | None:
        return self._items.get(ref)
