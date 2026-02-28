from __future__ import annotations

from executive.istari import AuditLog
from executive.istari_runtime import IstariProtocol


def test_istari_flow_propose_approve_execute_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = IstariProtocol()

    handled, text = p.handle("run tool hello_tool codex", "u1", toolbox_run_match=__import__('re').match(r"^run tool\s+([a-zA-Z0-9_\-]+)(?:\s+(.*))?$", "run tool hello_tool codex"))
    assert handled
    assert "proposal_action" in text
    proposal = p.proposals.list_pending()[-1]

    handled2, text2 = p.handle(f"approve {proposal['proposal_id']}", "u1")
    assert handled2
    assert "approval_token" in text2
    # parse between backticks after '- token: '
    token_line = [ln for ln in text2.splitlines() if ln.strip().startswith("- token:")][0]
    token_value = token_line.split("`", 2)[1]

    handled3, text3 = p.handle(f"execute {proposal['proposal_id']} {token_value}", "u1")
    assert handled3
    assert "executed_action" in text3


def test_audit_log_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log = AuditLog("audit")
    _ = log.append(
        "proposal_created",
        "p1",
        "shell.exec_scoped",
        "contains secret",
        metadata={"token": "sk-12345678901234567890"},
    )
    raw = (tmp_path / "audit" / "events.jsonl").read_text(encoding="utf-8")
    assert "[REDACTED]" in raw
    assert "sk-1234567890" not in raw


def test_istari_approve_without_pending_emits_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = IstariProtocol()
    handled, text = p.handle("approve", "u1")
    assert handled
    assert "denied_action" in text


def test_istari_execute_invalid_token_emits_structured_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = IstariProtocol()
    import re
    handled, _ = p.handle("run tool hello_tool codex", "u1", toolbox_run_match=re.match(r"^run tool\s+([a-zA-Z0-9_\-]+)(?:\s+(.*))?$", "run tool hello_tool codex"))
    assert handled
    proposal = p.proposals.list_pending()[-1]
    handled2, text2 = p.handle(f"execute {proposal['proposal_id']} badtoken", "u1")
    assert handled2
    assert "success: false" in text2


def test_istari_execute_usage_error_persists_executed_action_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = IstariProtocol()
    handled, text = p.handle("execute", "u1")
    assert handled
    assert "success: false" in text
    art = p.artifacts.get_last_by_type("u1", "executed_action")
    assert art is not None
    assert art["content"]["errors"][0]["code"] == "invalid_execute_syntax"


def test_istari_execute_missing_proposal_persists_executed_action_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = IstariProtocol()
    handled, text = p.handle("execute deadbeef badtoken", "u1")
    assert handled
    assert "proposal not found" in text
    art = p.artifacts.get_last_by_type("u1", "executed_action")
    assert art is not None
    assert art["content"]["errors"][0]["code"] == "proposal_not_found"
