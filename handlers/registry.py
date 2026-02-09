# handlers/registry.py — FINAL BULLETPROOF VERSION (stores raw text)
import sqlite3
import csv
import json
import os
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "registry_config.json"
DB_PATH = BASE_DIR / "registry.db"

def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
FIELDS = {f["key"]: f for f in config["fields"]}
REQUIRED_FIELD = config.get("required_field", "id")
TABLE_NAME = config.get("table_name", "patients")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    # Add raw_text, photo_message_id, saved_at
    base_columns = ", ".join([f"{k} TEXT" for k in FIELDS.keys()])
    extra_columns = "raw_text TEXT, photo_message_id INTEGER, saved_at TEXT"
    columns = f"{base_columns}, {extra_columns}"
    conn.execute(f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({columns})")
    conn.commit()
    conn.close()

def save_record(data: dict, force: bool = False) -> str:
    rid = data.get(REQUIRED_FIELD) or f"form_{int(datetime.now().timestamp())}"
    data[REQUIRED_FIELD] = rid

    conn = sqlite3.connect(DB_PATH)
    cols = ", ".join(FIELDS.keys()) + ", raw_text, photo_message_id, saved_at"
    placeholders = ", ".join(["?"] * (len(FIELDS) + 3))
    values = [data.get(k, None) for k in FIELDS.keys()] + [
        data.get("raw_text", ""),
        data.get("photo_message_id"),
        datetime.now().isoformat()
    ]

    try:
        conn.execute(f"INSERT OR REPLACE INTO {TABLE_NAME} ({cols}) VALUES ({placeholders})", values)
        conn.commit()
        conn.close()
        return "SAVED"
    except Exception as e:
        logger.error(f"Save failed: {e}")
        conn.close()
        return "ERROR"

def get_all_records():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY saved_at DESC")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    result = [dict(zip(cols, row)) for row in rows]
    conn.close()
    return result

def export_as_csv() -> str:
    recs = get_all_records()
    if not recs:
        return None
    path = BASE_DIR / "registry_export.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=recs[0].keys())
        writer.writeheader()
        writer.writerows(recs)
    return str(path)

def get_field_keys() -> str:
    return ", ".join(FIELDS.keys())

init_db()