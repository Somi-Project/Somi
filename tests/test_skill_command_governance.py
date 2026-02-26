from __future__ import annotations

from handlers.skills.dispatch import SkillDispatchResult, handle_skill_command
from handlers.skills.types import SkillDoc
from runtime.user_state import load_user_state


def _skill() -> SkillDoc:
    return SkillDoc(
        name="Demo Skill",
        description="demo",
        homepage=None,
        emoji=None,
        skill_key="demo",
        base_dir=".",
        frontmatter={},
        metadata={},
        openclaw={},
        body_md="demo body",
        user_invocable=True,
        disable_model_invocation=False,
        command_dispatch="tool",
        command_tool="demo.tool",
        command_arg_mode="raw",
    )


def test_skill_run_requires_governed_proposal_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import handlers.skills.dispatch as d

    skill = _skill()
    monkeypatch.setattr(d, "settings_dict", lambda: {"SKILLS_ENABLED": True, "SKILLS_ENTRIES": {}})
    monkeypatch.setattr(
        d,
        "build_registry_snapshot",
        lambda cfg, env, force_refresh=True: {
            "eligible": {"demo": skill},
            "ineligible": {},
            "snapshot": {"eligible": [], "ineligible": [], "rejected": []},
        },
    )
    monkeypatch.setattr(d, "_record_recent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(d, "_run_skill", lambda **kwargs: SkillDispatchResult(handled=True, response="ran"))

    out = handle_skill_command("/skill run demo delete old files", env={"SOMI_USER_ID": "u1"})
    assert out.handled
    assert "Proposed skill run" in out.response


def test_skill_confirm_blocked_in_safe_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import handlers.skills.dispatch as d
    from config import toolboxsettings as tbs

    skill = _skill()
    monkeypatch.setattr(d, "settings_dict", lambda: {"SKILLS_ENABLED": True, "SKILLS_ENTRIES": {}})
    monkeypatch.setattr(
        d,
        "build_registry_snapshot",
        lambda cfg, env, force_refresh=True: {
            "eligible": {"demo": skill},
            "ineligible": {},
            "snapshot": {"eligible": [], "ineligible": [], "rejected": []},
        },
    )
    monkeypatch.setattr(d, "_record_recent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(d, "_run_skill", lambda **kwargs: SkillDispatchResult(handled=True, response="ran"))
    monkeypatch.setattr(tbs, "TOOLBOX_MODE", tbs.MODE_SAFE)

    _ = handle_skill_command("/skill run demo delete old files", env={"SOMI_USER_ID": "u2"})
    out2 = handle_skill_command("/skill run demo --confirm delete old files", env={"SOMI_USER_ID": "u2"})
    assert out2.handled
    assert "SAFE mode blocks skill execution" in out2.response
    st = load_user_state("u2")
    assert st.pending_approvals, "pending approval should remain while SAFE blocks execution"


def test_skill_confirm_executes_after_proposal_in_guided(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import handlers.skills.dispatch as d
    from config import toolboxsettings as tbs

    skill = _skill()
    monkeypatch.setattr(d, "settings_dict", lambda: {"SKILLS_ENABLED": True, "SKILLS_ENTRIES": {}})
    monkeypatch.setattr(
        d,
        "build_registry_snapshot",
        lambda cfg, env, force_refresh=True: {
            "eligible": {"demo": skill},
            "ineligible": {},
            "snapshot": {"eligible": [], "ineligible": [], "rejected": []},
        },
    )
    monkeypatch.setattr(d, "_record_recent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(d, "_run_skill", lambda **kwargs: SkillDispatchResult(handled=True, response="ran"))
    monkeypatch.setattr(tbs, "TOOLBOX_MODE", tbs.MODE_GUIDED)

    _ = handle_skill_command("/skill run demo delete old files", env={"SOMI_USER_ID": "u3"})
    out2 = handle_skill_command("/skill run demo --confirm delete old files", env={"SOMI_USER_ID": "u3"})
    assert out2.handled
    assert out2.response == "ran"


def test_pending_approvals_are_bounded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import handlers.skills.dispatch as d
    from config import assistantsettings as aset

    skill = _skill()
    monkeypatch.setattr(d, "settings_dict", lambda: {"SKILLS_ENABLED": True, "SKILLS_ENTRIES": {}})
    monkeypatch.setattr(
        d,
        "build_registry_snapshot",
        lambda cfg, env, force_refresh=True: {
            "eligible": {"demo": skill},
            "ineligible": {},
            "snapshot": {"eligible": [], "ineligible": [], "rejected": []},
        },
    )
    monkeypatch.setattr(d, "_record_recent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(aset, "MAX_UNRESOLVED_LOOPS", 3)

    for i in range(6):
        out = handle_skill_command(f"/skill run demo delete old files {i}", env={"SOMI_USER_ID": "u4"})
        assert out.handled

    st = load_user_state("u4")
    assert len(st.pending_approvals) <= 3
