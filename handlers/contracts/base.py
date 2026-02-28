from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import hashlib
import uuid


ARTIFACT_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _normalize_input_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def _fingerprint_input(value: Any) -> str:
    normalized = _normalize_input_text(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_base(*, artifact_type: str, inputs: Dict[str, Any], content: Dict[str, Any], citations: list[dict] | None = None, metadata: dict | None = None, confidence: float | None = None) -> Dict[str, Any]:
    created_at = utc_now_iso()
    artifact_type_s = str(artifact_type)
    input_query = dict(inputs or {}).get("user_query", "")
    out: Dict[str, Any] = {
        "artifact_id": new_artifact_id(),
        "artifact_type": artifact_type_s,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "contract_name": artifact_type_s,
        "contract_version": ARTIFACT_SCHEMA_VERSION,
        "created_at": created_at,
        "timestamp": created_at,
        "inputs": dict(inputs or {}),
        "content": dict(content or {}),
        "data": dict(content or {}),
        "input_fingerprint": _fingerprint_input(input_query),
        "citations": list(citations or []),
        "metadata": dict(metadata or {}),
    }
    if confidence is not None:
        try:
            out["confidence"] = float(confidence)
        except Exception:
            pass
    return out
