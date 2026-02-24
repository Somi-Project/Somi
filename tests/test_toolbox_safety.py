from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import toolboxsettings as tbs
from runtime.approval import ApprovalReceipt
from runtime.audit import audit_path
from runtime.policy import enforce_policy
from runtime.risk import assess
from runtime.ticketing import ExecutionTicket, ticket_hash
from toolbox.loader import ToolLoader
from toolbox.registry import ToolRegistry


def _setup_tool(tmp_path: Path) -> tuple[ToolRegistry, str]:
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / "tool.py").write_text(
        "def run(args, ctx):\n    return {'ok': True}\n", encoding="utf-8"
    )
    (tool_dir / "manifest.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0"}), encoding="utf-8"
    )
    reg = ToolRegistry(path=str(tmp_path / "registry.json"))
    from runtime.hashing import sha256_file

    hashes = {
        "manifest.json": sha256_file(tool_dir / "manifest.json"),
        "tool.py": sha256_file(tool_dir / "tool.py"),
    }
    reg.register(
        {
            "name": "demo",
            "version": "1.0.0",
            "path": str(tool_dir),
            "hashes": hashes,
            "enabled": True,
        }
    )
    return reg, str(tool_dir)


def test_safe_mode_cannot_execute():
    with pytest.raises(Exception):
        enforce_policy({"trust": "TRUSTED", "action": "execute"})


def test_ticket_immutability_rejects_modified_ticket(tmp_path: Path):
    reg, _ = _setup_tool(tmp_path)
    loader = ToolLoader(registry=reg)
    ticket = loader.propose_exec("demo", {}, job_id="j1")
    th = ticket_hash(ticket)
    receipt = ApprovalReceipt(
        ticket_hash=th,
        user_confirmed_at="2025-01-01T00:00:00+00:00",
        confirm_method="typed_phrase",
    )
    mutated = ExecutionTicket(
        **{**ticket.__dict__, "timeout_seconds": ticket.timeout_seconds + 1}
    )
    with pytest.raises(ValueError):
        loader.execute_with_approval(mutated, receipt)


def test_bulk_huge_selection_high_risk():
    ticket = ExecutionTicket(
        job_id="j2",
        action="external_bulk",
        commands=[["echo", "x"]],
        cwd=".",
        bulk_targetset_id="t1",
    )
    report = assess(
        ticket, targetset={"estimated_count": tbs.MAX_BULK_ITEMS + 1}, settings=tbs
    )
    assert report.tier in {"HIGH", "CRITICAL"}


def test_delete_outside_workspace_is_critical():
    ticket = ExecutionTicket(
        job_id="j3",
        action="execute",
        commands=[["rm", "-rf", "/tmp/x"]],
        cwd=".",
        allow_delete=True,
        paths_rw=["/etc"],
    )
    report = assess(ticket, settings=tbs)
    assert report.tier == "CRITICAL"
    assert report.required_confirm == "typed"


def test_hash_integrity_extra_file_rejected(tmp_path: Path):
    reg, tool_dir = _setup_tool(tmp_path)
    (Path(tool_dir) / "extra.txt").write_text("oops", encoding="utf-8")
    loader = ToolLoader(registry=reg)
    with pytest.raises(Exception):
        loader.propose_exec("demo", {}, job_id="j4")


def test_typed_confirmation_requires_phrase_for_critical(tmp_path: Path):
    reg, _ = _setup_tool(tmp_path)
    loader = ToolLoader(registry=reg)
    ticket = loader.propose_exec("demo", {}, job_id="j5")
    risky = ExecutionTicket(**{**ticket.__dict__, "allow_delete": True})
    receipt = ApprovalReceipt(
        ticket_hash=ticket_hash(risky),
        user_confirmed_at="2025-01-01T00:00:00+00:00",
        confirm_method="typed_phrase",
        typed_phrase="",
    )
    with pytest.raises(ValueError):
        loader.execute_with_approval(risky, receipt)


def test_loader_ignores_sandbox_home_files(tmp_path: Path):
    reg, tool_dir = _setup_tool(tmp_path)
    sandbox = Path(tool_dir) / ".sandbox_home"
    sandbox.mkdir()
    (sandbox / "cache.txt").write_text("cache", encoding="utf-8")
    loader = ToolLoader(registry=reg)
    ticket = loader.propose_exec("demo", {}, job_id="j6")
    assert ticket.action == "execute"


def test_autonomy_execution_blocked_and_audited(tmp_path: Path):
    from jobs.engine import JobsEngine

    out = JobsEngine().run_create_tool("safe_autonomy_tool", "desc", "standard", False)
    assert out["result"]["state"] == "AWAITING_APPROVAL"
    assert audit_path(out["job_id"]).exists()


def test_guided_mode_blocks_non_staging_execution(tmp_path: Path, monkeypatch):
    reg, _ = _setup_tool(tmp_path)
    loader = ToolLoader(registry=reg)
    ticket = loader.propose_exec("demo", {}, job_id="j7")
    receipt = ApprovalReceipt(
        ticket_hash=ticket_hash(ticket),
        user_confirmed_at="2025-01-01T00:00:00+00:00",
        confirm_method="typed_phrase",
        typed_phrase="approve",
    )
    monkeypatch.setattr(tbs, "TOOLBOX_MODE", "guided")
    with pytest.raises(Exception):
        loader.execute_with_approval(ticket, receipt)


def test_staging_blocks_cwd_escape(tmp_path: Path):
    from runtime.staging import run_commands_in_staging

    ticket = ExecutionTicket(
        job_id="j8",
        action="verify",
        commands=[["python", "-c", "print('ok')"]],
        cwd="/tmp",
    )
    with pytest.raises(Exception):
        run_commands_in_staging(ticket)
