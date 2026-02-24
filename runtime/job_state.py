from __future__ import annotations

from enum import Enum


class JobPhase(str, Enum):
    NEW = "NEW"
    PURSUIT = "PURSUIT"
    PLAN_READY = "PLAN_READY"
    SIM_DONE = "SIM_DONE"
    PATCH_READY = "PATCH_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    DONE = "DONE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


_ALLOWED = {
    JobPhase.NEW: {JobPhase.PURSUIT, JobPhase.FAILED},
    JobPhase.PURSUIT: {JobPhase.PLAN_READY, JobPhase.FAILED},
    JobPhase.PLAN_READY: {JobPhase.SIM_DONE, JobPhase.FAILED},
    JobPhase.SIM_DONE: {JobPhase.PATCH_READY, JobPhase.FAILED},
    JobPhase.PATCH_READY: {JobPhase.AWAITING_APPROVAL, JobPhase.FAILED},
    JobPhase.AWAITING_APPROVAL: {JobPhase.EXECUTING, JobPhase.FAILED},
    JobPhase.EXECUTING: {JobPhase.DONE, JobPhase.FAILED, JobPhase.ROLLED_BACK},
    JobPhase.FAILED: {JobPhase.ROLLED_BACK},
    JobPhase.ROLLED_BACK: set(),
    JobPhase.DONE: set(),
}


def validate_transition(
    current: JobPhase, nxt: JobPhase, *, has_receipt: bool = False
) -> None:
    if nxt not in _ALLOWED[current]:
        raise ValueError(f"Invalid transition: {current} -> {nxt}")
    if nxt == JobPhase.EXECUTING and not has_receipt:
        raise ValueError("EXECUTING requires a valid ApprovalReceipt")
