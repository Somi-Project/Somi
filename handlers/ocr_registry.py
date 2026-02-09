# handlers/ocr_registry.py — FINAL UNIVERSAL + USER-DEFINED EXCEL FOLDER (Dec 2025)

import base64
import requests
import os
import pandas as pd
from datetime import datetime
import re
import tempfile
import sys
import io
from pathlib import Path
import json
import asyncio  # ← NEW: Added for asyncio.to_thread

# Fix Windows Unicode console issues
sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# Dynamic configuration
from config.settings import VISION_MODEL
from config.extraction_schema import (
    EXTRACTION_FIELDS,
    EXAMPLE_ENTRY,
    POST_PROCESSING,
    OUTPUT_COLUMNS
)

MODEL_NAME = VISION_MODEL  # e.g. "qwen2.5vl:7b"


def _call_qwen(image_path: str) -> str:
    """
    Sends image to local Ollama vision model and returns perfectly structured text.
    Prompt is 100% driven by user's EXAMPLE_ENTRY in extraction_schema.py
    """
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode('utf-8')

        # Build example block from user's real example
        example_lines = []
        for field in EXTRACTION_FIELDS:
            value = EXAMPLE_ENTRY.get(field, "—")
            example_lines.append(f"{field}: {value}")
        example_block = "\n".join(example_lines)

        # Build empty template for real extraction
        template_block = "\n".join([f"{field}: " for field in EXTRACTION_FIELDS])

        prompt = f"""Extract ALL records from the form image.

CRITICAL INSTRUCTIONS:
- Extract exactly these fields in exactly this order:
{', '.join(EXTRACTION_FIELDS)}
- Match the style, formatting, and detail level of the example below
- Preserve phone formats, medication lists, coordinates, dates, etc. exactly as written
- Use "—" only when a field is truly missing
- Never add explanations, markdown, bullet points, or extra text

EXAMPLE OF PERFECT OUTPUT (follow this format and style exactly):
ENTRY 1
{example_block}

NOW EXTRACT THE REAL DATA USING THIS EXACT FORMAT:

ENTRY 1
{template_block}

ENTRY 2
{template_block}

ENTRY 3
{template_block}

Continue with ENTRY 4, 5, etc. as needed.
Put one blank line between each entry.
NO extra text, NO thinking, NO markdown, NO code blocks."""

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64]
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "top_p": 1.0,
                "top_k": 1,
                "num_ctx": 16384,
                "num_predict": 8192,
                "seed": 42
            }
        }

        print(f"[OCR] Sending to {MODEL_NAME} | {len(EXTRACTION_FIELDS)} fields")
        r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=900)
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()

        result = raw if raw and len(raw) > 50 else "No structured data detected."
        print(f"[OCR] SUCCESS — {len(result)} chars extracted")
        return result

    except Exception as e:
        error_msg = f"OCR Error: {e}"
        print(error_msg)
        return f"{error_msg}\n\nPlease try with a clearer, well-lit photo."


def get_excel_save_path(filename: str) -> Path:
    """
    Returns the correct save path based on user's choice in Data Analysis Agent.
    Falls back to temp folder if config missing or invalid.
    """
    config_path = Path("config/storage.json")
    try:
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            folder = data.get("excel_output_folder")
            if folder and Path(folder).exists():
                save_dir = Path(folder)
            else:
                save_dir = Path(tempfile.gettempdir())
        else:
            save_dir = Path(tempfile.gettempdir())
    except Exception as e:
        print(f"[OCR] Could not read storage.json: {e}")
        save_dir = Path(tempfile.gettempdir())

    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir / filename


async def send_excel_version(raw_text: str, update):
    """
    Parses LLM output and sends clean Excel with dynamic columns.
    Now saves to user-defined folder via config/storage.json
    """
    if not raw_text or "ENTRY" not in raw_text.upper():
        await update.message.reply_text("No structured entries found in extracted text.")
        return

    entries = []

    pattern = re.compile(r'ENTRY\s*\d+\s*\n(.*?)(?=ENTRY\s*\d+|\Z)', re.DOTALL | re.IGNORECASE)
    for block_match in pattern.finditer(raw_text):
        block = block_match.group(1)
        entry = {}

        for line in block.split('\n'):
            if ':' not in line:
                continue
            try:
                key, val = line.split(':', 1)
            except ValueError:
                continue

            key = key.strip()
            val = val.strip()

            if val == "—" or val == "–" or not val:
                val = ""

            if key in EXTRACTION_FIELDS:
                cleaner = POST_PROCESSING.get(key, lambda x: x)
                entry[key] = cleaner(val)

        if entry:
            entries.append(entry)

    if not entries:
        await update.message.reply_text("Text extracted, but no complete entries parsed.")
        return

    df = pd.DataFrame(entries)
    df = df.reindex(columns=OUTPUT_COLUMNS, fill_value="")

    filename = f"Extracted_Form_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    path = get_excel_save_path(filename)  # NEW: User-controlled path

    try:
        df.to_excel(path, index=False, engine='openpyxl')
        with open(path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f"Extracted {len(df)} record(s) • {len(df.columns)} fields • Saved to your folder"
            )
        print(f"[Excel] Sent {len(df)} records → {path}")
    except Exception as e:
        print(f"[Excel] Failed: {e}")
        await update.message.reply_text("Failed to create Excel file.")
    finally:
        # We no longer delete — user wants to keep files!
        pass


async def process_registry_photo(image_path: str, update, context):
    """
    Main handler called from Telegram bot when user sends a form photo.
    Fully generic — just works.
    """
    await update.message.reply_text("Analyzing form… Extracting all records…")

    # ← PATCH: Offload the blocking sync Ollama vision call to a background thread
    result = await asyncio.to_thread(_call_qwen, image_path)

    await update.message.reply_text(result or "No text extracted.", parse_mode=None)

    await send_excel_version(result, update)

    try:
        os.remove(image_path)
    except:
        pass