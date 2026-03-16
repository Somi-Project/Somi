from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from workshop.toolbox.stacks.ocr_core.heuristics import extract_structured_candidates
from workshop.toolbox.stacks.ocr_core.quality import escalation_metadata, field_confidence_map, field_fill_rates, score_structured
from workshop.toolbox.stacks.ocr_core.schema import ensure_default_schema_migrated, load_schema


_FIXTURES: tuple[dict[str, Any], ...] = (
    {
        "id": "medical_form",
        "schema_id": "medical_intake",
        "text": (
            "Patient Name: Jane Doe\n"
            "Date of Birth: 1990-01-01\n"
            "Phone Number: +1 555 0101\n"
            "Diagnosis: Focal epilepsy\n"
            "Current Medications: Levetiracetam\n"
        ),
    },
    {
        "id": "invoice_table",
        "schema_id": "invoice_table",
        "text": (
            "Invoice Number | Invoice Date | Vendor | Line Description | Quantity | Unit Price | Line Total | Grand Total\n"
            "INV-001 | 2026-03-01 | Somi Labs | GPU Fan | 2 | 15.50 | 31.00 | 36.00\n"
            "INV-001 | 2026-03-01 | Somi Labs | Thermal Paste | 1 | 5.00 | 5.00 | 36.00\n"
        ),
    },
    {
        "id": "receipt_totals",
        "schema_id": "receipt_totals",
        "text": (
            "Merchant: Byte Cafe\n"
            "Receipt Date: 2026-03-05\n"
            "Subtotal: 12.50\n"
            "Tax: 1.25\n"
            "Total: 13.75\n"
            "Payment Method: Card\n"
        ),
    },
)


def _report_dir(root_dir: str | Path = "sessions/ocr_benchmarks") -> Path:
    target = Path(root_dir)
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_document_benchmarks(root_dir: str | Path = "sessions/ocr_benchmarks") -> dict[str, Any]:
    ensure_default_schema_migrated()
    rows: list[dict[str, Any]] = []
    for fixture in _FIXTURES:
        schema = load_schema(str(fixture["schema_id"]))
        started = time.perf_counter()
        records = extract_structured_candidates(str(fixture["text"]), schema)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        coverage, unk, parse_failures, score, reasons = score_structured(records, schema, str(fixture["text"]), {"blur_score": 1.0})
        field_coverage = field_fill_rates(records, schema)
        field_confidence = field_confidence_map(records, schema, parse_failures, str(fixture["text"]))
        escalation_level, manual_review_required, manual_review_message = escalation_metadata(
            reasons=reasons,
            coverage=coverage,
            field_coverage=field_coverage,
        )
        rows.append(
            {
                "id": fixture["id"],
                "schema_id": fixture["schema_id"],
                "elapsed_ms": elapsed_ms,
                "record_count": len(records),
                "coverage": coverage,
                "score": score,
                "unk_ratio": unk,
                "parse_failures": parse_failures,
                "manual_review_required": manual_review_required,
                "manual_review_message": manual_review_message,
                "escalation_level": escalation_level,
                "field_coverage": field_coverage,
                "field_confidence": field_confidence,
            }
        )

    avg_ms = round(sum(float(row["elapsed_ms"]) for row in rows) / max(1, len(rows)), 3)
    avg_score = round(sum(float(row["score"]) for row in rows) / max(1, len(rows)), 4)
    overall_ok = all(float(row["coverage"]) >= 0.7 and float(row["score"]) >= 0.75 for row in rows)
    report = {
        "ok": overall_ok,
        "suite": "ocr_document_intelligence_phase6",
        "consumer_hardware_safe": True,
        "network_required": False,
        "average_parse_ms": avg_ms,
        "average_score": avg_score,
        "cases": rows,
    }

    out_dir = _report_dir(root_dir)
    json_path = out_dir / "latest.json"
    md_path = out_dir / "latest.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_lines = [
        "# OCR Benchmark Report",
        "",
        f"- ok: {overall_ok}",
        f"- average_parse_ms: {avg_ms}",
        f"- average_score: {avg_score}",
        "",
    ]
    for row in rows:
        md_lines.extend(
            [
                f"## {row['id']}",
                "",
                f"- schema_id: {row['schema_id']}",
                f"- elapsed_ms: {row['elapsed_ms']}",
                f"- coverage: {row['coverage']}",
                f"- score: {row['score']}",
                f"- manual_review_required: {row['manual_review_required']}",
                "",
            ]
        )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    report["report_path"] = str(md_path.resolve())
    report["json_path"] = str(json_path.resolve())
    return report
