from __future__ import annotations

import time
from pathlib import Path

from config import settings
from handlers.ocr.contracts import OcrQualityReport, OcrRequest, OcrResult
from handlers.ocr.exports import export_general_excel, export_json, get_output_folder
from handlers.ocr.preprocess import compute_image_metrics, preprocess_image, should_preprocess
from handlers.ocr.prompts import general_ocr_prompt
from handlers.ocr.quality import score_general, should_escalate_general, unk_ratio
from handlers.ocr.vision_backend import VisionBackendError, ollama_vision_chat


def _aggregate_metrics(image_paths: list[str]) -> dict:
    metrics_list = [compute_image_metrics(p) for p in image_paths]
    if not metrics_list:
        return {}
    def _avg(name: str, default: float = 0.0) -> float:
        vals = [float(m.get(name, default)) for m in metrics_list if m.get(name) is not None]
        return (sum(vals) / len(vals)) if vals else default
    return {
        "count": len(metrics_list),
        "brightness": _avg("brightness", 0.5),
        "blur_score": _avg("blur_score", 0.5),
        "width_max": max([(m.get("width") or 0) for m in metrics_list], default=0),
        "height_max": max([(m.get("height") or 0) for m in metrics_list], default=0),
        "per_image": metrics_list,
    }


def general_ocr(req: OcrRequest) -> OcrResult:
    t0 = time.time()
    model = req.options.get("model") or settings.VISION_MODEL
    timeout = int(req.options.get("timeout_sec", getattr(settings, "OCR_TIMEOUT_SEC", 120)))
    policy = req.options.get("preprocess_policy", getattr(settings, "OCR_PREPROCESS_POLICY", "auto"))
    max_passes = int(getattr(settings, "OCR_MAX_PASSES", 2))

    metrics = _aggregate_metrics(req.image_paths)
    active_images = list(req.image_paths)
    preprocessed = False
    if should_preprocess(metrics, policy):
        active_images = [preprocess_image(p, metrics) for p in req.image_paths]
        preprocessed = True

    prompt = general_ocr_prompt(req.prompt)
    raw_text = ""
    reasons: list[str] = []
    score = 0.0
    for _ in range(max_passes):
        chunks: list[str] = []
        try:
            for idx, img in enumerate(active_images, start=1):
                text = ollama_vision_chat(
                    model=model,
                    prompt=prompt,
                    image_paths=[img],
                    timeout_sec=timeout,
                    options={
                        "temperature": getattr(settings, "OCR_TEMPERATURE", 0.0),
                        "num_predict": getattr(settings, "OCR_NUM_PREDICT", 1024),
                    },
                )
                chunks.append(f"=== IMAGE {idx} ===\n{text}" if len(active_images) > 1 else text)
            raw_text = "\n\n".join(chunks).strip()
        except VisionBackendError as exc:
            raw_text = f"OCR error: {exc}"
            reasons = ["vision_backend_error"]
            break

        score, reasons = score_general(raw_text, metrics)
        u = unk_ratio(raw_text)
        escalate, esc_reasons = should_escalate_general(
            score,
            u,
            metrics,
            {"min_score": 0.65, "max_unk_ratio": getattr(settings, "OCR_MAX_UNK_RATIO", 0.05)},
        )
        if not (getattr(settings, "OCR_SECOND_PASS", True) and escalate and max_passes > 1):
            reasons = esc_reasons or reasons
            break
        active_images = [preprocess_image(p, metrics) for p in req.image_paths]
        preprocessed = True
        prompt = general_ocr_prompt("RETRY STRICTLY. Preserve text exactly.")

    base_name = Path(req.image_paths[0]).stem
    txt_path = Path(get_output_folder()) / f"{base_name}.txt"
    txt_path.write_text(raw_text, encoding="utf-8")
    excel_path = export_general_excel(raw_text, base_name)
    json_path = export_json({"raw_text": raw_text, "metrics": metrics}, base_name + "_general")

    quality = OcrQualityReport(
        unk_ratio=unk_ratio(raw_text),
        image_metrics=metrics,
        escalated=bool(reasons),
        reasons=reasons,
        score=score,
    )
    return OcrResult(
        raw_text=raw_text,
        structured_records=None,
        structured_text=None,
        exports={"txt_path": str(txt_path.resolve()), "excel_path": excel_path, "json_path": json_path},
        quality=quality,
        provenance={"model": model, "preprocessed": preprocessed},
        debug={"latency_sec": round(time.time() - t0, 3)},
    )
