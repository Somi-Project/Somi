"""Model and hardware capability profiles.

This module centralizes model-related settings and context capability tiers.
GUI profile switching can update `MODEL_CAPABILITY_PROFILE` to adjust quality/speed.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict


PROFILE_LOW = "low"
PROFILE_MEDIUM = "medium"
PROFILE_HIGH = "high"
PROFILE_VERY_HIGH = "very_high"
PROFILE_ULTRA = "ultra"

MODEL_CAPABILITY_PROFILE = PROFILE_MEDIUM

MODEL_PROFILE_ALIASES = {
    "very high": PROFILE_VERY_HIGH,
    "very-high": PROFILE_VERY_HIGH,
    "very_high": PROFILE_VERY_HIGH,
    "vh": PROFILE_VERY_HIGH,
}

MODEL_CAPABILITY_PROFILES: Dict[str, Dict[str, Any]] = {
    PROFILE_LOW: {
        "general_model": "qwen2.5:3b-instruct",
        "instruct_model": "stable-code:3b",
        "coding_model": "stable-code:3b",
        "memory_model": "phi3:3.8b",
        "vision_model": "qwen2.5vl:3b",
        "scraper_model": "qwen2.5:1.5b",
        "default_temp": 0.35,
        "max_context_tokens": 4096,
        "chat_context_profile": "4k",
        "history_max_messages": 6,
        "default_max_new_tokens": 320,
        "response_token_soft_limit": 220,
        "prompt_budget_evidence": 900,
        "prompt_budget_history": 1400,
        "prompt_budget_user_reserve": 320,
    },
    PROFILE_MEDIUM: {
        "general_model": "qwen3:8b",
        "instruct_model": "stable-code:3b",
        "coding_model": "stable-code:3b",
        "memory_model": "phi3:3.8b",
        "vision_model": "qwen3.5:9b",
        "scraper_model": "qwen3.5:0.8b",
        "default_temp": 0.4,
        "max_context_tokens": 8192,
        "chat_context_profile": "8k",
        "history_max_messages": 10,
        "default_max_new_tokens": 512,
        "response_token_soft_limit": 300,
        "prompt_budget_evidence": 1200,
        "prompt_budget_history": 2200,
        "prompt_budget_user_reserve": 450,
    },
    PROFILE_HIGH: {
        "general_model": "qwen3:14b",
        "instruct_model": "qwen3:8b",
        "coding_model": "qwen2.5-coder:7b",
        "memory_model": "phi3:14b",
        "vision_model": "qwen2.5vl:7b",
        "scraper_model": "qwen3:4b",
        "default_temp": 0.45,
        "max_context_tokens": 16384,
        "chat_context_profile": "16k",
        "history_max_messages": 18,
        "default_max_new_tokens": 768,
        "response_token_soft_limit": 420,
        "prompt_budget_evidence": 1600,
        "prompt_budget_history": 4200,
        "prompt_budget_user_reserve": 700,
    },
    PROFILE_VERY_HIGH: {
        "general_model": "qwen3:32b",
        "instruct_model": "qwen3:14b",
        "coding_model": "qwen2.5-coder:14b",
        "memory_model": "qwen3:14b",
        "vision_model": "qwen2.5vl:32b",
        "scraper_model": "qwen3:8b",
        "default_temp": 0.45,
        "max_context_tokens": 24576,
        "chat_context_profile": "32k",
        "history_max_messages": 24,
        "default_max_new_tokens": 1024,
        "response_token_soft_limit": 550,
        "prompt_budget_evidence": 2000,
        "prompt_budget_history": 6000,
        "prompt_budget_user_reserve": 900,
    },
    PROFILE_ULTRA: {
        "general_model": "qwen3:72b",
        "instruct_model": "qwen3:32b",
        "coding_model": "qwen2.5-coder:32b",
        "memory_model": "qwen3:32b",
        "vision_model": "qwen2.5vl:72b",
        "scraper_model": "qwen3:14b",
        "default_temp": 0.5,
        "max_context_tokens": 32768,
        "chat_context_profile": "32k",
        "history_max_messages": 32,
        "default_max_new_tokens": 1280,
        "response_token_soft_limit": 720,
        "prompt_budget_evidence": 2600,
        "prompt_budget_history": 8200,
        "prompt_budget_user_reserve": 1200,
    },
}

AVAILABLE_MODEL_CAPABILITY_PROFILES = tuple(MODEL_CAPABILITY_PROFILES.keys())


def normalize_model_profile(name: str | None) -> str:
    key = str(name or "").strip().lower()
    if not key:
        return PROFILE_MEDIUM
    key = MODEL_PROFILE_ALIASES.get(key, key)
    if key in MODEL_CAPABILITY_PROFILES:
        return key
    return PROFILE_MEDIUM


def get_active_model_profile_name(profile_name: str | None = None) -> str:
    env = os.getenv("SOMI_MODEL_PROFILE", "")
    return normalize_model_profile(profile_name or env or MODEL_CAPABILITY_PROFILE)


def get_model_profile(profile_name: str | None = None) -> Dict[str, Any]:
    resolved = get_active_model_profile_name(profile_name)
    return deepcopy(MODEL_CAPABILITY_PROFILES.get(resolved, MODEL_CAPABILITY_PROFILES[PROFILE_MEDIUM]))
