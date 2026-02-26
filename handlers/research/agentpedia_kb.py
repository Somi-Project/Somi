from __future__ import annotations

import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from handlers.research.role_overlay import resolve_role_context

logger = logging.getLogger(__name__)


def _ensure_logger() -> None:
    logs_path = Path("sessions/logs/agentpedia.log")
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(__name__)
    log.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "").endswith(str(logs_path)) for h in log.handlers):
        h = RotatingFileHandler(logs_path, maxBytes=512_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)


AGENTPEDIA_DIR = Path("agentpedia")
AGENTPEDIA_DB = AGENTPEDIA_DIR / "agentpedia.sqlite"
AGENTPEDIA_PAGES_DIR = AGENTPEDIA_DIR / "pages"
AGENTPEDIA_STATE = AGENTPEDIA_DIR / "state.json"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", (text or "").strip().lower())
    return re.sub(r"\s+", "-", text).strip("-") or "untitled"


def _norm_claim(text: str) -> str:
    t = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().strip()
    except Exception:
        return ""


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


@dataclass
class AddResult:
    added_count: int
    updated_topics: list[str]
    skipped_reason_counts: dict[str, int]


@dataclass
class GrowResult:
    added_facts_count: int
    updated_topics: list[str]
    skipped_reason_counts: dict[str, int]
    errors: list[str]
    produced_events: list[dict[str, Any]]


