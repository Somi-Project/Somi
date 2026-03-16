from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CRITICAL_BACKUP_PATHS = (
    "agents.py",
    "somicontroller.py",
    "workshop/tools/registry.json",
    "docs/architecture/SYSTEM_MAP.md",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_recent_backups(backups_root: str | Path = "backups", *, limit: int = 8) -> list[dict[str, Any]]:
    root = Path(backups_root)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)[: max(1, int(limit or 8))]:
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "is_dir": path.is_dir(),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return rows


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
    for _ in target.rglob("*"):
        sample_files += 1
        if sample_files >= 200:
            break

    issues: list[str] = []
    if missing:
        issues.append("missing_critical_paths")
    if sample_files < 10:
        issues.append("backup_too_small")

    return {
        "ok": not issues,
        "path": str(target),
        "checked_at": _now_iso(),
        "issues": issues,
        "present": present,
        "missing": missing,
        "sample_file_count": sample_files,
    }


def verify_recent_backups(backups_root: str | Path = "backups", *, limit: int = 5) -> dict[str, Any]:
    rows = list_recent_backups(backups_root, limit=limit)
    reports = [verify_backup_dir(row["path"]) for row in rows if bool(row.get("is_dir"))]
    verified_count = sum(1 for item in reports if bool(item.get("ok", False)))
    return {
        "root": str(Path(backups_root)),
        "recent_count": len(rows),
        "verified_count": verified_count,
        "reports": reports,
    }
