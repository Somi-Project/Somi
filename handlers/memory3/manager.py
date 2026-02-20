from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from config.settings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MEMORY_DEBUG,
    MEMORY_MAX_FACT_LINES,
    MEMORY_PINNED_MD_PATH,
    MEMORY_VOLATILE_TTL_HOURS,
    SYSTEM_TIMEZONE,
    MEMORY_SUMMARY_EVERY_N_TURNS,
)

from .compiler import build_block
from .embedder import EmbeddingUnavailable, OllamaEmbedder
from .extract import heuristics, llm_extract, sanitize, should_call_llm, to_snake
from .retrieve import not_expired, rrf_merge
from .store import SQLiteMemoryStore, utcnow_iso

logger = logging.getLogger(__name__)
PINNED_KEYS = {"output_format", "timezone", "preferred_name", "default_location", "name", "favorite_color", "dog_name"}
VALID_SCOPES = {"global", "profile", "task", "conversation", "vision"}
IDENTITY_KEYS = {"name", "preferred_name", "timezone", "default_location", "favorite_color"}
CRITICAL_KEYS = {"name", "preferred_name", "timezone"}


class Memory3Manager:
    def __init__(self, ollama_client=None, user_id: str = "default_user", session_id: Optional[str] = None, time_handler=None):
        self.client = ollama_client
        self.user_id = str(user_id or "default_user")
        self.session_id = session_id
        self.time_handler = time_handler
        self.store = SQLiteMemoryStore()
        self.embedder = OllamaEmbedder(client=self.client, model=EMBEDDING_MODEL, dim=int(EMBEDDING_DIM))
        self.vec_enabled = self.store.vec_enabled
        self._turn_counts: Dict[str, int] = {}
        self._recent_user_texts: Dict[str, List[str]] = {}
        self._ensure_pinned_md()

    def _debug(self, msg: str, *args):
        if MEMORY_DEBUG:
            logger.info("[memory3] " + msg, *args)

    def _resolve_user_id(self, explicit_user_id: Optional[str] = None, session_id: Optional[str] = None) -> str:
        return str(explicit_user_id or session_id or self.user_id or "default_user")

    def _pinned_md_path(self, user_id: Optional[str] = None) -> str:
        base = MEMORY_PINNED_MD_PATH
        root, ext = os.path.splitext(base)
        uid = self._resolve_user_id(user_id)
        safe_uid = re.sub(r"[^a-zA-Z0-9_.-]+", "_", uid) or "default_user"
        return f"{root}_{safe_uid}{ext or '.md'}"

    def _ensure_pinned_md(self, user_id: Optional[str] = None):
        os.makedirs(os.path.dirname(self._pinned_md_path(user_id)) or ".", exist_ok=True)
        if not os.path.exists(self._pinned_md_path(user_id)):
            with open(self._pinned_md_path(user_id), "w", encoding="utf-8") as f:
                f.write("# Pinned Memory\n## Preferences\n- (none)\n## Profile/Constraints\n- (none)\n")

    def _write_pinned_md(self, user_id: Optional[str] = None):
        uid = self._resolve_user_id(user_id)
        rows = self.store.pinned_items(uid, limit=100)
        prefs, prof = [], []
        for r in rows:
            ln = f"- {r.get('mkey','fact')}: {r.get('value','')}"
            if r.get("kind") == "preference":
                prefs.append(ln)
            else:
                prof.append(ln)
        with open(self._pinned_md_path(user_id), "w", encoding="utf-8") as f:
            f.write("# Pinned Memory\n")
            f.write("## Preferences\n")
            for x in (prefs[:10] or ["- (none)"]):
                f.write(x + "\n")
            f.write("## Profile/Constraints\n")
            for x in (prof[:10] or ["- (none)"]):
                f.write(x + "\n")

    def _bucket_for_fact(self, key: str, value: str = "") -> str:
        k = (key or "").lower()
        v = (value or "").lower()
        if k in IDENTITY_KEYS:
            return "identity"
        if k in {"goal", "project", "deadline", "task"} or any(t in k for t in ("goal", "project", "task", "deadline")):
            return "ongoing_projects"
        if any(t in k for t in ("spouse", "partner", "friend", "boss", "manager", "family", "mother", "father", "wife", "husband")):
            return "relationships"
        if any(t in v for t in ("my wife", "my husband", "my partner", "my friend", "my boss", "my manager", "my mom", "my dad")):
            return "relationships"
        return "general"

    def _importance_for_fact(self, key: str, kind: str, bucket: str) -> float:
        if key in IDENTITY_KEYS:
            return 0.95
        if bucket == "ongoing_projects":
            return 0.85
        if bucket == "relationships":
            return 0.8
        if kind == "constraint":
            return 0.78
        if kind == "volatile":
            return 0.62
        return 0.7

    def _lane_for_fact(self, key: str, kind: str) -> str:
        if key in PINNED_KEYS or kind in ("profile", "preference"):
            return "pinned"
        return "facts"

    async def _embed_safe(self, text: str) -> Optional[List[float]]:
        try:
            return await self.embedder.embed(text)
        except EmbeddingUnavailable:
            return None

    async def upsert_fact(self, fact: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
        entity = "user"
        key = to_snake(str(fact.get("key", "")))
        value = str(fact.get("value", "")).strip()[:120]
        kind = str(fact.get("kind", "preference")).strip().lower()
        if kind not in {"profile", "preference", "constraint", "volatile"}:
            kind = "preference"
        uid = self._resolve_user_id(user_id)
        lane = self._lane_for_fact(key, kind)
        bucket = self._bucket_for_fact(key, value)
        importance = self._importance_for_fact(key, kind, bucket)
        conf = float(fact.get("confidence", 0.7) or 0.7)
        conf = max(0.0, min(1.0, conf))
        expires_at = None
        if kind == "volatile":
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=int(MEMORY_VOLATILE_TTL_HOURS))).isoformat()

        cur = self.store.active_fact(uid, entity, key)
        if cur and str(cur.get("value", "")).strip().lower() == value.lower():
            return cur

        supersedes = None
        conflict_notice = None
        if cur:
            old_value = str(cur.get("value", "")).strip()
            self.store.set_status(str(cur.get("id")), "superseded")
            supersedes = str(cur.get("id"))
            self._debug("superseded old %s", key)
            if key in CRITICAL_KEYS and old_value and old_value.lower() != value.lower():
                conflict_notice = f"Updated {key.replace('_', ' ')} from '{old_value}' to '{value}'."

        iid = hashlib.sha256(f"{entity}:{key}:{value}:{utcnow_iso()}".encode("utf-8")).hexdigest()
        item = {
            "id": iid,
            "ts": utcnow_iso(),
            "user_id": uid,
            "lane": lane,
            "type": "fact",
            "entity": entity,
            "mkey": key,
            "value": value,
            "kind": kind,
            "bucket": bucket,
            "importance": importance,
            "replaced_by": None,
            "content": f"{key}: {value}",
            "tags": f"{lane} {kind} {key}",
            "confidence": conf,
            "status": "active",
            "expires_at": expires_at,
            "supersedes": supersedes,
            "last_used": None,
        }
        emb = await self._embed_safe(item["content"])
        self.store.write_item(item, embedding=emb)
        if supersedes:
            self.store.set_replaced_by(supersedes, iid)
        if lane == "pinned":
            self._write_pinned_md(uid)
        if conflict_notice:
            item["_conflict_notice"] = conflict_notice
        return item

    async def write_skill(self, skill: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        trig = str(skill.get("trigger", "")).strip()[:120]
        if not trig:
            return {}
        steps = [str(x).strip()[:90] for x in (skill.get("steps", []) or []) if str(x).strip()][:8]
        tags = [to_snake(str(x))[:32] for x in (skill.get("tags", []) or []) if str(x).strip()][:10]
        iid = hashlib.sha256(f"skill:{trig}:{utcnow_iso()}".encode("utf-8")).hexdigest()
        content = f"{trig} | " + " ; ".join(steps)
        item = {
            "id": iid,
            "ts": utcnow_iso(),
            "user_id": uid,
            "lane": "skills",
            "type": "skill",
            "entity": "user",
            "mkey": "skill",
            "value": trig,
            "kind": "skill",
            "bucket": "ongoing_projects",
            "importance": 0.7,
            "replaced_by": None,
            "content": content[:2000],
            "tags": " ".join(tags),
            "confidence": max(0.0, min(1.0, float(skill.get("confidence", 0.7) or 0.7))),
            "status": "active",
            "expires_at": None,
            "supersedes": None,
            "last_used": None,
        }
        emb = await self._embed_safe(item["content"])
        self.store.write_item(item, embedding=emb)
        return item

    async def ingest_turn(self, user_text: str, assistant_text: str = "", tool_summaries: Optional[List[str]] = None, session_id: Optional[str] = None):
        uid = self._resolve_user_id(session_id=session_id)
        self.store.expire_items(utcnow_iso())
        base = heuristics(user_text, assistant_text)
        if should_call_llm(user_text, assistant_text):
            llm = await llm_extract(self.client, user_text, assistant_text, tool_summaries)
            merged = {"facts": (base.get("facts", []) + llm.get("facts", []))[:3], "skills": (base.get("skills", []) + llm.get("skills", []))[:1]}
        else:
            merged = base
        clean = sanitize(merged)
        conflict_notices: List[str] = []
        for f in clean.get("facts", []):
            row = await self.upsert_fact(f, user_id=uid)
            notice = str(row.get("_conflict_notice", "")).strip()
            if notice:
                conflict_notices.append(notice)
        for s in clean.get("skills", []):
            await self.write_skill(s, user_id=uid)

        # Lightweight periodic session summary (no extra model call; safe for consumer hardware).
        summary_every = max(4, int(MEMORY_SUMMARY_EVERY_N_TURNS or 8))
        self._turn_counts[uid] = int(self._turn_counts.get(uid, 0) or 0) + 1
        recent = self._recent_user_texts.setdefault(uid, [])
        t = str(user_text or "").strip()
        if t:
            recent.append(t[:220])
            if len(recent) > summary_every:
                del recent[:-summary_every]

        summary_created = False
        if self._turn_counts[uid] % summary_every == 0 and recent:
            digest = " | ".join(recent[-summary_every:])[:700]
            sid = hashlib.sha256(f"summary:{uid}:{utcnow_iso()}".encode("utf-8")).hexdigest()
            item = {
                "id": sid,
                "ts": utcnow_iso(),
                "user_id": uid,
                "lane": "facts",
                "type": "summary",
                "entity": "user",
                "mkey": "session_summary",
                "value": digest[:220],
                "kind": "summary",
                "bucket": "ongoing_projects",
                "importance": 0.66,
                "replaced_by": None,
                "content": f"session_summary: {digest}",
                "tags": "summary session recap",
                "confidence": 0.62,
                "status": "active",
                "expires_at": None,
                "supersedes": None,
                "last_used": None,
            }
            emb = await self._embed_safe(item["content"])
            self.store.write_item(item, embedding=emb)
            summary_created = True

        self._debug("ingest decisions facts=%d skills=%d", len(clean.get("facts", [])), len(clean.get("skills", [])))
        return {"conflict_notices": conflict_notices[:2], "summary_created": summary_created}

    def _read_pinned_lines(self, user_id: Optional[str] = None) -> List[str]:
        self._ensure_pinned_md(user_id)
        lines = []
        with open(self._pinned_md_path(user_id), "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t.startswith("- "):
                    lines.append(t)
        return lines

    async def build_injected_context(self, user_text: str, user_id: Optional[str] = None) -> str:
        uid = self._resolve_user_id(user_id)
        self.store.expire_items(utcnow_iso())
        pinned = self._read_pinned_lines(uid)
        fts_ids = self.store.fts_search(uid, user_text, limit=30)
        vec_ids: List[str] = []
        if self.store.vec_enabled:
            try:
                qv = await self.embedder.embed(user_text)
                vec_ids = self.store.vec_search(qv, limit=30)
            except Exception:
                vec_ids = []
        merged_ids = rrf_merge(fts_ids, vec_ids, k=60)
        candidates = self.store.get_items_by_ids(uid, merged_ids)

        q_tokens = [x for x in re.findall(r"[a-z0-9_]+", (user_text or "").lower()) if len(x) > 2][:12]
        now_utc = datetime.now(timezone.utc)

        def _score(it: Dict[str, Any]) -> float:
            content = f"{it.get('content','')} {it.get('tags','')}".lower()
            rel_hits = sum(1 for tok in q_tokens if tok in content)
            rel = min(1.0, rel_hits / max(1, len(q_tokens))) if q_tokens else 0.4
            ts_raw = str(it.get("ts") or "")
            recency = 0.35
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = max(0.0, (now_utc - ts).total_seconds() / 86400.0)
                recency = 1.0 / (1.0 + (age_days / 14.0))
            except Exception:
                pass
            importance = float(it.get("importance", 0.5) or 0.5)
            return (0.65 * rel) + (0.2 * recency) + (0.15 * importance)

        ranked = sorted(candidates, key=_score, reverse=True)

        facts, skills, volatile = [], [], []
        for it in ranked:
            if not not_expired(it):
                continue
            if it.get("type") == "skill":
                eff_conf = float(it.get("confidence", 0.7) or 0.7)
                lu = str(it.get("last_used") or "").strip()
                if lu:
                    try:
                        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(lu.replace("Z", "+00:00"))).days
                        if age_days > 30:
                            eff_conf = max(0.0, eff_conf - 0.02)
                    except Exception:
                        pass
                skills.append(f"- {it.get('value','skill')} (conf {eff_conf:.2f}): {it.get('content','')[:95]}")
                try:
                    self.store.reinforce_skill(str(it.get("id", "")), delta=0.02, cap=0.95)
                except Exception:
                    pass
            else:
                bucket = str(it.get('bucket','general')).strip()
                prefix = f"[{bucket}] " if bucket and bucket != 'general' else ''
                ln = f"- {prefix}{it.get('mkey','fact')}: {it.get('value','')}"
                if it.get("kind") == "volatile":
                    volatile.append(ln)
                elif it.get("lane") != "pinned":
                    facts.append(ln)

        block = build_block(pinned=pinned, facts=facts[: int(MEMORY_MAX_FACT_LINES)], skills=skills[:2], volatile=volatile[:4])
        self._debug("vec_enabled=%s fts=%d vec=%d facts=%d skills=%d injected_chars=%d", self.store.vec_enabled, len(fts_ids), len(vec_ids), len(facts), len(skills), len(block))
        return block

    # compatibility APIs used by agent
    async def retrieve_relevant_memories(self, query: str, user_id: str, min_score: float = 0.2, scope: str = "conversation") -> str:
        return await self.build_injected_context(query, user_id=user_id)

    async def maybe_extract_and_store(self, user_text: str, assistant_text: Optional[str] = None, tool_summaries: Optional[List[str]] = None, session_id: Optional[str] = None):
        await self.ingest_turn(user_text, assistant_text or "", tool_summaries=tool_summaries, session_id=session_id)

    # reminders
    def _local_timezone(self):
        tz_name = str(getattr(self.time_handler, "default_timezone", SYSTEM_TIMEZONE) or SYSTEM_TIMEZONE)
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return timezone.utc

    def _parse_clock_components(self, hour_str: str, minute_str: Optional[str], am_pm: str) -> Optional[tuple[int, int]]:
        hh = int(hour_str)
        mm = int(minute_str or 0)
        ap = (am_pm or "").strip().lower()

        if not (0 <= mm <= 59):
            return None

        if ap:
            # 12h clock input must be 1..12 (reject malformed values like 00am/13pm).
            if not (1 <= hh <= 12):
                return None
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            return hh, mm

        if not (0 <= hh <= 23):
            return None
        return hh, mm

    def _parse_due(self, when: str) -> Optional[str]:
        raw = (when or "").strip().lower()
        raw = re.sub(r"\s+", " ", raw)
        raw = re.sub(r"\bmins?\b", "minutes", raw)
        raw = re.sub(r"\bhrs?\b", "hours", raw)
        raw = re.sub(r"\bsecs?\b", "seconds", raw)
        raw = re.sub(r"\btmr\b", "tomorrow", raw)

        tz = self._local_timezone()
        now_local = datetime.now(tz)

        m = re.match(r"^in\s+(\d+)\s+(seconds?|s|minutes?|m|hours?|h|days?|d)$", raw)
        if m:
            n = int(m.group(1)); u = m.group(2)
            if u.startswith(("s", "sec")):
                return (now_local + timedelta(seconds=n)).astimezone(timezone.utc).isoformat()
            if u.startswith(("m", "min")):
                return (now_local + timedelta(minutes=n)).astimezone(timezone.utc).isoformat()
            if u.startswith(("h", "hour")):
                return (now_local + timedelta(hours=n)).astimezone(timezone.utc).isoformat()
            if u.startswith("d"):
                return (now_local + timedelta(days=n)).astimezone(timezone.utc).isoformat()

        m = re.match(r"^in\s+(?:a|an)\s+(minute|hour|day)$", raw)
        if m:
            unit = m.group(1)
            if unit == "minute":
                return (now_local + timedelta(minutes=1)).astimezone(timezone.utc).isoformat()
            if unit == "hour":
                return (now_local + timedelta(hours=1)).astimezone(timezone.utc).isoformat()
            if unit == "day":
                return (now_local + timedelta(days=1)).astimezone(timezone.utc).isoformat()

        if raw in ("in half an hour", "in half hour", "in 30 minutes"):
            return (now_local + timedelta(minutes=30)).astimezone(timezone.utc).isoformat()

        m = re.match(r"^at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", raw)
        if m:
            parsed = self._parse_clock_components(m.group(1), m.group(2), m.group(3) or "")
            if not parsed:
                return None
            hh, mm = parsed
            due_local = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due_local <= now_local:
                due_local += timedelta(days=1)
            return due_local.astimezone(timezone.utc).isoformat()

        m = re.match(r"^tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", raw)
        if m:
            parsed = self._parse_clock_components(m.group(1), m.group(2), m.group(3) or "")
            if not parsed:
                return None
            hh, mm = parsed
            due_local = (now_local + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            return due_local.astimezone(timezone.utc).isoformat()

        return None

    async def add_reminder(self, user_id: str, title: str, when: str, details: str = "", scope: str = "task", priority: int = 3):
        due = self._parse_due(when)
        if not due:
            return None
        rid = hashlib.sha256(f"{user_id}:{title}:{due}".encode("utf-8")).hexdigest()
        self.store.upsert_reminder({"id": rid, "ts": utcnow_iso(), "user_id": str(user_id), "title": title[:140], "due_ts": due, "status": "active", "scope": scope if scope in VALID_SCOPES else "task", "details": details[:240], "priority": int(priority), "last_notified_ts": None, "notify_count": 0})
        return rid

    async def peek_due_reminders(self, user_id: str, limit: int = 3):
        return [{"reminder_id": r["id"], "title": r["title"], "details": r.get("details", ""), "due_ts": r["due_ts"], "scope": r.get("scope", "task")} for r in self.store.due_reminders(str(user_id), utcnow_iso(), limit=max(1, int(limit)))]

    async def consume_due_reminders(self, user_id: str, limit: int = 3):
        due = await self.peek_due_reminders(user_id, limit=limit)
        for r in due:
            self.store.mark_reminder_done(str(r.get("reminder_id", "")))
        return due

    def consume_due_reminders_sync(self, user_id: str, limit: int = 3):
        due = self.store.due_reminders(str(user_id), utcnow_iso(), limit=max(1, int(limit)))
        out = []
        for r in due:
            self.store.mark_reminder_done(str(r.get("id", "")))
            out.append({"reminder_id": r["id"], "title": r["title"], "details": r.get("details", ""), "due_ts": r["due_ts"], "scope": r.get("scope", "task")})
        return out

    async def list_active_reminders(self, user_id: str, scope: str = "task", limit: int = 25):
        return self.store.active_reminders(str(user_id), scope=scope if scope in VALID_SCOPES else "task", limit=max(1, int(limit)))

    async def delete_reminder_by_title(self, user_id: str, title: str, scope: str = "task") -> int:
        return self.store.delete_reminder_by_title(str(user_id), str(title), scope=scope if scope in VALID_SCOPES else "task")

    # lightweight shims
    async def upsert_goal(self, user_id: str, title: str, **kwargs):
        uid = self._resolve_user_id(user_id)
        row = await self.upsert_fact({"key": "goal", "value": title, "kind": "constraint", "confidence": 0.72}, user_id=uid)
        return row.get("id")

    def list_active_goals_sync(self, user_id: str, scope: str = "task", limit: int = 6):
        uid = self._resolve_user_id(user_id)
        ids = self.store.fts_search(uid, "goal", limit=30)
        rows = self.store.get_items_by_ids(uid, ids)
        goals = [r for r in rows if r.get("type") == "fact" and r.get("mkey") == "goal" and r.get("status") == "active"]
        return [{"title": g.get("value", "Goal"), "progress": 0.0, "confidence": float(g.get("confidence", 0.7))} for g in goals[: max(1, int(limit))]]

    async def list_active_goals(self, user_id: str, scope: str = "task", limit: int = 6):
        return self.list_active_goals_sync(user_id, scope=scope, limit=limit)

    async def build_goal_context(self, user_id: str, scope: str = "task", limit: int = 3):
        g = await self.list_active_goals(user_id, scope=scope, limit=limit)
        if not g:
            return None
        return "\n".join([f"- {x['title']} (progress 0%, confidence {float(x.get('confidence',0.7)):.2f})" for x in g])

    async def delete_goal_by_title(self, user_id: str, title: str, scope: str = "task") -> bool:
        # best effort by inserting retraction fact
        uid = self._resolve_user_id(user_id)
        await self.upsert_fact({"key": "goal", "value": f"retracted:{title}", "kind": "constraint", "confidence": 0.7}, user_id=uid)
        return True

    async def forget_phrase(self, user_id: str, phrase: str, **kwargs) -> bool:
        uid = self._resolve_user_id(user_id)
        await self.upsert_fact({"key": "forget", "value": phrase[:120], "kind": "constraint", "confidence": 0.9}, user_id=uid)
        return True

    async def prune_old_memories(self):
        self.store.expire_items(utcnow_iso())

    async def curate_daily_digest(self):
        return
