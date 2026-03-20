from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import pdfplumber


SUPPORTED_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".log",
    ".yaml",
    ".yml",
}


def _clip(value: Any, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def clean_document_text(text: Any, *, limit: int = 6000) -> str:
    raw = str(text or "").replace("\x00", " ")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = "\n".join(line.strip() for line in raw.splitlines())
    cleaned = "\n".join(line for line in raw.splitlines() if line)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_csv_preview(path: Path) -> tuple[str, list[dict[str, str]]]:
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle)
        for idx, row in enumerate(reader):
            rows.append([str(item or "").strip() for item in row])
            if idx >= 4:
                break
    if not rows:
        return "", []
    header = rows[0]
    preview_lines = [" | ".join(header)] if header else []
    anchors: list[dict[str, str]] = []
    for idx, row in enumerate(rows[1:4], start=1):
        joined = " | ".join(row)
        preview_lines.append(joined)
        anchors.append({"label": f"row{idx}", "snippet": _clip(joined, limit=110)})
    if not anchors and header:
        anchors.append({"label": "header", "snippet": _clip(" | ".join(header), limit=110)})
    return "\n".join(preview_lines), anchors


def _extract_json_preview(path: Path) -> tuple[str, list[dict[str, str]]]:
    raw = _read_text_file(path)
    payload: Any = None
    try:
        payload = json.loads(raw)
        pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        pretty = raw
    cleaned = clean_document_text(pretty, limit=6000)
    anchors = []
    if isinstance(payload, dict):
        for key in list(payload.keys())[:4]:
            anchors.append({"label": str(key), "snippet": _clip(payload.get(key), limit=110)})
    if not anchors:
        anchors = _anchors_from_text(cleaned, prefix="line")
    return cleaned, anchors[:4]


def _anchors_from_text(text: str, *, prefix: str = "line") -> list[dict[str, str]]:
    anchors: list[dict[str, str]] = []
    for idx, line in enumerate([row.strip() for row in str(text or "").splitlines() if row.strip()], start=1):
        anchors.append({"label": f"{prefix}{idx}", "snippet": _clip(line, limit=110)})
        if len(anchors) >= 4:
            break
    return anchors


def extract_document_payload(
    file_path: str | Path,
    *,
    max_chars: int = 5000,
    max_pdf_pages: int = 6,
) -> dict[str, Any]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
        return {
            "ok": False,
            "document_kind": "unsupported",
            "file_name": path.name,
            "suffix": suffix,
            "error": "unsupported_document_type",
            "manual_review_required": True,
            "manual_review_message": "Supported uploads are PDF, TXT, MD, CSV, JSON, LOG, YAML, and YML.",
            "excerpt": "",
            "anchors": [],
        }

    if suffix == ".pdf":
        pages: list[str] = []
        anchors: list[dict[str, str]] = []
        page_count = 0
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            for idx, page in enumerate(pdf.pages[: max(1, int(max_pdf_pages or 6))], start=1):
                page_text = clean_document_text(page.extract_text() or "", limit=max_chars)
                if page_text:
                    pages.append(page_text)
                    first_line = page_text.splitlines()[0] if page_text.splitlines() else f"Page {idx}"
                    anchors.append({"label": f"p{idx}", "snippet": _clip(first_line, limit=110)})
        combined = clean_document_text("\n\n".join(pages), limit=max_chars)
        ok = bool(combined.strip())
        return {
            "ok": ok,
            "document_kind": "pdf",
            "file_name": path.name,
            "suffix": suffix,
            "page_count": page_count,
            "extracted_pages": min(page_count, max(1, int(max_pdf_pages or 6))),
            "excerpt": combined,
            "anchors": anchors[:4],
            "manual_review_required": not ok,
            "manual_review_message": (
                "This PDF did not expose readable embedded text. Send page screenshots if you need scan OCR."
                if not ok
                else ""
            ),
        }

    if suffix == ".csv":
        excerpt, anchors = _extract_csv_preview(path)
    elif suffix == ".json":
        excerpt, anchors = _extract_json_preview(path)
    else:
        excerpt = clean_document_text(_read_text_file(path), limit=max_chars)
        anchors = _anchors_from_text(excerpt, prefix="line")

    return {
        "ok": bool(excerpt.strip()),
        "document_kind": "text",
        "file_name": path.name,
        "suffix": suffix,
        "page_count": 1,
        "extracted_pages": 1,
        "excerpt": excerpt,
        "anchors": anchors[:4],
        "manual_review_required": not bool(excerpt.strip()),
        "manual_review_message": "" if excerpt.strip() else "The document did not contain readable text.",
    }


def build_document_note(payload: dict[str, Any] | None) -> str:
    data = dict(payload or {})
    if not data:
        return ""
    parts = [
        f"File: {str(data.get('file_name') or 'document').strip()}",
        f"Type: {str(data.get('document_kind') or 'document').strip()}",
    ]
    page_count = int(data.get("page_count") or 0)
    if page_count:
        parts.append(f"Pages: {page_count}")
    excerpt = str(data.get("excerpt") or "")
    if excerpt:
        parts.append(f"Chars: {len(excerpt)}")
    lines = ["Document note: " + " | ".join(parts)]
    anchors = list(data.get("anchors") or [])
    if anchors:
        lines.append("Anchors:")
        for anchor in anchors[:4]:
            lines.append(f"- {anchor.get('label')}: {anchor.get('snippet')}")
    message = str(data.get("manual_review_message") or "").strip()
    if message:
        lines.append(f"Review: {message}")
    return "\n".join(lines)
