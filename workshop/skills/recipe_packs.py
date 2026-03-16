from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _recipe_root(root_dir: str | Path = "workshop/skills/recipe_packs") -> Path:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_recipe_packs(root_dir: str | Path = "workshop/skills/recipe_packs") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(_recipe_root(root_dir).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload.setdefault("id", path.stem)
        payload["_path"] = str(path)
        rows.append(payload)
    return rows


def get_recipe_pack(recipe_id: str, root_dir: str | Path = "workshop/skills/recipe_packs") -> dict[str, Any] | None:
    needle = str(recipe_id or "").strip().lower()
    if not needle:
        return None
    for row in list_recipe_packs(root_dir=root_dir):
        if str(row.get("id") or "").strip().lower() == needle:
            return row
    return None
