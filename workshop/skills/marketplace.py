from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .catalog import build_catalog_snapshot
from .gating import check_eligibility
from .manager import SkillManager
from .parser import parse_skill_md
from .recipe_packs import get_recipe_pack, list_recipe_packs
from .registry import settings_dict, sys_platform
from .security_scanner import scan_directory_with_summary, should_block


def _json_read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


class SkillMarketplaceService:
    def __init__(self, cfg: dict[str, Any] | None = None, manager: SkillManager | None = None) -> None:
        self.cfg = dict(cfg or settings_dict())
        self.manager = manager or SkillManager(cfg=self.cfg)
        self.marketplace_dir = Path(self.cfg.get("SKILLS_MARKETPLACE_DIR", "workshop/skills/marketplace_packages"))
        self.marketplace_index = Path(self.cfg.get("SKILLS_MARKETPLACE_INDEX", "workshop/skills/marketplace_index.json"))

    def _iter_package_dirs(self) -> list[Path]:
        rows: list[Path] = []
        if self.marketplace_index.exists():
            payload = _json_read(self.marketplace_index)
            for row in list(payload.get("packages") or []):
                item = dict(row or {})
                path = Path(str(item.get("source_dir") or "")).expanduser()
                if not path.is_absolute():
                    path = (self.marketplace_index.parent / path).resolve()
                if path.exists() and path.is_dir():
                    rows.append(path)
        if self.marketplace_dir.exists():
            for path in sorted(self.marketplace_dir.iterdir()):
                if path.is_dir() and path not in rows:
                    rows.append(path)
        return rows

    def _package_summary(self, path: Path, *, env: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = _json_read(path / "skill_manifest.json")
        doc = parse_skill_md(path)
        env_view = dict(env or os.environ)
        compatibility_ok, compatibility_reasons = check_eligibility(doc, cfg=self.cfg, env=env_view, platform=sys_platform())
        report: dict[str, Any] = {"findings": [], "critical": 0, "warn": 0, "info": 0}
        findings: list[dict[str, Any]] = []
        blocked = False
        if bool(self.cfg.get("SKILLS_SECURITY_SCAN_ENABLED", True)):
            report = scan_directory_with_summary(
                path,
                max_files=int(self.cfg.get("SKILLS_SECURITY_SCAN_MAX_FILES", 500) or 500),
                max_file_bytes=int(self.cfg.get("SKILLS_SECURITY_SCAN_MAX_FILE_BYTES", 1024 * 1024) or (1024 * 1024)),
            )
            findings = list(report.get("findings") or [])
            blocked = should_block(findings, str(self.cfg.get("SKILLS_SECURITY_SCAN_BLOCK_ON_SEVERITY", "critical") or "critical"))
        package_id = str(manifest.get("package_id") or path.name).strip() or path.name
        return {
            "package_id": package_id,
            "skill_key": str(manifest.get("skill_key") or doc.skill_key or package_id),
            "name": str(manifest.get("name") or doc.name or package_id),
            "description": str(manifest.get("description") or doc.description or "").strip(),
            "version": str(manifest.get("version") or "1.0.0"),
            "update_channel": str(manifest.get("update_channel") or "stable"),
            "trust_badge": str(manifest.get("trust_badge") or "first_party"),
            "persona_tags": [str(item) for item in list(manifest.get("persona_tags") or []) if str(item).strip()],
            "workflow_tags": [str(item) for item in list(manifest.get("workflow_tags") or []) if str(item).strip()],
            "bundle_ids": [str(item) for item in list(manifest.get("bundle_ids") or []) if str(item).strip()],
            "source_dir": str(path.resolve()),
            "homepage": str(doc.homepage or manifest.get("homepage") or ""),
            "compatibility": {
                "ok": bool(compatibility_ok and not blocked),
                "reasons": compatibility_reasons,
                "summary": "ready" if compatibility_ok and not blocked else "; ".join(compatibility_reasons[:3]) or "Security blocked",
            },
            "security": {
                "blocked": bool(blocked),
                "critical": int(report.get("critical") or 0),
                "warn": int(report.get("warn") or 0),
                "info": int(report.get("info") or 0),
            },
        }

    def _bundle_rows(self, packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recipes = list_recipe_packs(root_dir=self.cfg.get("SKILLS_RECIPE_PACKS_DIR", "workshop/skills/recipe_packs"))
        package_by_bundle: dict[str, list[str]] = {}
        for package in packages:
            for bundle_id in list(package.get("bundle_ids") or []):
                package_by_bundle.setdefault(str(bundle_id), []).append(str(package.get("package_id") or ""))
        rows: list[dict[str, Any]] = []
        for recipe in recipes:
            bundle_id = str(recipe.get("bundle_id") or recipe.get("id") or "").strip()
            if not bundle_id:
                continue
            rows.append(
                {
                    "bundle_id": bundle_id,
                    "recipe_id": str(recipe.get("id") or ""),
                    "name": str(recipe.get("name") or bundle_id),
                    "description": str(recipe.get("description") or ""),
                    "primary_surface": str(recipe.get("primary_surface") or "chat"),
                    "package_ids": sorted({pkg for pkg in list(package_by_bundle.get(bundle_id) or []) if pkg}),
                    "toolsets": [str(item) for item in list(recipe.get("toolsets") or []) if str(item).strip()],
                }
            )
        return rows

    def build_snapshot(
        self,
        *,
        persona: str = "",
        workflow: str = "",
        env: dict[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        catalog = build_catalog_snapshot(cfg=self.cfg, env=env or {}, force_refresh=force_refresh)
        installed = {str(item.get("key") or ""): dict(item) for item in list(catalog.get("items") or [])}
        packages = [self._package_summary(path, env=env) for path in self._iter_package_dirs()]
        bundles = self._bundle_rows(packages)
        persona_key = str(persona or "").strip().lower()
        workflow_key = str(workflow or "").strip().lower()
        items: list[dict[str, Any]] = []
        for package in packages:
            installed_item = installed.get(str(package.get("skill_key") or ""))
            installed_state = dict((installed_item or {}).get("state") or {})
            installed_version = str(installed_state.get("installed_version") or "")
            package_version = str(package.get("version") or "")
            status = "available"
            if installed_item:
                status = "installed"
                if package_version and installed_version and package_version != installed_version:
                    status = "update_available"
            if not bool(dict(package.get("compatibility") or {}).get("ok", False)):
                status = "blocked" if bool(dict(package.get("security") or {}).get("blocked", False)) else "incompatible"
            recommended = False
            if persona_key and persona_key in {str(item).lower() for item in list(package.get("persona_tags") or [])}:
                recommended = True
            if workflow_key and workflow_key in {str(item).lower() for item in list(package.get("workflow_tags") or [])}:
                recommended = True
            rows = [row for row in bundles if str(row.get("bundle_id") or "") in set(package.get("bundle_ids") or [])]
            items.append(
                {
                    "package_id": str(package.get("package_id") or ""),
                    "skill_key": str(package.get("skill_key") or ""),
                    "name": str(package.get("name") or ""),
                    "description": str(package.get("description") or ""),
                    "version": package_version,
                    "installed_version": installed_version,
                    "status": status,
                    "trust_badge": str(package.get("trust_badge") or ""),
                    "update_channel": str(package.get("update_channel") or "stable"),
                    "source_dir": str(package.get("source_dir") or ""),
                    "compatibility": dict(package.get("compatibility") or {}),
                    "security": dict(package.get("security") or {}),
                    "homepage": str(package.get("homepage") or ""),
                    "recommended": recommended,
                    "bundle_ids": list(package.get("bundle_ids") or []),
                    "bundle_rows": rows,
                    "installed_state": installed_state,
                    "rollback_available": bool(installed_state.get("rollback_available")) if installed_item else False,
                }
            )
        items.sort(key=lambda row: (not bool(row.get("recommended")), str(row.get("status") or ""), str(row.get("name") or "").lower()))
        return {
            "count": len(items),
            "items": items,
            "bundles": bundles,
            "recommended": [row for row in items if bool(row.get("recommended"))],
            "status_counts": {
                "available": sum(1 for item in items if item.get("status") == "available"),
                "installed": sum(1 for item in items if item.get("status") == "installed"),
                "update_available": sum(1 for item in items if item.get("status") == "update_available"),
                "blocked": sum(1 for item in items if item.get("status") == "blocked"),
                "incompatible": sum(1 for item in items if item.get("status") == "incompatible"),
            },
        }

    def install_package(self, package_id: str, *, actor: str = "operator", env: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = self.build_snapshot(env=env, force_refresh=True)
        package = next((row for row in list(snapshot.get("items") or []) if row.get("package_id") == str(package_id or "")), None)
        if not package:
            raise ValueError(f"Unknown marketplace package: {package_id}")
        compatibility = dict(package.get("compatibility") or {})
        if not bool(compatibility.get("ok", False)):
            raise ValueError(f"Package is not compatible: {compatibility.get('summary') or 'blocked'}")
        mode = "update" if str(package.get("status") or "") == "update_available" else "install"
        provenance = {
            "source": "marketplace",
            "package_id": str(package.get("package_id") or ""),
            "trust_badge": str(package.get("trust_badge") or ""),
            "update_channel": str(package.get("update_channel") or "stable"),
        }
        install = self.manager.install_skill(
            str(package.get("source_dir") or ""),
            actor=actor,
            mode=mode,
            provenance=provenance,
            package_meta=package,
        )
        return {"ok": True, "package": package, "install": install}

    def rollback_package(self, skill_key: str, *, actor: str = "operator", rollback_id: str = "") -> dict[str, Any]:
        restored = self.manager.rollback_skill(skill_key, actor=actor, rollback_id=rollback_id)
        return {"ok": True, "rollback": restored}

    def bundle_details(self, bundle_id: str) -> dict[str, Any]:
        snapshot = self.build_snapshot(force_refresh=True)
        recipe = get_recipe_pack(str(bundle_id or ""), root_dir=self.cfg.get("SKILLS_RECIPE_PACKS_DIR", "workshop/skills/recipe_packs"))
        bundle = next((row for row in list(snapshot.get("bundles") or []) if row.get("bundle_id") == str(bundle_id or "")), None)
        return {
            "bundle": bundle or {},
            "recipe": recipe or {},
            "packages": [row for row in list(snapshot.get("items") or []) if str(bundle_id or "") in set(row.get("bundle_ids") or [])],
        }
