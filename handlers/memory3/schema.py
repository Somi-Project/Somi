from __future__ import annotations

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    user_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    type TEXT NOT NULL,
    entity TEXT,
    mkey TEXT,
    value TEXT,
    kind TEXT,
    bucket TEXT DEFAULT 'general',
    importance REAL DEFAULT 0.5,
    replaced_by TEXT,
    content TEXT NOT NULL,
    tags TEXT,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    expires_at TEXT,
    supersedes TEXT,
    last_used TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_user_lane_type_status ON memory_items(user_id, lane, type, status);
CREATE INDEX IF NOT EXISTS idx_memory_user_entity_key_status ON memory_items(user_id, entity, mkey, status);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_items(expires_at);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, tags, mkey, item_id UNINDEXED);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    due_ts TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    details TEXT,
    priority INTEGER DEFAULT 3,
    last_notified_ts TEXT,
    notify_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders_user_status_due ON reminders(user_id, status, due_ts);
"""
