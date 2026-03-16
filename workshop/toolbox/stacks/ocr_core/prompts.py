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
    field_specs = [dict(f) for f in schema.get("fields", []) if isinstance(f, dict) and f.get("name")]
    target_fields = set(missing_only or [f.get("name", "") for f in field_specs if f.get("name")])
    prompt_lines = []
    for field in field_specs:
        name = str(field.get("name") or "").strip()
        if name not in target_fields:
            continue
        aliases = [str(item) for item in list(field.get("aliases") or []) if str(item).strip()]
        type_hint = str(field.get("type") or "text").strip()
        required = bool(field.get("required", False))
        alias_text = f" aliases={aliases}" if aliases else ""
        required_text = " required" if required else ""
        prompt_lines.append(f"{name}:  # type={type_hint}{required_text}{alias_text}")
    template = "\n".join(prompt_lines)
    return (
        "Extract structured records from the image(s) in VERBATIM mode.\n"
        "Do not guess.\n"
        "If uncertain, output [UNK].\n"
        "Do not add explanations.\n"
        "Preserve table rows and form labels exactly before normalizing them.\n"
        "Output format:\n"
        "ENTRY 1\n"
        f"{template}\n"
        "---\n"
        "ENTRY 2\n"
        f"{template}\n"
        "Continue as needed."
    )


def structured_stage2_normalize_prompt(schema: dict, extracted_text: str) -> str:
    field_specs = [
        {
            "name": f.get("name"),
            "type": f.get("type", "text"),
            "aliases": list(f.get("aliases") or []),
            "required": bool(f.get("required", False)),
        }
        for f in schema.get("fields", [])
        if isinstance(f, dict) and f.get("name")
    ]
    return (
        "Normalize extracted OCR into strict JSON list of records.\n"
        "Do not guess.\n"
        "If uncertain, output [UNK].\n"
        "Do not add explanations.\n"
        f"Fields: {field_specs}\n"
        "Return ONLY valid JSON array.\n"
        f"Input:\n{extracted_text}"
    )


def vision_analysis_prompt(user_prompt: str = "") -> str:
    extra = f"\nUser request: {user_prompt.strip()}" if user_prompt.strip() else ""
    return (
        "Analyze the provided image(s) and answer the user request directly.\n"
        "Rules:\n"
        "- Be concrete and concise.\n"
        "- If readable text appears, quote the important text exactly.\n"
        "- If details are unclear, state uncertainty briefly and continue with best effort.\n"
        "- Do not return placeholder tokens as the final answer.\n"
        "- Do not invent facts not present in the image.\n"
        f"{extra}"
    )



def vision_fallback_prompt(user_prompt: str = "") -> str:
    extra = f"\nUser request: {user_prompt.strip()}" if user_prompt.strip() else ""
    return (
        "Describe the visible content in the image(s) even if text is unreadable.\n"
        "Rules:\n"
        "- Focus on objects, layout, colors, symbols, and context clues.\n"
        "- If text is too small, say it is unreadable and continue with visual description.\n"
        "- Give best-effort details, then a short confidence note.\n"
        "- Do not return placeholder tokens.\n"
        f"{extra}"
    )