class AgentpediaKB:
    def __init__(self):
        _ensure_logger()
        AGENTPEDIA_DIR.mkdir(parents=True, exist_ok=True)
        AGENTPEDIA_PAGES_DIR.mkdir(parents=True, exist_ok=True)
        self.path = AGENTPEDIA_DB
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=5)
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA busy_timeout=2000;")
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        with self._connect() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    summary TEXT,
                    topic TEXT NOT NULL,
                    tags TEXT,
                    source_url TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_date TEXT,
                    retrieved_at TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    evidence_snippet TEXT,
                    citation_key TEXT,
                    dedupe_key TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    supersedes_fact_id TEXT,
                    created_ts REAL NOT NULL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_facts_topic ON facts(topic)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_facts_dedupe ON facts(dedupe_key)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status)")
            c.commit()

    def _state(self) -> dict[str, Any]:
        if not AGENTPEDIA_STATE.exists():
            return {"last_topic_run": None, "last_run_ts": None, "per_topic_last_updated": {}, "run_count_week": 0, "week_start": None, "last_errors": []}
        try:
            return json.loads(AGENTPEDIA_STATE.read_text(encoding="utf-8"))
        except Exception:
            return {"last_topic_run": None, "last_run_ts": None, "per_topic_last_updated": {}, "run_count_week": 0, "week_start": None, "last_errors": []}

    def _save_state(self, state: dict[str, Any]) -> None:
        AGENTPEDIA_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def fact_count(self) -> int:
        with self._connect() as c:
            row = c.execute("SELECT COUNT(*) AS n FROM facts WHERE status='committed'").fetchone()
            return int(row["n"] if row else 0)

    def add_facts(self, facts: list[dict[str, Any]]) -> AddResult:
        added = 0
        updated_topics: set[str] = set()
        skipped = {"invalid": 0, "duplicate": 0, "low_confidence": 0}

        with self._connect() as c:
            for f in facts:
                claim = str(f.get("claim") or "").strip()
                topic = str(f.get("topic") or "").strip()
                source_url = str(f.get("source_url") or "").strip()
                source_title = str(f.get("source_title") or "").strip()
                confidence = float(f.get("confidence") or 0.0)
                if not claim or not topic or not source_url or not source_title:
                    skipped["invalid"] += 1
                    continue
                if len(claim) > 200:
                    skipped["invalid"] += 1
                    continue

                norm_claim = _norm_claim(claim)
                dedupe_key = str(f.get("dedupe_key") or _hash(f"{norm_claim}|{_domain(source_url)}"))

                existing = c.execute(
                    "SELECT fact_id, confidence FROM facts WHERE dedupe_key=? AND status='committed' ORDER BY confidence DESC, created_ts DESC LIMIT 1",
                    (dedupe_key,),
                ).fetchone()
                if existing:
                    if float(existing["confidence"] or 0.0) >= confidence:
                        skipped["duplicate"] += 1
                        continue

                # same normalized claim across domains -> supersede weaker
                norm_match = c.execute(
                    "SELECT fact_id, confidence FROM facts WHERE claim=? AND status='committed' ORDER BY confidence ASC, created_ts ASC LIMIT 1",
                    (claim,),
                ).fetchone()
                supersedes = norm_match["fact_id"] if norm_match and float(norm_match["confidence"] or 0.0) < confidence else None

                fact_id = str(f.get("fact_id") or _hash(f"{topic}|{claim}|{source_url}"))
                tags = f.get("tags") or []
                if isinstance(tags, (list, tuple)):
                    tags_json = json.dumps([str(t) for t in tags])
                else:
                    tags_json = json.dumps([str(tags)])

                c.execute(
                    """
                    INSERT OR REPLACE INTO facts(
                        fact_id, claim, summary, topic, tags, source_url, source_title, source_date,
                        retrieved_at, confidence, status, evidence_snippet, citation_key, dedupe_key,
                        version, supersedes_fact_id, created_ts
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fact_id,
                        claim,
                        str(f.get("summary") or "").strip(),
                        topic,
                        tags_json,
                        source_url,
                        source_title,
                        str(f.get("source_date") or "").strip() or None,
                        str(f.get("retrieved_at") or _now_iso()),
                        confidence,
                        str(f.get("status") or "committed"),
                        str(f.get("evidence_snippet") or "").strip()[:240],
                        str(f.get("citation_key") or "").strip(),
                        dedupe_key,
                        int(f.get("version") or 1),
                        supersedes,
                        time.time(),
                    ),
                )
                added += 1
                updated_topics.add(topic)

            c.commit()

        for topic in sorted(updated_topics):
            self._render_page(topic)

        return AddResult(added_count=added, updated_topics=sorted(updated_topics), skipped_reason_counts=skipped)

    def search(self, query: str, k: int = 8, tags: list[str] | None = None) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        pattern = f"%{q}%"
        with self._connect() as c:
            rows = c.execute(
                """
                SELECT * FROM facts
                WHERE status='committed'
                  AND LOWER(topic || ' ' || claim || ' ' || COALESCE(summary,'')) LIKE ?
                ORDER BY confidence DESC, created_ts DESC
                LIMIT ?
                """,
                (pattern, int(k)),
            ).fetchall()

        out = []
        for r in rows:
            item = dict(r)
            try:
                item["tags"] = json.loads(item.get("tags") or "[]")
            except Exception:
                item["tags"] = []
            if tags and not set(str(t).lower() for t in tags).intersection(set(str(t).lower() for t in item["tags"])):
                continue
            out.append(item)
        return out

    def list_topics(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as c:
            rows = c.execute(
                """
                SELECT topic, COUNT(*) as fact_count, MAX(retrieved_at) as last_updated
                FROM facts WHERE status='committed'
                GROUP BY topic
                ORDER BY last_updated DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_topic_page(self, topic: str) -> str:
        slug = _slug(topic)
        path = AGENTPEDIA_PAGES_DIR / f"{slug}.md"
        if not path.exists():
            self._render_page(topic)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"# {topic}\n\nNo Agentpedia page yet."

    def _render_page(self, topic: str) -> None:
        with self._connect() as c:
            rows = c.execute(
                """
                SELECT claim, summary, source_url, source_title, source_date, confidence, citation_key, tags, retrieved_at
                FROM facts
                WHERE status='committed' AND topic=?
                ORDER BY confidence DESC, created_ts DESC
                LIMIT 12
                """,
                (topic,),
            ).fetchall()
        if not rows:
            return

        now_iso = _now_iso()
        tags_accum: set[str] = set()
        claims = []
        sources = []
        for idx, r in enumerate(rows, start=1):
            cite = r["citation_key"] or f"[{idx}]"
            claims.append(f"- {r['claim']} {cite}")
            sources.append(f"{cite} {r['source_title']} — {_domain(r['source_url'])} — {r['source_date'] or 'n/a'} — {r['source_url']}")
            try:
                tags_accum.update(json.loads(r["tags"] or "[]"))
            except Exception:
                pass

        summary = " ".join([str(r["summary"] or r["claim"]).strip() for r in rows[:2]])
        summary = re.sub(r"\s+", " ", summary).strip()

        md = [
            f"# {topic}",
            f"Last updated: {now_iso}",
            f"Tags: {', '.join(sorted(str(t) for t in tags_accum if str(t).strip()))}",
            "",
            "## Summary",
            summary,
            "",
            "## Key facts",
            *claims,
            "",
            "## Details",
            "### Overview",
            "Agentpedia page compiled from committed factual records.",
            "",
            "## Sources",
            *sources,
            "",
        ]
        (AGENTPEDIA_PAGES_DIR / f"{_slug(topic)}.md").write_text("\n".join(md), encoding="utf-8")

    def _pick_topic(self, role: str | None, interests: list[str] | None) -> tuple[str, Any]:
        ctx = resolve_role_context(role, interests)
        seeds = list(ctx.topic_seeds or ["evidence literacy basics"])

        st = self._state()
        per_topic = st.get("per_topic_last_updated") or {}
        now = datetime.now().astimezone()
        cutoff = now - timedelta(days=7)

        eligible: list[str] = []
        recency: list[tuple[datetime, str]] = []
        for t in seeds:
            ts = per_topic.get(t)
            if not ts:
                eligible.append(t)
                recency.append((datetime.fromtimestamp(0, tz=now.tzinfo), t))
                continue
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=now.tzinfo)
            except Exception:
                eligible.append(t)
                recency.append((datetime.fromtimestamp(0, tz=now.tzinfo), t))
                continue
            recency.append((dt, t))
            if dt < cutoff:
                eligible.append(t)

        if eligible:
            return eligible[0], ctx

        # all recently updated: least recently updated fallback
        recency.sort(key=lambda x: x[0])
        return (recency[0][1] if recency else seeds[0]), ctx

    def grow(self, role: str | None, interests: list[str] | None, max_facts: int = 2, mode: str = "safe") -> GrowResult:
        topic, role_ctx = self._pick_topic(role, interests)
        now_iso = _now_iso()
        skipped: dict[str, int] = {}
        errors: list[str] = []

        # Safe/local-first candidate generation (no heavy autonomous polling).
        candidate_lines = [
            f"{topic.title()} benefits from clear definitions, measurable outcomes, and periodic review.",
            f"For {topic}, keeping source citations attached to claims improves retrieval precision and trust.",
        ]

        common_tags = [
            f"career_role:{str(role_ctx.role or 'General').lower()}",
            f"style:{str(role_ctx.nugget_style).lower()}",
        ]
        common_tags.extend([f"interest:{str(i).lower()}" for i in (interests or []) if str(i).strip()])
        common_tags.extend([f"domain:{str(d).lower()}" for d in (role_ctx.domains or []) if str(d).strip()])

        # FUTURE: apply source allowlist during retrieval.

        facts: list[dict[str, Any]] = []
        for idx, claim in enumerate(candidate_lines[: max(1, min(int(max_facts), 2))], start=1):
            if len(claim) > 200:
                skipped["too_long"] = skipped.get("too_long", 0) + 1
                continue
            source_url = "local://agentpedia-seed"
            source_title = "Agentpedia Seed Knowledge (local)"
            confidence = 0.30
            facts.append(
                {
                    "claim": claim,
                    "summary": claim[:120],
                    "topic": topic,
                    "tags": common_tags,
                    "source_url": source_url,
                    "source_title": source_title,
                    "source_date": datetime.now().date().isoformat(),
                    "retrieved_at": now_iso,
                    "confidence": confidence,
                    "status": "seed",
                    "evidence_snippet": claim[:240],
                    "citation_key": f"[{idx}]",
                    "dedupe_key": _hash(f"{_norm_claim(claim)}|{_domain(source_url)}"),
                    "version": 1,
                }
            )

        add = self.add_facts(facts)

        st = self._state()
        st["last_topic_run"] = topic
        st["last_run_ts"] = now_iso
        st["last_role"] = str(role_ctx.role or "General")
        st["last_nugget_style"] = str(role_ctx.nugget_style)
        per_topic = st.get("per_topic_last_updated") or {}
        per_topic[topic] = now_iso
        st["per_topic_last_updated"] = per_topic
        if errors:
            st["last_errors"] = errors[-5:]
        self._save_state(st)

        return GrowResult(
            added_facts_count=add.added_count,
            updated_topics=add.updated_topics,
            skipped_reason_counts={**add.skipped_reason_counts, **skipped},
            errors=errors,
            produced_events=[],
        )

