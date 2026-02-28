from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import uuid


ARTIFACT_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def build_base(*, artifact_type: str, inputs: Dict[str, Any], content: Dict[str, Any], citations: list[dict] | None = None, metadata: dict | None = None, confidence: float | None = None) -> Dict[str, Any]:
    created_at = utc_now_iso()
    out: Dict[str, Any] = {
        "artifact_id": new_artifact_id(),
        "artifact_type": str(artifact_type),
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "created_at": created_at,
        "timestamp": created_at,
        "inputs": dict(inputs or {}),
        "content": dict(content or {}),
        "citations": list(citations or []),
        "metadata": dict(metadata or {}),
    }
    if confidence is not None:
        try:
            out["confidence"] = float(confidence)
        except Exception:
            pass
    return out
