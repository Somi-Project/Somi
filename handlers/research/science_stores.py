"""
Science Stores v2.2
- SQLite stores for: verified facts, researched facts, textbook facts (+ book registry)
- AgentpediaManager for conflicts/dedupe/promotion (no network calls)
- No imports from handlers/science.py (prevents circular imports)

Fixes:
- FTS query escaping to prevent runtime errors
- Researched add_facts uses cursor.rowcount (no total_changes bug)
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

# ----------------------------
# Paths
# ----------------------------

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VERIFIED_DB = DATA_DIR / "verified_science.db"
DEFAULT_RESEARCHED_DB = DATA_DIR / "researched_science.db"
DEFAULT_TEXTBOOK_DB = DATA_DIR / "textbook_facts.db"


# ----------------------------
# Helpers
# ----------------------------

def _norm_space(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _fact_hash(topic: str, fact: str, source: str) -> str:
    blob = f"{topic}||{fact}||{source}".encode("utf-8", errors="ignore")
    return hashlib.sha1(blob).hexdigest()


def _now() -> float:
    return time.time()


def _confidence_rank(conf: str) -> int:
    conf = (conf or "").lower().strip()
    return {
        "very_high": 4,
        "high": 3,
        "foundational": 2,
        "medium": 1,
        "low": 0,
    }.get(conf, 1)


def _fts_escape(q: str) -> str:
    """
    Escape user query for FTS5 MATCH.
    Conservative: strip operators/punctuation and wrap as a phrase.
    Prevents: sqlite3.OperationalError: fts5: syntax error near ...
    """
    q = _norm_space(q)
    if not q:
        return ""
    q = re.sub(r'["\'`]', " ", q)
    q = re.sub(r"[^a-zA-Z0-9_\s]", " ", q)
    q = _norm_space(q)
    if not q:
        return ""
    return f'"{q}"'


# ----------------------------
# Base SQLite
# ----------------------------

class _SQLiteBase:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=5)
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA busy_timeout=2000;")
        return c

    def _init_db(self) -> None:
        raise NotImplementedError


# ----------------------------
# Verified Store
# ----------------------------

class VerifiedScienceStore(_SQLiteBase):
    def __init__(self, path: Path = DEFAULT_VERIFIED_DB):
        super().__init__(path)

    def _init_db(self) -> None:
        with self._connect() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS verified_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                fact TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence TEXT NOT NULL,
                tags TEXT,
                created_at REAL NOT NULL,
                fact_hash TEXT UNIQUE
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_verified_topic ON verified_facts(topic)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_verified_created ON verified_facts(created_at)")
            c.commit()

    def lookup(self, query: str, *, min_confidence: str = "high", limit: int = 5) -> List[Dict[str, Any]]:
        q = _norm_space(query).lower()
        if not q:
            return []
        min_rank = _confidence_rank(min_confidence)

        pattern = f"%{q}%"
        sql = """
        SELECT id, topic, fact, source, confidence, COALESCE(tags,''), created_at
        FROM verified_facts
        WHERE LOWER(topic || ' ' || fact || ' ' || COALESCE(tags,'')) LIKE ?
        ORDER BY created_at DESC
        LIMIT ?
        """
        out: List[Dict[str, Any]] = []
        with self._connect() as c:
            for rid, topic, fact, source, confidence, tags, created_at in c.execute(sql, (pattern, limit * 3)):
                if _confidence_rank(confidence) < min_rank:
                    continue
                out.append({
                    "id": rid,
                    "title": topic,
                    "description": fact,
                    "url": source if str(source).startswith("http") else "",
                    "source": "verified",
                    "confidence": confidence,
                    "tags": tags,
                    "created_at": created_at,
                    "volatile": False,
                    "category": "science",
                    "store": "verified",
                })
                if len(out) >= limit:
                    break
        return out

    def add_fact(self, *, topic: str, fact: str, source: str, confidence: str = "very_high", tags: str = "") -> None:
        topic = _norm_space(topic)
        fact = _norm_space(fact)
        source = _norm_space(source)
        if not topic or not fact or not source:
            return
        if confidence not in ("very_high", "high"):
            confidence = "high"

        fh = _fact_hash(topic, fact, source)
        with self._connect() as c:
            c.execute("""
            INSERT OR IGNORE INTO verified_facts
            (topic, fact, source, confidence, tags, created_at, fact_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (topic, fact, source, confidence, tags, _now(), fh))
            c.commit()


