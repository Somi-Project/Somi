from __future__ import annotations

import os


def detect_hardware() -> dict:
    cpus = os.cpu_count() or 1
    return {"cpus": cpus, "vram_gb": None}


def resolve_runtime_config(mode: str = "standard", vram: int | None = None, overrides: dict | None = None) -> dict:
    base = {
        "fast": {"workers": 2, "timeout_s": 20},
        "standard": {"workers": 1, "timeout_s": 40},
        "quality": {"workers": 1, "timeout_s": 60},
    }.get(mode, {"workers": 1, "timeout_s": 40}).copy()
    if vram is not None and vram < 4:
        base["workers"] = 1
    if overrides:
        base.update(overrides)
    return base
