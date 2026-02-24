from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillDoc:
    name: str
    description: str
    homepage: str | None
    emoji: str | None
    skill_key: str
    base_dir: str
    frontmatter: dict[str, str]
    metadata: dict[str, Any]
    openclaw: dict[str, Any]
    body_md: str
    user_invocable: bool = True
    disable_model_invocation: bool = False
    command_dispatch: str | None = None
    command_tool: str | None = None
    command_arg_mode: str | None = None
    parse_warnings: list[str] = field(default_factory=list)
