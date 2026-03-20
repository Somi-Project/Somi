from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from config.memorysettings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MEMORY_DEBUG,
    MEMORY_MAX_FACT_LINES,
    MEMORY_PINNED_MD_PATH,
    MEMORY_VOLATILE_TTL_HOURS,
    MEMORY_SUMMARY_EVERY_N_TURNS,
    USE_VECTOR_INDEX,
)
from config.settings import (
    SYSTEM_TIMEZONE,
    SUMMARY_ENABLED,
    SUMMARY_USE_LLM,
    SUMMARY_MODEL,
)

from .embedder import EmbeddingUnavailable, OllamaEmbedder
from .extract import heuristics, llm_extract, sanitize, should_call_llm, to_snake
from .frozen import FrozenMemoryStore
from .retrieve import not_expired
from .retrieval import apply_filters_and_caps, infer_memory_focus, rerank_items, rrf_fuse
from .injection import build_injection_payload
from .doctor import memory_doctor_report
from .preference_graph import build_preference_graph
from .review import build_memory_review
from .session_summary import build_summary_from_recent_turns, should_update_summary, trim_summary_text
from .store import SQLiteMemoryStore, utcnow_iso
from .vault import KnowledgeVaultService
from search import SessionSearchService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _compat_asyncio_timeout(seconds: float):
    if hasattr(asyncio, "timeout"):
        async with asyncio.timeout(seconds):
            yield
    else:
        yield

PINNED_KEYS = {"output_format", "timezone", "preferred_name", "default_location", "name", "favorite_color", "dog_name", "favorite_drink", "coding_style"}
VALID_SCOPES = {"global", "profile", "task", "conversation", "vision"}
IDENTITY_KEYS = {"name", "preferred_name", "timezone", "default_location", "favorite_color"}
CRITICAL_KEYS = {"name", "preferred_name", "timezone"}
TYPED_SCOPE_MAP = {"user": "user_memory", "project": "project_memory", "object": "object_memory"}