# ----------------------------
# Researched Store
# ----------------------------

class ResearchedScienceStore(_SQLiteBase):
    def __init__(self, path: Path = DEFAULT_RESEARCHED_DB):
        super().__init__(path)

    def _init_db(self) -> None:
        with self._connect() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS researched_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                fact TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence TEXT NOT NULL,
                domain TEXT,
                tags TEXT,
                evidence_snippet TEXT,
                created_at REAL NOT NULL,
                fact_hash TEXT UNIQUE
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_researched_topic ON researched_facts(topic)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_researched_domain ON researched_facts(domain)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_researched_created ON researched_facts(created_at)")
            c.commit()

    def lookup(self, query: str, *, domain: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        q = _norm_space(query).lower()
        if not q:
            return []
        pattern = f"%{q}%"

        sql = """
        SELECT id, topic, fact, source, confidence, COALESCE(domain,''), COALESCE(tags,''), COALESCE(evidence_snippet,''), created_at
        FROM researched_facts
        WHERE LOWER(topic || ' ' || fact || ' ' || COALESCE(tags,'')) LIKE ?
        """
        params: List[Any] = [pattern]
        if domain:
            sql += " AND (domain = ? OR domain IS NULL OR domain = '')"
            params.append(domain)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        out: List[Dict[str, Any]] = []
        with self._connect() as c:
            for rid, topic, fact, source, confidence, dom, tags, snippet, created_at in c.execute(sql, params):
                out.append({
                    "id": rid,
                    "title": topic,
                    "description": fact,
                    "url": source if str(source).startswith("http") else "",
                    "source": "researched",
                    "confidence": confidence,
                    "domain": dom or "general",
                    "tags": tags,
                    "evidence_snippet": snippet,
                    "created_at": created_at,
                    "volatile": False,
                    "category": "science",
                    "store": "researched",
                })
        return out

    def list_recent(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        sql = """
        SELECT id, topic, fact, source, confidence, COALESCE(domain,''), COALESCE(tags,''), COALESCE(evidence_snippet,''), created_at
        FROM researched_facts
        ORDER BY created_at DESC LIMIT ?
        """
        out: List[Dict[str, Any]] = []
        with self._connect() as c:
            for rid, topic, fact, source, confidence, dom, tags, snippet, created_at in c.execute(sql, (limit,)):
                out.append({
                    "id": rid,
                    "title": topic,
                    "description": fact,
                    "url": source if str(source).startswith("http") else "",
                    "source": "researched",
                    "confidence": confidence,
                    "domain": dom or "general",
                    "tags": tags,
                    "evidence_snippet": snippet,
                    "created_at": created_at,
                    "volatile": False,
                    "category": "science",
                    "store": "researched",
                })
        return out

    def add_facts(self, facts: List[Dict[str, Any]], *, domain: Optional[str] = None) -> int:
        """
        FIXED: counts inserts using cursor.rowcount instead of sqlite total_changes.
        """
        added = 0
        with self._connect() as c:
            for f in facts or []:
                topic = _norm_space(str(f.get("topic") or f.get("title") or ""))
                fact = _norm_space(str(f.get("fact") or f.get("description") or ""))
                source = _norm_space(str(f.get("source") or f.get("url") or ""))
                confidence = str(f.get("confidence") or "medium").lower().strip()
                tags = _norm_space(str(f.get("tags") or ""))
                snippet = _norm_space(str(f.get("evidence_snippet") or ""))

                if confidence not in ("high", "medium"):
                    confidence = "medium"
                if not topic or not fact or not source:
                    continue

                dom = domain or str(f.get("domain") or "")
                fh = _fact_hash(topic, fact, source)

                cur = c.execute("""
                INSERT OR IGNORE INTO researched_facts
                (topic, fact, source, confidence, domain, tags, evidence_snippet, created_at, fact_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (topic, fact, source, confidence, dom, tags, snippet, _now(), fh))

                if getattr(cur, "rowcount", 0) == 1:
                    added += 1

            c.commit()
        return added


# ----------------------------
# Textbook Store + Registry
# ----------------------------

class TextbookFactsStore(_SQLiteBase):
    def __init__(self, path: Path = DEFAULT_TEXTBOOK_DB):
        super().__init__(path)

    def _init_db(self) -> None:
        with self._connect() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS textbook_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT UNIQUE,
                title TEXT,
                file_path TEXT,
                file_hash TEXT,
                processed_at REAL,
                created_at REAL NOT NULL
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS textbook_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                title TEXT,
                page INTEGER NOT NULL,
                chunk TEXT NOT NULL,
                tags TEXT,
                created_at REAL NOT NULL
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_tb_book ON textbook_facts(book_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tb_page ON textbook_facts(page)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tb_created ON textbook_facts(created_at)")
            c.commit()

            # Optional FTS5 (safe attempt)
            try:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS textbook_facts_fts USING fts5(chunk, tags, title, book_id)")
                c.commit()
            except Exception:
                pass

    def book_exists(self, file_hash: str) -> bool:
        if not file_hash:
            return False
        with self._connect() as c:
            row = c.execute("SELECT 1 FROM textbook_books WHERE file_hash=? LIMIT 1", (file_hash,)).fetchone()
            return bool(row)

    def register_book(self, *, book_id: str, title: str, file_path: str, file_hash: str) -> None:
        with self._connect() as c:
            c.execute("""
            INSERT OR IGNORE INTO textbook_books (book_id, title, file_path, file_hash, processed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (book_id, title, file_path, file_hash, _now(), _now()))
            c.commit()

    def add_chunks(self, *, book_id: str, title: str, page: int, chunks: List[str], tags: str = "") -> int:
        book_id = _norm_space(book_id)
        if not book_id or not chunks:
            return 0
        inserted = 0
        with self._connect() as c:
            for ch in chunks:
                ch = _norm_space(ch)
                if len(ch) < 80:
                    continue
                c.execute("""
                INSERT INTO textbook_facts (book_id, title, page, chunk, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (book_id, title, int(page), ch, tags, _now()))
                inserted += 1

                # FTS mirror
                try:
                    c.execute("INSERT INTO textbook_facts_fts (chunk, tags, title, book_id) VALUES (?, ?, ?, ?)",
                              (ch, tags, title, book_id))
                except Exception:
                    pass
            c.commit()
        return inserted

    def lookup(self, query: str, *, limit: int = 5) -> List[Dict[str, Any]]:
        q_raw = _norm_space(query)
        q = q_raw.lower()
        if not q:
            return []
        out: List[Dict[str, Any]] = []

        # Try FTS first (ESCAPED)
        with self._connect() as c:
            try:
                fts_q = _fts_escape(q_raw)
                if fts_q:
                    rows = c.execute("""
                        SELECT title, book_id, chunk
                        FROM textbook_facts_fts
                        WHERE textbook_facts_fts MATCH ?
                        LIMIT ?
                    """, (fts_q, limit)).fetchall()
                else:
                    rows = []

                for title, book_id, chunk in rows:
                    out.append({
                        "title": f"{title} ({book_id})",
                        "description": chunk,
                        "url": "",
                        "source": "textbook",
                        "confidence": "foundational",
                        "volatile": False,
                        "category": "science",
                        "store": "textbook",
                    })
                if out:
                    return out
            except Exception:
                pass

        # Fallback LIKE
        pattern = f"%{q}%"
        with self._connect() as c:
            rows2 = c.execute("""
                SELECT title, book_id, page, chunk, COALESCE(tags,'')
                FROM textbook_facts
                WHERE LOWER(chunk || ' ' || COALESCE(tags,'')) LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (pattern, limit)).fetchall()

            for title, book_id, page, chunk, tags in rows2:
                out.append({
                    "title": f"{title} (p.{page})",
                    "description": chunk,
                    "url": "",
                    "source": "textbook",
                    "confidence": "foundational",
                    "tags": tags,
                    "volatile": False,
                    "category": "science",
                    "store": "textbook",
                })

        return out


# ----------------------------
# Agentpedia Manager
# ----------------------------

@dataclass
class AgentpediaConflict:
    store: str
    id: int
    topic: str
    fact: str
    confidence: str
    source: str


class AgentpediaManager:
    """
    Conflict handling + dedupe + promotion.
    Conservative defaults for medicine: keep both unless stronger evidence.
    """
    def __init__(self,
                 verified: Optional[VerifiedScienceStore] = None,
                 textbook: Optional[TextbookFactsStore] = None,
                 researched: Optional[ResearchedScienceStore] = None):
        self.verified = verified or VerifiedScienceStore()
        self.textbook = textbook or TextbookFactsStore()
        self.researched = researched or ResearchedScienceStore()

    def detect_conflicts(self, topic: str, new_fact: str, *, threshold: float = 0.82) -> List[AgentpediaConflict]:
        topic_n = _norm_space(topic).lower()
        fact_n = _norm_space(new_fact).lower()
        if not topic_n or not fact_n:
            return []

        conflicts: List[AgentpediaConflict] = []

        candidates: List[Dict[str, Any]] = []
        candidates.extend(self.verified.lookup(topic, min_confidence="high", limit=30))
        candidates.extend(self.researched.list_recent(limit=200))

        for c in candidates:
            ctopic = _norm_space(str(c.get("title") or "")).lower()
            cfact = _norm_space(str(c.get("description") or "")).lower()
            if not ctopic or not cfact:
                continue

            topic_sim = SequenceMatcher(None, topic_n, ctopic).ratio()
            if topic_sim < 0.72:
                continue

            sim = SequenceMatcher(None, fact_n, cfact).ratio()
            if sim >= threshold:
                conflicts.append(AgentpediaConflict(
                    store=str(c.get("store") or c.get("source") or "researched"),
                    id=int(c.get("id") or 0),
                    topic=str(c.get("title") or ""),
                    fact=str(c.get("description") or ""),
                    confidence=str(c.get("confidence") or "medium"),
                    source=str(c.get("url") or ""),
                ))

        return conflicts

    def deprecate_fact(self, store: str, fact_id: int) -> bool:
        store = (store or "").lower().strip()
        if fact_id <= 0:
            return False

        if store in ("verified", "verified_science"):
            table = "verified_facts"
            path = self.verified.path
        elif store in ("researched", "researched_science"):
            table = "researched_facts"
            path = self.researched.path
        else:
            return False

        with sqlite3.connect(path, timeout=5) as c:
            c.execute("PRAGMA busy_timeout=2000;")
            c.execute(f"DELETE FROM {table} WHERE id=?", (fact_id,))
            c.commit()
            return True

    def promote_researched_to_verified(self, *, dry_run: bool = True, min_age_days: int = 7) -> int:
        promoted = 0
        min_age = _now() - (min_age_days * 86400)

        for rf in self.researched.list_recent(limit=500):
            if (rf.get("confidence") or "") != "high":
                continue
            if float(rf.get("created_at") or 0) > min_age:
                continue

            topic = str(rf.get("title") or "").strip()
            fact = str(rf.get("description") or "").strip()
            url = str(rf.get("url") or "").strip()
            tags = str(rf.get("tags") or "").strip()

            if not topic or not fact or not url:
                continue
            if self.verified.lookup(topic, min_confidence="high", limit=1):
                continue

            if not dry_run:
                self.verified.add_fact(topic=topic, fact=fact, source=url, confidence="high", tags=tags)
            promoted += 1

        return promoted
