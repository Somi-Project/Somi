from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from config.settings import SESSION_MEDIA_DIR

try:
    import requests
except Exception as e:
    requests = None
    _REQUESTS_IMPORT_ERROR = e
else:
    _REQUESTS_IMPORT_ERROR = None

from .charts import ImageAttachment


def _ensure_requests_ready() -> None:
    if requests is None:
        detail = f": {_REQUESTS_IMPORT_ERROR}" if _REQUESTS_IMPORT_ERROR else ""
        raise RuntimeError(f"requests dependency unavailable{detail}")


def _default_txt2img_workflow(prompt: str) -> Dict[str, Any]:
    return {
        "3": {"class_type": "KSampler", "inputs": {"seed": int(time.time()), "steps": 20, "cfg": 8, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality, blurry", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "somi", "images": ["8", 0]}},
    }


def _download_output_image(base_url: str, image_meta: Dict[str, Any], out_dir: str = SESSION_MEDIA_DIR) -> str:
    _ensure_requests_ready()
    os.makedirs(out_dir, exist_ok=True)
    filename = str(image_meta.get("filename") or "").strip()
    if not filename:
        raise ValueError("ComfyUI output metadata missing filename")
    params = {
        "filename": filename,
        "subfolder": image_meta.get("subfolder", ""),
        "type": image_meta.get("type", "output"),
    }
    resp = requests.get(f"{base_url}/view", params=params, timeout=45)
    resp.raise_for_status()
    ext = os.path.splitext(filename)[1] or ".png"
    local_path = os.path.join(out_dir, f"comfy_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}{ext}")
    with open(local_path, "wb") as f:
        f.write(resp.content)
    return local_path


def generate_comfyui_image(
    prompt: str,
    base_url: str,
    timeout_s: int = 120,
    workflow: Optional[Dict[str, Any]] = None,
    out_dir: str = SESSION_MEDIA_DIR,
) -> ImageAttachment:
    _ensure_requests_ready()
    client_id = f"somi-{uuid.uuid4()}"
    payload = {
        "prompt": workflow or _default_txt2img_workflow(prompt),
        "client_id": client_id,
    }
    queue_resp = requests.post(f"{base_url}/prompt", json=payload, timeout=20)
    queue_resp.raise_for_status()
    queued = queue_resp.json()
    prompt_id = queued.get("prompt_id")
    if not prompt_id:
        raise ValueError(f"ComfyUI did not return prompt_id: {json.dumps(queued)}")

    start = time.time()
    while time.time() - start < timeout_s:
        hist_resp = requests.get(f"{base_url}/history/{prompt_id}", timeout=20)
        hist_resp.raise_for_status()
        history = hist_resp.json()
        run_data = history.get(prompt_id) if isinstance(history, dict) else None
        outputs = (run_data or {}).get("outputs", {})
        for node_data in outputs.values():
            images = node_data.get("images") if isinstance(node_data, dict) else None
            if images:
                image_path = _download_output_image(base_url, images[0], out_dir=out_dir)
                return ImageAttachment(type="image", path=image_path, title=f"ComfyUI: {prompt[:60]}")
        time.sleep(1.0)

    raise TimeoutError("ComfyUI image generation timed out")
