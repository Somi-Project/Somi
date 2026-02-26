from __future__ import annotations

from datetime import datetime, timezone

from config import toolboxsettings as tbs
from runtime.approval import ApprovalReceipt, validate_receipt
from runtime.bulk import TargetSet, validate_bulk_request
from runtime.controller import handle_turn
from runtime.user_state import load_user_state
from runtime.plan_lint import lint_plan
from runtime.risk import assess
from runtime.ticketing import ExecutionTicket, ticket_hash, validate_ticket_integrity


def test_safe_mode_cannot_execute_plan():
    errs = lint_plan({"steps": ["execute patch in repo"]}, mode=tbs.MODE_SAFE)
    assert errs


def test_ticket_mutation_invalidates_approval():
    t1 = ExecutionTicket(job_id="1", action="execute", commands=[["echo", "ok"]], cwd=".")
    h = ticket_hash(t1)
    t2 = ExecutionTicket(job_id="1", action="execute", commands=[["echo", "changed"]], cwd=".")
    try:
        validate_ticket_integrity(t2, h)
        assert False, "expected mutation failure"
    except ValueError:
        pass


def test_bulk_safeguards_block_mass_destructive_requests():
    ts = TargetSet(id="x", criteria={"kind": "email"}, estimated_count=tbs.MAX_BULK_ITEMS + 1, sample_preview=[{"id": 1}])
    try:
        validate_bulk_request(ts, tbs)
        assert False, "expected bulk refusal"
    except ValueError:
        pass


def test_protected_paths_score_critical():
    ticket = ExecutionTicket(
        job_id="2",
        action="execute",
        commands=[["echo", "x"]],
        cwd=".",
        paths_rw=["~/Documents"],
    )
    report = assess(ticket, settings=tbs)
    assert report.tier == "CRITICAL"


def test_critical_approval_requires_phrase():
    receipt = ApprovalReceipt(
        ticket_hash="abc",
        confirmation_method="typed_phrase",
        timestamp=datetime.now(timezone.utc).isoformat(),
        typed_phrase=None,
    )
    try:
        validate_receipt("abc", receipt, "CRITICAL")
        assert False, "expected phrase requirement"
    except ValueError:
        pass


def test_autonomy_flag_blocks_execution():
    errs = lint_plan({"steps": ["run tests"]}, mode=tbs.MODE_GUIDED, autonomy=True)
    assert errs


def test_controller_tracks_pending_approval_and_clears_on_approve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    ticket = ExecutionTicket(job_id="ctrl1", action="execute", commands=[["echo", "ok"]], cwd=".")
    first = handle_turn("run tool demo", {"user_id": "u1", "proposed_ticket": ticket})
    assert first.action_package and first.action_package.get("ticket_hash")

    st = load_user_state("u1")
    assert first.action_package["ticket_hash"] in st.pending_approvals

    second = handle_turn("approve & run", {"user_id": "u1", "pending_ticket": ticket})
    assert second.action_package and second.action_package.get("execute") is False  # SAFE mode downgraded

    st2 = load_user_state("u1")
    assert first.action_package["ticket_hash"] not in st2.pending_approvals


def test_controller_respects_quiet_hours_for_nudges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 23, 0, 0, tzinfo=timezone.utc)

    import runtime.controller as ctrl

    monkeypatch.setattr(ctrl, "datetime", _FakeDateTime)
    handle_turn("this is pending follow up", {"user_id": "u-quiet"})
    st = load_user_state("u-quiet")
    assert st.scheduled_nudges == []


def test_ticket_hash_deterministic_across_recreation():
    t1 = ExecutionTicket(job_id="h1", action="execute", commands=[["echo", "ok"]], cwd=".")
    t2 = ExecutionTicket(job_id="h1", action="execute", commands=[["echo", "ok"]], cwd=".")
    assert ticket_hash(t1) == ticket_hash(t2)
