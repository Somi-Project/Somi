from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


class VisionBackendError(Exception):
    pass


def _encode_image(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise VisionBackendError(f"Image not found: {path}")
    return base64.b64encode(p.read_bytes()).decode("utf-8")


def ollama_vision_chat(
    model: str,
    prompt: str,
    image_paths: List[str],
    timeout_sec: int,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    opts = options or {}
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": opts.get("temperature", 0.0),
            "num_predict": opts.get("num_predict", 1024),
        },
    }
    if image_paths:
        payload["messages"][0]["images"] = [_encode_image(p) for p in image_paths]

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        if "image" in err_body.lower() and "support" in err_body.lower():
            raise VisionBackendError(f"Model '{model}' does not support images. Response: {err_body[:400]}")
        raise VisionBackendError(f"Ollama error {exc.code}: {err_body[:600]}") from exc
    except Exception as exc:
        raise VisionBackendError(f"Ollama request failed: {exc}") from exc

    if status != 200:
        if "image" in raw.lower() and "support" in raw.lower():
            raise VisionBackendError(f"Model '{model}' does not support images. Response: {raw[:400]}")
        raise VisionBackendError(f"Ollama error {status}: {raw[:600]}")

    try:
        data = json.loads(raw)
        content = (data.get("message") or {}).get("content", "")
    except Exception as exc:
        raise VisionBackendError(f"Invalid Ollama response: {raw[:600]}") from exc

    if not isinstance(content, str):
        raise VisionBackendError("Ollama response missing assistant content")
    return content.strip()
