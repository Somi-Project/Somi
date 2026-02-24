from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from config import settings
from config import skillssettings

from .gating import check_eligibility
from .parser import parse_skill_md
from .types import SkillDoc

_IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".cache"}
_SNAPSHOT_LOCK = threading.Lock()
_CACHED_AT = 0.0
_CACHED_KEY = ""
_CACHED_RESULT: dict[str, Any] | None = None


def settings_dict() -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for mod in (settings, skillssettings):
        for key in dir(mod):
            if key.isupper():
                cfg[key] = getattr(mod, key)
    return cfg


def get_skill_roots(cfg: dict) -> list[Path]:
    roots = [
        Path(cfg.get("SKILLS_WORKSPACE_DIR", "skills_local")),
        Path(cfg.get("SKILLS_USER_DIR", "")),
        Path(cfg.get("SKILLS_BUNDLED_DIR", "skills")),
    ]
    roots.extend(Path(p) for p in (cfg.get("SKILLS_EXTRA_DIRS") or []) if str(p).strip())
    return roots


def _safe_subdir(root: Path, child: Path) -> bool:
    if child.is_symlink():
        return False
    try:
        child_resolved = child.resolve()
        root_resolved = root.resolve()
    except Exception:
        return False
    return str(child_resolved).startswith(str(root_resolved) + os.sep) or child_resolved == root_resolved


def scan_skills(roots: list[Path]) -> tuple[dict[str, SkillDoc], list[dict[str, str]]]:
    found: dict[str, SkillDoc] = {}
    rejected: list[dict[str, str]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for sub in root.iterdir():
            if sub.name in _IGNORED_DIRS or not sub.is_dir():
                continue
            if not _safe_subdir(root, sub):
                rejected.append({"path": str(sub), "reason": "Rejected symlink/path-escape"})
                continue
            skill_md = sub / "SKILL.md"
            if not skill_md.exists() or not skill_md.is_file():
                continue
            try:
                doc = parse_skill_md(sub)
            except Exception as exc:
                rejected.append({"path": str(sub), "reason": f"Parse failed: {type(exc).__name__}: {exc}"})
                continue
            if doc.skill_key not in found:
                found[doc.skill_key] = doc
    return found, rejected


def _requirements_summary(skill: SkillDoc) -> dict[str, Any]:
    requires = skill.openclaw.get("requires", {}) if isinstance(skill.openclaw, dict) else {}
    return {
        "os": skill.openclaw.get("os") if isinstance(skill.openclaw, dict) else None,
        "bins": requires.get("bins") if isinstance(requires, dict) else None,
        "anyBins": requires.get("anyBins") if isinstance(requires, dict) else None,
        "env": requires.get("env") if isinstance(requires, dict) else None,
    }


def _env_key(env: dict) -> str:
    keys = sorted(env.keys())
    return "|".join(keys[:200])


def _write_snapshot_atomic(snapshot: dict[str, Any]) -> None:
    cache_file = Path("runtime/cache/skills_snapshot.json")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    tmp.replace(cache_file)


def _compute_snapshot(cfg: dict, env: dict) -> dict[str, Any]:
    docs, rejected = scan_skills(get_skill_roots(cfg))
    eligible: dict[str, SkillDoc] = {}
    ineligible: dict[str, tuple[SkillDoc, list[str]]] = {}

    entries = cfg.get("SKILLS_ENTRIES", {}) if isinstance(cfg, dict) else {}

    for key, doc in docs.items():
        override = entries.get(key, {}) if isinstance(entries, dict) else {}
        if override.get("enabled") is False:
            ineligible[key] = (doc, ["Disabled by SKILLS_ENTRIES override"])
            continue
        ok, reasons = check_eligibility(doc, cfg=cfg, env=env, platform=sys_platform())
        if ok:
            eligible[key] = doc
        else:
            ineligible[key] = (doc, reasons)

    snapshot = {
        "eligible": [
            {
                "key": k,
                "name": d.name,
                "desc": d.description,
                "emoji": d.emoji,
                "homepage": d.homepage,
                "base_dir": d.base_dir,
                "dispatch": {
                    "command_dispatch": d.command_dispatch,
                    "command_tool": d.command_tool,
                    "command_arg_mode": d.command_arg_mode,
                },
                "requirements": _requirements_summary(d),
                "parse_warnings": d.parse_warnings,
            }
            for k, d in sorted(eligible.items())
        ],
        "ineligible": [
            {"key": k, "name": d.name, "reasons": reasons, "parse_warnings": d.parse_warnings}
            for k, (d, reasons) in sorted(ineligible.items())
        ],
        "rejected": rejected,
    }

    _write_snapshot_atomic(snapshot)

    return {
        "eligible": eligible,
        "ineligible": ineligible,
        "snapshot": snapshot,
    }


def build_registry_snapshot(cfg: dict | None = None, env: dict | None = None, force_refresh: bool = False) -> dict[str, Any]:
    global _CACHED_AT, _CACHED_KEY, _CACHED_RESULT
    cfg = cfg or settings_dict()
    env = env or dict(os.environ)

    ttl = int(cfg.get("SKILLS_SNAPSHOT_TTL_SECONDS", 10) or 10)
    cache_key = json.dumps(
        {
            "roots": [str(p) for p in get_skill_roots(cfg)],
            "entries": cfg.get("SKILLS_ENTRIES", {}),
            "platform": sys_platform(),
            "env_keys": _env_key(env),
        },
        sort_keys=True,
        default=str,
    )

    with _SNAPSHOT_LOCK:
        if not force_refresh and _CACHED_RESULT is not None and (time.time() - _CACHED_AT) < ttl and _CACHED_KEY == cache_key:
            return _CACHED_RESULT

        result = _compute_snapshot(cfg=cfg, env=env)
        _CACHED_RESULT = result
        _CACHED_KEY = cache_key
        _CACHED_AT = time.time()
        return result


def sys_platform() -> str:
    if os.name == "nt":
        return "win32"
    if os.uname().sysname.lower().startswith("darwin"):
        return "darwin"
    return "linux"
