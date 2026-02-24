from __future__ import annotations

import json
import re
from pathlib import Path


_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _parse_semver(v: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(str(v).strip())
    if not m:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


class ToolRegistry:
    def __init__(self, path: str = "tools/registry.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save({"tools": []})

    def load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def register(self, entry: dict) -> None:
        data = self.load()
        data.setdefault("tools", [])
        data["tools"] = [
            t
            for t in data["tools"]
            if not (t["name"] == entry["name"] and t["version"] == entry["version"])
        ]
        data["tools"].append(entry)
        self.save(data)

    def find(self, name: str, version: str | None = None) -> dict | None:
        raw = (name or "").strip()
        parsed_name, parsed_version = (
            (raw.split("@", 1) + [None])[:2] if "@" in raw else (raw, None)
        )
        target_version = version or parsed_version
        needle = parsed_name.lower()
        candidates = []
        for tool in self.load().get("tools", []):
            if not tool.get("enabled", True):
                continue
            names = [tool.get("name", "")] + list(tool.get("aliases", []))
            if any(needle == str(n).lower() for n in names):
                if target_version and tool.get("version") != target_version:
                    continue
                candidates.append(tool)
        if not candidates:
            return None
        if target_version:
            return candidates[0]
        return sorted(
            candidates,
            key=lambda t: _parse_semver(str(t.get("version", "0.0.0"))),
            reverse=True,
        )[0]

    def list_tools(self) -> list[dict]:
        return [t for t in self.load().get("tools", []) if t.get("enabled", True)]
