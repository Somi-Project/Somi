from __future__ import annotations

PROMPT_VERSION = "ocr_prompt_v1"


def general_ocr_prompt(user_prompt: str = "") -> str:
    extra = f"\nUser request: {user_prompt.strip()}" if user_prompt.strip() else ""
    return (
        "Perform strict OCR on the provided image(s).\n"
        "Rules:\n"
        "- Preserve line breaks exactly.\n"
        "- Do not paraphrase.\n"
        "- Do not guess.\n"
        "- If uncertain, output [UNK].\n"
        "- Do not add explanations.\n"
        "- Return only extracted text."
        f"{extra}"
    )


def structured_stage1_prompt(schema: dict, missing_only: list[str] | None = None) -> str:
    fields = [f.get("name", "") for f in schema.get("fields", []) if f.get("name")]
    target_fields = missing_only or fields
    template = "\n".join([f"{f}: " for f in target_fields])
    return (
        "Extract structured records from the image(s) in VERBATIM mode.\n"
        "Do not guess.\n"
        "If uncertain, output [UNK].\n"
        "Do not add explanations.\n"
        "Output format:\n"
        "ENTRY 1\n"
        f"{template}\n"
        "---\n"
        "ENTRY 2\n"
        f"{template}\n"
        "Continue as needed."
    )


def structured_stage2_normalize_prompt(schema: dict, extracted_text: str) -> str:
    return (
        "Normalize extracted OCR into strict JSON list of records.\n"
        "Do not guess.\n"
        "If uncertain, output [UNK].\n"
        "Do not add explanations.\n"
        f"Fields: {[f.get('name') for f in schema.get('fields', [])]}\n"
        "Return ONLY valid JSON array.\n"
        f"Input:\n{extracted_text}"
    )
