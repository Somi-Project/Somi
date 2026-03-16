from __future__ import annotations

import json
import re
from typing import Any


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower()).strip("._-")
    return text[:80] or "skill_draft"


def choose_template(*, dispatch_mode: str = "", capability: str = "", dependencies: dict[str, Any] | None = None) -> str:
    mode = str(dispatch_mode or "").strip().lower()
    deps = dict(dependencies or {})
    if mode == "cli" or list(deps.get("executables") or []):
        return "cli_bridge"
    if mode == "tool" or str(deps.get("tool_name") or "").strip():
        return "tool_bridge"
    if "automation" in str(capability or "").lower() or "browser" in str(capability or "").lower():
        return "tool_bridge"
    return "prompt_only"


def build_template_files(
    *,
    skill_name: str,
    skill_key: str,
    description: str,
    capability: str,
    objective: str,
    template_id: str,
    dependencies: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, str]:
    deps = dict(dependencies or {})
    dispatch_payload = dict(dispatch or {})
    metadata = {
        "runtime": {
            "skillKey": skill_key,
            "emoji": "wrench",
            "homepage": "",
            "requires": {
                "bins": list(deps.get("executables") or []),
                "env": list(deps.get("env") or []),
            },
        },
        "forge": {
            "template": template_id,
            "capability": capability,
            "objective": objective,
        },
    }
    frontmatter = [
        "---",
        f"name: {skill_name}",
        f"description: {description}",
        "user-invocable: true",
        "disable-model-invocation: false",
    ]
    if template_id == "tool_bridge":
        frontmatter.extend(
            [
                "command-dispatch: tool",
                f"command-tool: {dispatch_payload.get('tool_name') or 'tool.name'}",
                "command-arg-mode: raw",
            ]
        )
    elif template_id == "cli_bridge":
        frontmatter.extend(
            [
                "command-dispatch: cli",
                "command-arg-mode: argv",
            ]
        )
    frontmatter.append(f"metadata: {json.dumps(metadata, ensure_ascii=True)}")
    frontmatter.append("---")

    body_lines = [
        "",
        "# Purpose",
        f"- Capability: {capability}",
        f"- Original objective: {objective or 'TBD'}",
        f"- Template: {template_id}",
        "",
        "# Operating Rules",
        "- Stay local-first and approval-aware.",
        "- Prefer bounded actions over broad automation.",
        "- Document assumptions before invoking external tools or CLIs.",
        "",
        "# Examples",
        f"- Example request: {objective or f'Help with {capability}'}",
    ]
    if template_id == "tool_bridge":
        body_lines.append(f"- Dispatch target: {dispatch_payload.get('tool_name') or 'tool.name'}")
    elif template_id == "cli_bridge":
        body_lines.append(f"- Expected executable: {', '.join(list(deps.get('executables') or [])[:3]) or 'python'}")
    else:
        body_lines.append("- This draft starts as prompt-only and can be upgraded later.")

    manifest = {
        "skill_key": skill_key,
        "name": skill_name,
        "template": template_id,
        "capability": capability,
        "description": description,
        "dependencies": {
            "python_modules": list(deps.get("python_modules") or []),
            "executables": list(deps.get("executables") or []),
            "env": list(deps.get("env") or []),
        },
        "dispatch": {
            "mode": dispatch_payload.get("mode") or template_id.replace("_bridge", ""),
            "tool_name": dispatch_payload.get("tool_name") or "",
            "command_preview": dispatch_payload.get("command_preview") or "",
        },
        "provenance": dict(provenance or {}),
        "status": "draft",
    }
    regression = {
        "checks": [
            {"id": "skill_parse", "type": "skill_parse"},
            {"id": "security_scan", "type": "security_scan"},
            {"id": "manifest_consistency", "type": "manifest_consistency"},
        ]
    }
    changelog = (
        "# Change History\n\n"
        "- Draft created by Somi Skill Forge.\n"
        "- Use `/skill review <draft_id>` before approval.\n"
    )
    notes = (
        "# Review Notes\n\n"
        "- Confirm the capability boundary.\n"
        "- Add or trim dependencies before approval.\n"
        "- Keep consumer-hardware constraints in mind.\n"
    )
    return {
        "SKILL.md": "\n".join(frontmatter + body_lines).strip() + "\n",
        "skill_manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        "regression_checks.json": json.dumps(regression, indent=2, ensure_ascii=False) + "\n",
        "CHANGELOG.md": changelog,
        "NOTES.md": notes,
    }


__all__ = ["build_template_files", "choose_template", "_slug"]
