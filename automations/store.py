from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AutomationRun, AutomationSpec


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps(default, ensure_ascii=False, sort_keys=True)


class AutomationStore:
    def __init__(self, db_path: str | Path = "sessions/state/automations.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
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
                    CREATE TABLE IF NOT EXISTS automations (
                        automation_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        automation_type TEXT NOT NULL,
                        target_channel TEXT NOT NULL,
                        schedule_json TEXT NOT NULL DEFAULT '{}',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_run_at TEXT NOT NULL DEFAULT '',
                        next_run_at TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_automations_user_status
                    ON automations(user_id, status, next_run_at);

                    CREATE TABLE IF NOT EXISTS automation_runs (
                        run_id TEXT PRIMARY KEY,
                        automation_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        target_channel TEXT NOT NULL,
                        delivery_status TEXT NOT NULL,
                        output_text TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        FOREIGN KEY(automation_id) REFERENCES automations(automation_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_automation_runs_automation
                    ON automation_runs(automation_id, created_at);
                    """
                )

    def upsert_automation(self, spec: AutomationSpec | dict[str, Any]) -> dict[str, Any]:
        row = spec.to_record() if isinstance(spec, AutomationSpec) else dict(spec or {})
        payload = (
            str(row.get("automation_id") or ""),
            str(row.get("user_id") or ""),
            str(row.get("name") or ""),
            str(row.get("automation_type") or "session_digest"),
            str(row.get("target_channel") or "desktop"),
            _json(dict(row.get("schedule") or {}), {}),
            _json(dict(row.get("payload") or {}), {}),
            str(row.get("status") or "active"),
            str(row.get("created_at") or _now_iso()),
            str(row.get("updated_at") or _now_iso()),
            str(row.get("last_run_at") or ""),
            str((row.get("schedule") or {}).get("next_run_at") or row.get("next_run_at") or ""),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO automations(
                    automation_id, user_id, name, automation_type, target_channel, schedule_json, payload_json, status,
                    created_at, updated_at, last_run_at, next_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(automation_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    name=excluded.name,
                    automation_type=excluded.automation_type,
                    target_channel=excluded.target_channel,
                    schedule_json=excluded.schedule_json,
                    payload_json=excluded.payload_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    last_run_at=excluded.last_run_at,
                    next_run_at=excluded.next_run_at
                """,
                payload,
            )
        return self.get_automation(str(row.get("automation_id") or "")) or {}

    def get_automation(self, automation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM automations WHERE automation_id = ?", (str(automation_id),)).fetchone()
        return self._row_to_automation(row) if row else None

    def list_automations(self, *, user_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(str(user_id))
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status))
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM automations{where_sql} ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 50)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_automation(row) for row in rows]

    def due_automations(self, *, now_iso: str, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM automations
                WHERE status = 'active' AND next_run_at != '' AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (str(now_iso), max(1, int(limit or 25))),
            ).fetchall()
        return [self._row_to_automation(row) for row in rows]

    def update_schedule(self, automation_id: str, *, next_run_at: str, last_run_at: str, status: str | None = None) -> None:
        with self._connect() as conn:
            if status is None:
                conn.execute(
                    "UPDATE automations SET next_run_at = ?, last_run_at = ?, updated_at = ? WHERE automation_id = ?",
                    (str(next_run_at), str(last_run_at), _now_iso(), str(automation_id)),
                )
            else:
                conn.execute(
                    "UPDATE automations SET next_run_at = ?, last_run_at = ?, status = ?, updated_at = ? WHERE automation_id = ?",
                    (str(next_run_at), str(last_run_at), str(status), _now_iso(), str(automation_id)),
                )

    def record_run(self, run: AutomationRun | dict[str, Any]) -> dict[str, Any]:
        row = run.to_record() if isinstance(run, AutomationRun) else dict(run or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_runs(
                    run_id, automation_id, user_id, status, target_channel, delivery_status, output_text, metadata_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get("run_id") or ""),
                    str(row.get("automation_id") or ""),
                    str(row.get("user_id") or ""),
                    str(row.get("status") or ""),
                    str(row.get("target_channel") or ""),
                    str(row.get("delivery_status") or ""),
                    str(row.get("output_text") or ""),
                    _json(dict(row.get("metadata") or {}), {}),
                    str(row.get("created_at") or _now_iso()),
                    str(row.get("completed_at") or _now_iso()),
                ),
            )
        return self.list_runs(automation_id=str(row.get("automation_id") or ""), limit=1)[0]

    def list_runs(self, *, automation_id: str | None = None, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if automation_id is not None:
            clauses.append("automation_id = ?")
            params.append(str(automation_id))
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(str(user_id))
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM automation_runs{where_sql} ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit or 50)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "run_id": str(row["run_id"]),
                "automation_id": str(row["automation_id"]),
                "user_id": str(row["user_id"]),
                "status": str(row["status"]),
                "target_channel": str(row["target_channel"]),
                "delivery_status": str(row["delivery_status"]),
                "output_text": str(row["output_text"]),
                "metadata": json.loads(str(row["metadata_json"] or "{}")),
                "created_at": str(row["created_at"]),
                "completed_at": str(row["completed_at"]),
            }
            for row in rows
        ]

    def _row_to_automation(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "automation_id": str(row["automation_id"]),
            "user_id": str(row["user_id"]),
            "name": str(row["name"]),
            "automation_type": str(row["automation_type"]),
            "target_channel": str(row["target_channel"]),
            "schedule": json.loads(str(row["schedule_json"] or "{}")),
            "payload": json.loads(str(row["payload_json"] or "{}")),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_run_at": str(row["last_run_at"]),
            "next_run_at": str(row["next_run_at"]),
        }
