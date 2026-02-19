# handlers/websearch_tools/utils.py
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; SomiBot/1.0; +local)"

def normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip())

def has_year(q: str) -> bool:
    return bool(re.search(r"\b(19|20)\d{2}\b", q or ""))

def has_explicit_date(q: str) -> bool:
    # catches things like 2024-01-10 or 10/01/2024, etc.
    q = q or ""
    return bool(
        re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b", q)
        or re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", q)
        or has_year(q)
    )

def looks_like_definition(q: str) -> bool:
    ql = (q or "").lower()
    return any(x in ql for x in ["what is", "define ", "definition of", "meaning of", "what does"])

def looks_like_medical(q: str) -> bool:
    ql = (q or "").lower()
    markers = [
        "guideline", "treatment", "management", "diagnosis", "differential", "symptom", "syndrome",
        "dose", "mg", "contraindication", "side effect", "trial", "systematic review",
        "neurology", "seizure", "epilepsy", "stroke", "meningitis", "encephalopathy",
        "who guidance", "cdc", "nih", "ninds",
    ]
    return any(m in ql for m in markers)

def looks_like_coding(q: str) -> bool:
    ql = (q or "").lower()
    markers = ["python", "traceback", "error", "exception", "asyncio", "pip", "import", "module not found", "stack overflow"]
    return any(m in ql for m in markers)

def looks_like_papers(q: str) -> bool:
    ql = (q or "").lower()
    markers = ["doi", "paper", "study", "citation", "references", "journal", "preprint", "arxiv", "openalex", "crossref"]
    return any(m in ql for m in markers)

def looks_like_cs_ml(q: str) -> bool:
    ql = (q or "").lower()
    markers = ["arxiv", "transformer", "llm", "diffusion", "benchmark", "neural", "pytorch", "tensorflow", "attention", "token"]
    return any(m in ql for m in markers)

def looks_like_weather(q: str) -> bool:
    ql = (q or "").lower()
    markers = ["weather", "forecast", "temperature", "rain", "humidity", "wind", "uv", "storm", "hurricane", "sunrise", "sunset"]
    return any(m in ql for m in markers)

def extract_location_simple(q: str) -> Optional[str]:
    """
    Very lightweight.
    Extract 'in <location>' or 'for <location>' at the end of query.
    Prevents your weather misroute (no location -> don't do weather).
    """
    q = (q or "").strip()
    ql = q.lower()
    if "near me" in ql:
        return None
    m = re.search(r"\b(?:in|for)\s+([A-Za-z][A-Za-z\s\-,]{2,40})$", q)
    if m:
        loc = m.group(1).strip(" ,.-")
        return loc if loc else None
    return None

def jitter_sleep(base_s: float) -> None:
    time.sleep(base_s + random.uniform(0.05, 0.25))

def safe_preview(obj: Any, limit: int = 900) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    except Exception:
        s = str(obj)
    return (s[:limit] + "…") if len(s) > limit else s

def domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""
