from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from handlers.ocr.contracts import OcrRequest

CACHE_DIR = Path("sessions/ocr_cache")


def compute_cache_key(req: OcrRequest, provenance: Dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "images": provenance.get("image_hashes", []),
            "model": provenance.get("model"),
            "prompt_version": provenance.get("prompt_version"),
            "preprocess_version": provenance.get("preprocess_version"),
            "schema_id": req.schema_id,
            "template_id": req.template_id,
            "mode": req.mode,
            "prompt": req.prompt,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_get(key: str) -> Optional[Dict[str, Any]]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if time.time() > data.get("expires_at", 0):
        return None
    return data.get("payload")


def cache_put(key: str, payload: Dict[str, Any]) -> None:
    from config import settings

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ttl_days = int(getattr(settings, "OCR_CACHE_TTL_DAYS", 30))
    doc = {
        "created_at": time.time(),
        "expires_at": time.time() + ttl_days * 86400,
        "payload": payload,
    }
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def prune_cache(max_items: int) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max_items:]:
        old.unlink(missing_ok=True)
