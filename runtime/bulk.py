from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TargetSet:
    id: str
    criteria: dict
    estimated_count: int
    sample_preview: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DryRunResult:
    predicted_changes: dict[str, int]
    affected_ranges: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_bulk_request(targetset: TargetSet, settings) -> None:
    if not targetset.criteria:
        raise ValueError("refuse empty criteria")
    if targetset.estimated_count <= 0:
        raise ValueError("refuse unlimited/empty scope")
    if targetset.estimated_count > int(getattr(settings, "MAX_BULK_ITEMS", 200)):
        raise ValueError("bulk operations capped; use batched checkpoints")
    if not targetset.sample_preview:
        raise ValueError("sample preview required before bulk execution")


def require_checkpoint(batch_index: int, batch_size: int = 50) -> bool:
    return batch_index > 0 and batch_index % batch_size == 0
