from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Any

from runtime.runtime_secrets import get_runtime_secret


class ApprovalTokens:
    def __init__(self, *, ttl_s: float = 900.0, secret: str | None = None) -> None:
        self.ttl_s = float(ttl_s)
        resolved = str(secret or os.getenv("SOMI_APPROVAL_SECRET") or "").strip()
        if not resolved:
            resolved = get_runtime_secret("approval", create=True)
        self._secret = resolved or "somi-approval-secret"

    def issue(self, intent_id: str) -> str:
        token = secrets.token_urlsafe(24)
        return f"{str(intent_id or 'intent')}:{token}"

    def digest(self, token: str) -> str:
        return hmac.new(
            self._secret.encode("utf-8"),
            str(token or "").encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def build_approval_summary(ops_control: Any, *, limit: int = 12) -> dict[str, Any]:
    if ops_control is None:
        return {
            "active_profile": "",
            "active_autonomy_profile": "",
            "allowed": 0,
            "blocked": 0,
            "recent_policy_events": [],
        }
    snapshot = ops_control.snapshot(event_limit=limit)
    counts = dict(snapshot.get("policy_decision_counts") or {})
    recent_policy_events = [
        row for row in list(snapshot.get("recent_events") or []) if str(row.get("type") or "") == "policy_decision"
    ][-max(1, int(limit or 12)) :]
    return {
        "active_profile": str(dict(snapshot.get("active_profile") or {}).get("profile_id") or ""),
        "active_autonomy_profile": str(dict(snapshot.get("active_autonomy_profile") or {}).get("profile_id") or ""),
        "allowed": int(counts.get("allowed", 0)),
        "blocked": int(counts.get("blocked", 0)),
        "recent_policy_events": recent_policy_events,
    }
