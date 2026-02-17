from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .utils import utcnow_iso


class EventStore:
    def __init__(self, events_path: str):
        self.events_path = events_path
        os.makedirs(os.path.dirname(events_path), exist_ok=True)

    def append(self, event: Dict[str, Any]) -> None:
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def tail(self, max_lines: int = 400) -> List[Dict[str, Any]]:
        if not os.path.exists(self.events_path):
            return []
        try:
            with open(self.events_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-max_lines:]
            out: List[Dict[str, Any]] = []
            for line in lines:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
            return out
        except Exception:
            return []


class SQLiteMemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT,
                    status TEXT NOT NULL,
                    supersedes_claim_id TEXT,
                    superseded_by_claim_id TEXT,
                    contradiction_with_claim_id TEXT,
                    confidence REAL DEFAULT 0.60,
                    ts_created TEXT NOT NULL,
                    ts_updated TEXT NOT NULL,
                    salience REAL DEFAULT 0.5
                );
                CREATE INDEX IF NOT EXISTS idx_claims_user_scope_status ON claims(user_id, scope, status);

                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    payload_json TEXT,
                    ts_created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_user_scope ON nodes(user_id, scope);

                CREATE TABLE IF NOT EXISTS edges (
                    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    src_node_id TEXT NOT NULL,
                    dst_node_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    ts_created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_edges_user_scope_src ON edges(user_id, scope, src_node_id);
                CREATE INDEX IF NOT EXISTS idx_edges_user_scope_dst ON edges(user_id, scope, dst_node_id);

                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details TEXT,
                    due_ts TEXT NOT NULL,
                    recurrence TEXT,
                    channel TEXT DEFAULT 'in_app',
                    status TEXT NOT NULL DEFAULT 'active',
                    priority INTEGER DEFAULT 3,
                    snooze_until_ts TEXT,
                    last_fired_ts TEXT,
                    next_retry_ts TEXT,
                    fail_count INTEGER DEFAULT 0,
                    ts_created TEXT NOT NULL,
                    ts_updated TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(user_id, status, due_ts);
                CREATE INDEX IF NOT EXISTS idx_reminders_retry ON reminders(user_id, status, next_retry_ts);

                CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    progress REAL DEFAULT 0.0,
                    confidence REAL DEFAULT 0.6,
                    target_ts TEXT,
                    last_checkin_ts TEXT,
                    ts_created TEXT NOT NULL,
                    ts_updated TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_goals_user_status ON goals(user_id, status);
                """
            )

            for stmt in (
                "ALTER TABLE claims ADD COLUMN superseded_by_claim_id TEXT",
                "ALTER TABLE claims ADD COLUMN contradiction_with_claim_id TEXT",
                "ALTER TABLE claims ADD COLUMN confidence REAL DEFAULT 0.60",
            ):
                try:
                    conn.execute(stmt)
                except Exception:
                    pass

    def upsert_claim(
        self,
        claim_id: str,
        user_id: str,
        scope: str,
        memory_type: str,
        content: str,
        source: str,
        status: str = "active",
        supersedes_claim_id: Optional[str] = None,
        contradiction_with_claim_id: Optional[str] = None,
        confidence: float = 0.6,
        salience: float = 0.5,
    ) -> None:
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO claims(claim_id, user_id, scope, memory_type, content, source, status,
                                  supersedes_claim_id, superseded_by_claim_id, contradiction_with_claim_id,
                                  confidence, ts_created, ts_updated, salience)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(claim_id) DO UPDATE SET
                  content=excluded.content,
                  source=excluded.source,
                  status=excluded.status,
                  supersedes_claim_id=excluded.supersedes_claim_id,
                  superseded_by_claim_id=excluded.superseded_by_claim_id,
                  contradiction_with_claim_id=excluded.contradiction_with_claim_id,
                  confidence=excluded.confidence,
                  ts_updated=excluded.ts_updated,
                  salience=excluded.salience
                """,
                (
                    claim_id,
                    user_id,
                    scope,
                    memory_type,
                    content,
                    source,
                    status,
                    supersedes_claim_id,
                    None,
                    contradiction_with_claim_id,
                    float(confidence),
                    now,
                    now,
                    float(salience),
                ),
            )

    def set_claim_status(self, claim_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE claims SET status=?, ts_updated=? WHERE claim_id=?", (status, utcnow_iso(), claim_id))

    def mark_superseded(self, old_claim_id: str, by_claim_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE claims SET status='superseded', superseded_by_claim_id=?, ts_updated=? WHERE claim_id=?",
                (by_claim_id, utcnow_iso(), old_claim_id),
            )

    def recent_claims(self, user_id: str, scope: str, limit: int = 240) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT claim_id, content, memory_type, scope, status,
                       supersedes_claim_id, superseded_by_claim_id,
                       contradiction_with_claim_id, confidence,
                       ts_updated, salience
                FROM claims
                WHERE user_id=? AND scope=? AND status='active'
                ORDER BY ts_updated DESC LIMIT ?
                """,
                (user_id, scope, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_claim(self, user_id: str, claim_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT claim_id, user_id, scope, memory_type, content, source, status,
                       supersedes_claim_id, superseded_by_claim_id, contradiction_with_claim_id,
                       confidence, ts_created, ts_updated, salience
                FROM claims
                WHERE user_id=? AND claim_id=?
                LIMIT 1
                """,
                (user_id, claim_id),
            ).fetchone()
        return dict(row) if row else None

    def active_claim_count(self, user_id: str, scope: Optional[str] = None) -> int:
        with self._connect() as conn:
            if scope is None:
                row = conn.execute("SELECT COUNT(1) FROM claims WHERE user_id=? AND status='active'", (user_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(1) FROM claims WHERE user_id=? AND scope=? AND status='active'",
                    (user_id, scope),
                ).fetchone()
        return int(row[0] if row else 0)

    def add_reminder(
        self,
        reminder_id: str,
        user_id: str,
        scope: str,
        title: str,
        details: str,
        due_ts: str,
        channel: str = "in_app",
        recurrence: Optional[str] = None,
        priority: int = 3,
    ) -> None:
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reminders(reminder_id, user_id, scope, title, details, due_ts, recurrence, channel,
                                               status, priority, snooze_until_ts, last_fired_ts, next_retry_ts,
                                               fail_count, ts_created, ts_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, NULL, NULL, 0, ?, ?)
                """,
                (reminder_id, user_id, scope, title, details, due_ts, recurrence, channel, int(priority), now, now),
            )

    def due_reminders(self, user_id: str, now_iso: str, limit: int = 8) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE user_id=? AND status='active'
                  AND COALESCE(snooze_until_ts, due_ts) <= ?
                  AND (next_retry_ts IS NULL OR next_retry_ts <= ?)
                ORDER BY COALESCE(snooze_until_ts, due_ts) ASC, priority DESC
                LIMIT ?
                """,
                (user_id, now_iso, now_iso, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- NEW: list active reminders ----------------
    def active_reminders(self, user_id: str, scope: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Returns reminders that are still actionable (status='active').
        Ordered by soonest effective due time (snooze_until_ts overrides due_ts), then priority.
        """
        with self._connect() as conn:
            if scope is None:
                rows = conn.execute(
                    """
                    SELECT * FROM reminders
                    WHERE user_id=? AND status='active'
                    ORDER BY COALESCE(snooze_until_ts, due_ts) ASC, priority DESC, ts_updated DESC
                    LIMIT ?
                    """,
                    (user_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM reminders
                    WHERE user_id=? AND scope=? AND status='active'
                    ORDER BY COALESCE(snooze_until_ts, due_ts) ASC, priority DESC, ts_updated DESC
                    LIMIT ?
                    """,
                    (user_id, scope, int(limit)),
                ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- NEW: delete reminder(s) by title ----------------
    def delete_reminder_by_title(self, user_id: str, scope: str, title: str) -> int:
        """
        Deletes active reminders that match title (case-insensitive).
        Returns number deleted.
        """
        t = (title or "").strip()
        if not t:
            return 0

        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM reminders
                WHERE user_id=? AND scope=? AND status='active'
                  AND LOWER(title)=LOWER(?)
                """,
                (user_id, scope, t),
            )
            return int(cur.rowcount or 0)

    def mark_reminder_fired(self, reminder_id: str) -> None:
        now = utcnow_iso()
        next_retry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET last_fired_ts=?,
                    status=CASE
                        WHEN recurrence IS NULL OR TRIM(recurrence)='' THEN 'done'
                        WHEN LOWER(TRIM(recurrence)) IN ('daily', 'weekly', 'monthly') THEN status
                        ELSE 'done'
                    END,
                    next_retry_ts=CASE
                        WHEN LOWER(TRIM(recurrence)) IN ('daily', 'weekly', 'monthly') THEN ?
                        ELSE NULL
                    END,
                    fail_count=fail_count,
                    ts_updated=?
                WHERE reminder_id=?
                """,
                (now, next_retry, now, reminder_id),
            )

    def ack_reminder(self, reminder_id: str, action: str, snooze_until_ts: Optional[str] = None) -> None:
        now = utcnow_iso()
        action = (action or "done").strip().lower()
        with self._connect() as conn:
            if action == "snooze" and snooze_until_ts:
                conn.execute(
                    """
                    UPDATE reminders
                    SET snooze_until_ts=?, next_retry_ts=?, ts_updated=?
                    WHERE reminder_id=?
                    """,
                    (snooze_until_ts, snooze_until_ts, now, reminder_id),
                )
            elif action == "cancel":
                conn.execute("UPDATE reminders SET status='cancelled', ts_updated=? WHERE reminder_id=?", (now, reminder_id))
            else:
                conn.execute("UPDATE reminders SET status='done', ts_updated=? WHERE reminder_id=?", (now, reminder_id))

    def upsert_goal(
        self,
        goal_id: str,
        user_id: str,
        scope: str,
        title: str,
        objective: str,
        target_ts: Optional[str] = None,
        progress: float = 0.0,
        confidence: float = 0.6,
        status: str = "active",
    ) -> None:
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO goals(goal_id, user_id, scope, title, objective, status, progress, confidence, target_ts, last_checkin_ts, ts_created, ts_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_id) DO UPDATE SET
                  title=excluded.title,
                  objective=excluded.objective,
                  status=excluded.status,
                  progress=excluded.progress,
                  confidence=excluded.confidence,
                  target_ts=excluded.target_ts,
                  last_checkin_ts=excluded.last_checkin_ts,
                  ts_updated=excluded.ts_updated
                """,
                (goal_id, user_id, scope, title, objective, status, float(progress), float(confidence), target_ts, now, now, now),
            )

    def active_goals(self, user_id: str, scope: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            if scope is None:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE user_id=? AND status='active' ORDER BY ts_updated DESC LIMIT ?",
                    (user_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE user_id=? AND scope=? AND status='active' ORDER BY ts_updated DESC LIMIT ?",
                    (user_id, scope, int(limit)),
                ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- NEW: delete goal by title ----------------
    def delete_goal_by_title(self, user_id: str, scope: str, title: str) -> bool:
        """
        Deletes an active goal by exact title match (case-insensitive).
        Returns True if any row was deleted.
        """
        t = (title or "").strip()
        if not t:
            return False

        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM goals
                WHERE user_id=? AND scope=? AND status='active'
                  AND LOWER(title)=LOWER(?)
                """,
                (user_id, scope, t),
            )
            return bool(cur.rowcount and cur.rowcount > 0)

    def add_node(self, node_id: str, user_id: str, scope: str, kind: str, label: str, payload: Optional[Dict[str, Any]] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO nodes(node_id, user_id, scope, kind, label, payload_json, ts_created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, user_id, scope, kind, label, json.dumps(payload or {}, ensure_ascii=False), utcnow_iso()),
            )

    def add_edge(self, user_id: str, scope: str, src_node_id: str, dst_node_id: str, edge_type: str, weight: float = 1.0) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO edges(user_id, scope, src_node_id, dst_node_id, edge_type, weight, ts_created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, scope, src_node_id, dst_node_id, edge_type, float(weight), utcnow_iso()),
            )

    def neighbors(self, user_id: str, scope: str, node_ids: List[str], max_edges: int = 200) -> List[str]:
        if not node_ids:
            return []
        qmarks = ",".join(["?"] * len(node_ids))
        args = [user_id, scope, *node_ids, *node_ids, int(max_edges)]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT src_node_id, dst_node_id FROM edges
                WHERE user_id=? AND scope=?
                  AND (src_node_id IN ({qmarks}) OR dst_node_id IN ({qmarks}))
                ORDER BY ts_created DESC LIMIT ?
                """,
                args,
            ).fetchall()
        out: List[str] = []
        for r in rows:
            s, d = r[0], r[1]
            if s not in out:
                out.append(s)
            if d not in out:
                out.append(d)
        return out
