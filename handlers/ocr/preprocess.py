from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageStat
except Exception:  # pragma: no cover
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageStat = None

TMP_DIR = Path("sessions/ocr_tmp")
PREPROCESS_VERSION = "preprocess_v1"


def compute_image_metrics(image_path: str) -> Dict[str, Any]:
    if Image is None:
        size = Path(image_path).stat().st_size if Path(image_path).exists() else 0
        return {"brightness": 0.5, "blur_score": 0.5, "width": None, "height": None, "bytes": size}
    with Image.open(image_path) as img:
        gray = img.convert("L")
        stat = ImageStat.Stat(gray)
        brightness = stat.mean[0] / 255.0
        blur_score = stat.stddev[0] / 128.0
        w, h = img.size
    return {"brightness": brightness, "blur_score": blur_score, "width": w, "height": h}


def should_preprocess(metrics: Dict[str, Any], policy: str) -> bool:
    if policy == "off":
        return False
    if policy == "force":
        return True
    return (
        metrics.get("brightness", 0.5) < 0.2
        or metrics.get("brightness", 0.5) > 0.92
        or metrics.get("blur_score", 1.0) < 0.2
    )


def preprocess_image(image_path: str, metrics: Dict[str, Any]) -> str:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TMP_DIR / f"prep_{Path(image_path).name}"
    if Image is None:
        shutil.copy(image_path, out_path)
        return str(out_path)
    try:
        with Image.open(image_path) as img:
            work = img.convert("RGB")
            max_dim = 1800
            if max(work.size) > max_dim:
                work.thumbnail((max_dim, max_dim))
            if metrics.get("brightness", 0.5) < 0.3:
                work = ImageEnhance.Brightness(work).enhance(1.2)
            work = ImageEnhance.Contrast(work).enhance(1.1)
            work = work.filter(ImageFilter.SHARPEN)
            work.save(out_path)
    except Exception:
        shutil.copy(image_path, out_path)
    return str(out_path)
