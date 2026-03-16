from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_templates() -> Dict[str, Any]:
    path = Path("config/ocr_templates.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def match_template(image_path: str) -> Optional[str]:
    templates = load_templates()
    stem = Path(str(image_path or "")).stem.lower()
    for template_id in templates:
        token = str(template_id or "").lower().replace("_v1", "")
        if token and any(part for part in token.split("_") if part and part in stem):
            return template_id
    return None


def crop_rois(image_path: str, template_id: str) -> Dict[str, str]:
    raise NotImplementedError("ROI cropping is not implemented in v1")

