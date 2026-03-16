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
from .security_scanner import scan_directory_with_summary, should_block
from .state import SkillStateStore
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


def _scan_skill_security(doc: SkillDoc, skill_dir: Path, cfg: dict[str, Any]) -> SkillDoc:
    if not bool(cfg.get("SKILLS_SECURITY_SCAN_ENABLED", True)):
        return doc

    try:
        report = scan_directory_with_summary(
            skill_dir,
            max_files=int(cfg.get("SKILLS_SECURITY_SCAN_MAX_FILES", 500) or 500),
            max_file_bytes=int(cfg.get("SKILLS_SECURITY_SCAN_MAX_FILE_BYTES", 1024 * 1024) or (1024 * 1024)),
        )
        findings = list(report.get("findings") or [])
        max_findings = max(1, int(cfg.get("SKILLS_SECURITY_SCAN_MAX_FINDINGS_PER_SKILL", 25) or 25))
        doc.security_summary = {
            "scanned_files": int(report.get("scanned_files") or 0),
            "critical": int(report.get("critical") or 0),
            "warn": int(report.get("warn") or 0),
            "info": int(report.get("info") or 0),
            "blocked_on": str(cfg.get("SKILLS_SECURITY_SCAN_BLOCK_ON_SEVERITY", "critical") or "critical").lower(),
        }
        doc.security_findings = findings[:max_findings]
        doc.security_blocked = should_block(
            findings,
            str(cfg.get("SKILLS_SECURITY_SCAN_BLOCK_ON_SEVERITY", "critical") or "critical"),
        )
        if doc.security_blocked:
            doc.parse_warnings.append("Security scan flagged blocked findings")
    except Exception as exc:
        doc.parse_warnings.append(f"security scan failed: {type(exc).__name__}: {exc}")
    return doc


def scan_skills(roots: list[Path], cfg: dict[str, Any] | None = None) -> tuple[dict[str, SkillDoc], list[dict[str, str]]]:
    found: dict[str, SkillDoc] = {}
    rejected: list[dict[str, str]] = []
    cfg = cfg or {}

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
                doc = _scan_skill_security(doc, sub, cfg)
            except Exception as exc:
                rejected.append({"path": str(sub), "reason": f"Parse failed: {type(exc).__name__}: {exc}"})
                continue
            if doc.skill_key not in found:
                found[doc.skill_key] = doc
    return found, rejected


def _requirements_summary(skill: SkillDoc) -> dict[str, Any]:
    requires = skill.runtime_meta.get("requires", {}) if isinstance(skill.runtime_meta, dict) else {}
    return {
        "os": skill.runtime_meta.get("os") if isinstance(skill.runtime_meta, dict) else None,
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
    docs, rejected = scan_skills(get_skill_roots(cfg), cfg=cfg)
    eligible: dict[str, SkillDoc] = {}
    ineligible: dict[str, tuple[SkillDoc, list[str]]] = {}
    state_entries = dict(SkillStateStore(root_dir=cfg.get("SKILLS_STATE_ROOT", "sessions/skills")).load().get("entries") or {})

    entries = cfg.get("SKILLS_ENTRIES", {}) if isinstance(cfg, dict) else {}

    for key, doc in docs.items():
        override = entries.get(key, {}) if isinstance(entries, dict) else {}
        state_override = state_entries.get(key, {}) if isinstance(state_entries, dict) else {}
        merged_override = {**dict(state_override or {}), **dict(override or {})}
        if merged_override.get("enabled") is False:
            ineligible[key] = (doc, ["Disabled by SKILLS_ENTRIES override"])
            continue

        if bool(getattr(doc, "security_blocked", False)):
            ss = dict(getattr(doc, "security_summary", {}) or {})
            reason = (
                "Security scan blocked skill"
                f" (critical={int(ss.get('critical') or 0)}, warn={int(ss.get('warn') or 0)}, info={int(ss.get('info') or 0)})"
            )
            ineligible[key] = (doc, [reason])
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
                "enabled": bool({**dict(state_entries.get(k, {}) or {}), **dict(entries.get(k, {}) or {})}.get("enabled", True)),
                "dispatch": {
                    "command_dispatch": d.command_dispatch,
                    "command_tool": d.command_tool,
                    "command_arg_mode": d.command_arg_mode,
                },
                "requirements": _requirements_summary(d),
                "security": dict(getattr(d, "security_summary", {}) or {}),
                "parse_warnings": d.parse_warnings,
            }
            for k, d in sorted(eligible.items())
        ],
        "ineligible": [
            {
                "key": k,
                "name": d.name,
                "base_dir": d.base_dir,
                "enabled": bool({**dict(state_entries.get(k, {}) or {}), **dict(entries.get(k, {}) or {})}.get("enabled", True)),
                "reasons": reasons,
                "security": dict(getattr(d, "security_summary", {}) or {}),
                "parse_warnings": d.parse_warnings,
            }
            for k, (d, reasons) in sorted(ineligible.items())
        ],
        "rejected": rejected,
        "state_entries": state_entries,
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
            "scan": {
                "enabled": bool(cfg.get("SKILLS_SECURITY_SCAN_ENABLED", True)),
                "block_on": str(cfg.get("SKILLS_SECURITY_SCAN_BLOCK_ON_SEVERITY", "critical")),
                "max_files": int(cfg.get("SKILLS_SECURITY_SCAN_MAX_FILES", 500) or 500),
                "max_file_bytes": int(cfg.get("SKILLS_SECURITY_SCAN_MAX_FILE_BYTES", 1024 * 1024) or (1024 * 1024)),
            },
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
    try:
        if hasattr(os, "uname") and os.uname().sysname.lower().startswith("darwin"):
            return "darwin"
    except Exception:
        pass
    return "linux"

