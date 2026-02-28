from __future__ import annotations

import hmac
import json
import time
import uuid
from pathlib import Path

from executive.approvals import ApprovalTokens
from executive.budgets import ExecutiveBudgets
from executive.queue import ExecutiveQueue
from executive.signals import suggest_hello_intent
from handlers.toolbox_handler import create_tool_job
from runtime.errors import RateLimitError


class ExecutiveEngine:
    def __init__(self):
        self.budgets = ExecutiveBudgets()
        self.queue = ExecutiveQueue()
        self.approvals = ApprovalTokens()
        self.state_path = Path("executive/state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.paused = self._load_paused()

    def _load_paused(self) -> bool:
        if not self.state_path.exists():
            return False
        try:
            return bool(json.loads(self.state_path.read_text(encoding="utf-8")).get("paused", False))
        except Exception:
            return False

    def _save_paused(self) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"paused": self.paused}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def set_paused(self, paused: bool) -> dict:
        self.paused = bool(paused)
        self._save_paused()
        return {"paused": self.paused}

    def tick(self):
        if self.paused:
            return {"paused": True, "message": "Executive is paused"}
        try:
            self.budgets.allow_intent()
        except RateLimitError:
            return {"error": "rate_limited", "message": "Executive intent budget exceeded. Try again later."}
        intent = suggest_hello_intent()
        intent_id = str(uuid.uuid4())[:8]
        token = self.approvals.issue(intent_id)
        intent["intent_id"] = intent_id
        intent["state"] = "PENDING"
        intent["approval_token_hash"] = self.approvals.digest(token)
        intent["approval_expires_at"] = time.time() + float(self.approvals.ttl_s)
        self.queue.push(intent)

        # Return one-time plaintext token to caller, do not persist it in queue.
        ret = dict(intent)
        ret.pop("approval_token_hash", None)
        ret["approval_token"] = token
        return ret

    def approve_and_run(self, intent_id: str, approval_token: str | None = None):
        if self.paused:
            return {"error": "executive paused"}

        item = next((it for it in self.queue.list() if it.get("intent_id") == intent_id), None)
        if not item:
            return {"error": "intent not found"}
        if item.get("state") != "PENDING":
            return {"error": f"intent not pending: {item.get('state')}"}

        token = str(approval_token or "")
        expected_hash = str(item.get("approval_token_hash", ""))
        actual_hash = self.approvals.digest(token)
        if not hmac.compare_digest(actual_hash, expected_hash):
            return {"error": "approval token invalid or expired"}

        try:
            expires_at = float(item.get("approval_expires_at", 0))
        except (TypeError, ValueError):
            expires_at = 0
        if time.time() >= expires_at:
            self.queue.set_state(intent_id, "EXPIRED")
            return {"error": "approval token invalid or expired"}

        self.queue.set_state(intent_id, "APPROVED")
        p = item.get("payload", {})
        return create_tool_job(p.get("name", "hello_tool"), p.get("description", ""), active=False)
