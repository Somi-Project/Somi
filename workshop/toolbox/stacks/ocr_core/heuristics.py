from __future__ import annotations

import re
from typing import Any

from workshop.toolbox.stacks.ocr_core.schema import schema_alias_map, schema_field_names


_MULTISPACE_RE = re.compile(r"\s{2,}|\t+")


def _normalize_label(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _blank_record(field_names: list[str]) -> dict[str, Any]:
    return {field: "[UNK]" for field in field_names}


def _finalize_record(record: dict[str, Any], field_names: list[str]) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    if not any(str(record.get(field) or "").strip() not in {"", "[UNK]"} for field in field_names):
        return None
    return {field: str(record.get(field) or "[UNK]").strip() or "[UNK]" for field in field_names}


def parse_key_value_records(text: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    field_names = schema_field_names(schema)
    alias_map = schema_alias_map(schema)
    if not field_names or not alias_map:
        return []

    records: list[dict[str, Any]] = []
    current = _blank_record(field_names)
    for raw_line in str(text or "").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            finalized = _finalize_record(current, field_names)
            if finalized:
                records.append(finalized)
                current = _blank_record(field_names)
            continue

        label = ""
        value = ""
        if ":" in line:
            label, value = line.split(":", 1)
        else:
            parts = [part.strip() for part in _MULTISPACE_RE.split(line) if part.strip()]
            if len(parts) >= 2:
                label, value = parts[0], " ".join(parts[1:])
        canonical = alias_map.get(_normalize_label(label))
        if not canonical:
            continue

        if str(current.get(canonical) or "[UNK]").strip() not in {"", "[UNK]"}:
            finalized = _finalize_record(current, field_names)
            if finalized:
                records.append(finalized)
            current = _blank_record(field_names)
        current[canonical] = str(value or "[UNK]").strip() or "[UNK]"

    finalized = _finalize_record(current, field_names)
    if finalized:
        records.append(finalized)
    return records


def parse_table_records(text: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    field_names = schema_field_names(schema)
    alias_map = schema_alias_map(schema)
    if not field_names or not alias_map:
        return []

    lines = [str(line or "").strip() for line in str(text or "").splitlines() if str(line or "").strip()]
    header_fields: list[str] = []
    data_started = False
    records: list[dict[str, Any]] = []

    for line in lines:
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*|\t+|\s{2,}", line) if cell.strip()]
        if len(cells) < 2:
            continue
        mapped = [alias_map.get(_normalize_label(cell), "") for cell in cells]
        mapped_hits = [cell for cell in mapped if cell]
        if not data_started and len(mapped_hits) >= 2:
            header_fields = mapped
            data_started = True
            continue
        if not header_fields:
            continue

        record = _blank_record(field_names)
        filled = 0
        for idx, canonical in enumerate(header_fields):
            if not canonical or idx >= len(cells):
                continue
            value = str(cells[idx] or "").strip() or "[UNK]"
            record[canonical] = value
            if value != "[UNK]":
                filled += 1
        if filled:
            finalized = _finalize_record(record, field_names)
            if finalized:
                records.append(finalized)
    return records


def choose_best_records(candidates: list[list[dict[str, Any]]], schema: dict[str, Any]) -> list[dict[str, Any]]:
    field_names = schema_field_names(schema)
    best: list[dict[str, Any]] = []
    best_score = -1
    for candidate in candidates:
        score = 0
        for row in candidate:
            for field in field_names:
                if str(dict(row).get(field) or "").strip() not in {"", "[UNK]"}:
                    score += 1
        if score > best_score:
            best = [dict(row) for row in candidate]
            best_score = score
    return best


def extract_structured_candidates(text: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    return choose_best_records(
        [
            parse_table_records(text, schema),
            parse_key_value_records(text, schema),
        ],
        schema,
    )
