from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from config import settings
from handlers.ocr.contracts import OcrQualityReport, OcrRequest, OcrResult
from handlers.ocr.exports import export_json, export_structured_excel
from handlers.ocr.preprocess import compute_image_metrics, preprocess_image, should_preprocess
from handlers.ocr.prompts import structured_stage1_prompt, structured_stage2_normalize_prompt
from handlers.ocr.quality import score_structured, should_escalate_structured
from handlers.ocr.schema import ensure_default_schema_migrated, load_schema, schema_field_names
from handlers.ocr.vision_backend import VisionBackendError, ollama_vision_chat


ENTRY_RE = re.compile(r"ENTRY\s*\d+\s*\n(.*?)(?=\n---|ENTRY\s*\d+|\Z)", re.DOTALL | re.IGNORECASE)


def _parse_entry_blocks(text: str, field_names: List[str]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for block in ENTRY_RE.findall(text or ""):
        row: Dict[str, Any] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip()
            if key in field_names:
                row[key] = v.strip() or "[UNK]"
        if row:
            for f in field_names:
                row.setdefault(f, "[UNK]")
            entries.append(row)
    return entries


def _aggregate_metrics(image_paths: list[str]) -> dict:
    metrics_list = [compute_image_metrics(p) for p in image_paths]
    if not metrics_list:
        return {}
    def _avg(name: str, default: float = 0.0) -> float:
        vals = [float(m.get(name, default)) for m in metrics_list if m.get(name) is not None]
        return (sum(vals) / len(vals)) if vals else default
    return {
        "count": len(metrics_list),
        "brightness": _avg("brightness", 0.5),
        "blur_score": _avg("blur_score", 0.5),
        "width_max": max([(m.get("width") or 0) for m in metrics_list], default=0),
        "height_max": max([(m.get("height") or 0) for m in metrics_list], default=0),
        "per_image": metrics_list,
    }


def _stage1_per_image(model: str, prompt: str, images: list[str], timeout: int) -> str:
    chunks: list[str] = []
    for idx, img in enumerate(images, start=1):
        text = ollama_vision_chat(
            model=model,
            prompt=prompt,
            image_paths=[img],
            timeout_sec=timeout,
            options={"temperature": getattr(settings, "OCR_TEMPERATURE", 0.0), "num_predict": getattr(settings, "OCR_NUM_PREDICT", 1024)},
        )
        chunks.append(f"=== IMAGE {idx} ===\n{text}" if len(images) > 1 else text)
    return "\n\n".join(chunks).strip()


def structured_ocr(req: OcrRequest) -> OcrResult:
    t0 = time.time()
    ensure_default_schema_migrated()
    schema = load_schema(req.schema_id or "default")
    model = req.options.get("model") or settings.VISION_MODEL
    stage2_model = getattr(settings, "INSTRUCT_MODEL", model) or model
    timeout = int(req.options.get("timeout_sec", getattr(settings, "OCR_TIMEOUT_SEC", 120)))
    policy = req.options.get("preprocess_policy", getattr(settings, "OCR_PREPROCESS_POLICY", "auto"))
    max_passes = int(getattr(settings, "OCR_MAX_PASSES", 2))

    metrics = _aggregate_metrics(req.image_paths)
    active_images = list(req.image_paths)
    preprocessed = False
    if should_preprocess(metrics, policy):
        active_images = [preprocess_image(p, metrics) for p in req.image_paths]
        preprocessed = True

    field_names = schema_field_names(schema)
    stage1_text = ""
    records: List[Dict[str, Any]] = []
    reasons: List[str] = []
    coverage = 0.0
    unk = 1.0
    parse_failures: Dict[str, int] = {}
    score = 0.0

    for _ in range(max_passes):
        stage1_prompt = structured_stage1_prompt(schema)
        try:
            stage1_text = _stage1_per_image(model, stage1_prompt, active_images, timeout)
        except VisionBackendError as exc:
            stage1_text = f"OCR error: {exc}"
            reasons = ["vision_backend_error"]
            break

        stage2_prompt = structured_stage2_normalize_prompt(schema, stage1_text)
        try:
            norm = ollama_vision_chat(
                model=stage2_model,
                prompt=stage2_prompt,
                image_paths=[],
                timeout_sec=timeout,
                options={"temperature": 0.0, "num_predict": getattr(settings, "OCR_NUM_PREDICT", 1024)},
            )
            records = json.loads(norm)
            if not isinstance(records, list):
                raise ValueError("not a list")
        except Exception:
            records = _parse_entry_blocks(stage1_text, field_names)

        coverage, unk, parse_failures, score, reasons = score_structured(records, schema, stage1_text, metrics)
        escalate, esc = should_escalate_structured(
            coverage,
            unk,
            parse_failures,
            metrics,
            {
                "min_coverage": getattr(settings, "OCR_MIN_COVERAGE", 0.70),
                "max_unk_ratio": getattr(settings, "OCR_MAX_UNK_RATIO", 0.05),
                "max_parse_failures": 0,
            },
        )
        if not (getattr(settings, "OCR_SECOND_PASS", True) and escalate and max_passes > 1):
            reasons = esc or reasons
            break

        missing = [f for f in field_names if any((r.get(f, "") in ["", "[UNK]"]) for r in (records or [{}]))]
        active_images = [preprocess_image(p, metrics) for p in req.image_paths]
        preprocessed = True
        retry_prompt = structured_stage1_prompt(schema, missing_only=missing)
        try:
            retry_stage1 = _stage1_per_image(model, retry_prompt, active_images, timeout)
            retry_records = _parse_entry_blocks(retry_stage1, field_names)
            if retry_records and records:
                for i, rec in enumerate(records):
                    if i < len(retry_records):
                        for f in field_names:
                            if rec.get(f, "") in ["", "[UNK]"] and retry_records[i].get(f, "") not in ["", "[UNK]"]:
                                rec[f] = retry_records[i][f]
            stage1_text = retry_stage1
        except Exception:
            pass

    base = Path(req.image_paths[0]).stem
    excel_path = export_structured_excel(records, schema, base + "_structured")
    json_path = export_json(records, base + "_structured_records")
    quality = OcrQualityReport(
        coverage=coverage,
        unk_ratio=unk,
        parse_failures=parse_failures,
        image_metrics=metrics,
        escalated=bool(reasons),
        reasons=reasons,
        score=score,
    )
    return OcrResult(
        raw_text=stage1_text,
        structured_records=records,
        structured_text=stage1_text,
        exports={"excel_path": excel_path, "json_path": json_path},
        quality=quality,
        provenance={"model": model, "stage2_model": stage2_model, "preprocessed": preprocessed},
        debug={"latency_sec": round(time.time() - t0, 3)},
    )
