from __future__ import annotations

import json
import re
from typing import Any, Callable

from executive.strategic.validators import validate_phase8_artifact


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_block(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty_output")
    m = _JSON_BLOCK_RE.search(raw)
    if m:
        raw = m.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("json_object_required")
    return data


def validate_schema(schema_name: str, data: dict[str, Any], allowed_ids: set[str], exists_fn: Callable[[str], bool]) -> tuple[bool, list[str]]:
    return validate_phase8_artifact(schema_name, data, allowed_ids=allowed_ids, exists_fn=exists_fn)


def retry_with_repair(repair_fn: Callable[[str, str], str], prompt: str, bad_output: str, errors: list[str]) -> dict[str, Any]:
    repair_prompt = (
        f"{prompt}\n\nRepair the output into strict JSON object only. "
        f"Schema violations: {', '.join(errors[:12])}.\nBad output:\n{bad_output}"
    )
    repaired = repair_fn(repair_prompt, bad_output)
    return extract_json_block(repaired)


def validate_artifact_references(data: dict[str, Any], allowed_ids: set[str], exists_fn: Callable[[str], bool]) -> tuple[bool, list[str]]:
    ok, errs = validate_phase8_artifact(str(data.get("type") or ""), data, allowed_ids=allowed_ids, exists_fn=exists_fn)
    ref_errs = [e for e in errs if e.startswith("artifact_")]
    return (len(ref_errs) == 0, ref_errs)


def scan_for_forbidden_keys(data: dict[str, Any]) -> list[str]:
    ok, errs = validate_phase8_artifact(str(data.get("type") or ""), data, allowed_ids=set(), exists_fn=lambda _x: True)
    return [e for e in errs if e.startswith("forbidden_")]
