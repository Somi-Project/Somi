from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactPolicy:
    name: str
    relative_path: str
    max_files: int
    max_megabytes: float
    stale_days: int
    include_suffixes: tuple[str, ...]
    exclude_prefixes: tuple[str, ...] = ()


DEFAULT_POLICIES: tuple[ArtifactPolicy, ...] = (
    ArtifactPolicy(
        name="audit_generated",
        relative_path="audit",
        max_files=5000,
        max_megabytes=1536.0,
        stale_days=21,
        include_suffixes=(".md", ".json", ".jsonl", ".png", ".txt"),
        exclude_prefixes=("audit/backups", "audit/external_repos"),
    ),
    ArtifactPolicy(
        name="sessions_runtime",
        relative_path="sessions",
        max_files=10000,
        max_megabytes=512.0,
        stale_days=30,
        include_suffixes=(".md", ".json", ".jsonl", ".log", ".txt", ".png"),
        exclude_prefixes=("sessions/coding/rollbacks", "sessions/coding/sandbox_snapshots"),
    ),
)


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _human_size(megabytes: float) -> str:
    return f"{float(megabytes or 0.0):.2f} MB"


def _should_skip(path: Path, root: Path, excludes: tuple[str, ...]) -> bool:
    rel = path.relative_to(root).as_posix()
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in excludes)


def _artifact_files(root: Path, policy: ArtifactPolicy) -> list[Path]:
    target = root / policy.relative_path
    if not target.exists():
        return []
    rows: list[Path] = []
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path, root, policy.exclude_prefixes):
            continue
        rows.append(path)
    return rows


def _stale_candidates(
    files: list[Path],
    *,
    include_suffixes: tuple[str, ...],
    older_than: datetime,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in files:
        suffix = path.suffix.lower()
        if include_suffixes and suffix not in include_suffixes:
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified >= older_than:
            continue
        rows.append(
            {
                "path": str(path),
                "modified_at": modified.isoformat(),
                "size_bytes": int(path.stat().st_size),
            }
        )
    rows.sort(key=lambda item: (str(item.get("modified_at") or ""), str(item.get("path") or "")))
    return rows[:limit]


def run_artifact_hygiene(
    root_dir: str | Path = ".",
    *,
    policies: tuple[ArtifactPolicy, ...] | None = None,
) -> dict[str, Any]:
    root = Path(root_dir)
    active_policies = policies or DEFAULT_POLICIES
    now = datetime.now(timezone.utc)
    scopes: list[dict[str, Any]] = []
    warnings: list[str] = []
    cleanup_candidates: list[dict[str, Any]] = []

    for policy in active_policies:
        files = _artifact_files(root, policy)
        total_bytes = sum(int(path.stat().st_size) for path in files if path.exists())
        total_megabytes = total_bytes / (1024 * 1024)
        older_than = now - timedelta(days=int(policy.stale_days))
        stale = _stale_candidates(
            files,
            include_suffixes=policy.include_suffixes,
            older_than=older_than,
        )
        scope = {
            "name": policy.name,
            "path": str(root / policy.relative_path),
            "file_count": len(files),
            "total_megabytes": round(total_megabytes, 2),
            "max_files": int(policy.max_files),
            "max_megabytes": float(policy.max_megabytes),
            "stale_days": int(policy.stale_days),
            "stale_candidates": stale,
            "exclude_prefixes": list(policy.exclude_prefixes),
        }
        scopes.append(scope)
        cleanup_candidates.extend({"scope": policy.name, **item} for item in stale)
        if len(files) > int(policy.max_files):
            warnings.append(
                f"{policy.name} has {len(files)} files, which exceeds the guidance limit of {policy.max_files}."
            )
        if total_megabytes > float(policy.max_megabytes):
            warnings.append(
                f"{policy.name} is using {_human_size(total_megabytes)}, which exceeds the guidance budget of {_human_size(policy.max_megabytes)}."
            )

    recommendations: list[str] = []
    if cleanup_candidates:
        recommendations.append("Review stale generated artifacts and archive or trim older benchmark/report outputs.")
    if warnings:
        recommendations.append("Tighten retention windows before the next long benchmark or release-candidate run.")
    else:
        recommendations.append("Current generated-artifact load is within the configured budgets.")

    return {
        "ok": not warnings,
        "root_dir": str(root),
        "generated_at": now.isoformat(),
        "policies": [
            {
                "name": policy.name,
                "relative_path": policy.relative_path,
                "max_files": int(policy.max_files),
                "max_megabytes": float(policy.max_megabytes),
                "stale_days": int(policy.stale_days),
            }
            for policy in active_policies
        ],
        "scopes": scopes,
        "warnings": warnings,
        "cleanup_candidates": cleanup_candidates[:20],
        "recommendations": recommendations,
    }


def format_artifact_hygiene(report: dict[str, Any]) -> str:
    lines = [
        "[Artifact Hygiene]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- root_dir: {report.get('root_dir', '')}",
        "",
        "Scopes:",
    ]
    for scope in list(report.get("scopes") or []):
        lines.append(
            "- {name}: files={file_count} | total={total_megabytes:.2f} MB | budget={max_files} files / {max_megabytes:.2f} MB".format(
                name=scope.get("name", "scope"),
                file_count=int(scope.get("file_count") or 0),
                total_megabytes=float(scope.get("total_megabytes") or 0.0),
                max_files=int(scope.get("max_files") or 0),
                max_megabytes=float(scope.get("max_megabytes") or 0.0),
            )
        )
    lines.append("")
    lines.append("Warnings:")
    warnings = list(report.get("warnings") or [])
    if not warnings:
        lines.append("- none")
    else:
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")
    lines.append("Recommendations:")
    for rec in list(report.get("recommendations") or []):
        lines.append(f"- {rec}")
    return "\n".join(lines)
