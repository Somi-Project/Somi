from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from config.settings import COMFYUI_PORT, SESSION_MEDIA_DIR

from .charts import ImageAttachment, bar_chart, line_chart


_CHART_WORDS = ("chart", "graph", "plot", "bar chart", "bar graph", "line chart")
_COMFY_WORDS = (
    "generate me a picture",
    "make a pic",
    "do a pic",
    "a pic would be nice",
    "generate an image",
    "create an image",
    "generate a photo",
    "create a photo",
)


def infer_image_intent(prompt: str) -> Optional[str]:
    pl = (prompt or "").lower()
    if any(w in pl for w in _CHART_WORDS):
        return "chart"
    if any(w in pl for w in _COMFY_WORDS) or re.search(r"\b(generate|create|make|draw)\s+(me\s+)?(an?\s+)?(image|picture|pic|photo|artwork|illustration)\b", pl):
        return "comfyui"
    return None


def _coerce_chart_spec_from_prompt(prompt: str) -> Dict[str, Any]:
    # Best-effort fallback when caller didn't pass a strict JSON spec.
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", prompt)]
    is_line = "line" in prompt.lower()
    if is_line:
        x = list(range(1, len(nums) + 1)) or [1, 2, 3]
        y = nums or [1, 2, 3]
        return {"kind": "line", "title": "Line Chart", "x": x, "y": y, "x_label": "Index", "y_label": "Value"}
    labels = [f"Item {i+1}" for i in range(max(1, len(nums) or 3))]
    values = nums or [1, 2, 3]
    return {"kind": "bar", "title": "Bar Chart", "labels": labels[:len(values)], "values": values, "y_label": "Value"}


def generate_image(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    spec example:
    {
      "kind": "bar",
      "title": "...",
      "labels": [...],
      "values": [...],
      "y_label": "Count"
    }
    """
    kind = (spec.get("kind") or "").strip().lower()
    if kind == "bar":
        att: ImageAttachment = bar_chart(
            title=spec.get("title", ""),
            labels=spec.get("labels", []),
            values=spec.get("values", []),
            y_label=spec.get("y_label"),
            out_dir=str(spec.get("out_dir") or SESSION_MEDIA_DIR),
        )
        return [att.__dict__]

    if kind == "line":
        att = line_chart(
            title=spec.get("title", ""),
            x=spec.get("x", []),
            y=spec.get("y", []),
            x_label=spec.get("x_label"),
            y_label=spec.get("y_label"),
            out_dir=str(spec.get("out_dir") or SESSION_MEDIA_DIR),
        )
        return [att.__dict__]

    if kind in {"comfy", "comfyui", "image"}:
        prompt = (spec.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("ComfyUI image generation requires spec.prompt")
        base_url = str(spec.get("base_url") or f"http://127.0.0.1:{int(COMFYUI_PORT)}").strip()
        if base_url and "://" not in base_url:
            base_url = f"http://{base_url}"
        try:
            timeout_s = max(10, int(spec.get("timeout_s", 120)))
        except Exception:
            timeout_s = 120
        from .comfyui import generate_comfyui_image
        att = generate_comfyui_image(
            prompt=prompt,
            base_url=base_url,
            timeout_s=timeout_s,
            out_dir=str(spec.get("out_dir") or SESSION_MEDIA_DIR),
        )
        return [att.__dict__]

    raise ValueError(f"Unsupported image kind: {kind}")


def spec_from_text(prompt: str, provided_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if provided_spec is not None:
        if not isinstance(provided_spec, dict):
            raise ValueError("provided_spec must be a dict")
        direct = dict(provided_spec)
        nested = direct.get("spec")
        if isinstance(nested, dict):
            return dict(nested)
        return direct

    stripped = (prompt or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            maybe = json.loads(stripped)
            if isinstance(maybe, dict):
                return maybe.get("spec", maybe)
        except json.JSONDecodeError:
            pass

    intent = infer_image_intent(prompt or "")
    if intent == "chart":
        return _coerce_chart_spec_from_prompt(prompt or "")
    if intent == "comfyui":
        return {"kind": "comfyui", "prompt": prompt}
    raise ValueError("Could not infer image generation spec")
