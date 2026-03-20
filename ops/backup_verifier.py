from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CRITICAL_BACKUP_PATHS = (
    "agents.py",
    "somi.py",
    "workshop/tools/registry.json",
    "docs/architecture/SYSTEM_MAP.md",
)
CHECKPOINT_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"}
PHASE_LOG_HINTS = {"phase_upgrade.md", "agentupgrade.md", "searchupgrade.md", "update.md"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_backup_roots(backups_root: str | Path | list[str | Path] | tuple[str | Path, ...] = "backups") -> list[Path]:
    raw_roots: list[Path] = []
    if isinstance(backups_root, (list, tuple)):
        raw_roots.extend(Path(item) for item in backups_root)
    else:
        raw_roots.append(Path(backups_root))

    env_roots = str(os.environ.get("SOMI_BACKUP_ROOTS", "") or "").strip()
    if env_roots:
        raw_roots.extend(Path(item) for item in env_roots.split(os.pathsep) if str(item).strip())

    expanded: list[Path] = []
    for root in raw_roots:
        expanded.append(root)
        if root.name.lower() == "backups":
            expanded.append(root.parent / "audit" / "backups")

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in expanded:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def list_recent_backups(
    backups_root: str | Path | list[str | Path] | tuple[str | Path, ...] = "backups",
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in resolve_backup_roots(backups_root):
        if not root.exists():
            continue
        for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            rows.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "root": str(root),
                    "is_dir": path.is_dir(),
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return rows[: max(1, int(limit or 8))]


def _phase_checkpoint_ok(
    target: Path,
    *,
    file_count: int,
    source_like_count: int,
    upgrade_logs_present: list[str],
) -> bool:
    in_audit_root = target.parent.name.lower() == "backups" and target.parent.parent.name.lower() == "audit"
    phase_named = target.name.lower().startswith("phase")
    if not bool(in_audit_root or phase_named):
        return False
    if file_count < 3 or source_like_count < 3:
        return False
    if upgrade_logs_present:
        return True
    return phase_named


def verify_backup_dir(path: str | Path, *, required_paths: tuple[str, ...] = CRITICAL_BACKUP_PATHS) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"ok": False, "path": str(target), "issues": ["missing_backup"], "present": [], "missing": list(required_paths)}
    if not target.is_dir():
        return {"ok": False, "path": str(target), "issues": ["backup_not_directory"], "present": [], "missing": list(required_paths)}

    present: list[str] = []
    missing: list[str] = []
    for relative in required_paths:
        if (target / relative).exists():
            present.append(relative)
        else:
            missing.append(relative)

    sample_files = 0
    source_like_count = 0
    upgrade_logs_present: list[str] = []
    for child in target.rglob("*"):
        if not child.is_file():
            continue
        sample_files += 1
        if child.suffix.lower() in CHECKPOINT_SUFFIXES:
            source_like_count += 1
        if child.name.lower() in PHASE_LOG_HINTS:
            upgrade_logs_present.append(child.name)
        if sample_files >= 300:
            break

    issues: list[str] = []
    mode = "framework_backup"
    if missing or sample_files < 10:
        if _phase_checkpoint_ok(
            target,
            file_count=sample_files,
            source_like_count=source_like_count,
            upgrade_logs_present=upgrade_logs_present,
        ):
            mode = "phase_checkpoint"
        else:
            if missing:
                issues.append("missing_critical_paths")
            if sample_files < 10:
                issues.append("backup_too_small")

    return {
        "ok": not issues,
        "path": str(target),
        "checked_at": _now_iso(),
        "mode": mode,
        "issues": issues,
        "present": present,
        "missing": missing,
        "sample_file_count": sample_files,
        "source_like_count": source_like_count,
        "upgrade_logs_present": sorted(set(upgrade_logs_present)),
    }


def verify_recent_backups(
    backups_root: str | Path | list[str | Path] | tuple[str | Path, ...] = "backups",
    *,
    limit: int = 5,
) -> dict[str, Any]:
    rows = list_recent_backups(backups_root, limit=limit)
    reports = [verify_backup_dir(row["path"]) for row in rows if bool(row.get("is_dir"))]
    verified_count = sum(1 for item in reports if bool(item.get("ok", False)))
    mode_counts: dict[str, int] = {}
    for item in reports:
        mode = str(item.get("mode") or "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    roots = [str(path) for path in resolve_backup_roots(backups_root) if path.exists()]
    return {
        "root": str(resolve_backup_roots(backups_root)[0]),
        "roots": roots,
        "recent_count": len(rows),
        "verified_count": verified_count,
        "mode_counts": mode_counts,
        "reports": reports,
    }
