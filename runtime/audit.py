from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.hashing import sha256_text
from runtime.runtime_secrets import get_runtime_secret


def audit_path(job_id: str) -> Path:
    return Path("sessions/jobs") / str(job_id) / "audit.jsonl"


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _audit_secret(*, create: bool = False) -> str:
    env_secret = str(os.getenv("SOMI_AUDIT_SECRET", "") or "").strip()
    if env_secret:
        return env_secret
    try:
        from config import settings as settings_module

        configured = str(getattr(settings_module, "AUDIT_HMAC_SECRET", "") or "").strip()
        if configured:
            return configured
    except Exception:
        pass
    return get_runtime_secret("audit_hmac", create=create)


def _canonical_record(record: dict[str, Any]) -> str:
    base = {
        "seq": int(record.get("seq") or 0),
        "prev_hash": str(record.get("prev_hash") or ""),
        "ts": str(record.get("ts") or ""),
        "event": str(record.get("event") or ""),
        "data": dict(record.get("data") or {}),
    }
    return _stable_json(base)


def _read_last_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    last: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                last = parsed
    return last


def append_event(
    job_id: str, event: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    path = audit_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    last = _read_last_record(path)
    prev_hash = ""
    prev_seq = 0
    if isinstance(last, dict):
        prev_hash = str(last.get("record_hash") or "")
        try:
            prev_seq = int(last.get("seq") or 0)
        except Exception:
            prev_seq = 0

    rec = {
        "seq": prev_seq + 1,
        "prev_hash": prev_hash,
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": str(event),
        "data": dict(data or {}),
    }

    rec_hash = sha256_text(_canonical_record(rec))
    rec["record_hash"] = rec_hash

    secret = _audit_secret(create=True)
    if secret:
        rec["signature"] = hmac.new(
            secret.encode("utf-8"),
            rec_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    with path.open("a", encoding="utf-8") as f:
        f.write(_stable_json(rec) + "\n")
    return rec


def verify_audit_path(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {
            "ok": False,
            "path": str(p),
            "error": "missing",
            "records": 0,
            "hashed_records": 0,
            "legacy_records": 0,
            "issues": ["audit log not found"],
        }

    issues: list[str] = []
    total_records = 0
    hashed_records = 0
    legacy_records = 0

    expected_prev_hash = ""
    expected_next_seq = 1

    secret = _audit_secret(create=False)

    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            total_records += 1

            try:
                rec = json.loads(line)
            except Exception as exc:
                issues.append(f"line {line_no}: invalid json ({type(exc).__name__})")
                continue

            if not isinstance(rec, dict):
                issues.append(f"line {line_no}: record is not an object")
                continue

            has_chain_fields = (
                "seq" in rec
                and "prev_hash" in rec
                and "record_hash" in rec
            )
            if not has_chain_fields:
                legacy_records += 1
                if hashed_records > 0:
                    issues.append(f"line {line_no}: legacy record appears after hashed chain")
                continue

            hashed_records += 1

            try:
                seq = int(rec.get("seq") or 0)
            except Exception:
                seq = 0

            prev_hash = str(rec.get("prev_hash") or "")
            record_hash = str(rec.get("record_hash") or "")

            if seq != expected_next_seq:
                issues.append(
                    f"line {line_no}: sequence mismatch (expected {expected_next_seq}, got {seq})"
                )
            if prev_hash != expected_prev_hash:
                issues.append(
                    f"line {line_no}: previous hash mismatch"
                )

            recomputed = sha256_text(_canonical_record(rec))
            if record_hash != recomputed:
                issues.append(f"line {line_no}: record hash mismatch")

            if "signature" in rec and secret:
                expected_sig = hmac.new(
                    secret.encode("utf-8"),
                    record_hash.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                if str(rec.get("signature") or "") != expected_sig:
                    issues.append(f"line {line_no}: signature mismatch")

            expected_prev_hash = record_hash
            expected_next_seq = max(expected_next_seq, seq + 1)

    return {
        "ok": not issues,
        "path": str(p),
        "records": total_records,
        "hashed_records": hashed_records,
        "legacy_records": legacy_records,
        "issues": issues,
    }


def verify_audit_log(job_id: str) -> dict[str, Any]:
    return verify_audit_path(audit_path(job_id))
