from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import (
    EMBEDDING_DIM,
    MEMORY_DB_PATH,
    MEMORY_DEBUG,
    SQLITE_VEC_ENABLED,
    SQLITE_VEC_EXTENSION_PATH,
)

from .schema import SCHEMA_SQL

logger = logging.getLogger(__name__)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteMemoryStore:
    def __init__(self, db_path: str = MEMORY_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.vec_enabled = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _try_load_vec(self, conn: sqlite3.Connection) -> bool:
        if not SQLITE_VEC_ENABLED:
            return False
        try:
            conn.enable_load_extension(True)
            names = []
            if SQLITE_VEC_EXTENSION_PATH:
                names.append(SQLITE_VEC_EXTENSION_PATH)
            names.extend(["sqlite_vec", "vec0", "vec"])
            ok = False
            for n in names:
                try:
                    conn.load_extension(n)
                    ok = True
                    break
                except Exception:
                    continue
            conn.enable_load_extension(False)
            return ok
        except Exception:
            return False

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
            needed = {
                "user_id": "TEXT",
                "bucket": "TEXT DEFAULT 'general'",
                "importance": "REAL DEFAULT 0.5",
                "replaced_by": "TEXT",
                "scope": "TEXT DEFAULT 'conversation'",
                "mem_type": "TEXT DEFAULT 'note'",
                "text": "TEXT DEFAULT ''",
                "entities_json": "TEXT",
                "tags_json": "TEXT",
                "supersedes_id": "TEXT",
                "contradicts_id": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
                "last_used_at": "TEXT",
                "slot_key": "TEXT",
            }
            for c, ddl in needed.items():
                if c not in cols:
                    conn.execute(f"ALTER TABLE memory_items ADD COLUMN {c} {ddl}")
            conn.execute("UPDATE memory_items SET user_id='default_user' WHERE user_id IS NULL OR user_id=''")
            conn.execute("UPDATE memory_items SET scope=COALESCE(NULLIF(scope,''),'conversation')")
            conn.execute("UPDATE memory_items SET mem_type=COALESCE(NULLIF(mem_type,''),'note')")
            conn.execute("UPDATE memory_items SET text=COALESCE(NULLIF(text,''),content)")
            conn.execute("UPDATE memory_items SET created_at=COALESCE(created_at, ts)")
            conn.execute("UPDATE memory_items SET updated_at=COALESCE(updated_at, ts)")
            conn.execute("UPDATE memory_items SET last_used_at=COALESCE(last_used_at, last_used)")

            # create post-migration indexes that reference newly added columns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user_scope_status ON memory_items(user_id, scope, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user_slot_status ON memory_items(user_id, slot_key, status)")

            self.vec_enabled = self._try_load_vec(conn)
            if self.vec_enabled:
                try:
                    conn.execute(
                        f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(embedding float[{int(EMBEDDING_DIM)}], item_id TEXT)"
                    )
                except Exception as e:
                    self.vec_enabled = False
                    if MEMORY_DEBUG:
                        logger.warning("memory_vec create failed; fallback to FTS-only: %s", e)
            if MEMORY_DEBUG:
                logger.info("memory3 init vec_enabled=%s", self.vec_enabled)

    def _upsert_fts(self, conn: sqlite3.Connection, item_id: str, content: str, tags: str, mkey: str) -> None:
        conn.execute("DELETE FROM memory_fts WHERE item_id=?", (item_id,))
        conn.execute(
            "INSERT INTO memory_fts(content, tags, mkey, item_id) VALUES (?, ?, ?, ?)",
            (content or "", tags or "", mkey or "", item_id),
        )

    def _upsert_vec(self, conn: sqlite3.Connection, item_id: str, vec: Optional[List[float]]) -> None:
        if not self.vec_enabled or vec is None:
            return
        try:
            conn.execute("DELETE FROM memory_vec WHERE item_id=?", (item_id,))
            conn.execute("INSERT INTO memory_vec(embedding, item_id) VALUES (?, ?)", (json.dumps(vec), item_id))
        except Exception:
            pass

    def write_item(self, item: Dict[str, Any], embedding: Optional[List[float]] = None) -> None:
        now_iso = utcnow_iso()
        item_id = str(item.get("id") or uuid.uuid4())
        payload = (
            item_id,
            item.get("ts") or now_iso,
            item.get("user_id", "default_user"),
            item.get("lane", "facts"),
            item.get("type", "fact"),
            item.get("entity", "user"),
            item.get("mkey", "fact"),
            item.get("value", ""),
            item.get("kind", "preference"),
            item.get("bucket", "general"),
            float(item.get("importance", 0.5) or 0.5),
            item.get("replaced_by"),
            item.get("content", item.get("text", "")),
            item.get("tags", ""),
            float(item.get("confidence", 0.7) or 0.7),
            item.get("status", "active"),
            item.get("expires_at"),
            item.get("supersedes"),
            item.get("last_used"),
            item.get("scope", "conversation"),
            item.get("mem_type", item.get("type", "note")),
            item.get("text", item.get("content", "")),
            item.get("entities_json"),
            item.get("tags_json"),
            item.get("supersedes_id", item.get("supersedes")),
            item.get("contradicts_id"),
            item.get("created_at", item.get("ts") or now_iso),
            item.get("updated_at", item.get("ts") or now_iso),
            item.get("last_used_at", item.get("last_used")),
            item.get("slot_key"),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items(
                    id, ts, user_id, lane, type, entity, mkey, value, kind, bucket, importance, replaced_by,
                    content, tags, confidence, status, expires_at, supersedes, last_used,
                    scope, mem_type, text, entities_json, tags_json, supersedes_id, contradicts_id,
                    created_at, updated_at, last_used_at, slot_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            self._upsert_fts(conn, item_id, str(item.get("content", item.get("text", ""))), str(item.get("tags", "")), str(item.get("mkey", "")))
            self._upsert_vec(conn, item_id, embedding)

    def log_event(self, user_id: str, event_type: str, memory_id: Optional[str], payload: Optional[Dict[str, Any]] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memory_events(id, user_id, event_type, memory_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, event_type, memory_id, json.dumps(payload or {}, ensure_ascii=False), utcnow_iso()),
            )

    def recent_events(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_events WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def active_fact(self, user_id: str, entity: str, mkey: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND type='fact' AND entity=? AND mkey=? AND status='active' ORDER BY ts DESC LIMIT 1",
                (user_id, entity, mkey),
            ).fetchone()
        return dict(row) if row else None

    def active_by_slot(self, user_id: str, slot_key: str) -> Optional[Dict[str, Any]]:
        if not slot_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND slot_key=? AND status='active' ORDER BY ts DESC LIMIT 1",
                (user_id, slot_key),
            ).fetchone()
        return dict(row) if row else None

    def set_replaced_by(self, item_id: str, new_item_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE memory_items SET replaced_by=?, updated_at=? WHERE id=?", (new_item_id, utcnow_iso(), item_id))

    def set_status(self, item_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE memory_items SET status=?, updated_at=? WHERE id=?", (status, utcnow_iso(), item_id))

    def expire_items(self, now_iso: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE memory_items SET status='expired', updated_at=? WHERE status='active' AND expires_at IS NOT NULL AND expires_at<=?",
                (now_iso, now_iso),
            )
            return int(cur.rowcount or 0)

    def pinned_items(self, user_id: str, limit: int = 32) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND lane='pinned' AND status='active' ORDER BY ts DESC LIMIT ?",
                (user_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_by_scope(self, user_id: str, scope: str, limit: int = 8) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND scope=? AND status='active' ORDER BY ts DESC LIMIT ?",
                (user_id, scope, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_session_summary(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND mem_type='summary' AND status='active' ORDER BY ts DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def fts_search(self, user_id: str, query: str, limit: int = 30) -> List[str]:
        rows = self.fts_search_scored(user_id, query, scopes=None, limit=limit)
        return [iid for iid, _ in rows]

    def fts_search_scored(self, user_id: str, query: str, scopes: Optional[List[str]] = None, limit: int = 30) -> List[Tuple[str, float]]:
        q = (query or "").strip()
        if not q:
            return []
        with self._connect() as conn:
            try:
                if scopes:
                    ph = ",".join(["?"] * len(scopes))
                    sql = f"""
                        SELECT f.item_id, bm25(memory_fts) AS score
                        FROM memory_fts f
                        JOIN memory_items i ON i.id=f.item_id
                        WHERE memory_fts MATCH ? AND i.user_id=? AND i.status='active' AND i.scope IN ({ph})
                        ORDER BY bm25(memory_fts) ASC LIMIT ?
                    """
                    rows = conn.execute(sql, [q, user_id] + scopes + [int(limit)]).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT f.item_id, bm25(memory_fts) AS score
                        FROM memory_fts f
                        JOIN memory_items i ON i.id=f.item_id
                        WHERE memory_fts MATCH ? AND i.user_id=? AND i.status='active'
                        ORDER BY bm25(memory_fts) ASC LIMIT ?
                        """,
                        (q, user_id, int(limit)),
                    ).fetchall()
                return [(str(r[0]), float(r[1] or 0.0)) for r in rows]
            except Exception:
                return []

    def vec_search(self, vec: List[float], limit: int = 30) -> List[str]:
        if not self.vec_enabled:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT item_id FROM memory_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                    (json.dumps(vec), int(limit)),
                ).fetchall()
                return [str(r[0]) for r in rows]
            except Exception:
                return []

    def get_items_by_ids(self, user_id: str, ids: List[str]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        qmarks = ",".join(["?"] * len(ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_items WHERE user_id=? AND id IN ({qmarks}) AND status='active' ORDER BY ts DESC",
                [user_id] + ids,
            ).fetchall()
        return [dict(r) for r in rows]

    def db_stats(self, user_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE user_id=?", (user_id,)).fetchone()[0])
            active = int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0])
            events = int(conn.execute("SELECT COUNT(*) FROM memory_events WHERE user_id=?", (user_id,)).fetchone()[0])
            fts = int(conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])
        return {"memory_items_total": total, "memory_items_active": active, "memory_events": events, "memory_fts": fts}

    # reminders
    def upsert_reminder(self, r: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reminders(id, ts, user_id, title, due_ts, status, scope, details, priority, last_notified_ts, notify_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  ts=excluded.ts,status=excluded.status,last_notified_ts=excluded.last_notified_ts,notify_count=excluded.notify_count,
                  due_ts=excluded.due_ts,title=excluded.title,details=excluded.details,scope=excluded.scope,priority=excluded.priority
                """,
                (
                    r.get("id"), r.get("ts"), r.get("user_id"), r.get("title"), r.get("due_ts"), r.get("status"), r.get("scope", "task"),
                    r.get("details", ""), int(r.get("priority", 3) or 3), r.get("last_notified_ts"), int(r.get("notify_count", 0) or 0),
                ),
            )

    def due_reminders(self, user_id: str, now_iso: str, limit: int = 5) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE user_id=? AND status='active' AND due_ts<=? ORDER BY due_ts ASC LIMIT ?",
                (user_id, now_iso, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def active_reminders(self, user_id: str, scope: str = "task", limit: int = 25) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE user_id=? AND status='active' AND scope=? ORDER BY due_ts ASC LIMIT ?",
                (user_id, scope, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_reminder_by_title(self, user_id: str, title: str, scope: str = "task") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE reminders SET status='retracted', ts=? WHERE user_id=? AND status='active' AND scope=? AND lower(title)=lower(?)",
                (utcnow_iso(), user_id, scope, title),
            )
            return int(cur.rowcount or 0)

    def mark_reminder_done(self, reminder_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET status='done', ts=?, last_notified_ts=?, notify_count=notify_count+1 WHERE id=?",
                (utcnow_iso(), utcnow_iso(), reminder_id),
            )

    def all_active_for_decay(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM memory_items WHERE status='active'").fetchall()
        return [dict(r) for r in rows]

    def reinforce_skill(self, item_id: str, delta: float = 0.02, cap: float = 0.95) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT confidence FROM memory_items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return
            conf = float(row[0] or 0.0)
            conf = min(float(cap), max(0.0, conf + float(delta)))
            conn.execute(
                "UPDATE memory_items SET confidence=?, last_used=?, last_used_at=?, updated_at=? WHERE id=?",
                (conf, utcnow_iso(), utcnow_iso(), utcnow_iso(), item_id),
            )
