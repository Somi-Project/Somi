from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_EXCLUDED_PREFIXES = (
    ".git",
    ".venv",
    "audit/backups",
    "audit/external_repos",
    "sessions/coding/rollbacks",
    "sessions/coding/sandbox_snapshots",
    "sessions/finality_lab",
)
DEFAULT_EXCLUDED_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
DEFAULT_EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}
DEFAULT_AUTO_EXCLUDED_TOP_LEVEL = {
    "audit",
    "sessions",
}
DEFAULT_ROOT_FILES = (
    "README.md",
    "docs/release/FRAMEWORK_RELEASE_NOTES.md",
    "docs/release/UPGRADE_PATH_VERIFIED.md",
    "docs/release/FRAMEWORK_FREEZE.md",
    "requirements.txt",
    "somi.py",
    "agents.py",
)
PHASE_DIR_PATTERN = re.compile(r"^phase\d+_", re.IGNORECASE)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize_label(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label or "").strip())
    return slug.strip("._-") or "phase_backup"


def _normalize_paths(values: Iterable[str | Path]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip().replace("\\", "/").strip("/")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def _relative_text(path: Path) -> str:
    return path.as_posix().strip("/")


def _should_skip(rel_path: Path, *, excluded_prefixes: set[str]) -> bool:
    if not rel_path.parts:
        return False
    if any(part in DEFAULT_EXCLUDED_NAMES for part in rel_path.parts):
        return True
    if rel_path.suffix.lower() in DEFAULT_EXCLUDED_SUFFIXES:
        return True
    rel_text = _relative_text(rel_path).lower()
    if any(rel_text == prefix or rel_text.startswith(prefix + "/") for prefix in excluded_prefixes):
        return True
    return False


def _default_include_paths(root_dir: Path) -> list[str]:
    includes: list[str] = []
    for file_name in DEFAULT_ROOT_FILES:
        if (root_dir / file_name).exists():
            includes.append(file_name)
    for child in sorted(root_dir.iterdir(), key=lambda item: item.name.lower()):
        if child.name in DEFAULT_EXCLUDED_NAMES:
            continue
        if PHASE_DIR_PATTERN.match(child.name):
            continue
        if child.name in DEFAULT_AUTO_EXCLUDED_TOP_LEVEL:
            continue
        if child.name.startswith("."):
            continue
        if child.is_dir():
            includes.append(child.name)
    return _normalize_paths(includes)


def _copy_tree(
    source_root: Path,
    destination_root: Path,
    *,
    root_dir: Path,
    excluded_prefixes: set[str],
    stats: dict[str, int],
) -> None:
    for path in source_root.rglob("*"):
        rel_path = path.relative_to(root_dir)
        if _should_skip(rel_path, excluded_prefixes=excluded_prefixes):
            if path.is_dir():
                stats["skipped_dirs"] += 1
            else:
                stats["skipped_files"] += 1
            continue
        target = destination_root / rel_path
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        stats["copied_files"] += 1


def create_phase_backup(
    root_dir: str | Path,
    *,
    label: str,
    include_paths: Iterable[str | Path] | None = None,
    output_root: str | Path | None = None,
    excluded_prefixes: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    project_root = Path(root_dir).resolve()
    backup_root = Path(output_root).resolve() if output_root else (project_root / "audit" / "backups").resolve()
    backup_root.mkdir(parents=True, exist_ok=True)

    include_list = _normalize_paths(include_paths or _default_include_paths(project_root))
    excluded = set(item.lower() for item in _normalize_paths(DEFAULT_EXCLUDED_PREFIXES))
    excluded.update(item.lower() for item in _normalize_paths(excluded_prefixes or []))

    destination = backup_root / f"{_sanitize_label(label)}_{_now_stamp()}"
    destination.mkdir(parents=True, exist_ok=False)

    stats = {
        "copied_files": 0,
        "copied_roots": 0,
        "skipped_dirs": 0,
        "skipped_files": 0,
    }
    copied_roots: list[str] = []
    missing: list[str] = []

    for item in include_list:
        source = (project_root / item).resolve()
        try:
            rel_path = source.relative_to(project_root)
        except ValueError:
            missing.append(item)
            continue
        if not source.exists():
            missing.append(item)
            continue
        rel_text = _relative_text(rel_path)
        if _should_skip(rel_path, excluded_prefixes=excluded):
            missing.append(item)
            continue
        copied_roots.append(rel_text)
        stats["copied_roots"] += 1
        target = destination / rel_path
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            _copy_tree(source, destination, root_dir=project_root, excluded_prefixes=excluded, stats=stats)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            stats["copied_files"] += 1

    return {
        "ok": not missing and stats["copied_roots"] > 0 and stats["copied_files"] > 0,
        "label": _sanitize_label(label),
        "root_dir": str(project_root),
        "backup_root": str(backup_root),
        "backup_dir": str(destination),
        "included": include_list,
        "copied_roots": copied_roots,
        "missing": missing,
        "excluded_prefixes": sorted(excluded),
        "stats": stats,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def format_backup_creation(report: dict[str, Any]) -> str:
    stats = dict(report.get("stats") or {})
    return "\n".join(
        [
            "[Somi Backup Create]",
            f"- ok: {bool(report.get('ok', False))}",
            f"- backup_dir: {report.get('backup_dir', '')}",
            f"- copied_roots: {int(stats.get('copied_roots') or 0)}",
            f"- copied_files: {int(stats.get('copied_files') or 0)}",
            f"- skipped_dirs: {int(stats.get('skipped_dirs') or 0)}",
            f"- skipped_files: {int(stats.get('skipped_files') or 0)}",
            f"- missing: {len(list(report.get('missing') or []))}",
        ]
    )
