from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from workshop.toolbox.stacks.ocr_core.contracts import OcrRequest
from workshop.toolbox.stacks.ocr_core.templates import load_templates


_PRESETS: dict[str, dict[str, Any]] = {
    "generic_form": {
        "id": "generic_form",
        "label": "Generic Form",
        "description": "Structured OCR tuned for key-value forms and intake sheets.",
        "mode": "structured",
        "schema_id": "default",
        "prompt_hint": "Extract the visible form fields exactly.",
        "options": {"preprocess_policy": "auto"},
    },
    "medical_intake": {
        "id": "medical_intake",
        "label": "Medical Intake",
        "description": "Structured OCR for patient intake forms and clinical registration sheets.",
        "mode": "structured",
        "schema_id": "medical_intake",
        "prompt_hint": "Extract patient identity, diagnosis, medication, and contact details.",
        "options": {"preprocess_policy": "auto"},
    },
    "invoice_table": {
        "id": "invoice_table",
        "label": "Invoice Table",
        "description": "Structured OCR for invoices with line items and totals.",
        "mode": "structured",
        "schema_id": "invoice_table",
        "prompt_hint": "Capture invoice header fields and line-item rows without guessing.",
        "options": {"preprocess_policy": "auto"},
    },
    "receipt_totals": {
        "id": "receipt_totals",
        "label": "Receipt Totals",
        "description": "Structured OCR for receipts and proof-of-purchase summaries.",
        "mode": "structured",
        "schema_id": "receipt_totals",
        "prompt_hint": "Extract merchant, date, subtotal, tax, total, and payment method.",
        "options": {"preprocess_policy": "auto"},
    },
    "vision_brief": {
        "id": "vision_brief",
        "label": "Vision Brief",
        "description": "Direct vision analysis for image descriptions when extraction is not enough.",
        "mode": "vision",
        "schema_id": None,
        "prompt_hint": "Summarize the visible content clearly and only quote readable text.",
        "options": {"preprocess_policy": "auto"},
    },
}


def list_document_presets() -> list[dict[str, Any]]:
    return [deepcopy(_PRESETS[key]) for key in sorted(_PRESETS)]


def resolve_document_preset(preset_id: str) -> dict[str, Any] | None:
    key = str(preset_id or "").strip().lower()
    if not key:
        return None
    payload = _PRESETS.get(key)
    if not isinstance(payload, dict):
        template_payload = dict(load_templates().get(key) or {})
        mapped_key = str(template_payload.get("preset_id") or "").strip().lower()
        if mapped_key:
            payload = _PRESETS.get(mapped_key)
    return deepcopy(payload) if isinstance(payload, dict) else None


def apply_document_preset(req: OcrRequest) -> OcrRequest:
    preset_id = str((req.options or {}).get("preset_id") or req.template_id or "").strip().lower()
    preset = resolve_document_preset(preset_id)
    if not preset:
        return req

    merged_options = {**dict(preset.get("options") or {}), **dict(req.options or {})}
    merged_options.setdefault("preset_id", preset_id)
    prompt = str(req.prompt or "").strip()
    prompt_hint = str(preset.get("prompt_hint") or "").strip()
    if prompt_hint and prompt_hint.lower() not in prompt.lower():
        prompt = f"{prompt_hint}\n{prompt}".strip()

    payload = asdict(req)
    payload["mode"] = str(req.mode or "") if str(req.mode or "").strip() not in {"", "auto"} else str(preset.get("mode") or req.mode)
    payload["schema_id"] = req.schema_id or preset.get("schema_id")
    payload["prompt"] = prompt
    payload["options"] = merged_options
    payload["template_id"] = preset_id
    return OcrRequest(**payload)
