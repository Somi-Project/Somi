from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional, Set

import numpy as np

VOLATILE_KEYWORDS = [
    "price", "stock", "bitcoin", "crypto", "ethereum", "solana", "market",
    "weather", "forecast", "current time", "today", "breaking", "news", "scores",
    "live", "now", "latest",
]


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokenize(text: str) -> Set[str]:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s:]+", " ", text)
    return {t for t in text.split()[:64] if len(t) > 1}


def is_volatile(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in VOLATILE_KEYWORDS)


def normalize_embedding(vec: np.ndarray) -> Optional[np.ndarray]:
    v = np.asarray(vec, dtype=np.float32)
    v = np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)
    n = float(np.linalg.norm(v))
    if n <= 1e-10:
        return None
    return v / n
