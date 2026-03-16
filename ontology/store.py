from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import OntologyLink, OntologyObject


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps(default, ensure_ascii=False, sort_keys=True)


class OntologyStore:
    def __init__(self, db_path: str | Path = "sessions/state/ontology.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._fts_enabled: bool | None = None
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
                    CREATE TABLE IF NOT EXISTS objects (
                        object_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        label TEXT NOT NULL,
                        status TEXT NOT NULL,
                        owner_user_id TEXT NOT NULL DEFAULT '',
                        thread_id TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL DEFAULT '',
                        attributes_json TEXT NOT NULL DEFAULT '{}',
                        searchable_text TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_objects_kind_user
                    ON objects(kind, owner_user_id, thread_id);

                    CREATE TABLE IF NOT EXISTS links (
                        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        from_id TEXT NOT NULL,
                        relation TEXT NOT NULL,
                        to_id TEXT NOT NULL,
                        owner_user_id TEXT NOT NULL DEFAULT '',
                        thread_id TEXT NOT NULL DEFAULT '',
                        attributes_json TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL,
                        UNIQUE(from_id, relation, to_id, owner_user_id, thread_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_links_from_rel
                    ON links(from_id, relation, owner_user_id, thread_id);
                    """
                )
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS object_fts
                        USING fts5(
                            object_id UNINDEXED,
                            kind,
                            label,
                            searchable_text
                        )
                        """
                    )
                    self._fts_enabled = True
                except sqlite3.OperationalError:
                    self._fts_enabled = False

    def upsert_object(self, item: OntologyObject | dict[str, Any]) -> dict[str, Any]:
        row = item.to_record() if isinstance(item, OntologyObject) else dict(item or {})
        updated_at = str(row.get("updated_at") or _now_iso())
        payload = (
            str(row.get("object_id") or ""),
            str(row.get("kind") or "System"),
            str(row.get("label") or ""),
            str(row.get("status") or "active"),
            str(row.get("owner_user_id") or ""),
            str(row.get("thread_id") or ""),
            str(row.get("source") or ""),
            _json(dict(row.get("attributes") or {}), {}),
            str(row.get("searchable_text") or ""),
            updated_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO objects(
                    object_id, kind, label, status, owner_user_id, thread_id, source, attributes_json, searchable_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_id) DO UPDATE SET
                    kind=excluded.kind,
                    label=excluded.label,
                    status=excluded.status,
                    owner_user_id=excluded.owner_user_id,
                    thread_id=excluded.thread_id,
                    source=excluded.source,
                    attributes_json=excluded.attributes_json,
                    searchable_text=excluded.searchable_text,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
            if self._fts_enabled:
                conn.execute("DELETE FROM object_fts WHERE object_id = ?", (str(row.get("object_id") or ""),))
                conn.execute(
                    "INSERT INTO object_fts(object_id, kind, label, searchable_text) VALUES (?, ?, ?, ?)",
                    (
                        str(row.get("object_id") or ""),
                        str(row.get("kind") or "System"),
                        str(row.get("label") or ""),
                        str(row.get("searchable_text") or ""),
                    ),
                )
        out = dict(row)
        out["updated_at"] = updated_at
        return out

    def upsert_link(self, link: OntologyLink | dict[str, Any]) -> dict[str, Any]:
        row = link.to_record() if isinstance(link, OntologyLink) else dict(link or {})
        updated_at = str(row.get("updated_at") or _now_iso())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO links(
                    from_id, relation, to_id, owner_user_id, thread_id, attributes_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(from_id, relation, to_id, owner_user_id, thread_id) DO UPDATE SET
                    attributes_json=excluded.attributes_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(row.get("from_id") or ""),
                    str(row.get("relation") or ""),
                    str(row.get("to_id") or ""),
                    str(row.get("owner_user_id") or ""),
                    str(row.get("thread_id") or ""),
                    _json(dict(row.get("attributes") or {}), {}),
                    updated_at,
                ),
            )
        out = dict(row)
        out["updated_at"] = updated_at
        return out

    def delete_scope(self, *, owner_user_id: str = "", thread_id: str = "", kinds: list[str] | None = None) -> None:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_user_id:
            clauses.append("owner_user_id = ?")
            params.append(str(owner_user_id))
        if thread_id:
            clauses.append("thread_id = ?")
            params.append(str(thread_id))
        if kinds:
            placeholders = ",".join(["?"] * len(kinds))
            clauses.append(f"kind IN ({placeholders})")
            params.extend([str(kind) for kind in kinds])
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            object_ids = [str(row[0]) for row in conn.execute(f"SELECT object_id FROM objects{where_sql}", tuple(params)).fetchall()]
            conn.execute(f"DELETE FROM objects{where_sql}", tuple(params))
            if self._fts_enabled:
                for object_id in object_ids:
                    conn.execute("DELETE FROM object_fts WHERE object_id = ?", (object_id,))
            link_clauses = []
            link_params: list[Any] = []
            if owner_user_id:
                link_clauses.append("owner_user_id = ?")
                link_params.append(str(owner_user_id))
            if thread_id:
                link_clauses.append("thread_id = ?")
                link_params.append(str(thread_id))
            link_where = " WHERE " + " AND ".join(link_clauses) if link_clauses else ""
            conn.execute(f"DELETE FROM links{link_where}", tuple(link_params))

    def list_objects(
        self,
        *,
        kind: str | None = None,
        owner_user_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(str(kind))
        if owner_user_id is not None:
            clauses.append("owner_user_id = ?")
            params.append(str(owner_user_id))
        if thread_id is not None:
            clauses.append("thread_id = ?")
            params.append(str(thread_id))
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM objects{where_sql} ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 50)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "object_id": str(row["object_id"]),
                "kind": str(row["kind"]),
                "label": str(row["label"]),
                "status": str(row["status"]),
                "owner_user_id": str(row["owner_user_id"]),
                "thread_id": str(row["thread_id"]),
                "source": str(row["source"]),
                "attributes": json.loads(str(row["attributes_json"] or "{}")),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def get_object(self, object_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM objects WHERE object_id = ?",
                (str(object_id or ""),),
            ).fetchone()
        if row is None:
            return None
        return {
            "object_id": str(row["object_id"]),
            "kind": str(row["kind"]),
            "label": str(row["label"]),
            "status": str(row["status"]),
            "owner_user_id": str(row["owner_user_id"]),
            "thread_id": str(row["thread_id"]),
            "source": str(row["source"]),
            "attributes": json.loads(str(row["attributes_json"] or "{}")),
            "updated_at": str(row["updated_at"]),
        }

    def list_links(
        self,
        *,
        object_id: str | None = None,
        relation: str | None = None,
        owner_user_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if object_id:
            clauses.append("(from_id = ? OR to_id = ?)")
            params.extend([str(object_id), str(object_id)])
        if relation:
            clauses.append("relation = ?")
            params.append(str(relation))
        if owner_user_id is not None:
            clauses.append("owner_user_id = ?")
            params.append(str(owner_user_id))
        if thread_id is not None:
            clauses.append("thread_id = ?")
            params.append(str(thread_id))
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM links{where_sql} ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 100)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "from_id": str(row["from_id"]),
                "relation": str(row["relation"]),
                "to_id": str(row["to_id"]),
                "owner_user_id": str(row["owner_user_id"]),
                "thread_id": str(row["thread_id"]),
                "attributes": json.loads(str(row["attributes_json"] or "{}")),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        owner_user_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        with self._connect() as conn:
            if self._fts_enabled:
                clauses = ["object_fts MATCH ?"]
                params: list[Any] = [q]
                if kind:
                    clauses.append("o.kind = ?")
                    params.append(str(kind))
                if owner_user_id is not None:
                    clauses.append("o.owner_user_id = ?")
                    params.append(str(owner_user_id))
                if thread_id is not None:
                    clauses.append("o.thread_id = ?")
                    params.append(str(thread_id))
                sql = f"""
                    SELECT
                        o.object_id,
                        o.kind,
                        o.label,
                        o.status,
                        o.owner_user_id,
                        o.thread_id,
                        o.source,
                        o.attributes_json,
                        o.updated_at,
                        bm25(object_fts) AS score
                    FROM object_fts
                    JOIN objects o ON o.object_id = object_fts.object_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY score ASC, o.updated_at DESC
                    LIMIT ?
                """
                params.append(max(1, int(limit or 12)))
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [
                    {
                        "object_id": str(row["object_id"]),
                        "kind": str(row["kind"]),
                        "label": str(row["label"]),
                        "status": str(row["status"]),
                        "owner_user_id": str(row["owner_user_id"]),
                        "thread_id": str(row["thread_id"]),
                        "source": str(row["source"]),
                        "attributes": json.loads(str(row["attributes_json"] or "{}")),
                        "updated_at": str(row["updated_at"]),
                        "score": float(row["score"] or 0.0),
                    }
                    for row in rows
                ]

            like = f"%{q}%"
            clauses = ["(label LIKE ? OR searchable_text LIKE ?)"]
            params = [like, like]
            if kind:
                clauses.append("kind = ?")
                params.append(str(kind))
            if owner_user_id is not None:
                clauses.append("owner_user_id = ?")
                params.append(str(owner_user_id))
            if thread_id is not None:
                clauses.append("thread_id = ?")
                params.append(str(thread_id))
            sql = f"SELECT * FROM objects WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?"
            params.append(max(1, int(limit or 12)))
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [
                {
                    "object_id": str(row["object_id"]),
                    "kind": str(row["kind"]),
                    "label": str(row["label"]),
                    "status": str(row["status"]),
                    "owner_user_id": str(row["owner_user_id"]),
                    "thread_id": str(row["thread_id"]),
                    "source": str(row["source"]),
                    "attributes": json.loads(str(row["attributes_json"] or "{}")),
                    "updated_at": str(row["updated_at"]),
                    "score": 0.0,
                }
                for row in rows
            ]
