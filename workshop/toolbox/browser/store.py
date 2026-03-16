from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, *, fallback: str = "capture") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower()).strip("._-")
    return text[:64] or fallback


class BrowserAutomationStore:
    def __init__(self, root_dir: str | Path = "sessions/browser_runtime") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.captures_dir = self.root_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.root_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def next_capture_path(self, *, label: str = "capture", suffix: str = ".png") -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        return self.captures_dir / f"{stamp}_{_slug(label)}{suffix}"

    def write_run(self, payload: dict[str, Any], *, label: str = "browser_run") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = self.runs_dir / f"{stamp}_{_slug(label, fallback='browser_run')}.json"
        data = {**dict(payload or {}), "logged_at": _now_iso()}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return str(path.resolve())
