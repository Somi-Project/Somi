from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ApprovalRequest:
    ticket_hash: str
    risk_tier: str
    consequence_summary: str
    required_confirm_method: str


@dataclass
class ApprovalReceipt:
    ticket_hash: str
    user_confirmed_at: str
    confirm_method: str
    typed_phrase: str | None = None
    scope: str = "one_time"
    expires_at: str | None = None


def validate_receipt(
    ticket_hash_value: str, receipt: ApprovalReceipt | None, required_level: str
) -> None:
    if receipt is None:
        raise ValueError("Approval receipt required")
    if receipt.ticket_hash != ticket_hash_value:
        raise ValueError("Approval receipt does not match ticket hash")
    if receipt.expires_at:
        if datetime.now(timezone.utc) > datetime.fromisoformat(receipt.expires_at):
            raise ValueError("Approval receipt expired")
    required = {
        "LOW": "single_click",
        "MEDIUM": "double_confirm",
        "HIGH": "typed",
        "CRITICAL": "typed",
    }
    min_method = required.get(required_level.upper(), "single_click")
    methods = {"single_click": 1, "double_confirm": 2, "typed": 3}
    got = (
        "typed" if receipt.confirm_method == "typed_phrase" else receipt.confirm_method
    )
    if methods.get(got, 0) < methods.get(min_method, 1):
        raise ValueError("Approval confirmation strength too low")
    if min_method == "typed" and receipt.confirm_method == "typed_phrase":
        if not str(receipt.typed_phrase or "").strip():
            raise ValueError("Typed confirmation requires a non-empty phrase")
