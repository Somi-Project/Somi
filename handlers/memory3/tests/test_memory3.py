from __future__ import annotations

import asyncio
import sys
import os
import shutil

_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config.settings import MEMORY_DB_PATH, MEMORY_PINNED_MD_PATH, MEMORY_MAX_TOTAL_CHARS, MEMORY_MODEL
from handlers.memory3.manager import Memory3Manager


def _reset():
    root = os.path.dirname(MEMORY_DB_PATH) or "memory_store"
    shutil.rmtree(root, ignore_errors=True)


async def main() -> int:
    _reset()
    m = Memory3Manager(user_id="u1")

    # pinned persists
    await m.ingest_turn("don't output json", "")
    m2 = Memory3Manager(user_id="u1")
    block = await m2.build_injected_context("format")
    assert "output_format" in block.lower(), "pinned preference missing"

    # supersede
    await m2.ingest_turn("timezone is America/New_York", "")
    await m2.ingest_turn("timezone is America/Port_of_Spain", "")
    block2 = await m2.build_injected_context("timezone")
    assert "america/port_of_spain" in block2.lower(), "supersede not reflected"
    upd = await m2.ingest_turn("timezone is America/Chicago", "")
    assert (upd or {}).get("conflict_notices"), "critical fact conflict notice missing"


    # fts recall
    await m2.upsert_fact({"key": "ui_rule", "value": "Tkinter queue main thread", "kind": "facts", "confidence": 0.9})
    block3 = await m2.build_injected_context("main thread ui")
    assert "tkinter" in block3.lower(), "fts recall failed"

    # caps
    assert len(block3) <= int(MEMORY_MAX_TOTAL_CHARS), "cap exceeded"

    # vec optional path shouldn't crash
    _ = await m2.build_injected_context("semantic deadlock")
    # periodic summary should eventually be created
    summary_seen = False
    for i in range(8):
        out = await m2.ingest_turn(f"session note {i}", "")
        if (out or {}).get("summary_created"):
            summary_seen = True
            break
    assert summary_seen, "session summary was not created"


    # MEMORY_MODEL extraction path should call configured model when heuristic triggers
    class FakeClient:
        def __init__(self):
            self.model_used = None
        async def chat(self, **kwargs):
            self.model_used = kwargs.get("model")
            return {"message": {"content": '{"facts":[{"entity":"user","key":"timezone","value":"America/New_York","kind":"profile","confidence":0.9}],"skills":[]}'}}

    fc = FakeClient()
    m3 = Memory3Manager(user_id="u1", ollama_client=fc)
    await m3.ingest_turn("timezone is America/New_York", "")
    assert fc.model_used == MEMORY_MODEL, "MEMORY_MODEL was not used for LLM extraction"

    # user isolation: other user memory should not leak
    m_other = Memory3Manager(user_id="u2")
    await m_other.ingest_turn("my favorite color is scarletx", "")
    own_ctx = await m2.build_injected_context("favorite color")
    other_ctx = await m_other.build_injected_context("favorite color")
    assert "scarletx" not in own_ctx.lower(), "cross-user memory leak into u1 context"
    assert "scarletx" in other_ctx.lower(), "u2 memory not retrievable in u2 context"

    # user isolation should also hold when a single manager ingests different session_ids
    m_shared = Memory3Manager(user_id="default_user")
    await m_shared.ingest_turn("my favorite color is cyanx", "", session_id="u_session_1")
    await m_shared.ingest_turn("my favorite color is magentax", "", session_id="u_session_2")
    ctx_s1 = await m_shared.build_injected_context("favorite color", user_id="u_session_1")
    ctx_s2 = await m_shared.build_injected_context("favorite color", user_id="u_session_2")
    assert "cyanx" in ctx_s1.lower() and "magentax" not in ctx_s1.lower(), "session_id user isolation failed for u_session_1"
    assert "magentax" in ctx_s2.lower() and "cyanx" not in ctx_s2.lower(), "session_id user isolation failed for u_session_2"

    # reminders
    rid = await m2.add_reminder("u1", "take pills", "in 1 seconds")
    assert rid, "reminder not created"
    rid_local = await m2.add_reminder("u1", "evening meds", "at 8:30 pm")
    assert rid_local, "local-time reminder parse failed"
    rid_article = await m2.add_reminder("u1", "stretch", "in an hour")
    assert rid_article, "article-based relative reminder parse failed"
    rid_tmr = await m2.add_reminder("u1", "prep bag", "tmr at 9 am")
    assert rid_tmr, "tmr shorthand reminder parse failed"
    rid_bad = await m2.add_reminder("u1", "bad time", "at 99:99")
    assert rid_bad is None, "invalid local-time reminder should be rejected"
    rid_bad_ampm = await m2.add_reminder("u1", "bad ampm", "at 13pm")
    assert rid_bad_ampm is None, "invalid am/pm reminder time should be rejected"
    rid_bad_tomorrow = await m2.add_reminder("u1", "bad tomorrow", "tomorrow at 0pm")
    assert rid_bad_tomorrow is None, "invalid tomorrow am/pm reminder time should be rejected"

    print("memory3 tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
