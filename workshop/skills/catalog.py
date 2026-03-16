from __future__ import annotations

from pathlib import Path
from typing import Any

from .recipe_packs import list_recipe_packs
from .registry import build_registry_snapshot, get_skill_roots, settings_dict
from .state import SkillStateStore


def _source_kind(base_dir: str, roots: list[Path]) -> str:
    try:
        base = Path(base_dir).resolve()
    except Exception:
        return "unknown"
    labels = ("workspace", "user", "bundled")
    for index, root in enumerate(roots[:3]):
        try:
            resolved = root.resolve()
        except Exception:
            continue
        if base == resolved or resolved in base.parents:
            return labels[index]
    for root in roots[3:]:
        try:
            resolved = root.resolve()
        except Exception:
            continue
        if base == resolved or resolved in base.parents:
            return "extra"
    return "unknown"


def _trust_label(*, source_kind: str, eligible: bool, blocked: bool) -> str:
    if blocked:
        return "blocked"
    if source_kind == "bundled":
        return "bundled_trusted"
    if source_kind == "user":
        return "user_installed"
    if source_kind == "workspace":
        return "workspace_local"
    if source_kind == "extra":
        return "extra_source"
    if eligible:
        return "verified_local"
    return "unknown"


def _trust_badge(*, source_kind: str, blocked: bool) -> str:
    if blocked:
        return "blocked"
    if source_kind == "bundled":
        return "first_party"
    if source_kind == "extra":
        return "community_reviewed"
    return "local_experimental"


def _status_label(*, eligible: bool, reasons: list[str], enabled: bool, blocked: bool) -> str:
    if blocked:
        return "blocked"
    if not enabled:
        return "disabled"
    if eligible:
        return "active"
    if reasons:
        return "needs_setup"
    return "inactive"


def build_catalog_snapshot(cfg: dict[str, Any] | None = None, env: dict[str, Any] | None = None, force_refresh: bool = False) -> dict[str, Any]:
    cfg = dict(cfg or settings_dict())
    reg = build_registry_snapshot(cfg=cfg, env=dict(env or {}), force_refresh=force_refresh)
    state_store = SkillStateStore(root_dir=cfg.get("SKILLS_STATE_ROOT", "sessions/skills"))
    state_entries = dict(state_store.load().get("entries") or {})
    recipes = list_recipe_packs(root_dir=cfg.get("SKILLS_RECIPE_PACKS_DIR", "workshop/skills/recipe_packs"))
    roots = get_skill_roots(cfg)

    recipe_by_skill: dict[str, list[str]] = {}
    for recipe in recipes:
        recipe_id = str(recipe.get("id") or "").strip()
        for skill_key in list(recipe.get("skills") or []):
            key = str(skill_key or "").strip()
            if not key:
                continue
            recipe_by_skill.setdefault(key, []).append(recipe_id)

    eligible_map = {str(item.get("key") or ""): dict(item) for item in list(reg["snapshot"].get("eligible") or [])}
    ineligible_map = {str(item.get("key") or ""): dict(item) for item in list(reg["snapshot"].get("ineligible") or [])}
    docs = {**eligible_map, **ineligible_map}
    items: list[dict[str, Any]] = []

    for skill_key in sorted(docs.keys()):
        item = dict(docs[skill_key] or {})
        base_dir = str(item.get("base_dir") or "")
        source_kind = _source_kind(base_dir, roots)
        state_entry = dict(state_entries.get(skill_key) or {})
        enabled = bool(item.get("enabled", True))
        if "enabled" in state_entry:
            enabled = bool(state_entry.get("enabled"))
        reasons = list(item.get("reasons") or [])
        blocked = any("Security scan blocked skill" in str(reason) for reason in reasons)
        eligible = skill_key in reg["eligible"]
        trust_label = str(state_entry.get("trust_label_override") or _trust_label(source_kind=source_kind, eligible=eligible, blocked=blocked))
        trust_badge = str(state_entry.get("trust_badge_override") or state_entry.get("trust_badge") or _trust_badge(source_kind=source_kind, blocked=blocked))
        status = _status_label(eligible=eligible, reasons=reasons, enabled=enabled, blocked=blocked)

        items.append(
            {
                "key": skill_key,
                "name": str(item.get("name") or skill_key),
                "description": str(item.get("desc") or ""),
                "homepage": str(item.get("homepage") or ""),
                "emoji": str(item.get("emoji") or ""),
                "base_dir": base_dir,
                "source_kind": source_kind,
                "trust_label": trust_label,
                "trust_badge": trust_badge,
                "status": status,
                "enabled": enabled,
                "eligible": eligible,
                "compatibility": {
                    "ok": bool(eligible and not blocked),
                    "summary": "ready" if eligible and not blocked else "; ".join(reasons[:3]) or "blocked",
                    "reasons": reasons,
                },
                "reasons": reasons,
                "requirements": dict(item.get("requirements") or {}),
                "security": dict(item.get("security") or {}),
                "parse_warnings": list(item.get("parse_warnings") or []),
                "recipes": list(recipe_by_skill.get(skill_key) or []),
                "update_channel": str(state_entry.get("update_channel") or "stable"),
                "package_id": str(state_entry.get("package_id") or ""),
                "rollback_available": bool(state_entry.get("rollback_available", False)),
                "state": state_entry,
            }
        )

    return {
        "count": len(items),
        "items": items,
        "recipes": recipes,
        "trust_labels": sorted({str(item.get("trust_label") or "") for item in items if str(item.get("trust_label") or "").strip()}),
        "trust_badges": sorted({str(item.get("trust_badge") or "") for item in items if str(item.get("trust_badge") or "").strip()}),
        "status_counts": {
            "active": sum(1 for item in items if item.get("status") == "active"),
            "disabled": sum(1 for item in items if item.get("status") == "disabled"),
            "blocked": sum(1 for item in items if item.get("status") == "blocked"),
            "needs_setup": sum(1 for item in items if item.get("status") == "needs_setup"),
        },
    }
