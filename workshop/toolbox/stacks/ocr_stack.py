from __future__ import annotations

from typing import Any


def run_ocr_stack(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    if action == "list_presets":
        try:
            from workshop.toolbox.stacks.ocr_core.presets import list_document_presets
        except Exception as exc:
            return {"ok": False, "error": f"ocr presets unavailable: {exc}"}
        return {"ok": True, "presets": list_document_presets()}

    if action == "benchmark":
        try:
            from workshop.toolbox.stacks.ocr_core.benchmarks import run_document_benchmarks
        except Exception as exc:
            return {"ok": False, "error": f"ocr benchmark unavailable: {exc}"}
        try:
            return run_document_benchmarks()
        except Exception as exc:
            return {"ok": False, "error": f"ocr benchmark failed: {exc}"}

    if action != "run":
        return {"ok": False, "error": "unsupported action; use action='run', 'list_presets', or 'benchmark'"}

    image_paths = [str(x) for x in (args.get("image_paths") or []) if str(x).strip()]
    if not image_paths:
        return {"ok": False, "error": "image_paths is required"}

    try:
        from workshop.toolbox.stacks.ocr_core.contracts import OcrRequest
        from workshop.toolbox.stacks.ocr_core.pipeline import run_ocr
    except Exception as exc:
        return {"ok": False, "error": f"ocr stack unavailable: {exc}"}

    try:
        options = dict(args.get("options") or {})
        req = OcrRequest(
            image_paths=image_paths,
            mode=str(args.get("mode") or "general"),
            schema_id=str(args.get("schema_id") or "") or None,
            prompt=str(options.get("prompt") or "").strip(),
            template_id=str(options.get("template_id") or options.get("preset_id") or "").strip() or None,
            source=str(options.get("source") or "api").strip() or "api",
            options=options,
        )
        out = run_ocr(req)
    except Exception as exc:
        return {"ok": False, "error": f"ocr failed: {exc}"}

    return {
        "ok": True,
        "raw_text": out.raw_text,
        "structured_records": out.structured_records,
        "structured_text": out.structured_text,
        "exports": out.exports,
        "quality": {
            "coverage": out.quality.coverage,
            "unk_ratio": out.quality.unk_ratio,
            "parse_failures": out.quality.parse_failures,
            "escalated": out.quality.escalated,
            "reasons": out.quality.reasons,
            "score": out.quality.score,
            "field_coverage": out.quality.field_coverage,
            "field_confidence": out.quality.field_confidence,
            "table_shapes": out.quality.table_shapes,
            "record_count": out.quality.record_count,
            "escalation_level": out.quality.escalation_level,
            "manual_review_required": out.quality.manual_review_required,
            "manual_review_message": out.quality.manual_review_message,
        },
        "provenance": out.provenance,
        "debug": out.debug,
    }

