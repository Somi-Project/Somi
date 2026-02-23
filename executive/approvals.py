from __future__ import annotations

import hashlib
import secrets


class ApprovalTokens:
    def __init__(self, ttl_s: int = 3600):
        self.ttl_s = ttl_s

    def issue(self, intent_id: str) -> str:
        return f"appr-{intent_id}-{secrets.token_urlsafe(24)}"

    def digest(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
