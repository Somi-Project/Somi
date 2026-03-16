from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DEFAULT_DB_PATH = Path("sessions/state/system_state.sqlite3")
SEARCH_TEXT_LIMIT = 4000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any, *, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps(default, ensure_ascii=False, sort_keys=True)


def _search_text(value: Any, *, limit: int = SEARCH_TEXT_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _session_id(user_id: str, thread_id: str) -> str:
    return f"{str(user_id or 'default_user')}::{str(thread_id or 'general')}"


@dataclass(frozen=True)
class TurnTrace:
    session_id: str
    turn_id: int
    turn_index: int
    user_id: str
    thread_id: str
    started_at: str


class SessionEventStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._fts_enabled: Optional[bool] = None
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        turn_count INTEGER NOT NULL DEFAULT 0,
                        last_route TEXT NOT NULL DEFAULT '',
                        last_model TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS idx_sessions_user_thread
                    ON sessions(user_id, thread_id);

                    CREATE TABLE IF NOT EXISTS turns (
                        turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        turn_index INTEGER NOT NULL,
                        user_text TEXT NOT NULL DEFAULT '',
                        routing_prompt TEXT NOT NULL DEFAULT '',
                        assistant_text TEXT NOT NULL DEFAULT '',
                        route TEXT NOT NULL DEFAULT '',
                        model_name TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'started',
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        tool_event_count INTEGER NOT NULL DEFAULT 0,
                        attachments_json TEXT NOT NULL DEFAULT '[]',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_turns_session_turn
                    ON turns(session_id, turn_index);

                    CREATE INDEX IF NOT EXISTS idx_turns_created_at
                    ON turns(created_at);

                    CREATE TABLE IF NOT EXISTS events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        turn_id INTEGER,
                        event_type TEXT NOT NULL,
                        event_name TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        searchable_text TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                        FOREIGN KEY(turn_id) REFERENCES turns(turn_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_events_session_turn
                    ON events(session_id, turn_id, created_at);

                    CREATE INDEX IF NOT EXISTS idx_events_name
                    ON events(event_name, created_at);
                    """
                )
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS turn_fts
                        USING fts5(
                            session_id UNINDEXED,
                            turn_id UNINDEXED,
                            user_text,
                            routing_prompt,
                            assistant_text,
                            route,
                            model_name
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS event_fts
                        USING fts5(
                            session_id UNINDEXED,
                            event_id UNINDEXED,
                            event_type,
                            event_name,
                            searchable_text
                        )
                        """
                    )
                    self._fts_enabled = True
                except sqlite3.OperationalError:
                    self._fts_enabled = False

    def _upsert_session(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        thread_id: str,
        timestamp: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, sqlite3.Row]:
        session_id = _session_id(user_id, thread_id)
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO sessions(session_id, user_id, thread_id, started_at, last_seen_at, turn_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    session_id,
                    str(user_id or "default_user"),
                    str(thread_id or "general"),
                    timestamp,
                    timestamp,
                    _safe_json(dict(metadata or {}), default={}),
                ),
            )
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return session_id, row

    def start_turn(
        self,
        *,
        user_id: str,
        thread_id: str,
        user_text: str,
        routing_prompt: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> TurnTrace:
        timestamp = str(created_at or _now_iso())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session_id, session_row = self._upsert_session(
                conn,
                user_id=str(user_id or "default_user"),
                thread_id=str(thread_id or "general"),
                timestamp=timestamp,
                metadata=metadata,
            )
            turn_index = int(session_row["turn_count"] or 0) + 1
            cur = conn.execute(
                """
                INSERT INTO turns(
                    session_id,
                    turn_index,
                    user_text,
                    routing_prompt,
                    status,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, 'started', ?, ?)
                """,
                (
                    session_id,
                    turn_index,
                    str(user_text or ""),
                    str(routing_prompt or user_text or ""),
                    _safe_json(dict(metadata or {}), default={}),
                    timestamp,
                ),
            )
            turn_id = int(cur.lastrowid or 0)
            conn.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?, turn_count = ?, metadata_json = COALESCE(NULLIF(?, ''), metadata_json)
                WHERE session_id = ?
                """,
                (timestamp, turn_index, _safe_json(dict(metadata or {}), default={}), session_id),
            )
            self._insert_event_row(
                conn,
                session_id=session_id,
                turn_id=turn_id,
                event_type="turn_started",
                event_name="turn_started",
                payload={
                    "turn_index": turn_index,
                    "user_text": str(user_text or ""),
                    "routing_prompt": str(routing_prompt or user_text or ""),
                    "metadata": dict(metadata or {}),
                },
                created_at=timestamp,
            )
            conn.commit()
        return TurnTrace(
            session_id=session_id,
            turn_id=turn_id,
            turn_index=turn_index,
            user_id=str(user_id or "default_user"),
            thread_id=str(thread_id or "general"),
            started_at=timestamp,
        )

    def _insert_event_row(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        turn_id: int | None,
        event_type: str,
        event_name: str,
        payload: Any,
        created_at: str,
    ) -> int:
        payload_json = _safe_json(payload, default={})
        searchable_text = _search_text(payload)
        cur = conn.execute(
            """
            INSERT INTO events(session_id, turn_id, event_type, event_name, payload_json, searchable_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                turn_id,
                str(event_type or "event"),
                str(event_name or "event"),
                payload_json,
                searchable_text,
                str(created_at or _now_iso()),
            ),
        )
        event_id = int(cur.lastrowid or 0)
        if self._fts_enabled:
            conn.execute(
                """
                INSERT INTO event_fts(rowid, session_id, event_id, event_type, event_name, searchable_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    event_id,
                    str(event_type or "event"),
                    str(event_name or "event"),
                    searchable_text,
                ),
            )
        return event_id

    def record_event(
        self,
        *,
        event_type: str,
        event_name: str,
        payload: Any,
        trace: TurnTrace | None = None,
        user_id: str | None = None,
        thread_id: str | None = None,
        created_at: str | None = None,
    ) -> int:
        timestamp = str(created_at or _now_iso())
        resolved_user_id = str((trace.user_id if trace else user_id) or "default_user")
        resolved_thread_id = str((trace.thread_id if trace else thread_id) or "general")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session_id, _ = self._upsert_session(
                conn,
                user_id=resolved_user_id,
                thread_id=resolved_thread_id,
                timestamp=timestamp,
            )
            event_id = self._insert_event_row(
                conn,
                session_id=session_id,
                turn_id=(trace.turn_id if trace else None),
                event_type=event_type,
                event_name=event_name,
                payload=payload,
                created_at=timestamp,
            )
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                (timestamp, session_id),
            )
            conn.commit()
            return event_id

    def _tool_event_type(self, row: dict[str, Any]) -> str:
        status = str((row or {}).get("status") or "").strip().lower()
        if status in {"started", "queued", "requested", "calling"}:
            return "tool_called"
        if status in {"ok", "selected", "recovered", "repaired", "success"}:
            return "tool_completed"
        if status in {"error", "failed", "timeout", "blocked"}:
            return "tool_failed"
        return "tool_completed"

    def finish_turn(
        self,
        *,
        trace: TurnTrace | None,
        assistant_text: str,
        status: str,
        route: str = "",
        model_name: str = "",
        routing_prompt: str = "",
        latency_ms: int | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        completed_at: str | None = None,
    ) -> None:
        if trace is None:
            return
        timestamp = str(completed_at or _now_iso())
        events = list(tool_events or [])
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE turns
                SET assistant_text = ?,
                    routing_prompt = ?,
                    route = ?,
                    model_name = ?,
                    status = ?,
                    latency_ms = ?,
                    tool_event_count = ?,
                    attachments_json = ?,
                    metadata_json = ?,
                    completed_at = ?
                WHERE turn_id = ?
                """,
                (
                    str(assistant_text or ""),
                    str(routing_prompt or ""),
                    str(route or ""),
                    str(model_name or ""),
                    str(status or "completed"),
                    int(latency_ms or 0),
                    len(events),
                    _safe_json(list(attachments or []), default=[]),
                    _safe_json(dict(metadata or {}), default={}),
                    timestamp,
                    int(trace.turn_id),
                ),
            )
            conn.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?,
                    last_route = ?,
                    last_model = ?
                WHERE session_id = ?
                """,
                (timestamp, str(route or ""), str(model_name or ""), trace.session_id),
            )
            self._insert_event_row(
                conn,
                session_id=trace.session_id,
                turn_id=trace.turn_id,
                event_type="turn_completed",
                event_name="turn_completed",
                payload={
                    "turn_index": trace.turn_index,
                    "status": str(status or "completed"),
                    "route": str(route or ""),
                    "model_name": str(model_name or ""),
                    "latency_ms": int(latency_ms or 0),
                    "tool_event_count": len(events),
                    "metadata": dict(metadata or {}),
                },
                created_at=timestamp,
            )
            for row in events:
                if not isinstance(row, dict):
                    continue
                tool_name = str(row.get("tool") or row.get("name") or "tool")
                self._insert_event_row(
                    conn,
                    session_id=trace.session_id,
                    turn_id=trace.turn_id,
                    event_type=self._tool_event_type(row),
                    event_name=tool_name,
                    payload=row,
                    created_at=timestamp,
                )
            if self._fts_enabled:
                conn.execute(
                    "DELETE FROM turn_fts WHERE rowid = ?",
                    (trace.turn_id,),
                )
                conn.execute(
                    """
                    INSERT INTO turn_fts(
                        rowid,
                        session_id,
                        turn_id,
                        user_text,
                        routing_prompt,
                        assistant_text,
                        route,
                        model_name
                    )
                    SELECT
                        turn_id,
                        session_id,
                        turn_id,
                        user_text,
                        routing_prompt,
                        assistant_text,
                        route,
                        model_name
                    FROM turns
                    WHERE turn_id = ?
                    """,
                    (trace.turn_id,),
                )
            conn.commit()

    def load_session_timeline(self, *, user_id: str, thread_id: str) -> dict[str, Any]:
        session_id = _session_id(user_id, thread_id)
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session_row is None:
                return {"session": None, "turns": [], "unbound_events": []}
            turn_rows = conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index ASC",
                (session_id,),
            ).fetchall()
            event_rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY created_at ASC, event_id ASC",
                (session_id,),
            ).fetchall()

        events_by_turn: dict[int, list[dict[str, Any]]] = {}
        unbound_events: list[dict[str, Any]] = []
        for row in event_rows:
            item = {
                "event_id": int(row["event_id"]),
                "event_type": str(row["event_type"]),
                "event_name": str(row["event_name"]),
                "created_at": str(row["created_at"]),
                "payload": json.loads(str(row["payload_json"] or "{}")),
            }
            turn_id = row["turn_id"]
            if turn_id is None:
                unbound_events.append(item)
            else:
                events_by_turn.setdefault(int(turn_id), []).append(item)

        turns: list[dict[str, Any]] = []
        for row in turn_rows:
            turns.append(
                {
                    "turn_id": int(row["turn_id"]),
                    "turn_index": int(row["turn_index"]),
                    "user_text": str(row["user_text"]),
                    "routing_prompt": str(row["routing_prompt"]),
                    "assistant_text": str(row["assistant_text"]),
                    "route": str(row["route"]),
                    "model_name": str(row["model_name"]),
                    "status": str(row["status"]),
                    "latency_ms": int(row["latency_ms"] or 0),
                    "tool_event_count": int(row["tool_event_count"] or 0),
                    "attachments": json.loads(str(row["attachments_json"] or "[]")),
                    "metadata": json.loads(str(row["metadata_json"] or "{}")),
                    "created_at": str(row["created_at"]),
                    "completed_at": str(row["completed_at"] or ""),
                    "events": events_by_turn.get(int(row["turn_id"]), []),
                }
            )

        session = {
            "session_id": str(session_row["session_id"]),
            "user_id": str(session_row["user_id"]),
            "thread_id": str(session_row["thread_id"]),
            "started_at": str(session_row["started_at"]),
            "last_seen_at": str(session_row["last_seen_at"]),
            "turn_count": int(session_row["turn_count"] or 0),
            "last_route": str(session_row["last_route"]),
            "last_model": str(session_row["last_model"]),
            "metadata": json.loads(str(session_row["metadata_json"] or "{}")),
        }
        return {"session": session, "turns": turns, "unbound_events": unbound_events}

    def list_sessions(
        self,
        *,
        user_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(str(user_id))
        if thread_id is not None:
            clauses.append("thread_id = ?")
            params.append(str(thread_id))
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM sessions{where_sql} ORDER BY last_seen_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "session_id": str(row["session_id"]),
                "user_id": str(row["user_id"]),
                "thread_id": str(row["thread_id"]),
                "started_at": str(row["started_at"]),
                "last_seen_at": str(row["last_seen_at"]),
                "turn_count": int(row["turn_count"] or 0),
                "last_route": str(row["last_route"] or ""),
                "last_model": str(row["last_model"] or ""),
                "metadata": json.loads(str(row["metadata_json"] or "{}")),
            }
            for row in rows
        ]

    def list_recent_events(
        self,
        *,
        user_id: str | None = None,
        thread_id: str | None = None,
        event_type: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("s.user_id = ?")
            params.append(str(user_id))
        if thread_id is not None:
            clauses.append("s.thread_id = ?")
            params.append(str(thread_id))
        if event_type is not None:
            clauses.append("e.event_type = ?")
            params.append(str(event_type))
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT
                e.event_id,
                e.session_id,
                e.turn_id,
                e.event_type,
                e.event_name,
                e.payload_json,
                e.created_at,
                s.user_id,
                s.thread_id
            FROM events e
            JOIN sessions s ON s.session_id = e.session_id
            {where_sql}
            ORDER BY e.created_at DESC, e.event_id DESC
            LIMIT ?
        """
        params.append(max(1, int(limit or 30)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "event_id": int(row["event_id"]),
                "session_id": str(row["session_id"]),
                "turn_id": int(row["turn_id"]) if row["turn_id"] is not None else None,
                "event_type": str(row["event_type"]),
                "event_name": str(row["event_name"]),
                "payload": json.loads(str(row["payload_json"] or "{}")),
                "created_at": str(row["created_at"]),
                "user_id": str(row["user_id"]),
                "thread_id": str(row["thread_id"]),
            }
            for row in rows
        ]

    def search_text(
        self,
        query: str,
        *,
        user_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        limit = max(1, int(limit or 10))
        with self._connect() as conn:
            if self._fts_enabled:
                return self._search_fts(conn, query=q, user_id=user_id, thread_id=thread_id, limit=limit)
            return self._search_like(conn, query=q, user_id=user_id, thread_id=thread_id, limit=limit)

    def _search_fts(
        self,
        conn: sqlite3.Connection,
        *,
        query: str,
        user_id: str | None,
        thread_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if user_id:
            filters.append("s.user_id = ?")
            params.append(str(user_id))
        if thread_id:
            filters.append("s.thread_id = ?")
            params.append(str(thread_id))
        turn_where = "WHERE turn_fts MATCH ?"
        event_where = "WHERE event_fts MATCH ?"
        if filters:
            extra = " AND " + " AND ".join(filters)
            turn_where += extra
            event_where += extra

        sql = f"""
            SELECT * FROM (
                SELECT
                    'turn' AS source_type,
                    t.turn_id AS source_id,
                    s.session_id AS session_id,
                    s.user_id AS user_id,
                    s.thread_id AS thread_id,
                    t.created_at AS created_at,
                    (COALESCE(t.user_text, '') || ' ' || COALESCE(t.assistant_text, '')) AS snippet,
                    bm25(turn_fts) AS score
                FROM turn_fts
                JOIN turns t ON t.turn_id = turn_fts.rowid
                JOIN sessions s ON s.session_id = t.session_id
                {turn_where}
                UNION ALL
                SELECT
                    'event' AS source_type,
                    e.event_id AS source_id,
                    s.session_id AS session_id,
                    s.user_id AS user_id,
                    s.thread_id AS thread_id,
                    e.created_at AS created_at,
                    (COALESCE(e.event_name, '') || ' ' || COALESCE(e.searchable_text, '')) AS snippet,
                    bm25(event_fts) AS score
                FROM event_fts
                JOIN events e ON e.event_id = event_fts.rowid
                JOIN sessions s ON s.session_id = e.session_id
                {event_where}
            )
            ORDER BY score ASC, created_at DESC
            LIMIT ?
        """
        effective_params = [query]
        effective_params.extend(params)
        effective_params.append(query)
        effective_params.extend(params)
        effective_params.append(limit)
        rows = conn.execute(sql, tuple(effective_params)).fetchall()
        return [
            {
                "source_type": str(row["source_type"]),
                "source_id": int(row["source_id"]),
                "session_id": str(row["session_id"]),
                "user_id": str(row["user_id"]),
                "thread_id": str(row["thread_id"]),
                "created_at": str(row["created_at"]),
                "score": float(row["score"] or 0.0),
                "snippet": _search_text(row["snippet"], limit=280),
            }
            for row in rows
        ]

    def _search_like(
        self,
        conn: sqlite3.Connection,
        *,
        query: str,
        user_id: str | None,
        thread_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        filters: list[str] = []
        params: list[Any] = []
        if user_id:
            filters.append("s.user_id = ?")
            params.append(str(user_id))
        if thread_id:
            filters.append("s.thread_id = ?")
            params.append(str(thread_id))
        where_sql = f" AND {' AND '.join(filters)}" if filters else ""
        sql = f"""
            SELECT * FROM (
                SELECT
                    'turn' AS source_type,
                    t.turn_id AS source_id,
                    s.session_id AS session_id,
                    s.user_id AS user_id,
                    s.thread_id AS thread_id,
                    t.created_at AS created_at,
                    (COALESCE(t.user_text, '') || ' ' || COALESCE(t.assistant_text, '')) AS snippet
                FROM turns t
                JOIN sessions s ON s.session_id = t.session_id
                WHERE (
                    t.user_text LIKE ?
                    OR t.routing_prompt LIKE ?
                    OR t.assistant_text LIKE ?
                    OR t.route LIKE ?
                    OR t.model_name LIKE ?
                ){where_sql}
                UNION ALL
                SELECT
                    'event' AS source_type,
                    e.event_id AS source_id,
                    s.session_id AS session_id,
                    s.user_id AS user_id,
                    s.thread_id AS thread_id,
                    e.created_at AS created_at,
                    (COALESCE(e.event_name, '') || ' ' || COALESCE(e.searchable_text, '')) AS snippet
                FROM events e
                JOIN sessions s ON s.session_id = e.session_id
                WHERE (
                    e.event_name LIKE ?
                    OR e.searchable_text LIKE ?
                ){where_sql}
            )
            ORDER BY created_at DESC
            LIMIT ?
        """
        effective_params = [pattern, pattern, pattern, pattern, pattern]
        effective_params.extend(params)
        effective_params.extend([pattern, pattern])
        effective_params.extend(params)
        effective_params.append(limit)
        rows = conn.execute(sql, tuple(effective_params)).fetchall()
        return [
            {
                "source_type": str(row["source_type"]),
                "source_id": int(row["source_id"]),
                "session_id": str(row["session_id"]),
                "user_id": str(row["user_id"]),
                "thread_id": str(row["thread_id"]),
                "created_at": str(row["created_at"]),
                "score": 0.0,
                "snippet": _search_text(row["snippet"], limit=280),
            }
            for row in rows
        ]
