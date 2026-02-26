from __future__ import annotations

import asyncio
import sys
import os
import shutil
import sqlite3

_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config.memorysettings import MEMORY_DB_PATH, MEMORY_PINNED_MD_PATH, MEMORY_MAX_TOTAL_CHARS, MEMORY_MODEL
from handlers.memory.manager import Memory3Manager


def _reset():
    root = os.path.dirname(MEMORY_DB_PATH) or "memory_store"
    shutil.rmtree(root, ignore_errors=True)




async def _legacy_db_migration_smoke() -> None:
    _reset()
    root = os.path.dirname(MEMORY_DB_PATH) or "memory_store"
    os.makedirs(root, exist_ok=True)
    with sqlite3.connect(MEMORY_DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE memory_items (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            user_id TEXT,
            lane TEXT,
            type TEXT,
            entity TEXT,
            mkey TEXT,
            value TEXT,
            kind TEXT,
            bucket TEXT,
            importance REAL,
            replaced_by TEXT,
            content TEXT NOT NULL,
            tags TEXT,
            confidence REAL,
            status TEXT,
            expires_at TEXT,
            supersedes TEXT,
            last_used TEXT
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(content, tags, mkey, item_id UNINDEXED);
        """)
        conn.execute(
            "INSERT INTO memory_items(id, ts, user_id, lane, type, entity, mkey, value, kind, content, tags, confidence, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy1", "2025-01-01T00:00:00+00:00", "u_legacy", "facts", "fact", "user", "favorite_color", "bluez", "preference", "favorite_color: bluez", "facts", 0.9, "active"),
        )

    m = Memory3Manager(user_id="u_legacy")
    block = await m.build_injected_context("favorite color", user_id="u_legacy")
    assert "bluez" in block.lower(), "legacy memory row not migrated to memory3 canonical schema"

    with m.store._connect() as conn:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
        fts_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(memory_fts)").fetchall()}
    assert "text" in cols and "created_at" in cols, "canonical memory3 columns missing after migration"
    assert "content" not in fts_cols and "text" in fts_cols, "fts schema not migrated to text column"


async def main() -> int:
    _reset()
    await _legacy_db_migration_smoke()

    _reset()
    m = Memory3Manager(user_id="u1")

    # fresh schema should be memory3-only (no legacy memory2 columns)
    with m.store._connect() as conn:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
    assert "ts" not in cols and "content" not in cols and "supersedes" not in cols and "last_used" not in cols, "legacy memory2 columns remain in fresh DB"

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
