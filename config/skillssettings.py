from __future__ import annotations

import os
from pathlib import Path

SKILLS_ENABLED = True
SKILLS_BUNDLED_DIR = "skills"
SKILLS_WORKSPACE_DIR = "skills_local"

if os.name == "nt":
    _user_root = Path(os.environ.get("APPDATA", Path.home())) / "Somi"
else:
    _user_root = Path.home() / ".somi"

SKILLS_USER_DIR = str(_user_root / "skills")
SKILLS_EXTRA_DIRS: list[str] = []

SKILLS_ENTRIES: dict[str, dict] = {}
SKILLS_SNAPSHOT_TTL_SECONDS = 10

SKILLS_CLI_EXEC_SAFE_ALLOWLIST = [
    "python",
    "python3",
    "node",
    "npm",
    "npx",
    "git",
    "remindctl",
]
