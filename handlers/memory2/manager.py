from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from ollama import AsyncClient
except Exception:  # pragma: no cover
    AsyncClient = None  # type: ignore

from config.settings import MEMORY2_VOLATILE_TTL_HOURS, SYSTEM_TIMEZONE
from .compiler import compile_memory_block
from .extract import heuristic_extract, llm_extract, normalize_fact_candidate, normalize_skill_candidate, should_attempt_llm
from .retrieve import (
    active_facts,
    get_constraint_facts,
    get_preference_facts,
    get_profile_facts,
    get_relevant_facts,
    get_relevant_skills,
    get_volatile_facts,
)
from .store import ensure_store_dir, load_facts, load_reminders, load_skills, write_event, write_fact, write_reminder, write_skill
from .types import Fact, FactCandidate, Reminder, Skill, SkillCandidate

VALID_SCOPES = {"global", "profile", "task", "conversation", "vision"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class Memory2Manager:
    def _format_due(self, due_ts: str) -> str:
        if self.time_handler is not None and hasattr(self.time_handler, "format_iso_to_local"):
            try:
                return str(self.time_handler.format_iso_to_local(due_ts, SYSTEM_TIMEZONE))
            except Exception:
                pass
        return due_ts

    def __init__(
        self,
        ollama_client: Optional[AsyncClient] = None,
        session_id: Optional[str] = None,
        time_handler: Optional[Any] = None,
        user_id: str = "default_user",
    ):
        ensure_store_dir()
        self.client = ollama_client or (AsyncClient() if AsyncClient is not None else None)
        self.session_id = session_id
        self.user_id = str(user_id or "default_user")
        self.time_handler = time_handler
        self._facts: List[Dict[str, Any]] = []
        self._skills: List[Dict[str, Any]] = []
        self._reminders: List[Dict[str, Any]] = []
        self._active_by_entity_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._facts = load_facts()
        self._skills = load_skills()
        self._reminders = load_reminders()
        self._reindex()

    def _reindex(self) -> None:
        self._active_by_entity_key = {}
        for f in self._facts:
            entity, key = str(f.get("entity", "user")), str(f.get("key", ""))
            if not key:
                continue
            ek = (entity, key)
            st = str(f.get("status", "active"))
            if st == "active":
                self._active_by_entity_key[ek] = f
            elif st in ("superseded", "retracted", "expired") and ek in self._active_by_entity_key:
                cur = self._active_by_entity_key[ek]
                if cur.get("id") == f.get("id"):
                    del self._active_by_entity_key[ek]

    def _norm_scope(self, scope: str) -> str:
        s = str(scope or "task").strip().lower()
        return s if s in VALID_SCOPES else "task"

    def _fact_id(self, entity: str, key: str, value: str) -> str:
        return hashlib.sha256(f"{entity}:{key}:{value}:{_utcnow_iso()}".encode("utf-8")).hexdigest()

    def _reminder_id(self, user_id: str, title: str, due_ts: str) -> str:
        return hashlib.sha256(f"{user_id}:{title}:{due_ts}".encode("utf-8")).hexdigest()

    def log_event(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> None:
        eid = hashlib.sha256(f"{_utcnow_iso()}:{event_type}:{json.dumps(payload, sort_keys=True)}".encode("utf-8")).hexdigest()
        write_event({"id": eid, "ts": _utcnow_iso(), "event_type": event_type, "payload": payload, "source": source, "session_id": self.session_id})

    def expire_volatiles(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        changed = False
        for f in list(self._facts):
            if str(f.get("status", "")) != "active" or str(f.get("kind")) != "volatile":
                continue
            ex = str(f.get("expires_at") or "")
            if not ex:
                continue
            try:
                dt = _parse_iso(ex)
            except Exception:
                continue
            if dt <= now:
                tomb = dict(f)
                tomb["ts"] = _utcnow_iso()
                tomb["status"] = "expired"
                tomb["source"] = "system"
                write_fact(tomb)
                self._facts.append(tomb)
                changed = True
        if changed:
            self._reindex()

    def _retract_by_hint(self, text: str) -> int:
        tl = _norm(text)
        if "forget" not in tl:
            return 0
        n = 0
        for _, f in list(self._active_by_entity_key.items()):
            value = _norm(str(f.get("value", "")))
            if value and value in tl:
                tomb = dict(f)
                tomb["ts"] = _utcnow_iso()
                tomb["status"] = "retracted"
                tomb["source"] = "user"
                write_fact(tomb)
                self._facts.append(tomb)
                n += 1
        if n:
            self._reindex()
        return n

    def upsert_fact(self, candidate: FactCandidate) -> Fact:
        entity = _norm(candidate.entity or "user") or "user"
        key = re.sub(r"[^a-z0-9_]+", "_", _norm(candidate.key))[:48].strip("_") or "fact"
        value = (candidate.value or "").strip()[:120]
        kind = candidate.kind if candidate.kind in {"profile", "preference", "constraint", "volatile"} else "preference"
        confidence = max(0.0, min(1.0, float(candidate.confidence or 0.6)))
        expires_at = candidate.expires_at
        if kind == "volatile" and not expires_at:
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=int(MEMORY2_VOLATILE_TTL_HOURS))).isoformat()

        cur = self._active_by_entity_key.get((entity, key))
        if cur and _norm(str(cur.get("value", ""))) == _norm(value):
            return Fact(**{k: cur.get(k) for k in Fact.__dataclass_fields__.keys()})

        if cur:
            old = dict(cur)
            old["ts"] = _utcnow_iso()
            old["status"] = "superseded"
            write_fact(old)
            self._facts.append(old)

        row = Fact(
            id=self._fact_id(entity, key, value),
            ts=_utcnow_iso(),
            entity=entity,
            key=key,
            value=value,
            kind=kind,
            confidence=confidence,
            status="active",
            supersedes=str(cur.get("id")) if cur else None,
            expires_at=expires_at,
            source=candidate.source,
            session_id=candidate.session_id or self.session_id,
        )
        write_fact(asdict(row))
        self._facts.append(asdict(row))
        self._reindex()
        return row

    def add_skill(self, skill_candidate: SkillCandidate) -> Skill:
        sid = hashlib.sha256(f"skill:{skill_candidate.trigger}:{_utcnow_iso()}".encode("utf-8")).hexdigest()
        skill = Skill(
            id=sid,
            ts=_utcnow_iso(),
            trigger=skill_candidate.trigger[:120],
            steps=[s[:120] for s in (skill_candidate.steps or [])[:8]],
            tools=[t[:32] for t in (skill_candidate.tools or [])[:8]],
            success=bool(skill_candidate.success),
            tags=[t[:32] for t in (skill_candidate.tags or [])[:10]],
            confidence=max(0.0, min(1.0, float(skill_candidate.confidence or 0.6))),
            last_used=None,
        )
        write_skill(asdict(skill))
        self._skills.append(asdict(skill))
        return skill

    def _parse_due_time(self, when: str) -> Optional[str]:
        raw = (when or "").strip().lower()
        if not raw:
            return None

        now_local = datetime.now(timezone.utc)
        m = re.match(r"^in\s+(\d+)\s+(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)$", raw)
        if m:
            n = int(m.group(1))
            u = m.group(2)
            if u.startswith(("s", "sec")):
                return (now_local + timedelta(seconds=n)).isoformat()
            if u.startswith(("m", "min")):
                return (now_local + timedelta(minutes=n)).isoformat()
            if u.startswith(("h", "hr")):
                return (now_local + timedelta(hours=n)).isoformat()
            if u.startswith("d"):
                return (now_local + timedelta(days=n)).isoformat()

        if raw in ("in half an hour", "in half hour"):
            return (now_local + timedelta(minutes=30)).isoformat()

        m = re.match(r"^in\s+(a|an)\s+(minute|hour|day)$", raw)
        if m:
            unit = m.group(2)
            if unit == "minute":
                return (now_local + timedelta(minutes=1)).isoformat()
            if unit == "hour":
                return (now_local + timedelta(hours=1)).isoformat()
            return (now_local + timedelta(days=1)).isoformat()

        # at 8:30 pm / at 20:30
        m = re.match(r"^at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", raw)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            ap = (m.group(3) or "").lower()
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                now = datetime.now(timezone.utc)
                due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if due <= now:
                    due += timedelta(days=1)
                return due.isoformat()

        m = re.match(r"^tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", raw)
        if m:
            hh = int(m.group(1)); mm = int(m.group(2) or 0); ap = (m.group(3) or "").lower()
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            now = datetime.now(timezone.utc) + timedelta(days=1)
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return due.isoformat()

        return None

    def _latest_reminders(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        latest: Dict[str, Dict[str, Any]] = {}
        for r in load_reminders():
            if str(r.get("user_id", "")) != str(user_id):
                continue
            rid = str(r.get("id", ""))
            if not rid:
                continue
            latest[rid] = r
        return latest

    async def add_reminder(self, user_id: str, title: str, when: str, details: str = "", scope: str = "task", priority: int = 3) -> Optional[str]:
        due_ts = self._parse_due_time(when)
        if not due_ts:
            return None
        uid = str(user_id or self.user_id)
        rid = self._reminder_id(uid, title.strip(), due_ts)
        row = Reminder(
            id=rid,
            ts=_utcnow_iso(),
            user_id=uid,
            title=(title or "Reminder").strip()[:140],
            due_ts=due_ts,
            status="active",
            scope=self._norm_scope(scope),
            details=(details or "").strip()[:240],
            priority=int(priority),
        )
        write_reminder(asdict(row))
        self.log_event("reminder_create", {"id": rid, "title": row.title, "due_ts": due_ts}, source="user")
        return rid

    async def peek_due_reminders(self, user_id: str, limit: int = 3) -> List[Dict[str, str]]:
        uid = str(user_id or self.user_id)
        now = datetime.now(timezone.utc)
        out: List[Dict[str, str]] = []
        for r in self._latest_reminders(uid).values():
            if str(r.get("status")) != "active":
                continue
            try:
                due = _parse_iso(str(r.get("due_ts", "")))
            except Exception:
                continue
            if due <= now:
                out.append({
                    "reminder_id": str(r.get("id", "")),
                    "title": str(r.get("title", "Reminder")),
                    "details": str(r.get("details", "")),
                    "due_ts": str(r.get("due_ts", "")),
                    "scope": str(r.get("scope", "task")),
                })
        out.sort(key=lambda x: x.get("due_ts", ""))
        return out[: max(1, int(limit))]

    def consume_due_reminders_sync(self, user_id: str, limit: int = 3) -> List[Dict[str, str]]:
        uid = str(user_id or self.user_id)
        due = []
        for r in self._latest_reminders(uid).values():
            if str(r.get("status")) != "active":
                continue
            try:
                if _parse_iso(str(r.get("due_ts", ""))) <= datetime.now(timezone.utc):
                    due.append(r)
            except Exception:
                continue
        due.sort(key=lambda x: str(x.get("due_ts", "")))
        fired: List[Dict[str, str]] = []
        for r in due[: max(1, int(limit))]:
            upd = dict(r)
            upd["ts"] = _utcnow_iso()
            upd["status"] = "done"
            upd["last_notified_ts"] = _utcnow_iso()
            upd["notify_count"] = int(r.get("notify_count", 0) or 0) + 1
            write_reminder(upd)
            fired.append(
                {
                    "reminder_id": str(r.get("id", "")),
                    "title": str(r.get("title", "Reminder")),
                    "details": str(r.get("details", "")),
                    "due_ts": str(r.get("due_ts", "")),
                    "scope": str(r.get("scope", "task")),
                }
            )
        return fired

    async def consume_due_reminders(self, user_id: str, limit: int = 3) -> List[Dict[str, str]]:
        return self.consume_due_reminders_sync(user_id=user_id, limit=limit)

    async def list_active_reminders(self, user_id: str, scope: str = "task", limit: int = 25) -> List[Dict[str, Any]]:
        uid = str(user_id or self.user_id)
        sc = self._norm_scope(scope)
        out = []
        for r in self._latest_reminders(uid).values():
            if str(r.get("status")) != "active":
                continue
            if str(r.get("scope", "task")) != sc:
                continue
            out.append(r)
        out.sort(key=lambda x: str(x.get("due_ts", "")))
        return out[: max(1, int(limit))]

    async def delete_reminder_by_title(self, user_id: str, title: str, scope: str = "task") -> int:
        uid = str(user_id or self.user_id)
        t = _norm(title)
        n = 0
        for r in self._latest_reminders(uid).values():
            if str(r.get("status")) != "active":
                continue
            if _norm(str(r.get("title", ""))) != t:
                continue
            if str(r.get("scope", "task")) != self._norm_scope(scope):
                continue
            tomb = dict(r)
            tomb["ts"] = _utcnow_iso()
            tomb["status"] = "retracted"
            write_reminder(tomb)
            n += 1
        return n

    async def upsert_goal(self, *args, **kwargs) -> str:
        # goals intentionally flattened into preference memory for now
        title = str(kwargs.get("title") or (args[1] if len(args) > 1 else "goal"))
        row = self.upsert_fact(FactCandidate(entity="user", key="goal", value=title[:120], kind="constraint", confidence=0.7))
        return row.id

    async def list_active_goals(self, user_id: str, scope: str = "task", limit: int = 6) -> List[Dict[str, Any]]:
        facts = [f for f in active_facts(self._facts) if f.get("key") == "goal"]
        return [{"title": f.get("value", "Goal"), "progress": 0.0, "confidence": float(f.get("confidence", 0.6))} for f in facts[: max(1, int(limit))]]

    async def build_goal_context(self, user_id: str, scope: str = "task", limit: int = 3) -> Optional[str]:
        goals = await self.list_active_goals(user_id, scope=scope, limit=limit)
        if not goals:
            return None
        return "\n".join([f"- {g['title']} (progress {int(float(g.get('progress',0))*100)}%, confidence {float(g.get('confidence',0.6)):.2f})" for g in goals])

    async def delete_goal_by_title(self, user_id: str, title: str, scope: str = "task") -> bool:
        target = _norm(title)
        for f in active_facts(self._facts):
            if str(f.get("key")) == "goal" and _norm(str(f.get("value", ""))) == target:
                tomb = dict(f)
                tomb["ts"] = _utcnow_iso()
                tomb["status"] = "retracted"
                write_fact(tomb)
                self._facts.append(tomb)
                self._reindex()
                return True
        return False

    async def forget_phrase(self, user_id: str, phrase: str, source: str = "forget", scope: str = "conversation") -> bool:
        return self._retract_by_hint(f"forget {phrase}") > 0

    async def list_recent_memories(self, user_id: str, limit: int = 20, scope: str = "conversation") -> List[Dict[str, Any]]:
        rows = active_facts(self._facts)[: max(1, int(limit))]
        return [{"ts": r.get("ts", ""), "type": r.get("kind", "fact"), "content": f"{r.get('key')}: {r.get('value')}", "hash": r.get("id", ""), "scope": scope} for r in rows]

    def retrieve_context(self, query_text: str) -> str:
        self.reload()
        self.expire_volatiles()
        profile = get_profile_facts(self._facts)
        prefs = get_preference_facts(self._facts)
        cons = get_constraint_facts(self._facts)
        vol = get_volatile_facts(self._facts)
        rf = get_relevant_facts(self._facts, query_text, limit=8)
        rs = get_relevant_skills(self._skills, query_text, limit=3)

        # include open reminders as volatile hints
        for r in self._latest_reminders(self.user_id).values():
            if str(r.get("status")) != "active":
                continue
            vol.append(
                {
                    "key": "reminder",
                    "value": f"{r.get('title','Reminder')} (due {self._format_due(str(r.get('due_ts','')))})",
                    "expires_at": r.get("due_ts", ""),
                }
            )
        return compile_memory_block(profile, prefs, cons, vol, rs, rf)

    async def maybe_extract_and_store(self, user_text: str, assistant_text: Optional[str] = None, tool_summaries: Optional[List[str]] = None) -> None:
        self.reload()
        self._retract_by_hint(user_text)

        cands: List[FactCandidate] = heuristic_extract(user_text)
        if should_attempt_llm(user_text, assistant_text):
            data = await llm_extract(self.client, user_text, assistant_text=assistant_text, tool_summaries=tool_summaries)
            for d in data.get("facts", []):
                fc = normalize_fact_candidate(d)
                if fc:
                    cands.append(fc)
            for d in data.get("skills", []):
                sc = normalize_skill_candidate(d)
                if sc:
                    self.add_skill(sc)

        seen = set()
        for c in cands:
            sig = (c.entity, c.key, _norm(c.value), c.kind)
            if sig in seen:
                continue
            seen.add(sig)
            self.upsert_fact(c)

        self.maybe_add_skill_from_task(assistant_text or "", tool_summaries=tool_summaries)

    def maybe_add_skill_from_task(self, assistant_text: str, tool_summaries: Optional[List[str]] = None, success: bool = True) -> Optional[Skill]:
        text = assistant_text or ""
        steps = [ln.strip("- ") for ln in text.splitlines() if re.search(r"\b(run|edit|patch|set|create|open|use|check|test)\b", ln.lower())]
        if len(steps) < 3 and not (tool_summaries and len(tool_summaries) >= 2):
            return None
        trig = str((tool_summaries or ["procedural fix"])[0])[:120]
        return self.add_skill(SkillCandidate(trigger=trig, steps=steps[:8], tools=[], tags=["auto", "replay"], confidence=0.62, success=success))

    # compatibility shims for existing agent path
    async def retrieve_relevant_memories(self, query: str, user_id: str, min_score: float = 0.2, scope: str = "conversation") -> str:
        return self.retrieve_context(query)

    def stage_memory(self, *args, **kwargs) -> None:
        return

    async def should_store_memory(self, input_text: str, output_text: str, user_id: str):
        return False, None, None

    async def curate_daily_digest(self) -> None:
        return

    async def prune_old_memories(self) -> None:
        self.expire_volatiles()
        return
