from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TargetSet:
    id: str
    domain: str
    criteria: dict
    estimated_count: int
    sample_items: list[dict] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class DryRunResult:
    action_counts: dict[str, int]
    oldest_ts: str | None = None
    newest_ts: str | None = None
    exceptions: list[str] = field(default_factory=list)


def validate_bulk_request(targetset: TargetSet, action: str, settings) -> None:
    if not targetset.criteria:
        raise ValueError("Bulk criteria cannot be empty")
    if targetset.estimated_count <= 0:
        raise ValueError("Bulk estimated count must be > 0")
    if targetset.estimated_count > settings.MAX_BULK_ITEMS:
        raise ValueError(
            "Bulk selection too large; batching + typed confirmation required"
        )
    if (
        action == "delete"
        and getattr(settings, "DEFAULT_EMAIL_ACTION", "archive") == "archive"
    ):
        raise ValueError("Delete disabled by default; prefer archive/trash")
