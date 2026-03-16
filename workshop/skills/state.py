from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillStateStore:
    def __init__(self, root_dir: str | Path = "sessions/skills") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.root_dir / "skill_state.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"entries": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"entries": {}}
        if not isinstance(data, dict):
            return {"entries": {}}
        data.setdefault("entries", {})
        return data

    def save(self, payload: dict[str, Any]) -> None:
        data = dict(payload or {})
        data.setdefault("entries", {})
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def get_entry(self, skill_key: str) -> dict[str, Any]:
        data = self.load()
        return dict((data.get("entries") or {}).get(str(skill_key or "").strip(), {}) or {})

    def update_entry(self, skill_key: str, patch: dict[str, Any]) -> dict[str, Any]:
        key = str(skill_key or "").strip()
        if not key:
            raise ValueError("skill_key is required")
        data = self.load()
        entries = dict(data.get("entries") or {})
        row = dict(entries.get(key) or {})
        row.update(dict(patch or {}))
        row["skill_key"] = key
        row["updated_at"] = _now_iso()
        entries[key] = row
        data["entries"] = entries
        self.save(data)
        return row

    def append_history(self, skill_key: str, event: dict[str, Any], *, limit: int = 40) -> dict[str, Any]:
        entry = self.get_entry(skill_key)
        history = [dict(item) for item in list(entry.get("history") or []) if isinstance(item, dict)]
        history.append({"timestamp": _now_iso(), **dict(event or {})})
        entry["history"] = history[-max(1, int(limit or 40)) :]
        return self.update_entry(skill_key, entry)

    def set_enabled(self, skill_key: str, enabled: bool, *, actor: str = "operator") -> dict[str, Any]:
        row = self.update_entry(
            skill_key,
            {
                "enabled": bool(enabled),
                "last_action": "enable" if enabled else "disable",
                "actor": str(actor or "operator"),
            },
        )
        return self.append_history(
            skill_key,
            {
                "action": "enable" if enabled else "disable",
                "actor": str(actor or "operator"),
                "enabled": bool(enabled),
            },
        )

    def record_install(
        self,
        skill_key: str,
        *,
        source_dir: str,
        install_root: str,
        mode: str,
        actor: str = "operator",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.update_entry(
            skill_key,
            {
                "enabled": True,
                "last_action": str(mode or "install"),
                "actor": str(actor or "operator"),
                "source_dir": str(source_dir or ""),
                "install_root": str(install_root or ""),
                "installed_at": _now_iso(),
                "provenance": dict(provenance or {}),
            },
        )
        return self.append_history(
            skill_key,
            {
                "action": str(mode or "install"),
                "actor": str(actor or "operator"),
                "source_dir": str(source_dir or ""),
                "install_root": str(install_root or ""),
                "provenance": dict(provenance or {}),
            },
        )
