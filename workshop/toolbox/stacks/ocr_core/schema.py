from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


SCHEMA_DIR = Path("config/extraction_schemas")
DEFAULT_SCHEMA_PATH = SCHEMA_DIR / "default.json"


def ensure_default_schema_migrated() -> str:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    if DEFAULT_SCHEMA_PATH.exists():
        return str(DEFAULT_SCHEMA_PATH)

    fields: List[str] = ["patient_name", "dob"]
    example: Dict[str, Any] = {"patient_name": "John Doe", "dob": "1990-01-01"}
    output_columns: List[str] = ["patient_name", "dob"]
    try:
        from config import extraction_schema as py_schema

        fields = list(getattr(py_schema, "EXTRACTION_FIELDS", fields)) or fields
        example = dict(getattr(py_schema, "EXAMPLE_ENTRY", example)) or example
        output_columns = list(getattr(py_schema, "OUTPUT_COLUMNS", fields)) or fields
    except Exception:
        pass

    payload = {
        "schema_id": "default",
        "version": "1.0",
        "fields": [{"name": f, "type": "text", "required": False} for f in fields],
        "output_columns": output_columns,
        "example": example,
    }
    DEFAULT_SCHEMA_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(DEFAULT_SCHEMA_PATH)


def load_schema(schema_id: str = "default") -> Dict[str, Any]:
    ensure_default_schema_migrated()
    path = SCHEMA_DIR / f"{schema_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("fields", [])
    data.setdefault("output_columns", [f.get("name") for f in data["fields"] if f.get("name")])
    data.setdefault("example", {})
    data.setdefault("version", "1.0")
    return data


def schema_field_names(schema: Dict[str, Any]) -> List[str]:
    return [f.get("name") for f in schema.get("fields", []) if f.get("name")]


def schema_required_fields(schema: Dict[str, Any]) -> List[str]:
    return [f.get("name") for f in schema.get("fields", []) if f.get("required") and f.get("name")]


def schema_field_specs(schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(item) for item in list(schema.get("fields") or []) if isinstance(item, dict) and item.get("name")]


def schema_alias_map(schema: Dict[str, Any]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for field in schema_field_specs(schema):
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        aliases = [name, *[str(item) for item in list(field.get("aliases") or []) if str(item).strip()]]
        for alias in aliases:
            normalized = "".join(ch.lower() for ch in alias if ch.isalnum())
            if normalized:
                alias_map.setdefault(normalized, name)
    return alias_map

