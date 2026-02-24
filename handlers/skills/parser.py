from __future__ import annotations

import json
import re
from pathlib import Path

from .types import SkillDoc


class SkillParseError(ValueError):
    pass


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _fix_trailing_commas(payload: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", payload)


def expand_vars(text: str, base_dir: str, workspace_dir: str = ".") -> str:
    expanded = str(text or "")
    expanded = expanded.replace("{baseDir}", str(base_dir))
    expanded = expanded.replace("{workspaceDir}", str(workspace_dir))
    return expanded


def parse_skill_md(skill_dir: Path) -> SkillDoc:
    skill_md = Path(skill_dir) / "SKILL.md"
    warnings: list[str] = []
    if not skill_md.exists():
        raise FileNotFoundError(f"Missing SKILL.md in {skill_dir}")

    raw = skill_md.read_text(encoding="utf-8")
    frontmatter: dict[str, str] = {}
    body_md = raw

    if raw.startswith("---"):
        lines = raw.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is not None:
            for line in lines[1:end_idx]:
                if not line.strip() or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
            body_md = "\n".join(lines[end_idx + 1 :]).strip()
        else:
            warnings.append("Frontmatter delimiter not closed; treating entire file as body")

    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()
    if not name or not description:
        missing = []
        if not name:
            missing.append("name")
        if not description:
            missing.append("description")
        raise SkillParseError(f"Missing required frontmatter key(s): {', '.join(missing)}")

    metadata: dict = {}
    metadata_raw = frontmatter.get("metadata", "{}").strip()
    if metadata_raw:
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            try:
                metadata = json.loads(_fix_trailing_commas(metadata_raw))
                warnings.append("metadata JSON had trailing commas and was auto-fixed")
            except json.JSONDecodeError as exc:
                metadata = {}
                warnings.append(f"metadata JSON parse failed: {exc}")

    openclaw = metadata.get("openclaw", {}) if isinstance(metadata, dict) else {}
    skill_key = str(openclaw.get("skillKey") or name)
    homepage = frontmatter.get("homepage") or openclaw.get("homepage")
    emoji = openclaw.get("emoji")

    return SkillDoc(
        name=name,
        description=description,
        homepage=str(homepage) if homepage else None,
        emoji=str(emoji) if emoji else None,
        skill_key=skill_key,
        base_dir=str(Path(skill_dir).resolve()),
        frontmatter=frontmatter,
        metadata=metadata if isinstance(metadata, dict) else {},
        openclaw=openclaw if isinstance(openclaw, dict) else {},
        body_md=body_md,
        user_invocable=_parse_bool(frontmatter.get("user-invocable"), True),
        disable_model_invocation=_parse_bool(frontmatter.get("disable-model-invocation"), False),
        command_dispatch=frontmatter.get("command-dispatch"),
        command_tool=frontmatter.get("command-tool"),
        command_arg_mode=frontmatter.get("command-arg-mode"),
        parse_warnings=warnings,
    )
