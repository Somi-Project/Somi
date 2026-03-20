from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from config.memorysettings import (
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

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> Set[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        except Exception:
            return set()
        return {str(r[1]) for r in rows}

    def _migrate_memory_items_if_needed(self, conn: sqlite3.Connection) -> None:
        cols = self._table_columns(conn, "memory_items")
        if not cols:
            return

        required = {
            "id", "created_at", "updated_at", "user_id", "lane", "type", "entity", "mkey", "value", "kind",
            "bucket", "importance", "replaced_by", "text", "tags", "confidence", "status", "expires_at",
            "scope", "mem_type", "entities_json", "tags_json", "supersedes_id", "contradicts_id", "last_used_at", "slot_key",
        }
        if required.issubset(cols):
            return

        def c(name: str, fallback: str = "NULL") -> str:
            return name if name in cols else fallback

        conn.execute("ALTER TABLE memory_items RENAME TO memory_items_legacy")
        conn.executescript(SCHEMA_SQL)

        insert_sql = f"""
            INSERT INTO memory_items(
                id, created_at, updated_at, user_id, lane, type, entity, mkey, value, kind,
                bucket, importance, replaced_by, text, tags, confidence, status, expires_at,
                scope, mem_type, entities_json, tags_json, supersedes_id, contradicts_id, last_used_at, slot_key
            )
            SELECT
                {c('id')},
                COALESCE({c('created_at')}, {c('ts')}, '{utcnow_iso()}'),
                COALESCE({c('updated_at')}, {c('created_at')}, {c('ts')}, '{utcnow_iso()}'),
                COALESCE(NULLIF({c('user_id', "''")}, ''), 'default_user'),
                COALESCE({c('lane', "'facts'")}, 'facts'),
                COALESCE({c('type', "'fact'")}, 'fact'),
                {c('entity')},
                {c('mkey')},
                {c('value')},
                COALESCE({c('kind', "'preference'")}, 'preference'),
                COALESCE({c('bucket', "'general'")}, 'general'),
                COALESCE({c('importance', '0.5')}, 0.5),
                {c('replaced_by')},
                COALESCE(NULLIF({c('text', "''")}, ''), {c('content', "''")}, {c('value', "''")}, ''),
                {c('tags')},
                COALESCE({c('confidence', '0.7')}, 0.7),
                COALESCE({c('status', "'active'")}, 'active'),
                {c('expires_at')},
                COALESCE(NULLIF({c('scope', "''")}, ''), 'conversation'),
                COALESCE(NULLIF({c('mem_type', "''")}, ''), {c('type', "'note'")}, 'note'),
                {c('entities_json')},
                {c('tags_json')},
                COALESCE({c('supersedes_id')}, {c('supersedes')}),
                {c('contradicts_id')},
                COALESCE({c('last_used_at')}, {c('last_used')}),
                {c('slot_key')}
            FROM memory_items_legacy
        """
        conn.execute(insert_sql)
        conn.execute("DROP TABLE memory_items_legacy")

    def _ensure_fts_schema(self, conn: sqlite3.Connection) -> None:
        fts_cols = self._table_columns(conn, "memory_fts")
        if fts_cols and "text" not in fts_cols:
            conn.execute("DROP TABLE memory_fts")
            conn.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(text, tags, mkey, item_id UNINDEXED)")

        conn.execute("DELETE FROM memory_fts")
        conn.execute(
            "INSERT INTO memory_fts(text, tags, mkey, item_id) SELECT COALESCE(text,''), COALESCE(tags,''), COALESCE(mkey,''), id FROM memory_items"
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            existing_cols = self._table_columns(conn, "memory_items")
            if existing_cols:
                self._migrate_memory_items_if_needed(conn)
            conn.executescript(SCHEMA_SQL)
            self._ensure_fts_schema(conn)
            conn.execute("UPDATE memory_items SET user_id='default_user' WHERE user_id IS NULL OR user_id=''")
            conn.execute("UPDATE memory_items SET scope=COALESCE(NULLIF(scope,''),'conversation')")
            conn.execute("UPDATE memory_items SET mem_type=COALESCE(NULLIF(mem_type,''),'note')")
            conn.execute("UPDATE memory_items SET text=COALESCE(NULLIF(text,''),value)")
            conn.execute("UPDATE memory_items SET updated_at=COALESCE(updated_at, created_at)")

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

    def _upsert_fts(self, conn: sqlite3.Connection, item_id: str, text: str, tags: str, mkey: str) -> None:
        conn.execute("DELETE FROM memory_fts WHERE item_id=?", (item_id,))
        conn.execute(
            "INSERT INTO memory_fts(text, tags, mkey, item_id) VALUES (?, ?, ?, ?)",
            (text or "", tags or "", mkey or "", item_id),
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
        created_at = str(item.get("created_at") or now_iso)
        updated_at = str(item.get("updated_at") or created_at)
        text = str(item.get("text") or item.get("value") or "")
        payload = (
            item_id,
            created_at,
            updated_at,
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
            text,
            item.get("tags", ""),
            float(item.get("confidence", 0.7) or 0.7),
            item.get("status", "active"),
            item.get("expires_at"),
            item.get("scope", "conversation"),
            item.get("mem_type", item.get("type", "note")),
            item.get("entities_json"),
            item.get("tags_json"),
            item.get("supersedes_id"),
            item.get("contradicts_id"),
            item.get("last_used_at"),
            item.get("slot_key"),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items(
                    id, created_at, updated_at, user_id, lane, type, entity, mkey, value, kind,
                    bucket, importance, replaced_by, text, tags, confidence, status, expires_at,
                    scope, mem_type, entities_json, tags_json, supersedes_id, contradicts_id,
                    last_used_at, slot_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            self._upsert_fts(conn, item_id, text, str(item.get("tags", "")), str(item.get("mkey", "")))
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

    def upsert_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        source_id = str(source.get("source_id") or uuid.uuid4())
        now_iso = utcnow_iso()
        payload = (
            source_id,
            str(source.get("user_id") or "default_user"),
            str(source.get("source_type") or "note"),
            str(source.get("title") or source_id),
            str(source.get("location") or ""),
            str(source.get("content_type") or ""),
            int(source.get("item_count") or 0),
            str(source.get("status") or "active"),
            json.dumps(dict(source.get("metadata") or {}), ensure_ascii=False),
            str(source.get("created_at") or now_iso),
            str(source.get("updated_at") or now_iso),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_sources(
                    source_id, user_id, source_type, title, location, content_type,
                    item_count, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    source_type=excluded.source_type,
                    title=excluded.title,
                    location=excluded.location,
                    content_type=excluded.content_type,
                    item_count=excluded.item_count,
                    status=excluded.status,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
        return self.get_source(source_id) or {"source_id": source_id}

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        if not str(source_id or "").strip():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_sources WHERE source_id=? LIMIT 1",
                (str(source_id),),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["metadata"] = json.loads(str(item.get("metadata_json") or "{}"))
        except Exception:
            item["metadata"] = {}
        return item

    def list_sources(self, user_id: str, limit: int = 20, source_type: str = "") -> List[Dict[str, Any]]:
        params: list[Any] = [str(user_id)]
        sql = "SELECT * FROM memory_sources WHERE user_id=?"
        if str(source_type or "").strip():
            sql += " AND source_type=?"
            params.append(str(source_type))
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(str(item.get("metadata_json") or "{}"))
            except Exception:
                item["metadata"] = {}
            out.append(item)
        return out

    def source_summary(self, user_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_type, status, COUNT(*) AS source_count, COALESCE(SUM(item_count), 0) AS item_total
                FROM memory_sources
                WHERE user_id=?
                GROUP BY source_type, status
                """,
                (str(user_id),),
            ).fetchall()
        total_sources = 0
        total_items = 0
        by_type: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for row in rows:
            source_type = str(row["source_type"] or "unknown")
            status = str(row["status"] or "unknown")
            source_count = int(row["source_count"] or 0)
            item_total = int(row["item_total"] or 0)
            total_sources += source_count
            total_items += item_total
            by_type[source_type] = by_type.get(source_type, 0) + source_count
            by_status[status] = by_status.get(status, 0) + source_count
        return {
            "total_sources": total_sources,
            "total_items": total_items,
            "by_type": by_type,
            "by_status": by_status,
        }

    def log_retrieval_trace(self, user_id: str, query: str, trace: Dict[str, Any]) -> str:
        trace_id = str(trace.get("trace_id") or f"trace-{uuid.uuid4().hex[:16]}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_retrieval_traces(trace_id, user_id, query, trace_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (trace_id, str(user_id), str(query or ""), json.dumps(dict(trace or {}), ensure_ascii=False), utcnow_iso()),
            )
        return trace_id

    def latest_retrieval_trace(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_retrieval_traces WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (str(user_id),),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["trace"] = json.loads(str(item.get("trace_json") or "{}"))
        except Exception:
            item["trace"] = {}
        return item

    def list_retrieval_traces(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_retrieval_traces WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (str(user_id), int(limit)),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["trace"] = json.loads(str(item.get("trace_json") or "{}"))
            except Exception:
                item["trace"] = {}
            out.append(item)
        return out

    def scope_counts(self, user_id: str, scopes: Optional[List[str]] = None) -> Dict[str, int]:
        params: list[Any] = [str(user_id)]
        sql = "SELECT scope, COUNT(*) AS item_count FROM memory_items WHERE user_id=? AND status='active'"
        if scopes:
            placeholders = ",".join(["?"] * len(scopes))
            sql += f" AND scope IN ({placeholders})"
            params.extend([str(scope) for scope in scopes])
        sql += " GROUP BY scope"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row["scope"] or "conversation"): int(row["item_count"] or 0) for row in rows}

    def active_fact(self, user_id: str, entity: str, mkey: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND type='fact' AND entity=? AND mkey=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                (user_id, entity, mkey),
            ).fetchone()
        return dict(row) if row else None

    def active_by_slot(self, user_id: str, slot_key: str) -> Optional[Dict[str, Any]]:
        if not slot_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND slot_key=? AND status='active' ORDER BY created_at DESC LIMIT 1",
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
                "SELECT * FROM memory_items WHERE user_id=? AND lane='pinned' AND status='active' ORDER BY created_at DESC LIMIT ?",
                (user_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_by_scope(self, user_id: str, scope: str, limit: int = 8) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND scope=? AND status='active' ORDER BY created_at DESC LIMIT ?",
                (user_id, scope, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_items(
        self,
        user_id: str,
        *,
        scopes: Optional[List[str]] = None,
        statuses: Optional[List[str]] = None,
        limit: int = 80,
    ) -> List[Dict[str, Any]]:
        params: list[Any] = [str(user_id)]
        sql = "SELECT * FROM memory_items WHERE user_id=?"
        if scopes:
            placeholders = ",".join(["?"] * len(scopes))
            sql += f" AND scope IN ({placeholders})"
            params.extend([str(scope) for scope in scopes])
        if statuses:
            placeholders = ",".join(["?"] * len(statuses))
            sql += f" AND status IN ({placeholders})"
            params.extend([str(status) for status in statuses])
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        params.append(max(1, int(limit or 80)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def latest_session_summary(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE user_id=? AND mem_type='summary' AND status='active' ORDER BY created_at DESC LIMIT 1",
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
                f"SELECT * FROM memory_items WHERE user_id=? AND id IN ({qmarks}) AND status='active' ORDER BY created_at DESC",
                [user_id] + ids,
            ).fetchall()
        return [dict(r) for r in rows]

    def db_stats(self, user_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE user_id=?", (user_id,)).fetchone()[0])
            active = int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0])
            events = int(conn.execute("SELECT COUNT(*) FROM memory_events WHERE user_id=?", (user_id,)).fetchone()[0])
            fts = int(conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])
            sources = int(conn.execute("SELECT COUNT(*) FROM memory_sources WHERE user_id=?", (user_id,)).fetchone()[0])
            retrieval_traces = int(
                conn.execute("SELECT COUNT(*) FROM memory_retrieval_traces WHERE user_id=?", (user_id,)).fetchone()[0]
            )
        return {
            "memory_items_total": total,
            "memory_items_active": active,
            "memory_events": events,
            "memory_fts": fts,
            "memory_sources": sources,
            "memory_retrieval_traces": retrieval_traces,
        }

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
                "UPDATE memory_items SET confidence=?, last_used_at=?, updated_at=? WHERE id=?",
                (conf, utcnow_iso(), utcnow_iso(), item_id),
            )
