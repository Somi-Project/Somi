from __future__ import annotations

import re
import time
from pathlib import Path

from config import settings
from workshop.toolbox.stacks.ocr_core.contracts import OcrQualityReport, OcrRequest, OcrResult
from workshop.toolbox.stacks.ocr_core.exports import export_general_excel, export_json, get_output_folder
from workshop.toolbox.stacks.ocr_core.preprocess import compute_image_metrics, preprocess_image, should_preprocess
from workshop.toolbox.stacks.ocr_core.prompts import general_ocr_prompt, vision_analysis_prompt, vision_fallback_prompt
from workshop.toolbox.stacks.ocr_core.quality import score_general, should_escalate_general, unk_ratio
from workshop.toolbox.stacks.ocr_core.vision_backend import VisionBackendError, ollama_vision_chat


LOW_SIGNAL_ANALYSIS_MARKERS = [
    "not readable",
    "cannot be read",
    "can't be read",
    "cannot be conducted",
    "no analysis",
    "unable to analyze",
    "unable to analyse",
    "image is unreadable",
    "cannot determine",
    "insufficient detail",
]


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


def _is_unknownish(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return True
    norm = re.sub(r"[^A-Za-z\[\]]", "", clean).upper()
    if norm in {"UNK", "[UNK]", "UNKNOWN", "N/A", "NA"}:
        return True
    words = clean.split()
    if not words:
        return True
    unk_tokens = 0
    for w in words:
        token = re.sub(r"[^A-Za-z\[\]]", "", w).upper()
        if token in {"UNK", "[UNK]", "UNKNOWN"}:
            unk_tokens += 1
    return (unk_tokens / max(1, len(words))) >= 0.7


def _is_low_signal_analysis(text: str) -> bool:
    clean = (text or "").strip()
    if _is_unknownish(clean):
        return True
    lower = clean.lower()
    if len(clean) < 24:
        return True
    return any(marker in lower for marker in LOW_SIGNAL_ANALYSIS_MARKERS)


def _resolve_vision_models(req: OcrRequest) -> list[str]:
    explicit = req.options.get("model")
    primary = explicit or getattr(settings, "VISION_ANALYSIS_MODEL", None) or settings.VISION_MODEL
    candidates: list[str] = []
    if primary:
        candidates.append(str(primary))

    configured = getattr(settings, "VISION_ANALYSIS_FALLBACK_MODELS", []) or []
    for m in configured:
        if m:
            candidates.append(str(m))

    fast = getattr(settings, "OCR_FAST_MODEL", None)
    if fast:
        candidates.append(str(fast))

    if getattr(settings, "VISION_MODEL", None):
        candidates.append(str(settings.VISION_MODEL))

    seen: set[str] = set()
    ordered: list[str] = []
    for m in candidates:
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered


def _run_vision_inference(model: str, prompt: str, image_paths: list[str], timeout: int) -> str:
    chunks: list[str] = []
    for idx, img in enumerate(image_paths, start=1):
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
        chunks.append(f"=== IMAGE {idx} ===\n{text}" if len(image_paths) > 1 else text)
    return "\n\n".join(chunks).strip()


def general_ocr(req: OcrRequest) -> OcrResult:
    t0 = time.time()
    requested_model = req.options.get("model") or settings.VISION_MODEL
    timeout = int(req.options.get("timeout_sec", getattr(settings, "OCR_TIMEOUT_SEC", 120)))
    policy = req.options.get("preprocess_policy", getattr(settings, "OCR_PREPROCESS_POLICY", "auto"))
    max_passes = int(getattr(settings, "OCR_MAX_PASSES", 2))
    is_vision_mode = str(getattr(req, "mode", "")).lower() == "vision"

    metrics = _aggregate_metrics(req.image_paths)
    active_images = list(req.image_paths)
    preprocessed = False
    if should_preprocess(metrics, policy):
        active_images = [preprocess_image(p, metrics) for p in req.image_paths]
        preprocessed = True

    raw_text = ""
    reasons: list[str] = []
    score = 0.0
    model_used = str(requested_model)

    if is_vision_mode:
        prompts = [vision_analysis_prompt(req.prompt)]
        if bool(getattr(settings, "VISION_ANALYSIS_SECOND_PROMPT", True)):
            prompts.append(vision_fallback_prompt(req.prompt))

        last_error = ""
        vision_models = _resolve_vision_models(req)
        for model_candidate in vision_models:
            for prompt_idx, prompt in enumerate(prompts):
                try:
                    candidate_text = _run_vision_inference(model_candidate, prompt, active_images, timeout)
                except VisionBackendError as exc:
                    last_error = str(exc)
                    continue

                if not _is_low_signal_analysis(candidate_text):
                    raw_text = candidate_text
                    model_used = model_candidate
                    score = min(1.0, 0.45 + (min(len(raw_text), 1200) / 1200.0) * 0.55)
                    reasons = []
                    if prompt_idx > 0:
                        reasons.append("vision_second_prompt")
                    if vision_models and model_candidate != vision_models[0]:
                        reasons.append("vision_fallback_model")
                    break

                raw_text = candidate_text
                model_used = model_candidate
                reasons = ["vision_low_confidence"]

            if raw_text and not _is_low_signal_analysis(raw_text):
                break

        if not raw_text or _is_low_signal_analysis(raw_text):
            if last_error:
                reasons = ["vision_backend_error", "vision_low_confidence"]
            raw_text = (
                "I couldn't reliably analyze this image yet. "
                "Try a clearer/cropped image, or ask a targeted prompt like 'extract visible text' or 'describe objects only'."
            )
            score = 0.15

    else:
        model = str(requested_model)
        model_used = model
        prompt = general_ocr_prompt(req.prompt)
        for _ in range(max_passes):
            try:
                raw_text = _run_vision_inference(model, prompt, active_images, timeout)
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
    suffix = "_vision" if is_vision_mode else ""
    txt_path = Path(get_output_folder()) / f"{base_name}{suffix}.txt"
    txt_path.write_text(raw_text, encoding="utf-8")

    excel_path = ""
    if not is_vision_mode:
        excel_path = export_general_excel(raw_text, f"{base_name}{suffix}")

    json_suffix = "_vision" if is_vision_mode else "_general"
    json_path = export_json(
        {
            "raw_text": raw_text,
            "metrics": metrics,
            "mode": "vision" if is_vision_mode else "general",
            "reasons": reasons,
            "model_used": model_used,
        },
        base_name + json_suffix,
    )

    quality = OcrQualityReport(
        unk_ratio=unk_ratio(raw_text),
        image_metrics=metrics,
        escalated=bool(reasons),
        reasons=reasons,
        score=score,
        record_count=0,
        escalation_level="warning" if reasons else "none",
        manual_review_required=bool(reasons),
        manual_review_message=("Manual review recommended because: " + ", ".join(reasons[:4])) if reasons else "",
    )
    return OcrResult(
        raw_text=raw_text,
        structured_records=None,
        structured_text=None,
        exports={"txt_path": str(txt_path.resolve()), "excel_path": excel_path, "json_path": json_path},
        quality=quality,
        provenance={"model": model_used, "preprocessed": preprocessed},
        debug={"latency_sec": round(time.time() - t0, 3)},
    )

