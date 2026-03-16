from __future__ import annotations

from typing import Any, Dict, Optional

from config.settings import (
    DEFAULT_THINK_FALSE,
    MODEL_KEEP_ALIVE_SECONDS,
    MODELS_WITHOUT_THINK,
)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _keep_alive_seconds(model: str, role: str) -> int:
    cfg = MODEL_KEEP_ALIVE_SECONDS if isinstance(MODEL_KEEP_ALIVE_SECONDS, dict) else {}
    if role and role in cfg:
        return max(0, _coerce_int(cfg.get(role), 180))
    if model and model in cfg:
        return max(0, _coerce_int(cfg.get(model), 180))
    return max(0, _coerce_int(cfg.get("default", 180), 180))


def _supports_think(model: str) -> bool:
    disabled = {str(x).strip().lower() for x in (MODELS_WITHOUT_THINK or []) if str(x).strip()}
    return str(model or "").strip().lower() not in disabled


def build_ollama_chat_options(
    *,
    model: str,
    role: str = "default",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    think: Optional[bool] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build standardized Ollama chat options with sane defaults.

    - keep_alive is set from MODEL_KEEP_ALIVE_SECONDS by role/model.
    - think defaults to False when DEFAULT_THINK_FALSE is enabled.
    - think is omitted for models listed in MODELS_WITHOUT_THINK.
    """
    opts: Dict[str, Any] = {}

    if temperature is not None:
        opts["temperature"] = float(temperature)
    if max_tokens is not None:
        opts["max_tokens"] = int(max_tokens)

    opts["keep_alive"] = _keep_alive_seconds(str(model or ""), str(role or "default"))

    supports_think = _supports_think(str(model or ""))
    requested_think = think
    if requested_think is None and bool(DEFAULT_THINK_FALSE):
        requested_think = False
    if requested_think is not None and supports_think:
        opts["think"] = bool(requested_think)

    if isinstance(extra, dict):
        for k, v in extra.items():
            if v is not None:
                opts[k] = v

    return opts

