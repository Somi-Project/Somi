from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def get_output_folder() -> str:
    storage_path = Path("config/storage.json")
    default = Path("sessions/exports")
    folder = None
    if storage_path.exists():
        try:
            data = json.loads(storage_path.read_text(encoding="utf-8"))
            folder = data.get("excel_output_folder") or data.get("output_folder")
        except Exception:
            folder = None
    out = Path(folder) if folder else default
    out.mkdir(parents=True, exist_ok=True)
    return str(out.resolve())


def _base(base_name: str) -> str:
    return base_name or f"ocr_{datetime.now():%Y%m%d_%H%M%S}"


def _write_table(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    try:
        import pandas as pd

        df = pd.DataFrame(rows)
        if columns:
            df = df.reindex(columns=columns, fill_value="")
        df.to_excel(path, index=False, engine="openpyxl")
        return
    except Exception:
        csv_path = path.with_suffix(".csv")
        import csv

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns or list(rows[0].keys()) if rows else [])
            if w.fieldnames:
                w.writeheader()
                w.writerows(rows)
        path.write_text(f"CSV fallback generated: {csv_path}", encoding="utf-8")


def export_structured_excel(records: List[Dict[str, Any]], schema: Dict[str, Any], base_name: str) -> str:
    cols = schema.get("output_columns") or [f.get("name") for f in schema.get("fields", [])]
    path = Path(get_output_folder()) / f"{_base(base_name)}.xlsx"
    _write_table(path, records or [], cols)
    return str(path.resolve())


def export_general_excel(raw_text: str, base_name: str) -> str:
    blocks = [b.strip() for b in raw_text.split("\n\n") if b.strip()] or [raw_text.strip()]
    rows = [{"doc_id": _base(base_name), "block_index": i, "text": b} for i, b in enumerate(blocks, start=1)]
    path = Path(get_output_folder()) / f"{_base(base_name)}_general.xlsx"
    _write_table(path, rows, ["doc_id", "block_index", "text"])
    return str(path.resolve())


def export_json(data: Any, base_name: str) -> str:
    path = Path(get_output_folder()) / f"{_base(base_name)}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path.resolve())
