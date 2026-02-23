from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from config import settings
from handlers.ocr.cache import cache_get, cache_put, compute_cache_key, prune_cache
from handlers.ocr.contracts import OcrQualityReport, OcrRequest, OcrResult
from handlers.ocr.extract_general import general_ocr
from handlers.ocr.extract_structured import structured_ocr
from handlers.ocr.preprocess import PREPROCESS_VERSION
from handlers.ocr.prompts import PROMPT_VERSION
from handlers.ocr.schema import ensure_default_schema_migrated
from handlers.ocr.utils import image_hashes


def detect_mode(req: OcrRequest) -> str:
    if req.mode != "auto":
        return req.mode
    prompt = (req.prompt or "").lower()
    structured_triggers = [x.lower() for x in (getattr(settings, "REGISTRY_TRIGGERS", []) + getattr(settings, "STRUCTURED_OCR_TRIGGERS", []))]
    general_triggers = [x.lower() for x in (getattr(settings, "GENERAL_OCR_TRIGGERS", ["ocr"]) + getattr(settings, "OCR_TRIGGERS", []))]
    if req.schema_id or any(t in prompt for t in structured_triggers):
        return "structured"
    if any(t in prompt for t in general_triggers):
        return "general"
    if req.image_paths:
        return "general"
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
            unk_ratio=q.get("unk_ratio",0.0),
            parse_failures=q.get("parse_failures",{}),
            image_metrics=q.get("image_metrics",{}),
            escalated=q.get("escalated",False),
            reasons=q.get("reasons",[]),
            score=q.get("score",0.0),
        ),
        provenance=payload.get("provenance", {}),
        debug=payload.get("debug", {}),
    )


def run_ocr(req: OcrRequest) -> OcrResult:
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
    }

    if getattr(settings, "OCR_CACHE_ENABLED", True):
        key = compute_cache_key(req, provenance)
        cached = cache_get(key)
        if cached:
            return _result_from_payload(cached)

    effective_req = OcrRequest(**{**asdict(req), "mode": mode})
    result = structured_ocr(effective_req) if mode == "structured" else general_ocr(effective_req)
    result.provenance.update(provenance)

    if getattr(settings, "OCR_CACHE_ENABLED", True):
        cache_put(key, asdict(result))
        prune_cache(int(getattr(settings, "OCR_CACHE_MAX_ITEMS", 2000)))

    return result