class Memory3Manager:
    def __init__(
        self,
        ollama_client=None,
        user_id: str = "default_user",
        session_id: Optional[str] = None,
        time_handler=None,
        session_search: Optional[SessionSearchService] = None,
        store: Optional[SQLiteMemoryStore] = None,
        frozen_store: Optional[FrozenMemoryStore] = None,
    ):
        self.client = ollama_client
        self.user_id = str(user_id or "default_user")
        self.session_id = session_id
        self.time_handler = time_handler
        self.store = store or SQLiteMemoryStore()
        self.embedder = OllamaEmbedder(client=self.client, model=EMBEDDING_MODEL, dim=int(EMBEDDING_DIM))
        self.session_search = session_search or SessionSearchService()
        self.frozen_store = frozen_store or FrozenMemoryStore()
        self.vault = KnowledgeVaultService(store=self.store, embed_text=self._embed_safe)
        self.vec_enabled = self.store.vec_enabled
        self._turn_counts: Dict[str, int] = {}
        self._recent_user_texts: Dict[str, List[str]] = {}
        self._last_summary_turn: Dict[str, int] = {}
        self._ensure_pinned_md()

    def _debug(self, msg: str, *args):
        if MEMORY_DEBUG:
            logger.info("[memory3] " + msg, *args)

    def build_preference_graph_sync(self, user_id: Optional[str] = None, limit: int = 24) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        profile_rows = self.store.latest_by_scope(uid, "profile", limit=max(1, int(limit or 24)))
        pref_rows = self.store.latest_by_scope(uid, "preferences", limit=max(1, int(limit or 24)))
        return build_preference_graph(profile_rows=profile_rows, preference_rows=pref_rows, limit=limit)

    async def build_preference_graph(self, user_id: Optional[str] = None, limit: int = 24) -> Dict[str, Any]:
        return self.build_preference_graph_sync(user_id=user_id, limit=limit)

    def build_memory_review_sync(self, user_id: Optional[str] = None, limit: int = 6, review_window: int = 96) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        memory_items = self.store.list_items(
            uid,
            scopes=[
                "profile",
                "preferences",
                "conversation",
                "user_memory",
                "project_memory",
                "object_memory",
                "projects",
                "tasks",
            ],
            statuses=["active", "superseded", "expired"],
            limit=max(12, int(review_window or 96)),
        )
        return build_memory_review(
            items=memory_items,
            recent_events=self.store.recent_events(uid, limit=max(12, int(review_window or 96))),
            pinned_rows=self.store.pinned_items(uid, limit=12),
            summary_row=self.store.latest_session_summary(uid) or {},
            preference_graph=self.build_preference_graph_sync(uid, limit=12),
            limit=limit,
        )

    async def build_memory_review(self, user_id: Optional[str] = None, limit: int = 6, review_window: int = 96) -> Dict[str, Any]:
        return self.build_memory_review_sync(user_id=user_id, limit=limit, review_window=review_window)

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
        k = (key or "").lower()
        if key in PINNED_KEYS or kind in ("profile", "preference"):
            return "pinned"
        if any(token in k for token in ("goal", "project", "task", "reminder", "deadline", "milestone")):
            return "workflows"
        if kind == "constraint":
            return "workflows"
        return "facts"

    def _slot_key_for_fact(self, key: str, kind: str) -> str:
        k = (key or "").lower()
        if k == "name":
            return "profile.name"
        if k == "favorite_drink":
            return "preferences.favorite_drink"
        if k in {"coding_style", "code_style"}:
            return "preferences.code_style"
        if kind in {"profile", "preference"}:
            return f"{kind}.{k}"
        return ""

    def _scope_for_fact(self, key: str, kind: str) -> str:
        k = (key or "").lower()
        if k in {"name", "preferred_name", "timezone", "default_location"}:
            return "profile"
        if kind in {"preference", "constraint"} or "favorite" in k or "code" in k:
            return "preferences"
        if any(t in k for t in ("goal", "project")):
            return "projects"
        if any(t in k for t in ("task", "reminder")):
            return "tasks"
        return "conversation"

    def _deterministic_capture(self, user_text: str) -> List[Dict[str, Any]]:
        t = (user_text or "").strip()
        tl = t.lower()
        out: List[Dict[str, Any]] = []

        m = re.search(r"\bmy\s+name\s+is\s+([a-zA-Z0-9 _'-]{1,40})", t, flags=re.IGNORECASE)
        if m:
            out.append({"entity": "user", "key": "name", "value": m.group(1).strip(), "kind": "profile", "confidence": 0.98})

        m = re.search(r"\bmy\s+favorite\s+drink\s+is\s+([a-zA-Z0-9 _'-]{1,48})", t, flags=re.IGNORECASE)
        if m:
            out.append({"entity": "user", "key": "favorite_drink", "value": m.group(1).strip(), "kind": "preference", "confidence": 0.97})

        if re.search(r"\b(from now on\s+)?when\s+i\s+ask\s+for\s+code", tl):
            out.append({"entity": "user", "key": "coding_style", "value": t[:120], "kind": "preference", "confidence": 0.92})

        remember_boost = 0.03 if ("remember this" in tl or tl.endswith("remember") or " remember" in tl) else 0.0
        for f in out:
            f["confidence"] = min(1.0, float(f.get("confidence", 0.8)) + remember_boost)
        return out

    async def _embed_safe(self, text: str) -> Optional[List[float]]:
        if not str(text or "").strip():
            return None
        try:
            return await self.embedder.embed(text)
        except EmbeddingUnavailable:
            return None
        except Exception as e:
            self._debug("embed fallback due to unexpected error: %s", e)
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
        scope = self._scope_for_fact(key, kind)
        slot_key = self._slot_key_for_fact(key, kind)
        importance = self._importance_for_fact(key, kind, bucket)
        conf = float(fact.get("confidence", 0.7) or 0.7)
        conf = max(0.0, min(1.0, conf))
        expires_at = None
        if kind == "volatile":
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=int(MEMORY_VOLATILE_TTL_HOURS))).isoformat()

        cur = self.store.active_by_slot(uid, slot_key) if slot_key else self.store.active_fact(uid, entity, key)
        if cur and str(cur.get("value", "")).strip().lower() == value.lower():
            return cur

        supersedes = None
        conflict_notice = None
        if cur:
            old_value = str(cur.get("value", "")).strip()
            self.store.set_status(str(cur.get("id")), "superseded")
            self.store.log_event(uid, "suppress", str(cur.get("id")), {"reason": "superseded", "slot_key": slot_key})
            supersedes = str(cur.get("id"))
            self._debug("superseded old %s", key)
            if key in CRITICAL_KEYS and old_value and old_value.lower() != value.lower():
                conflict_notice = f"Updated {key.replace('_', ' ')} from '{old_value}' to '{value}'."

        iid = hashlib.sha256(f"{entity}:{key}:{value}:{utcnow_iso()}".encode("utf-8")).hexdigest()
        item = {
            "id": iid,
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
            "tags": f"{lane} {kind} {key}",
            "confidence": conf,
            "status": "active",
            "expires_at": expires_at,
            "scope": scope,
            "mem_type": "preference" if kind == "preference" else "fact",
            "text": f"{key}: {value}",
            "entities_json": json.dumps({"key": key, "value": value}, ensure_ascii=False),
            "tags_json": json.dumps([lane, kind, key], ensure_ascii=False),
            "supersedes_id": supersedes,
            "contradicts_id": None,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "last_used_at": None,
            "slot_key": slot_key,
        }
        emb = await self._embed_safe(item["text"])
        self.store.write_item(item, embedding=emb)
        self.store.log_event(uid, "upsert", iid, {"scope": scope, "slot_key": slot_key, "key": key})
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
        text = (f"{trig} | " + " ; ".join(steps)).strip()[:2000]
        item = {
            "id": iid,
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
            "text": text,
            "tags": " ".join(tags),
            "confidence": max(0.0, min(1.0, float(skill.get("confidence", 0.7) or 0.7))),
            "status": "active",
            "expires_at": None,
            "scope": "skills",
            "mem_type": "skill",
            "entities_json": json.dumps({"trigger": trig, "steps": steps}, ensure_ascii=False),
            "tags_json": json.dumps(tags, ensure_ascii=False),
            "supersedes_id": None,
            "contradicts_id": None,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "last_used_at": None,
            "slot_key": None,
        }
        emb = await self._embed_safe(item["text"])
        self.store.write_item(item, embedding=emb)
        self.store.log_event(uid, "upsert", iid, {"scope": "skills", "key": "skill"})
        return item

    async def write_typed_memory(
        self,
        category: str,
        name: str,
        value: str,
        *,
        user_id: Optional[str] = None,
        status: str = "active",
        tags: Optional[List[str]] = None,
        confidence: float = 0.76,
    ) -> Dict[str, Any]:
        kind = str(category or "").strip().lower()
        scope = TYPED_SCOPE_MAP.get(kind)
        if not scope:
            raise ValueError(f"Unsupported typed memory category: {category}")
        uid = self._resolve_user_id(user_id)
        key = to_snake(str(name or "").strip()) or kind
        slot_key = f"{scope}.{key}"
        current = self.store.active_by_slot(uid, slot_key)
        if current:
            self.store.set_status(str(current.get("id")), "superseded")

        item_id = hashlib.sha256(f"{slot_key}:{utcnow_iso()}".encode("utf-8")).hexdigest()
        text = str(value or "").strip()[:1200]
        item = {
            "id": item_id,
            "user_id": uid,
            "lane": "identity" if kind == "user" else ("workflows" if kind == "project" else "evidence"),
            "type": "typed_memory",
            "entity": "knowledge",
            "mkey": key,
            "value": text[:220],
            "kind": kind,
            "bucket": "knowledge",
            "importance": 0.8 if kind == "project" else 0.74,
            "replaced_by": None,
            "text": text,
            "tags": " ".join([scope, kind] + [str(tag) for tag in list(tags or [])[:8]]),
            "confidence": max(0.0, min(1.0, float(confidence or 0.76))),
            "status": str(status or "active"),
            "expires_at": None,
            "scope": scope,
            "mem_type": "typed_memory",
            "entities_json": json.dumps({"category": kind, "name": name, "value": text}, ensure_ascii=False),
            "tags_json": json.dumps([scope, kind] + [str(tag) for tag in list(tags or [])[:8]], ensure_ascii=False),
            "supersedes_id": str(current.get("id")) if current else None,
            "contradicts_id": None,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "last_used_at": None,
            "slot_key": slot_key,
        }
        emb = await self._embed_safe(item["text"])
        self.store.write_item(item, embedding=emb)
        self.store.log_event(uid, "typed_upsert", item_id, {"scope": scope, "name": name})
        return item

    async def ingest_knowledge_text(
        self,
        *,
        title: str,
        text: str,
        user_id: Optional[str] = None,
        location: str = "",
        source_type: str = "note",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        return await self.vault.ingest_text(
            user_id=uid,
            title=title,
            text=text,
            location=location,
            source_type=source_type,
            metadata=metadata,
            tags=tags,
        )

    async def ingest_knowledge_file(
        self,
        path: str,
        *,
        user_id: Optional[str] = None,
        title: str = "",
        source_type: str = "document",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        return await self.vault.ingest_file(
            path,
            user_id=uid,
            title=title,
            source_type=source_type,
            metadata=metadata,
            tags=tags,
        )

    async def ingest_workspace_knowledge(
        self,
        path: str,
        *,
        user_id: Optional[str] = None,
        limit_files: int = 24,
    ) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        return await self.vault.ingest_workspace(path, user_id=uid, limit_files=limit_files)

    async def ingest_turn(self, user_text: str, assistant_text: str = "", tool_summaries: Optional[List[str]] = None, session_id: Optional[str] = None):
        uid = self._resolve_user_id(session_id=session_id)
        self.store.expire_items(utcnow_iso())
        det = self._deterministic_capture(user_text)
        base = heuristics(user_text, assistant_text)
        if det:
            merged = {"facts": (det + base.get("facts", []))[:8], "skills": base.get("skills", [])[:1]}
        elif should_call_llm(user_text, assistant_text):
            llm = await llm_extract(self.client, user_text, assistant_text, tool_summaries)
            merged = {"facts": (base.get("facts", []) + llm.get("facts", []))[:8], "skills": (base.get("skills", []) + llm.get("skills", []))[:1]}
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

        # session summary update (rolling history summary)
        self._turn_counts[uid] = int(self._turn_counts.get(uid, 0) or 0) + 1
        recent = self._recent_user_texts.setdefault(uid, [])
        t = str(user_text or "").strip()
        if t:
            recent.append(t[:220])
            if len(recent) > 20:
                del recent[:-20]
        history_for_summary: List[Dict[str, str]] = []
        for x in recent[-12:]:
            history_for_summary.append({"role": "user", "content": x})
        summary_created = await self.maybe_update_session_summary(uid, history_for_summary)

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

    def build_session_summary_context(self, user_id: Optional[str] = None) -> str:
        uid = self._resolve_user_id(user_id)
        row = self.store.latest_session_summary(uid)
        if not row:
            return ""
        txt = str(row.get("text") or "").strip()
        if not txt:
            return ""
        return "[Session Summary]\n- " + trim_summary_text(txt)

    async def maybe_update_session_summary(self, user_id: str, recent_history: List[Dict[str, str]]) -> bool:
        uid = self._resolve_user_id(user_id)
        if not bool(SUMMARY_ENABLED):
            return False

        turn_counter = int(self._turn_counts.get(uid, 0) or 0)
        last = int(self._last_summary_turn.get(uid, 0) or 0)
        if not should_update_summary(turn_counter, last):
            return False

        summary_text = build_summary_from_recent_turns(recent_history)
        if SUMMARY_USE_LLM and self.client is not None:
            try:
                raw_turns = "\n".join([f"{t.get('role','user')}: {t.get('content','')}" for t in recent_history[-12:]])
                prompt = (
                    "Summarize the active conversation thread in <= 8 bullets, concise and factual. "
                    "Focus on stable user goals/preferences and open tasks."
                    f"\n\nTurns:\n{raw_turns}"
                )
                async with _compat_asyncio_timeout(25.0):
                    resp = await self.client.chat(
                        model=SUMMARY_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0.0, "max_tokens": 220},
                    )
                candidate = str(resp.get("message", {}).get("content", "") or "").strip()
                if candidate:
                    summary_text = candidate
            except Exception:
                pass

        summary_text = trim_summary_text(summary_text)
        if not summary_text:
            return False

        # simple replace semantics: supersede previous active summary in-slot
        cur = self.store.active_by_slot(uid, "session.summary")
        if cur:
            self.store.set_status(str(cur.get("id")), "superseded")
            self.store.log_event(uid, "suppress", str(cur.get("id")), {"reason": "summary_refresh"})

        sid = hashlib.sha256(f"summary:{uid}:{utcnow_iso()}".encode("utf-8")).hexdigest()
        item = {
            "id": sid,
            "user_id": uid,
            "lane": "summary",
            "type": "summary",
            "entity": "user",
            "mkey": "session_summary",
            "value": summary_text[:220],
            "kind": "summary",
            "bucket": "ongoing_projects",
            "importance": 0.66,
            "replaced_by": None,
            "tags": "summary session recap",
            "confidence": 0.62,
            "status": "active",
            "expires_at": None,
            "scope": "session_summary",
            "mem_type": "summary",
            "text": summary_text,
            "entities_json": None,
            "tags_json": json.dumps(["summary", "session"], ensure_ascii=False),
            "supersedes_id": str(cur.get("id")) if cur else None,
            "contradicts_id": None,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "last_used_at": None,
            "slot_key": "session.summary",
        }
        emb = await self._embed_safe(item["text"])
        self.store.write_item(item, embedding=emb)
        self.store.log_event(uid, "upsert", sid, {"scope": "session_summary", "mem_type": "summary"})
        self._last_summary_turn[uid] = turn_counter
        return True

    def _active_goal_rows(self, user_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        ids = self.store.fts_search(str(user_id), "goal", limit=40)
        rows = self.store.get_items_by_ids(str(user_id), ids)
        goals = []
        for row in rows:
            if row.get("type") != "fact" or row.get("mkey") != "goal" or row.get("status") != "active":
                continue
            value = str(row.get("value") or "").strip()
            if not value or value.lower().startswith("retracted:"):
                continue
            goals.append({"title": value, "value": value, "updated_at": row.get("updated_at")})
        return goals[: max(1, int(limit))]

    def _operational_session_hits(self, query: str, user_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        q = str(query or "").strip()
        if len(q) < 8:
            return []
        ql = q.lower()
        if not any(marker in ql for marker in ("last week", "earlier", "previous", "decid", "discuss", "what did we", "before")):
            return []
        try:
            hits = self.session_search.search(q, user_id=str(user_id), limit=max(1, int(limit)))
        except Exception:
            return []
        return [
            {
                "text": f"{hit.source_kind}: {hit.snippet}",
                "source_kind": hit.source_kind,
                "created_at": hit.created_at,
            }
            for hit in hits[: max(1, int(limit))]
        ]

    def run_hygiene_check(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        uid = self._resolve_user_id(user_id)
        expired_count = int(self.store.expire_items(utcnow_iso()) or 0)
        snapshot = self.frozen_store.read_snapshot(uid) or {}
        issues = list(snapshot.get("scan_issues") or [])
        source_summary = self.vault.source_summary(uid)
        retrieval_trace = self.store.latest_retrieval_trace(uid) or {}
        review = self.build_memory_review_sync(uid, limit=4, review_window=64)
        return {
            "user_id": uid,
            "expired_count": expired_count,
            "scan_issue_count": len(issues),
            "scan_issues": issues[:5],
            "snapshot_present": bool(snapshot),
            "vault_source_count": int(source_summary.get("total_sources") or 0),
            "retrieval_trace_present": bool(retrieval_trace),
            "review_status": str(review.get("status") or "idle"),
            "review_alert_count": int(review.get("alert_count") or 0),
            "promotion_count": int(review.get("promotion_count") or 0),
            "conflict_count": int(review.get("conflict_count") or 0),
            "stale_count": int(review.get("stale_count") or 0),
        }

    async def build_injected_context(self, user_text: str, user_id: Optional[str] = None, thread_hint: str = "") -> str:
        uid = self._resolve_user_id(user_id)
        self.store.expire_items(utcnow_iso())
        query = str(user_text or "").strip()
        focus = infer_memory_focus(query, thread_hint=str(thread_hint or ""))

        scopes = [
            "profile",
            "preferences",
            "user_memory",
            "project_memory",
            "object_memory",
            "projects",
            "tasks",
            "conversation",
            "skills",
            "session_summary",
            "vault",
        ]
        fts_hits = self.store.fts_search_scored(uid, query, scopes=scopes, limit=30) if query else []

        vec_ids: List[str] = []
        if self.store.vec_enabled and USE_VECTOR_INDEX and query:
            try:
                qv = await self.embedder.embed(query)
                vec_ids = self.store.vec_search(qv, limit=30)
            except Exception:
                vec_ids = []

        fused_ids = rrf_fuse(fts_hits, vec_ids)
        candidates = self.store.get_items_by_ids(uid, fused_ids)
        fts_map = {iid: float(score or 0.0) for iid, score in fts_hits}
        vec_set = set(vec_ids)
        for item in candidates:
            item_id = str(item.get("id") or "")
            via: List[str] = []
            if item_id in fts_map:
                via.append("fts")
            if item_id in vec_set:
                via.append("vec")
            item["_retrieved_via"] = via or ["rrf"]
            item["_fts_score"] = float(fts_map.get(item_id, 0.0))
        ranked = rerank_items(candidates, query, thread_hint=str(thread_hint or ""))
        caps_by_scope = {
            "profile": 4,
            "preferences": 5,
            "user_memory": 3,
            "project_memory": 4,
            "object_memory": 4,
            "projects": 3,
            "tasks": 3,
            "conversation": 6,
            "skills": 3,
            "session_summary": 1,
            "vault": 4,
        }
        caps_by_lane = {
            "pinned": 5,
            "identity": 3,
            "workflows": 5,
            "skills": 3,
            "summary": 2,
            "evidence": 4,
            "vault": 4,
            "facts": 8,
        }
        if focus == "coding":
            caps_by_scope.update({"project_memory": 5, "skills": 4, "tasks": 4, "projects": 4, "vault": 2, "preferences": 3})
            caps_by_lane.update({"workflows": 6, "skills": 4, "facts": 6})
        elif focus == "reminders":
            caps_by_scope.update({"tasks": 5, "projects": 4, "conversation": 4, "vault": 2})
            caps_by_lane.update({"workflows": 6, "summary": 2, "facts": 5})
        elif focus == "planning":
            caps_by_scope.update({"projects": 5, "tasks": 4, "project_memory": 5, "conversation": 4, "profile": 3})
            caps_by_lane.update({"workflows": 6, "summary": 2, "facts": 5})
        elif focus == "personal":
            caps_by_scope.update({"profile": 5, "preferences": 6, "user_memory": 4, "conversation": 4, "vault": 2, "skills": 2})
            caps_by_lane.update({"pinned": 6, "identity": 4, "facts": 5})
        elif focus == "research":
            caps_by_scope.update({"vault": 5, "object_memory": 5, "project_memory": 4, "conversation": 4, "preferences": 3})
            caps_by_lane.update({"evidence": 5, "vault": 5, "facts": 5})
        filtered = apply_filters_and_caps(
            ranked,
            caps_by_scope=caps_by_scope,
            caps_by_lane=caps_by_lane,
        )
        profile_limit = 5 if focus == "personal" else 4
        pref_limit = 6 if focus == "personal" else (3 if focus == "research" else 5)
        user_limit = 4 if focus == "personal" else 3
        project_limit = 5 if focus in {"coding", "planning", "research"} else 4
        object_limit = 5 if focus == "research" else 4
        profile_rows = self.store.latest_by_scope(uid, "profile", limit=profile_limit)
        pref_rows = self.store.latest_by_scope(uid, "preferences", limit=pref_limit)
        user_rows = self.store.latest_by_scope(uid, "user_memory", limit=user_limit)
        project_rows = self.store.latest_by_scope(uid, "project_memory", limit=project_limit)
        object_rows = self.store.latest_by_scope(uid, "object_memory", limit=object_limit)
        summary = self.store.latest_session_summary(uid)
        summary_text = str((summary or {}).get("text") or "")
        goal_rows = self._active_goal_rows(uid, limit=4 if focus in {"planning", "reminders"} else 3)
        reminder_rows = self.store.active_reminders(uid, scope="task", limit=4 if focus == "reminders" else 3)
        operational_items = self._operational_session_hits(query, uid, limit=4 if focus in {"planning", "coding"} else 3)
        vault_rows = [item for item in filtered if str(item.get("scope") or "") == "vault"][: (5 if focus == "research" else 4)]
        vault_source_summary = self.vault.source_summary(uid)
        latest_sources = self.vault.list_sources(uid, limit=6)
        memory_review = self.build_memory_review_sync(uid, limit=6, review_window=96)

        block = build_injection_payload(
            profile_rows=profile_rows,
            pref_rows=pref_rows,
            session_summary=summary_text,
            relevant_items=filtered,
            goal_rows=goal_rows,
            reminder_rows=reminder_rows,
            operational_items=operational_items,
            user_rows=user_rows,
            project_rows=project_rows,
            object_rows=object_rows,
            vault_rows=vault_rows,
        )
        retrieval_trace = {
            "trace_id": "",
            "query": query[:240],
            "focus": focus,
            "scope_counts": self.store.scope_counts(uid, scopes=scopes),
            "fts_hit_count": len(fts_hits),
            "vector_hit_count": len(vec_ids),
            "session_hit_count": len(operational_items),
            "selected_items": [
                {
                    "id": str(item.get("id") or ""),
                    "scope": str(item.get("scope") or ""),
                    "mem_type": str(item.get("mem_type") or ""),
                    "retrieved_via": list(item.get("_retrieved_via") or []),
                    "fts_score": float(item.get("_fts_score") or 0.0),
                    "preview": str(item.get("text") or item.get("value") or "")[:180],
                }
                for item in filtered[:10]
            ],
            "vault_sources": [
                {
                    "source_id": str(row.get("source_id") or ""),
                    "title": str(row.get("title") or ""),
                    "source_type": str(row.get("source_type") or ""),
                    "location": str(row.get("location") or ""),
                }
                for row in latest_sources[:6]
            ],
        }
        trace_id = self.store.log_retrieval_trace(uid, query, retrieval_trace)
        retrieval_trace["trace_id"] = trace_id
        self.frozen_store.write_snapshot(
            uid,
            {
                "preference_graph": self.build_preference_graph_sync(uid, limit=12),
                "query": query[:240],
                "focus": focus,
                "profile_rows": profile_rows[:4],
                "preference_rows": pref_rows[:5],
                "user_rows": user_rows[:3],
                "project_rows": project_rows[:4],
                "object_rows": object_rows[:4],
                "goal_rows": goal_rows[:3],
                "reminder_rows": reminder_rows[:3],
                "operational_items": operational_items[:3],
                "vault_rows": vault_rows[:4],
                "vault_sources": latest_sources[:6],
                "vault_source_summary": vault_source_summary,
                "session_summary": summary_text[:400],
                "relevant_items": filtered[:8],
                "retrieval_trace_id": trace_id,
                "retrieval_trace": retrieval_trace,
                "memory_review": memory_review,
                "payload": block,
                "scan_issues": [],
            },
        )
        self._debug(
            "vec_enabled=%s fts=%d vec=%d selected=%d injected_chars=%d",
            self.store.vec_enabled,
            len(fts_hits),
            len(vec_ids),
            len(filtered),
            len(block),
        )
        return block

    async def memory_doctor(self, query: str, user_id: Optional[str] = None) -> str:
        uid = self._resolve_user_id(user_id)
        scopes = [
            "profile",
            "preferences",
            "user_memory",
            "project_memory",
            "object_memory",
            "projects",
            "tasks",
            "conversation",
            "skills",
            "session_summary",
            "vault",
        ]
        fts_hits = self.store.fts_search_scored(uid, query, scopes=scopes, limit=12)
        vec_hits: List[str] = []
        if self.store.vec_enabled and USE_VECTOR_INDEX:
            try:
                qv = await self.embedder.embed(query)
                vec_hits = self.store.vec_search(qv, limit=12)
            except Exception:
                vec_hits = []
        fused = rrf_fuse(fts_hits, vec_hits)
        preview = await self.build_injected_context(query, user_id=uid)
        events = self.store.recent_events(uid, limit=10)
        stats = self.store.db_stats(uid)
        retrieval_trace = self.store.latest_retrieval_trace(uid)
        source_summary = self.vault.source_summary(uid)
        latest_sources = self.vault.list_sources(uid, limit=5)
        review_summary = self.build_memory_review_sync(uid, limit=4, review_window=64)
        return memory_doctor_report(
            user_id=uid,
            query=query,
            vec_enabled=bool(self.store.vec_enabled and USE_VECTOR_INDEX),
            scopes=scopes,
            fts_hits=fts_hits,
            vec_hits=vec_hits,
            fused_ids=fused,
            injected_preview=preview,
            events=events,
            stats=stats,
            retrieval_trace=retrieval_trace,
            source_summary=source_summary,
            latest_sources=latest_sources,
            review_summary=review_summary,
        )

    # compatibility APIs used by agent
    async def retrieve_relevant_memories(self, query: str, user_id: str, min_score: float = 0.2, scope: str = "conversation", thread_hint: str = "") -> str:
        return await self.build_injected_context(query, user_id=user_id, thread_hint=thread_hint)

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

