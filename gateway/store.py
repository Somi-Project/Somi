from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return "{}"


def _json_loads(raw: str | None) -> Any:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


class GatewayStore:
    def __init__(self, root_dir: str | Path = "sessions/gateway") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "gateway.sqlite3"
        self._lock = RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    client_label TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    auth_mode TEXT NOT NULL DEFAULT 'local',
                    trust_level TEXT NOT NULL DEFAULT 'trusted_local',
                    status TEXT NOT NULL DEFAULT 'online',
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_sessions_surface ON gateway_sessions(surface, last_seen_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_presence (
                    session_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'online',
                    activity TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_presence_surface ON gateway_presence(surface, updated_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_health (
                    service_key TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_health_surface ON gateway_health(surface, updated_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    level TEXT NOT NULL DEFAULT 'info',
                    user_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    client_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_events_surface ON gateway_events(surface, created_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    requested_surface TEXT NOT NULL,
                    client_label TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    owner_user_id TEXT NOT NULL DEFAULT 'default_user',
                    session_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_pairings_code ON gateway_pairings(code, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_nodes (
                    node_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    node_type TEXT NOT NULL DEFAULT '',
                    client_label TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    trust_level TEXT NOT NULL DEFAULT 'untrusted_remote',
                    status TEXT NOT NULL DEFAULT 'pending',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_nodes_type ON gateway_nodes(node_type, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_gateway_nodes_status ON gateway_nodes(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_remote_audit (
                    audit_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    capability TEXT NOT NULL DEFAULT '',
                    requested_path TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    operator_confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_remote_audit_node ON gateway_remote_audit(node_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS gateway_node_tokens (
                    token_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    token_hash TEXT NOT NULL DEFAULT '',
                    preview TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    rotated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_node_tokens_node ON gateway_node_tokens(node_id, rotated_at DESC);
                """
            )

    def _decode_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in list(item.keys()):
            if key.endswith("_json"):
                base = key[:-5]
                item[base] = _json_loads(item.pop(key))
        return item

    def upsert_session(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_sessions (
                    session_id, user_id, surface, client_id, client_label, platform,
                    auth_mode, trust_level, status, created_at, last_seen_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    surface=excluded.surface,
                    client_id=excluded.client_id,
                    client_label=excluded.client_label,
                    platform=excluded.platform,
                    auth_mode=excluded.auth_mode,
                    trust_level=excluded.trust_level,
                    status=excluded.status,
                    last_seen_at=excluded.last_seen_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    row.get("session_id", ""),
                    row.get("user_id", ""),
                    row.get("surface", ""),
                    row.get("client_id", ""),
                    row.get("client_label", ""),
                    row.get("platform", ""),
                    row.get("auth_mode", "local"),
                    row.get("trust_level", "trusted_local"),
                    row.get("status", "online"),
                    row.get("created_at", ""),
                    row.get("last_seen_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_session(str(row.get("session_id") or "")) or {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_sessions WHERE session_id = ?",
                (str(session_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def list_sessions(self, *, limit: int = 20, surface: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_sessions"
        params: list[Any] = []
        if str(surface or "").strip():
            sql += " WHERE surface = ?"
            params.append(str(surface).strip().lower())
        sql += " ORDER BY last_seen_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def upsert_presence(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_presence (
                    session_id, client_id, user_id, surface, status, activity, detail, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    client_id=excluded.client_id,
                    user_id=excluded.user_id,
                    surface=excluded.surface,
                    status=excluded.status,
                    activity=excluded.activity,
                    detail=excluded.detail,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    row.get("session_id", ""),
                    row.get("client_id", ""),
                    row.get("user_id", ""),
                    row.get("surface", ""),
                    row.get("status", "online"),
                    row.get("activity", ""),
                    row.get("detail", ""),
                    row.get("updated_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_presence(str(row.get("session_id") or "")) or {}

    def get_presence(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_presence WHERE session_id = ?",
                (str(session_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def list_presence(self, *, limit: int = 20, surface: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_presence"
        params: list[Any] = []
        if str(surface or "").strip():
            sql += " WHERE surface = ?"
            params.append(str(surface).strip().lower())
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def record_health(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        service_id = str(row.get("service_id") or "")
        surface = str(row.get("surface") or "").strip().lower()
        service_key = f"{surface}:{service_id}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_health (
                    service_key, service_id, surface, status, summary, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_key) DO UPDATE SET
                    status=excluded.status,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    service_key,
                    service_id,
                    surface,
                    row.get("status", ""),
                    row.get("summary", ""),
                    row.get("updated_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_health(service_id=service_id, surface=surface) or {}

    def get_health(self, *, service_id: str, surface: str) -> dict[str, Any] | None:
        service_key = f"{str(surface or '').strip().lower()}:{str(service_id or '')}"
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_health WHERE service_key = ?",
                (service_key,),
            ).fetchone()
        item = self._decode_row(row)
        if item is not None:
            item.pop("service_key", None)
        return item

    def list_health(self, *, limit: int = 20, surface: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_health"
        params: list[Any] = []
        if str(surface or "").strip():
            sql += " WHERE surface = ?"
            params.append(str(surface).strip().lower())
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = self._decode_row(row) or {}
            item.pop("service_key", None)
            out.append(item)
        return out

    def append_event(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_events (
                    event_id, event_type, surface, title, body, level, user_id, session_id, client_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("event_id", ""),
                    row.get("event_type", ""),
                    row.get("surface", ""),
                    row.get("title", ""),
                    row.get("body", ""),
                    row.get("level", "info"),
                    row.get("user_id", ""),
                    row.get("session_id", ""),
                    row.get("client_id", ""),
                    row.get("created_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_event(str(row.get("event_id") or "")) or {}

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_events WHERE event_id = ?",
                (str(event_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def list_events(self, *, limit: int = 40, surface: str = "", event_type: str = "") -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(surface or "").strip():
            clauses.append("surface = ?")
            params.append(str(surface).strip().lower())
        if str(event_type or "").strip():
            clauses.append("event_type = ?")
            params.append(str(event_type).strip().lower())
        sql = "SELECT * FROM gateway_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit or 40)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def issue_pairing(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_pairings (
                    pairing_id, code, requested_surface, client_label, platform, owner_user_id,
                    session_id, status, scopes_json, created_at, updated_at, expires_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("pairing_id", ""),
                    row.get("code", self.random_code()),
                    row.get("requested_surface", ""),
                    row.get("client_label", ""),
                    row.get("platform", ""),
                    row.get("owner_user_id", "default_user"),
                    row.get("session_id", ""),
                    row.get("status", "pending"),
                    _json_dumps(row.get("scopes") or []),
                    row.get("created_at", ""),
                    row.get("updated_at", ""),
                    row.get("expires_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_pairing(str(row.get("pairing_id") or "")) or {}

    def get_pairing(self, pairing_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_pairings WHERE pairing_id = ?",
                (str(pairing_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def get_pairing_by_code(self, code: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM gateway_pairings
                WHERE code = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (str(code or "").strip(),),
            ).fetchone()
        return self._decode_row(row)

    def confirm_pairing(
        self,
        *,
        code: str,
        session_id: str = "",
        status: str = "paired",
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        updated_at: str = "",
    ) -> dict[str, Any] | None:
        item = self.get_pairing_by_code(code)
        if not item:
            return None
        merged_metadata = dict(item.get("metadata") or {})
        merged_metadata.update(dict(metadata or {}))
        merged_scopes = list(item.get("scopes") or [])
        for scope in scopes or []:
            key = str(scope or "").strip().lower()
            if key and key not in merged_scopes:
                merged_scopes.append(key)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE gateway_pairings
                SET session_id = ?, status = ?, scopes_json = ?, updated_at = ?, metadata_json = ?
                WHERE pairing_id = ?
                """,
                (
                    str(session_id or item.get("session_id") or ""),
                    str(status or "paired"),
                    _json_dumps(merged_scopes),
                    str(updated_at or item.get("updated_at") or ""),
                    _json_dumps(merged_metadata),
                    str(item.get("pairing_id") or ""),
                ),
            )
        return self.get_pairing(str(item.get("pairing_id") or ""))

    def list_pairings(self, *, limit: int = 20, status: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_pairings"
        params: list[Any] = []
        if str(status or "").strip():
            sql += " WHERE status = ?"
            params.append(str(status).strip().lower())
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def upsert_node(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_nodes (
                    node_id, session_id, user_id, node_type, client_label, platform,
                    trust_level, status, capabilities_json, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    user_id=excluded.user_id,
                    node_type=excluded.node_type,
                    client_label=excluded.client_label,
                    platform=excluded.platform,
                    trust_level=excluded.trust_level,
                    status=excluded.status,
                    capabilities_json=excluded.capabilities_json,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    row.get("node_id", ""),
                    row.get("session_id", ""),
                    row.get("user_id", ""),
                    row.get("node_type", ""),
                    row.get("client_label", ""),
                    row.get("platform", ""),
                    row.get("trust_level", "untrusted_remote"),
                    row.get("status", "pending"),
                    _json_dumps(row.get("capabilities") or []),
                    row.get("created_at", ""),
                    row.get("updated_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_node(str(row.get("node_id") or "")) or {}

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_nodes WHERE node_id = ?",
                (str(node_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def get_node_by_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_nodes WHERE session_id = ?",
                (str(session_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def list_nodes(self, *, limit: int = 20, status: str = "", node_type: str = "") -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(status or "").strip():
            clauses.append("status = ?")
            params.append(str(status).strip().lower())
        if str(node_type or "").strip():
            clauses.append("node_type = ?")
            params.append(str(node_type).strip().lower())
        sql = "SELECT * FROM gateway_nodes"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def append_remote_audit(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_remote_audit (
                    audit_id, node_id, session_id, user_id, action, capability, requested_path,
                    outcome, reason, actor, requires_approval, operator_confirmed, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("audit_id", ""),
                    row.get("node_id", ""),
                    row.get("session_id", ""),
                    row.get("user_id", ""),
                    row.get("action", ""),
                    row.get("capability", ""),
                    row.get("requested_path", ""),
                    row.get("outcome", ""),
                    row.get("reason", ""),
                    row.get("actor", ""),
                    1 if bool(row.get("requires_approval")) else 0,
                    1 if bool(row.get("operator_confirmed")) else 0,
                    row.get("created_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_remote_audit(str(row.get("audit_id") or "")) or {}

    def get_remote_audit(self, audit_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_remote_audit WHERE audit_id = ?",
                (str(audit_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def list_remote_audit(self, *, limit: int = 40, node_id: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_remote_audit"
        params: list[Any] = []
        if str(node_id or "").strip():
            sql += " WHERE node_id = ?"
            params.append(str(node_id).strip().lower())
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit or 40)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def rotate_node_token(self, record: dict[str, Any]) -> dict[str, Any]:
        row = dict(record or {})
        with self._lock, self._connect() as conn:
            if str(row.get("node_id") or "").strip():
                conn.execute(
                    "UPDATE gateway_node_tokens SET status = 'rotated', rotated_at = ? WHERE node_id = ? AND status = 'active'",
                    (str(row.get("rotated_at") or row.get("created_at") or ""), str(row.get("node_id") or "").strip().lower()),
                )
            conn.execute(
                """
                INSERT INTO gateway_node_tokens (
                    token_id, node_id, label, token_hash, preview, status, created_at, rotated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("token_id", ""),
                    row.get("node_id", ""),
                    row.get("label", ""),
                    row.get("token_hash", ""),
                    row.get("preview", ""),
                    row.get("status", "active"),
                    row.get("created_at", ""),
                    row.get("rotated_at", ""),
                    _json_dumps(row.get("metadata") or {}),
                ),
            )
        return self.get_node_token(str(row.get("token_id") or "")) or {}

    def get_node_token(self, token_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_node_tokens WHERE token_id = ?",
                (str(token_id or ""),),
            ).fetchone()
        return self._decode_row(row)

    def list_node_tokens(self, *, node_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_node_tokens"
        params: list[Any] = []
        if str(node_id or "").strip():
            sql += " WHERE node_id = ?"
            params.append(str(node_id).strip().lower())
        sql += " ORDER BY rotated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    @staticmethod
    def random_code() -> str:
        return "".join(secrets.choice("0123456789") for _ in range(6))
