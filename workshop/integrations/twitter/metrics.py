import sqlite3
from pathlib import Path


def init_metrics_db(path: str = "twitter_metrics.db"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS engagement_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            collected_at TEXT,
            hour_offset INTEGER,
            likes INTEGER,
            replies INTEGER,
            reposts INTEGER
        )
    """)
    conn.commit()
    return conn
