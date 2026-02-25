from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ApprovalRequest:
    ticket_hash: str
    risk_tier: str
    explanation: str
    potential_outcomes: list[str]
    confirmation_requirement: str


@dataclass
class ApprovalReceipt:
    """Backward/forward compatible approval receipt.

    Supports both legacy fields (`user_confirmed_at`, `confirm_method`) and
    new fields (`timestamp`, `confirmation_method`).
    """

    ticket_hash: str
    confirmation_method: str | None = None
    timestamp: str | None = None
    expiry: str | None = None
    typed_phrase: str | None = None
    # Legacy aliases kept for interoperability
    user_confirmed_at: str | None = None
    confirm_method: str | None = None

    def __post_init__(self) -> None:
        if not self.confirmation_method and self.confirm_method:
            self.confirmation_method = self.confirm_method
        if not self.timestamp and self.user_confirmed_at:
            self.timestamp = self.user_confirmed_at


def validate_receipt(
    ticket_hash_value: str, receipt: ApprovalReceipt | None, required_level: str
) -> None:
    if receipt is None:
        raise ValueError("Approval receipt required")
    if receipt.ticket_hash != ticket_hash_value:
        raise ValueError("Approval receipt does not match ticket hash")

    expiry = receipt.expiry
    if expiry and datetime.now(timezone.utc) > datetime.fromisoformat(expiry):
        raise ValueError("Approval receipt expired")

    required = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 3}
    method = receipt.confirmation_method or receipt.confirm_method or ""
    got = {
        "single_click": 1,
        "double_confirm": 2,
        "typed": 3,
        "typed_phrase": 3,
    }.get(method, 0)
    if got < required.get(required_level.upper(), 1):
        raise ValueError("Approval confirmation strength too low")
    if required_level.upper() == "CRITICAL" and not str(receipt.typed_phrase or "").strip():
        raise ValueError("CRITICAL approvals require typed confirmation phrase")
