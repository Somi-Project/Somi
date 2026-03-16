from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from config import settings
from workshop.toolbox.stacks.ocr_core.cache import cache_get, cache_put, compute_cache_key, prune_cache
from workshop.toolbox.stacks.ocr_core.contracts import OcrQualityReport, OcrRequest, OcrResult
from workshop.toolbox.stacks.ocr_core.extract_general import general_ocr
from workshop.toolbox.stacks.ocr_core.extract_structured import structured_ocr
from workshop.toolbox.stacks.ocr_core.presets import apply_document_preset
from workshop.toolbox.stacks.ocr_core.preprocess import PREPROCESS_VERSION
from workshop.toolbox.stacks.ocr_core.prompts import PROMPT_VERSION
from workshop.toolbox.stacks.ocr_core.schema import ensure_default_schema_migrated
from workshop.toolbox.stacks.ocr_core.templates import match_template
from workshop.toolbox.stacks.ocr_core.utils import image_hashes


def detect_mode(req: OcrRequest) -> str:
    if req.mode != "auto":
        return req.mode

    prompt = (req.prompt or "").lower()
    structured_triggers = [
        x.lower() for x in (getattr(settings, "REGISTRY_TRIGGERS", []) + getattr(settings, "STRUCTURED_OCR_TRIGGERS", []))
    ]
    general_triggers = [
        x.lower() for x in (getattr(settings, "GENERAL_OCR_TRIGGERS", ["ocr"]) + getattr(settings, "OCR_TRIGGERS", []))
    ]
    analysis_triggers = [x.lower() for x in getattr(settings, "IMAGE_ANALYSIS_TRIGGERS", [])]

    if req.schema_id or any(t in prompt for t in structured_triggers):
        return "structured"
    if any(t in prompt for t in general_triggers):
        return "general"
    if any(t in prompt for t in analysis_triggers):
        return "vision"
    if req.image_paths:
        return "vision"
    raise ValueError("No images provided for OCR")


def _result_from_payload(payload: Dict[str, Any]) -> OcrResult:
    q = payload.get("quality", {})
    return OcrResult(
        raw_text=payload.get("raw_text", ""),
        structured_records=payload.get("structured_records"),
        structured_text=payload.get("structured_text"),
        exports=payload.get("exports", {}),
        quality=OcrQualityReport(
            coverage=q.get("coverage"),
            unk_ratio=q.get("unk_ratio", 0.0),
            parse_failures=q.get("parse_failures", {}),
            image_metrics=q.get("image_metrics", {}),
            escalated=q.get("escalated", False),
            reasons=q.get("reasons", []),
            score=q.get("score", 0.0),
            field_coverage=q.get("field_coverage", {}),
            field_confidence=q.get("field_confidence", {}),
            table_shapes=q.get("table_shapes", []),
            record_count=q.get("record_count", 0),
            escalation_level=q.get("escalation_level", "none"),
            manual_review_required=q.get("manual_review_required", False),
            manual_review_message=q.get("manual_review_message", ""),
        ),
        provenance=payload.get("provenance", {}),
        debug=payload.get("debug", {}),
    )


def run_ocr(req: OcrRequest) -> OcrResult:
    if not str(req.template_id or "").strip() and req.image_paths:
        inferred_template = match_template(req.image_paths[0])
        if inferred_template:
            req = OcrRequest(**{**asdict(req), "template_id": inferred_template})
    req = apply_document_preset(req)
    if not req.image_paths:
        raise ValueError("image_paths must be non-empty")
    for p in req.image_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"Image not found: {p}")

    ensure_default_schema_migrated()
    mode = detect_mode(req)
    model = req.options.get("model") or settings.VISION_MODEL
    provenance = {
        "prompt_version": PROMPT_VERSION,
        "preprocess_version": PREPROCESS_VERSION,
        "model": model,
        "image_hashes": image_hashes(req.image_paths),
        "mode": mode,
        "preset_id": str(req.template_id or req.options.get("preset_id") or "").strip(),
    }

    effective_req = OcrRequest(**{**asdict(req), "mode": mode})

    if getattr(settings, "OCR_CACHE_ENABLED", True):
        key = compute_cache_key(effective_req, provenance)
        cached = cache_get(key)
        if cached:
            return _result_from_payload(cached)

    result = structured_ocr(effective_req) if mode == "structured" else general_ocr(effective_req)
    result.provenance.update(provenance)

    if getattr(settings, "OCR_CACHE_ENABLED", True):
        cache_put(key, asdict(result))
        prune_cache(int(getattr(settings, "OCR_CACHE_MAX_ITEMS", 2000)))

    return result

