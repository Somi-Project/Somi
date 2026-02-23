from __future__ import annotations

import json
from pathlib import Path


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
        data["tools"] = [t for t in data["tools"] if not (t["name"] == entry["name"] and t["version"] == entry["version"])]
        data["tools"].append(entry)
        self.save(data)

    def find(self, name: str) -> dict | None:
        needle = (name or "").strip().lower()
        for tool in self.load().get("tools", []):
            if not tool.get("enabled", True):
                continue
            names = [tool.get("name", "")] + list(tool.get("aliases", []))
            if any(needle == str(n).lower() for n in names):
                return tool
        return None

    def list_tools(self) -> list[dict]:
        return [t for t in self.load().get("tools", []) if t.get("enabled", True)]
