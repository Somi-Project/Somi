from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List

from runtime.background_tasks import build_background_resource_budget


@dataclass
class PerfPolicy:
    load_level: str
    token_scale: float
    max_output_tokens: int
    response_timeout_seconds: float
    allow_parallel_tools: bool


class PerformanceController:
    def __init__(self, *, profile_name: str = "medium", window_size: int = 24) -> None:
        self.profile_name = str(profile_name or "medium")
        self.window_size = max(6, int(window_size))
        self.samples: List[Dict[str, Any]] = []

    def observe_turn(
        self,
        *,
        latency_ms: int,
        success: bool,
        prompt_chars: int,
        history_tokens: int,
        model_name: str,
    ) -> None:
        self.samples.append(
            {
                "ts": time.time(),
                "latency_ms": int(max(0, latency_ms)),
                "success": bool(success),
                "prompt_chars": int(max(0, prompt_chars)),
                "history_tokens": int(max(0, history_tokens)),
                "model": str(model_name or ""),
            }
        )
        if len(self.samples) > self.window_size:
            self.samples = self.samples[-self.window_size :]

    def _load_level(self) -> str:
        if not self.samples:
            return "normal"
        latencies = [int(s.get("latency_ms") or 0) for s in self.samples]
        avg = sum(latencies) / max(1, len(latencies))
        failure_ratio = sum(1 for s in self.samples if not bool(s.get("success", True))) / max(1, len(self.samples))

        if avg >= 22000 or failure_ratio >= 0.35:
            return "critical"
        if avg >= 14000 or failure_ratio >= 0.20:
            return "high"
        if avg >= 8500 or failure_ratio >= 0.10:
            return "medium"
        return "normal"

    def current_load_level(self) -> str:
        return self._load_level()

    def policy_for_turn(self, *, requested_max_tokens: int, should_search: bool) -> PerfPolicy:
        level = self._load_level()

        if level == "critical":
            scale = 0.55
            timeout = 85.0
            parallel = False
        elif level == "high":
            scale = 0.70
            timeout = 105.0
            parallel = False
        elif level == "medium":
            scale = 0.85
            timeout = 125.0
            parallel = bool(should_search)
        else:
            scale = 1.0
            timeout = 150.0
            parallel = bool(should_search)

        cap = max(128, int(int(requested_max_tokens or 256) * scale))
        return PerfPolicy(
            load_level=level,
            token_scale=scale,
            max_output_tokens=cap,
            response_timeout_seconds=timeout,
            allow_parallel_tools=parallel,
        )

    def background_budget_hint(self) -> dict[str, Any]:
        return build_background_resource_budget(load_level=self._load_level())

    def reorder_models_for_load(self, models: List[str]) -> List[str]:
        rows = [str(m or "").strip() for m in list(models or []) if str(m or "").strip()]
        if not rows:
            return []

        level = self._load_level()
        if level not in {"high", "critical"}:
            return rows

        def weight(name: str) -> int:
            n = name.lower()
            if any(x in n for x in ("72b", "70b", "67b")):
                return 5
            if any(x in n for x in ("32b", "34b")):
                return 4
            if any(x in n for x in ("14b", "13b", "15b")):
                return 3
            if any(x in n for x in ("8b", "7b", "9b")):
                return 2
            return 1

        # Preserve options but prefer smaller models under load.
        return sorted(rows, key=lambda x: weight(x))
