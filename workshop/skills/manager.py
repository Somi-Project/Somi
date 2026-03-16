from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import build_catalog_snapshot
from .parser import parse_skill_md
from .state import SkillStateStore


def _slug(text: str) -> str:
    value = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text or "").strip())
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("_") or "skill"


class SkillManager:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = dict(cfg or {})
        self.workspace_dir = Path(self.cfg.get("SKILLS_WORKSPACE_DIR", "skills_local"))
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.rollback_root = Path(self.cfg.get("SKILLS_ROLLBACK_ROOT", "sessions/skills/rollbacks"))
        self.rollback_root.mkdir(parents=True, exist_ok=True)
        self.state_store = SkillStateStore(root_dir=self.cfg.get("SKILLS_STATE_ROOT", "sessions/skills"))

    def catalog(self, *, env: dict[str, Any] | None = None, force_refresh: bool = False) -> dict[str, Any]:
        return build_catalog_snapshot(cfg=self.cfg, env=env, force_refresh=force_refresh)

    def set_enabled(self, skill_key: str, enabled: bool, *, actor: str = "operator") -> dict[str, Any]:
        return self.state_store.set_enabled(skill_key, enabled, actor=actor)

    def _rollback_dir(self, skill_key: str) -> Path:
        path = self.rollback_root / _slug(skill_key)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _snapshot_install(self, skill_key: str, install_root: Path, *, actor: str, reason: str) -> str:
        if not install_root.exists() or not install_root.is_dir():
            return ""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        target = self._rollback_dir(skill_key) / stamp
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(install_root, target)
        meta = {
            "skill_key": str(skill_key or ""),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "actor": str(actor or "operator"),
            "reason": str(reason or "snapshot"),
            "source_root": str(install_root),
        }
        (target / "rollback_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return str(target)

    def list_rollbacks(self, skill_key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        root = self._rollback_dir(skill_key)
        for path in sorted(root.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            meta_path = path / "rollback_meta.json"
            metadata: dict[str, Any] = {}
            if meta_path.exists():
                try:
                    raw = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    raw = {}
                if isinstance(raw, dict):
                    metadata = raw
            rows.append(
                {
                    "rollback_id": path.name,
                    "path": str(path),
                    "captured_at": str(metadata.get("captured_at") or ""),
                    "reason": str(metadata.get("reason") or ""),
                    "actor": str(metadata.get("actor") or ""),
                }
            )
        return rows

    def _marketplace_state_patch(self, package_meta: dict[str, Any] | None) -> dict[str, Any]:
        meta = dict(package_meta or {})
        patch: dict[str, Any] = {}
        for src, dest in (
            ("package_id", "package_id"),
            ("version", "installed_version"),
            ("update_channel", "update_channel"),
            ("trust_badge", "trust_badge"),
        ):
            value = str(meta.get(src) or "").strip()
            if value:
                patch[dest] = value
        if isinstance(meta.get("bundle_ids"), list):
            patch["bundle_ids"] = [str(item) for item in list(meta.get("bundle_ids") or []) if str(item).strip()]
        return patch

    def install_skill(
        self,
        src_dir: str,
        *,
        actor: str = "operator",
        mode: str = "install",
        provenance: dict[str, Any] | None = None,
        package_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        src = Path(str(src_dir or "")).expanduser().resolve()
        if not src.exists() or not src.is_dir():
            raise FileNotFoundError(f"Skill source not found: {src}")
        doc = parse_skill_md(src)
        dest = self.workspace_dir / _slug(doc.skill_key)
        rollback_snapshot = ""
        if dest.exists():
            rollback_snapshot = self._snapshot_install(doc.skill_key, dest, actor=actor, reason=f"pre_{mode}")
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        doc = parse_skill_md(dest)
        state = self.state_store.record_install(
            doc.skill_key,
            source_dir=str(src),
            install_root=str(dest),
            mode=mode,
            actor=actor,
            provenance=provenance,
        )
        patch = self._marketplace_state_patch(package_meta)
        if rollback_snapshot:
            patch["last_snapshot_path"] = rollback_snapshot
        if patch:
            state = self.state_store.update_entry(doc.skill_key, {**state, **patch})
        rollbacks = self.list_rollbacks(doc.skill_key)
        if rollback_snapshot or rollbacks:
            state = self.state_store.update_entry(doc.skill_key, {**state, "rollback_available": bool(rollbacks)})
        return {
            "ok": True,
            "skill_key": doc.skill_key,
            "name": doc.name,
            "root_path": str(dest),
            "state": state,
            "rollback_snapshot": rollback_snapshot,
            "rollbacks": rollbacks,
        }

    def update_skill(
        self,
        skill_key: str,
        *,
        src_dir: str = "",
        actor: str = "operator",
        package_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if str(src_dir or "").strip():
            return self.install_skill(src_dir, actor=actor, mode="update", package_meta=package_meta)
        entry = self.state_store.get_entry(skill_key)
        if not entry:
            raise ValueError(f"Skill is not tracked for update: {skill_key}")
        return self.state_store.update_entry(skill_key, {"last_action": "refresh", "actor": actor})

    def rollback_skill(self, skill_key: str, *, rollback_id: str = "", actor: str = "operator") -> dict[str, Any]:
        entry = self.state_store.get_entry(skill_key)
        install_root = Path(str(entry.get("install_root") or "")).expanduser()
        if not str(entry.get("install_root") or "").strip():
            raise ValueError(f"Skill is not installed: {skill_key}")
        rollbacks = self.list_rollbacks(skill_key)
        if not rollbacks:
            raise ValueError(f"No rollback snapshots available for {skill_key}")
        chosen = next((item for item in rollbacks if item.get("rollback_id") == str(rollback_id or "").strip()), None)
        if chosen is None:
            chosen = rollbacks[0]
        snapshot_path = self._snapshot_install(skill_key, install_root, actor=actor, reason="pre_restore") if install_root.exists() else ""
        if install_root.exists():
            shutil.rmtree(install_root)
        shutil.copytree(Path(str(chosen.get("path") or "")), install_root)
        state = self.state_store.update_entry(
            skill_key,
            {
                **entry,
                "last_action": "rollback",
                "actor": str(actor or "operator"),
                "rollback_available": True,
                "rollback_restored_from": str(chosen.get("rollback_id") or ""),
                "last_snapshot_path": snapshot_path or str(entry.get("last_snapshot_path") or ""),
            },
        )
        state = self.state_store.append_history(
            skill_key,
            {
                "action": "rollback",
                "actor": str(actor or "operator"),
                "rollback_id": str(chosen.get("rollback_id") or ""),
                "snapshot_path": snapshot_path,
            },
        )
        return {
            "ok": True,
            "skill_key": str(skill_key or ""),
            "install_root": str(install_root),
            "restored_from": str(chosen.get("rollback_id") or ""),
            "snapshot_path": snapshot_path,
            "state": state,
        }
