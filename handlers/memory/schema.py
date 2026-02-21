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
    last_used TEXT,
    scope TEXT DEFAULT 'conversation',
    mem_type TEXT DEFAULT 'note',
    text TEXT DEFAULT '',
    entities_json TEXT,
    tags_json TEXT,
    supersedes_id TEXT,
    contradicts_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    last_used_at TEXT,
    slot_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_user_lane_type_status ON memory_items(user_id, lane, type, status);
CREATE INDEX IF NOT EXISTS idx_memory_user_entity_key_status ON memory_items(user_id, entity, mkey, status);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_items(expires_at);
CREATE INDEX IF NOT EXISTS idx_memory_user_scope_status ON memory_items(user_id, scope, status);
CREATE INDEX IF NOT EXISTS idx_memory_user_slot_status ON memory_items(user_id, slot_key, status);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, tags, mkey, item_id UNINDEXED);

CREATE TABLE IF NOT EXISTS memory_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    memory_id TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_events_user_created ON memory_events(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_links (
    src_id TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    weight REAL DEFAULT 0.5,
    created_at TEXT NOT NULL
);

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
