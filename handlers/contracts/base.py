from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import hashlib
import uuid


ARTIFACT_SCHEMA_VERSION = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _normalize_input_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def fingerprint_input(value: Any) -> str:
    normalized = _normalize_input_text(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_envelope(artifact: Dict[str, Any], *, session_id: str | None = None) -> Dict[str, Any]:
    payload = dict(artifact or {})
    contract_name = str(payload.get("contract_name") or payload.get("artifact_type") or "").strip()
    created = str(payload.get("timestamp") or payload.get("created_at") or utc_now_iso())
    if not contract_name:
        raise ValueError("contract_name required")

    trigger = payload.get("trigger_reason")
    if not isinstance(trigger, dict):
        trigger = {}
    trigger = {
        "explicit_request": bool(trigger.get("explicit_request", False)),
        "matched_phrases": [str(x).strip() for x in list(trigger.get("matched_phrases") or []) if str(x).strip()],
        "structural_signals": [str(x).strip() for x in list(trigger.get("structural_signals") or []) if str(x).strip()],
        "tie_break": str(trigger.get("tie_break") or "").strip() or None,
    }

    data = dict(payload.get("data") or payload.get("content") or {})
    warnings = [str(x).strip() for x in list(payload.get("warnings") or []) if str(x).strip()]
    extra_sections = payload.get("extra_sections")
    if not isinstance(extra_sections, list):
        extra_sections = list((data.get("extra_sections") or [])) if isinstance(data, dict) else []

    try:
        contract_version = int(payload.get("contract_version") or payload.get("schema_version") or ARTIFACT_SCHEMA_VERSION)
    except Exception:
        contract_version = ARTIFACT_SCHEMA_VERSION
    try:
        schema_version = int(payload.get("schema_version") or ARTIFACT_SCHEMA_VERSION)
    except Exception:
        schema_version = ARTIFACT_SCHEMA_VERSION

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    out: Dict[str, Any] = {
        "artifact_id": str(payload.get("artifact_id") or new_artifact_id()),
        "session_id": str(payload.get("session_id") or session_id or "default_user"),
        "timestamp": created,
        "contract_name": contract_name,
        "contract_version": contract_version,
        "schema_version": schema_version,
        "route": str(payload.get("route") or payload.get("inputs", {}).get("route") or "llm_only"),
        "trigger_reason": trigger,
        "confidence": max(0.0, min(1.0, confidence)),
        "input_fingerprint": str(payload.get("input_fingerprint") or fingerprint_input(payload.get("inputs", {}).get("user_query", ""))),
        "data": data,
        "extra_sections": extra_sections,
        "warnings": warnings,
        "revises_artifact_id": payload.get("revises_artifact_id"),
        "diff_summary": payload.get("diff_summary"),
        # backward aliases
        "artifact_type": contract_name,
        "content": data,
        "created_at": created,
        "inputs": dict(payload.get("inputs") or {}),
        "citations": list(payload.get("citations") or []),
        "metadata": dict(payload.get("metadata") or {}),
    }
    return out


def build_base(
    *,
    artifact_type: str,
    inputs: Dict[str, Any],
    content: Dict[str, Any],
    citations: list[dict] | None = None,
    metadata: dict | None = None,
    confidence: float | None = None,
    trigger_reason: Dict[str, Any] | None = None,
    revises_artifact_id: str | None = None,
    diff_summary: str | None = None,
) -> Dict[str, Any]:
    artifact_type_s = str(artifact_type)
    out: Dict[str, Any] = {
        "artifact_id": new_artifact_id(),
        "artifact_type": artifact_type_s,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "contract_name": artifact_type_s,
        "contract_version": ARTIFACT_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "inputs": dict(inputs or {}),
        "content": dict(content or {}),
        "data": dict(content or {}),
        "input_fingerprint": fingerprint_input(dict(inputs or {}).get("user_query", "")),
        "citations": list(citations or []),
        "metadata": dict(metadata or {}),
        "route": str(dict(inputs or {}).get("route") or "llm_only"),
        "trigger_reason": dict(trigger_reason or {}),
        "warnings": [],
        "revises_artifact_id": revises_artifact_id,
        "diff_summary": diff_summary,
    }
    if confidence is not None:
        out["confidence"] = float(confidence)
    return normalize_envelope(out)
