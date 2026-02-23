from __future__ import annotations

import json
import shutil
from pathlib import Path

from runtime.capabilities import CAP_TOOL_INSTALL, require_cap
from runtime.hashing import sha256_file
from runtime.journal import Journal
from runtime.privilege import PrivilegeLevel, require_privilege
from toolbox.registry import ToolRegistry


class ToolInstaller:
    def __init__(self, registry: ToolRegistry | None = None, journal: Journal | None = None) -> None:
        self.registry = registry or ToolRegistry()
        self.journal = journal or Journal(Path("tools/install.journal.jsonl"))

    def install(self, src_dir: str, name: str, version: str, ctx, job_id: str = "job") -> dict:
        require_cap(ctx, CAP_TOOL_INSTALL)
        require_privilege(ctx, PrivilegeLevel.ACTIVE)

        src = Path(src_dir)
        staging = Path("tools/.staging") / job_id / name / version
        final = Path("tools/installed") / name / version

        if staging.exists():
            shutil.rmtree(staging)
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, staging, dirs_exist_ok=True)

        manifest_path = staging / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

        hashes = {}
        for rel in ["manifest.json", "tool.py", "README.md", "test_tool.py"]:
            p = staging / rel
            if p.exists():
                hashes[rel] = sha256_file(p)

        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(staging), str(final))

        entry = {
            "name": name,
            "version": version,
            "path": str(final),
            "hashes": hashes,
            "enabled": True,
            "aliases": manifest.get("aliases", []),
            "examples": manifest.get("examples", []),
            "tags": manifest.get("tags", []),
            "input_schema": manifest.get("input_schema", {}),
        }
        self.registry.register(entry)
        self.journal.append("tool.install", "Installed tool", {"name": name, "version": version, "path": str(final)})
        return entry
