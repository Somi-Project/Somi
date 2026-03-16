from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config.settings import CODING_SKILL_DRAFTS_ROOT


_SKILL_GAP_RULES: tuple[dict[str, Any], ...] = (
    {
        "capability": "browser automation",
        "keywords": ("playwright", "selenium", "browser automation", "login flow", "dynamic site"),
        "skill_name": "Browser Automation Draft",
        "description": "Bounded browser automation helpers for coding mode tasks.",
    },
    {
        "capability": "desktop packaging",
        "keywords": ("electron", "tauri", "desktop app", "installer", "msi"),
        "skill_name": "Desktop Packaging Draft",
        "description": "Packaging and desktop-delivery helpers for local apps.",
    },
    {
        "capability": "container orchestration",
        "keywords": ("docker", "container", "dockerfile", "compose", "kubernetes", "k8s"),
        "skill_name": "Container Ops Draft",
        "description": "Container build and orchestration helpers for coding mode.",
    },
    {
        "capability": "mobile build pipeline",
        "keywords": ("android", "ios", "react native", "flutter", "apk", "app store"),
        "skill_name": "Mobile Build Draft",
        "description": "Mobile build and packaging helpers for coding mode.",
    },
    {
        "capability": "native systems toolchain",
        "keywords": ("rust", "cargo", "c++", "cmake", "go build", "golang"),
        "skill_name": "Native Toolchain Draft",
        "description": "Native toolchain helpers for Rust, Go, and C/C++ tasks.",
    },
)


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower()).strip("._-")
    return text[:80] or "coding_skill_draft"


def detect_skill_gap(objective: str, *, profile_key: str, available_runtime_keys: set[str] | None = None) -> dict[str, Any] | None:
    text = str(objective or "").strip().lower()
    if not text:
        return None
    runtime_keys = {str(x or "").strip().lower() for x in set(available_runtime_keys or set())}

    for rule in _SKILL_GAP_RULES:
        if any(keyword in text for keyword in tuple(rule.get("keywords") or ())):
            capability = str(rule.get("capability") or "specialized capability")
            return {
                "capability": capability,
                "skill_name": str(rule.get("skill_name") or capability.title()),
                "description": str(rule.get("description") or f"Draft skill for {capability}."),
                "message": f"I can stay productive here, but a dedicated skill draft for {capability} would make this smoother.",
                "profile_key": str(profile_key or "python"),
            }

    if profile_key in {"javascript", "typescript"} and "node" not in runtime_keys:
        return {
            "capability": "node runtime enablement",
            "skill_name": "Node Runtime Enablement Draft",
            "description": "Setup notes and checks for Node-based coding workspaces.",
            "message": "This workspace is Node-oriented, but Node.js is not currently available here, so execution will stay scaffold-first until that runtime is present.",
            "profile_key": str(profile_key or "javascript"),
        }

    return None


def build_skill_gap_prompt(hint: dict[str, Any] | None) -> str:
    if not isinstance(hint, dict) or not hint:
        return ""
    if hint.get("proposal_ready") is False and not bool(hint.get("force_prompt")):
        return ""
    capability = str(hint.get("capability") or "this capability").strip()
    return f"I can scaffold a dedicated skill draft for {capability} if you want."


def draft_skill_scaffold(
    *,
    skill_name: str,
    description: str,
    capability: str,
    objective: str = "",
    root_dir: str | Path = CODING_SKILL_DRAFTS_ROOT,
) -> dict[str, Any]:
    safe_name = str(skill_name or capability or "Coding Skill Draft").strip() or "Coding Skill Draft"
    skill_key = _slugify(safe_name)
    root_path = Path(root_dir) / skill_key
    root_path.mkdir(parents=True, exist_ok=True)

    metadata = {
        "runtime": {
            "skillKey": skill_key,
            "homepage": "",
            "emoji": "wrench",
        }
    }
    skill_md = (
        "---\n"
        f"name: {safe_name}\n"
        f"description: {description.strip() or f'Draft skill for {capability}'}\n"
        "user-invocable: true\n"
        "disable-model-invocation: false\n"
        f"metadata: {json.dumps(metadata, ensure_ascii=True)}\n"
        "---\n\n"
        "# Purpose\n"
        f"- Capability: {capability}\n"
        f"- Original objective: {objective or 'TBD'}\n\n"
        "# Draft Notes\n"
        "- Define the exact workflows this skill should own.\n"
        "- Add safe dispatch/entrypoint details before enabling active execution.\n"
        "- Keep the first version bounded, local, and approval-aware.\n"
    )
    notes_md = (
        "# Skill Draft Checklist\n\n"
        "- Confirm the capability boundary.\n"
        "- Decide whether this should stay prompt-only or dispatch to a tool.\n"
        "- Add runtime requirements and install notes.\n"
        "- Add at least one concrete example invocation.\n"
    )

    created_files: list[str] = []
    skill_md_path = root_path / "SKILL.md"
    if not skill_md_path.exists():
        skill_md_path.write_text(skill_md, encoding="utf-8")
        created_files.append("SKILL.md")
    notes_path = root_path / "NOTES.md"
    if not notes_path.exists():
        notes_path.write_text(notes_md, encoding="utf-8")
        created_files.append("NOTES.md")

    return {
        "ok": True,
        "skill_key": skill_key,
        "skill_name": safe_name,
        "root_path": str(root_path.as_posix()),
        "created_files": created_files,
    }
