from __future__ import annotations

from pathlib import Path

from handlers.contracts.schemas import validate_artifact
from handlers.routing import decide_route
from executive.istari import CapabilityRegistry, PolicyEnforcer, ProposalStore, TokenStore, build_proposal


def test_read_only_routes_bypass_execution_flag():
    assert decide_route("weather in london").signals.get("requires_execution") is False
    assert decide_route("latest news about ai").signals.get("requires_execution") is False
    assert decide_route("BTC price now").signals.get("requires_execution") is False
    assert decide_route("tell me a bedtime story").signals.get("requires_execution") is False


def test_phase5_artifact_validators_strict():
    proposal = {
        "content": {
            "type": "proposal_action",
            "proposal_id": "p1",
            "capability": "file.write_scoped",
            "risk_tier": "tier2",
            "summary": "write file",
            "justification": ["requested by user"],
            "scope": {"paths": ["/workspace/Somi/tmp.txt"]},
            "steps": [{"step_id": "s1", "action": "write_file", "parameters": {"path": "/workspace/Somi/tmp.txt", "content": "x"}}],
            "preconditions": ["diff preview will be shown"],
            "requires_approval": True,
            "expires_in_s": 300,
            "no_autonomy": True,
            "related_artifact_ids": [],
            "ui_hints": {"show_diff": True},
        }
    }
    assert validate_artifact("proposal_action", proposal)


def test_token_ttl_and_one_time_and_revoke(tmp_path):
    store = TokenStore(str(tmp_path / "executive"))
    proposal = {"proposal_id": "p1", "capability": "file.write_scoped", "scope": {"paths": ["/tmp/a"]}}
    issued = store.issue(proposal, ttl_seconds=1, one_time=True)
    ok, _, row = store.validate(issued["token"], "p1")
    assert ok and row
    store.redeem(issued["token_digest"])
    ok2, why2, _ = store.validate(issued["token"], "p1")
    assert not ok2 and why2 == "token_already_used"

    issued2 = store.issue(proposal, ttl_seconds=300, one_time=True)
    rev = store.revoke(token_digest=issued2["token_digest"], reason="test")
    assert rev


def test_policy_enforcer_protected_paths_and_denylist(tmp_path):
    cfg = Path("/workspace/Somi/config/capability_registry.json")
    reg = CapabilityRegistry(str(cfg))
    enforcer = PolicyEnforcer(reg)

    proposal = build_proposal(
        capability="file.write_scoped",
        summary="attempt protected write",
        justification=["user asked"],
        scope={"paths": ["/workspace/Somi/config/assistantsettings.py"]},
        steps=[{"step_id": "s1", "action": "write_file", "parameters": {"path": "/workspace/Somi/config/assistantsettings.py", "content": "x"}}],
    )
    ok, errs = enforcer.enforce(proposal, {"proposal_id": proposal["proposal_id"]}, preview_ready=True)
    assert not ok
    assert any(e["code"] == "protected_path" for e in errs)

    proposal2 = build_proposal(
        capability="shell.exec_scoped",
        summary="danger cmd",
        justification=["user asked"],
        scope={"commands": ["rm -rf /tmp/x"]},
        steps=[{"step_id": "s1", "action": "run_command", "parameters": {"command": ["rm", "-rf", "/tmp/x"], "cwd": "/workspace/Somi"}}],
        risk_tier="tier3",
    )
    ok2, errs2 = enforcer.enforce(proposal2, {"proposal_id": proposal2["proposal_id"]}, preview_ready=True)
    assert not ok2
    assert any(e["code"] in {"command_not_allowlisted", "command_denylisted"} for e in errs2)


def test_path_traversal_rejection():
    reg = CapabilityRegistry("/workspace/Somi/config/capability_registry.json")
    enforcer = PolicyEnforcer(reg)
    proposal = build_proposal(
        capability="file.write_scoped",
        summary="traversal",
        justification=["user asked"],
        scope={"paths": ["/workspace/Somi/../secrets/x"]},
        steps=[],
    )
    ok, errs = enforcer.enforce(proposal, {"proposal_id": proposal["proposal_id"]}, preview_ready=True)
    assert not ok
    assert any(e["code"] == "path_traversal" for e in errs)


def test_pending_proposal_store_roundtrip(tmp_path):
    ps = ProposalStore(str(tmp_path / "executive"))
    p = build_proposal(capability="file.write_scoped", summary="x", justification=["y"], scope={"paths": ["/tmp/a"]}, steps=[])
    ps.append(p)
    assert ps.find(p["proposal_id"])


def test_step_path_must_match_scoped_paths():
    reg = CapabilityRegistry('/workspace/Somi/config/capability_registry.json')
    enforcer = PolicyEnforcer(reg)
    proposal = build_proposal(
        capability='file.write_scoped',
        summary='scope mismatch write',
        justification=['user asked'],
        scope={'paths': ['/workspace/Somi/docs/allowed.txt']},
        steps=[
            {
                'step_id': 's1',
                'action': 'write_file',
                'parameters': {'path': '/workspace/Somi/README.md', 'content': 'bad'},
            }
        ],
    )
    ok, errs = enforcer.enforce(proposal, {'proposal_id': proposal['proposal_id']}, preview_ready=True)
    assert not ok
    assert any(e['code'] == 'scope_step_path_mismatch' for e in errs)


def test_step_command_and_cwd_must_match_scope_and_roots():
    reg = CapabilityRegistry('/workspace/Somi/config/capability_registry.json')
    enforcer = PolicyEnforcer(reg)
    proposal = build_proposal(
        capability='shell.exec_scoped',
        summary='scope mismatch command',
        justification=['user asked'],
        scope={'commands': ['python -V']},
        steps=[
            {
                'step_id': 's1',
                'action': 'run_command',
                'parameters': {'command': ['python', '-c', 'print(1)'], 'cwd': '/tmp'},
            }
        ],
        risk_tier='tier3',
    )
    ok, errs = enforcer.enforce(proposal, {'proposal_id': proposal['proposal_id']}, preview_ready=True)
    assert not ok
    codes = {e['code'] for e in errs}
    assert 'scope_step_command_mismatch' in codes
    assert 'cwd_outside_allowed_roots' in codes


def test_revoke_only_targets_approval_tokens(tmp_path):
    store = TokenStore(str(tmp_path / 'executive'))
    p = {'proposal_id': 'p1', 'capability': 'file.write_scoped', 'scope': {'paths': ['/tmp/a']}}
    issued = store.issue(p)
    store.redeem(issued['token_digest'])
    revoked = store.revoke(proposal_id='p1', reason='test')
    assert len(revoked) == 1
    assert revoked[0]['token_digest'] == issued['token_digest']
