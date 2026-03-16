from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Any, Dict


_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"reveal\s+(the\s+)?system\s+prompt",
    r"developer\s+message",
    r"jailbreak",
    r"act\s+as\s+system",
    r"bypass\s+safety",
)
_RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def sanitize_untrusted_text(text: str, *, max_len: int = 800) -> str:
    raw = str(text or "")
    # Strip code-fence wrappers and control chars that often carry prompt-injection payloads.
    raw = raw.replace("```", " ")
    raw = "".join(ch for ch in raw if ch >= " " or ch in "\n\t")
    raw = re.sub(r"\s+", " ", raw).strip()

    for pat in _INJECTION_PATTERNS:
        raw = re.sub(pat, "[filtered]", raw, flags=re.IGNORECASE)

    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1].rstrip() + "..."


def sanitize_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            return sanitize_untrusted_text(value, max_len=1200)
        if isinstance(value, dict):
            return {str(k): _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        return value

    for k, v in dict(args or {}).items():
        out[str(k)] = _walk(v)

    # Tighten query length for web-like tools.
    tn = str(tool_name or "").lower()
    if "web" in tn or "search" in tn:
        q = str(out.get("query") or "").strip()
        out["query"] = sanitize_untrusted_text(q, max_len=420)

    return out


def normalize_execution_backend(value: Any, *, default: str = "local") -> str:
    raw = str(value or default).strip().lower()
    aliases = {
        "shell": "local",
        "subprocess": "local",
        "process": "local",
        "desktop": "local",
        "cli": "local",
        "container": "docker",
        "ssh": "remote",
        "k8s": "remote",
    }
    return aliases.get(raw, raw or default)


def normalize_delivery_channel(value: Any, *, default: str = "chat") -> str:
    raw = str(value or default).strip().lower()
    aliases = {
        "desktop": "gui",
        "ui": "gui",
        "telegram_bot": "telegram",
        "voice_chat": "voice",
        "scheduled": "automation",
    }
    return aliases.get(raw, raw or default)


def normalize_risk_tier(value: Any) -> str:
    tier = str(value or "LOW").strip().upper()
    if tier == "MED":
        tier = "MEDIUM"
    if tier not in _RISK_ORDER:
        return "LOW"
    return tier


def risk_exceeds(tool_risk: Any, max_risk: Any) -> bool:
    normalized_tool = normalize_risk_tier(tool_risk)
    normalized_max = normalize_risk_tier(max_risk)
    return _RISK_ORDER[normalized_tool] > _RISK_ORDER[normalized_max]


def tool_allows_backend(tool_entry: Dict[str, Any], backend: str) -> bool:
    requested = normalize_execution_backend(backend)
    allowed = [
        normalize_execution_backend(item)
        for item in list(
            (dict(tool_entry or {}).get("backends"))
            or (dict(dict(tool_entry or {}).get("runtime") or {}).get("backends"))
            or ["local"]
        )
    ]
    return requested in set(allowed or ["local"])


def tool_allows_channel(tool_entry: Dict[str, Any], channel: str) -> bool:
    requested = normalize_delivery_channel(channel)
    allowed = [
        normalize_delivery_channel(item)
        for item in list(dict(tool_entry or {}).get("channels") or ["chat"])
    ]
    exposure = dict(dict(tool_entry or {}).get("exposure") or {})
    if requested == "gui" and not bool(exposure.get("ui", True)):
        return False
    if requested in {"chat", "voice", "telegram", "api"} and not bool(exposure.get("agent", True)):
        return False
    if requested == "automation" and not bool(exposure.get("automation", False)):
        return False
    return requested in set(allowed or ["chat"])


def trust_tier_for_domain(domain: str) -> int:
    d = str(domain or "").strip().lower()
    if not d:
        return 0
    if d.endswith(".gov") or d.endswith(".edu"):
        return 3
    if any(d.endswith(x) for x in (".org", "nature.com", "science.org", "who.int", "nih.gov", "cdc.gov")):
        return 3
    if any(x in d for x in ("reuters.com", "apnews.com", "bbc.", "ft.com", "wsj.com", "bloomberg.com")):
        return 2
    if any(x in d for x in ("github.com", "readthedocs.io", "developer.mozilla.org")):
        return 2
    if d in {"localhost", "127.0.0.1", "::1"}:
        return 0
    return 1


def trust_label(tier: int) -> str:
    t = int(tier)
    if t >= 3:
        return "high"
    if t == 2:
        return "medium"
    if t == 1:
        return "low"
    return "blocked"


def domain_from_url(url: str) -> str:
    try:
        return urlparse(str(url or "")).netloc.lower().strip()
    except Exception:
        return ""
