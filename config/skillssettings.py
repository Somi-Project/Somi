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
SKILLS_STATE_ROOT = "sessions/skills"
SKILLS_FORGE_ROOT = "sessions/skills/forge"
SKILLS_DRAFTS_DIR = "sessions/skills/forge/workspace"
SKILLS_FORGE_PROPOSAL_THRESHOLD = 2
SKILLS_FORGE_HISTORY_LIMIT = 40
SKILLS_RECIPE_PACKS_DIR = "workshop/skills/recipe_packs"
SKILLS_MARKETPLACE_DIR = "workshop/skills/marketplace_packages"
SKILLS_MARKETPLACE_INDEX = "workshop/skills/marketplace_index.json"
SKILLS_ROLLBACK_ROOT = "sessions/skills/rollbacks"

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

# Skill security scanning
SKILLS_SECURITY_SCAN_ENABLED = True
SKILLS_SECURITY_SCAN_MAX_FILES = 500
SKILLS_SECURITY_SCAN_MAX_FILE_BYTES = 1024 * 1024
SKILLS_SECURITY_SCAN_BLOCK_ON_SEVERITY = "critical"  # off|info|warn|critical
SKILLS_SECURITY_SCAN_MAX_FINDINGS_PER_SKILL = 25
