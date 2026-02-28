from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from config import assistantsettings as aset
from config import toolboxsettings as tbs
from runtime.approval import ApprovalRequest
from runtime.plan_lint import lint_plan
from runtime.risk import assess
from runtime.ticketing import ticket_hash
from runtime.user_state import OpenLoop, load_user_state, save_user_state, upsert_active_item


@dataclass
class ControllerResult:
    response_text: str
    action_package: dict[str, Any] | None = None
    handled: bool = False


def _within_quiet_hours(dt: datetime) -> bool:
    start = int(aset.QUIET_HOURS_START)
    end = int(aset.QUIET_HOURS_END)
    hour = dt.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _detect_approval(text: str) -> str | None:
    low = text.strip().lower()
    if low in {"approve patch", "approve & run", "cancel"}:
        return low
    if text.strip() == tbs.SYSTEM_AGENT_REQUIRED_PHRASE:
        return "typed_confirmation"
    return None


def _classify(user_input: str, approval_signal: str | None) -> str:
    if approval_signal == "approve & run":
        return "EXECUTE_APPROVED"
    if approval_signal == "cancel":
        return "CANCEL_PENDING"
    if approval_signal:
        return "CHAT_WITH_SUGGESTION"
    low = user_input.lower()
    if any(k in low for k in ["run tool", "execute", "apply patch"]):
        return "PROPOSE_JOB"
    if "?" in user_input and len(user_input.split()) < 4:
        return "CLARIFY_FIRST"
    if "next step" in low or "suggest" in low:
        return "CHAT_WITH_SUGGESTION"
    return "CHAT_ONLY"


def _should_track_active_item(text: str) -> bool:
    t = (text or "").strip()
    if len(t.split()) < 3:
        return False
    low = t.lower()
    action = bool(re.search(r"\b(i need to|i should|i must|working on|my project|my task|help me with)\b", low))
    topic = bool(re.search(r"\b(project|task|learning|problem)\b", low))
    return action and topic


def _should_open_loop(text: str, approval_signal: str | None) -> bool:
    if approval_signal is not None:
        return False
    low = (text or "").lower()
    if len(low.split()) < 4:
        return False
    return bool(re.search(r"\b(pending|follow[ -]?up|unfinished|blocked|todo|to do)\b", low))


def handle_turn(user_input: str, session_context: dict[str, Any]) -> ControllerResult:
    """Six-stage governed turn handler.

    Stages: intake, state update, intent decision, compose outputs,
    governance gate, post-turn scheduling.
    """
    user_id = str(session_context.get("user_id", "default_user"))
    state = load_user_state(user_id)

    # Stage A — Intake (approval detection first)
    text = (user_input or "").strip()
    approval_signal = _detect_approval(text)

    # Stage B — State update
    if text:
        if _should_track_active_item(text):
            upsert_active_item(
                state,
                title=text[:80],
                item_type="task",
                summary=text[:140],
            )
        if _should_open_loop(text, approval_signal):
            exists = any(l.title.lower() == text[:80].lower() for l in state.open_loops)
            if not exists and len(state.open_loops) < aset.MAX_UNRESOLVED_LOOPS:
                state.open_loops.append(OpenLoop(title=text[:80], loop_type="pending implementation steps"))

        if len(state.active_items) > aset.MAX_TRACKED_ACTIVE_ITEMS:
            state.active_items = sorted(state.active_items, key=lambda i: i.last_mentioned_ts, reverse=True)[: aset.MAX_TRACKED_ACTIVE_ITEMS]

    # Stage C — Intent decision
    intent = _classify(text, approval_signal)

    # Stage D — Compose outputs
    action_package: dict[str, Any] | None = None
    response = ""
    if intent == "EXECUTE_APPROVED":
        ticket = session_context.get("pending_ticket")
        if not ticket:
            response = "No pending ticket found to execute."
        else:
            risk = assess(ticket, settings=tbs)
            th = ticket_hash(ticket)
            if th not in state.pending_approvals:
                response = "No pending approval exists for this ticket. Please request execution again."
            else:
                action_package = {
                    "ticket_hash": th,
                    "risk_report": risk,
                    "execute": True,
                }
                state.pending_approvals = [h for h in state.pending_approvals if h != th]
                response = "Approval received. Preparing staged execution."
    elif intent == "CANCEL_PENDING":
        if state.pending_approvals:
            state.pending_approvals = []
            response = "Cancelled pending approvals for this session."
        else:
            response = "There are no pending approvals to cancel."
    elif intent == "PROPOSE_JOB":
        proposed_ticket = session_context.get("proposed_ticket")
        if proposed_ticket:
            risk = assess(proposed_ticket, settings=tbs)
            th = ticket_hash(proposed_ticket)
            if th not in state.pending_approvals:
                state.pending_approvals.append(th)
            action_package = {
                "plan": ["Review patch", "Prepare staged sandbox execution (post-approval)", "Audit outputs"],
                "ticket_hash": th,
                "risk_report": risk,
                "approval_request": ApprovalRequest(
                    ticket_hash=th,
                    risk_tier=risk.tier,
                    explanation="Execution requires explicit approval.",
                    potential_outcomes=risk.potential_outcomes or ["No-op"],
                    confirmation_requirement="typed" if risk.tier in {"HIGH", "CRITICAL"} else "click",
                ),
            }
            response = "I prepared a safe proposal. Approve with 'approve & run' after review."
    elif intent == "CHAT_WITH_SUGGESTION":
        response = "Noted. I can propose the next safe step when you're ready."
    elif intent == "CLARIFY_FIRST":
        response = "Can you clarify your goal in one sentence so I can propose a safe plan?"
    else:
        response = "Understood. I will keep tracking this context and avoid autonomous execution."

    # Stage E — Governance gate
    if action_package:
        mode = tbs.normalized_mode()
        lint_errors = lint_plan({"steps": action_package.get("plan", [])}, mode=mode)
        if mode == tbs.MODE_SAFE and action_package.get("execute"):
            lint_errors.append("SAFE mode blocks execution")
        if lint_errors:
            action_package["execute"] = False
            action_package["lint_errors"] = lint_errors
            response = f"Plan downgraded to proposal-only: {', '.join(lint_errors)}"

    # Stage F — Post-turn scheduling
    now = datetime.now(timezone.utc)
    if state.open_loops and len(state.scheduled_nudges) < aset.DAILY_PROACTIVE_MESSAGE_BUDGET and not _within_quiet_hours(now):
        if not state.scheduled_nudges:
            can_schedule = True
        else:
            latest_ts = max(n.get("not_before", "") for n in state.scheduled_nudges if isinstance(n, dict))
            try:
                latest = datetime.fromisoformat(latest_ts) if latest_ts else now - timedelta(days=1)
            except Exception:
                latest = now - timedelta(days=1)
            can_schedule = now >= latest
        if can_schedule:
            state.scheduled_nudges.append(
                {
                    "kind": "unfinished_work_resurface",
                    "not_before": (now + timedelta(minutes=aset.MIN_PROACTIVE_SUGGESTION_INTERVAL_MINUTES)).isoformat(),
                }
            )
    state.recent_context_summary = text[:240]
    save_user_state(state)

    return ControllerResult(response_text=response, action_package=action_package, handled=bool(action_package) or bool(approval_signal))
