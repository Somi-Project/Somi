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
        self.base_dir = base_dir
        self.disable_financial_memory = disable_financial_memory

        self.session_dir = os.path.join(self.base_dir, self.user_id)
        self.memory_dir = os.path.join(self.session_dir, "memory")
        os.makedirs(self.memory_dir, exist_ok=True)

        self.chronicle_path = os.path.join(self.session_dir, "chronicle.md")
        self.daily_logs_dir = os.path.join(self.session_dir, "daily_logs")
        os.makedirs(self.daily_logs_dir, exist_ok=True)
        self.today_log_path = os.path.join(self.daily_logs_dir, f"{date.today().isoformat()}.md")

        if not os.path.exists(self.chronicle_path):
            with open(self.chronicle_path, "w", encoding="utf-8") as f:
                f.write(f"# Somi Memory Chronicle (User: {self.user_id})\nStarted: {date.today().isoformat()}\n\n")
        if not os.path.exists(self.today_log_path):
            with open(self.today_log_path, "w", encoding="utf-8") as f:
                f.write(f"# Daily Interactions - {date.today().isoformat()}\n\n")

        self.events = EventStore(os.path.join(self.memory_dir, "events.jsonl"))
        self.sql = SQLiteMemoryStore(os.path.join(self.memory_dir, "memory.sqlite"))
        self.graph = GraphExpander(self.sql)
        self.snapshot_path = os.path.join(self.memory_dir, "snapshot_v3.json")
        self.markdown_ledger_path = os.path.join(self.memory_dir, "memory_ledger.md")
        self._migration_marker = os.path.join(self.memory_dir, ".migration_v3_done")
        self._legacy_files = {
            "preferences": os.path.join(self.memory_dir, "preferences.jsonl"),
            "facts": os.path.join(self.memory_dir, "facts.jsonl"),
            "instructions": os.path.join(self.memory_dir, "instructions.jsonl"),
            "episodic": os.path.join(self.memory_dir, "episodic.jsonl"),
        }

        self.embedding_dim = 384
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

        self.max_snapshot_items = 1000
        self.max_line_items_per_file = 4000
        self.episodic_ttl_days = 30
        self._ensure_markdown_ledger()
        self._load_snapshot()
        self._migrate_legacy_jsonl_if_needed()

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


    def _ensure_markdown_ledger(self) -> None:
        if os.path.exists(self.markdown_ledger_path):
            return
        with open(self.markdown_ledger_path, "w", encoding="utf-8") as f:
            f.write("# Memory Ledger (append-only)\n\n")

    def _append_markdown_ledger(self, row: Dict[str, Any]) -> None:
        self._ensure_markdown_ledger()
        with open(self.markdown_ledger_path, "a", encoding="utf-8") as f:
            f.write(f"- {json.dumps(row, ensure_ascii=False)}\n")

    def _read_markdown_ledger_tail(self, max_lines: int = 2400) -> List[Dict[str, Any]]:
        if not os.path.exists(self.markdown_ledger_path):
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(self.markdown_ledger_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-max_lines:]
            for raw in lines:
                line = raw.strip()
                if not line.startswith("- {"):
                    continue
                payload = line[2:].strip()
                try:
                    obj = json.loads(payload)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
        except Exception:
            return []
        return out

    def _recent_claims_fallback(self, user_id: str, scope: str, limit: int = 240) -> List[Dict[str, Any]]:
        rows = self.sql.recent_claims(user_id, scope, limit=limit)
        if rows:
            return rows

        latest: Dict[str, Dict[str, Any]] = {}
        for ev in self._read_markdown_ledger_tail(max_lines=3600):
            if str(ev.get("user_id", "")) != user_id:
                continue
            if str(ev.get("scope", "conversation")) != scope:
                continue
            et = str(ev.get("event_type", ""))
            cid = str(ev.get("claim_id", ""))
            if not cid:
                continue
            if et == "claim_upsert":
                latest[cid] = {
                    "claim_id": cid,
                    "content": str(ev.get("content", "")),
                    "memory_type": str(ev.get("memory_type", "facts")),
                    "scope": scope,
                    "status": "active",
                    "supersedes_claim_id": ev.get("supersedes_claim_id"),
                    "superseded_by_claim_id": None,
                    "contradiction_with_claim_id": ev.get("contradiction_with_claim_id"),
                    "confidence": float(ev.get("confidence", 0.6) or 0.6),
                    "ts_updated": str(ev.get("ts", "")),
                    "salience": float(ev.get("salience", 0.5) or 0.5),
                }
            elif et == "claim_status":
                st = str(ev.get("status", "")).strip().lower()
                if cid in latest and st:
                    latest[cid]["status"] = st
                    latest[cid]["ts_updated"] = str(ev.get("ts", latest[cid].get("ts_updated", "")))

        active = [r for r in latest.values() if r.get("status") == "active" and r.get("content")]
        active.sort(key=lambda x: str(x.get("ts_updated", "")), reverse=True)
        return active[: max(1, int(limit))]

    def _normalize_scope(self, scope: Optional[str]) -> str:
        s = (scope or "conversation").strip().lower()
        return s if s in VALID_SCOPES else "conversation"

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
                return (now + timedelta(days=1)).isoformat()

        if raw in ("in half an hour", "in half hour"):
            return (now + timedelta(minutes=30)).isoformat()

        return None

    def _is_negated(self, text: str) -> bool:
        t = (text or "").lower()
        return any(k in t for k in (" not ", "don't", "dont", "never", "dislike", "hate", "no longer"))

    def _zero_vec(self) -> np.ndarray:
        return np.zeros((self.embedding_dim,), dtype=np.float32)

    def _embed(self, text: str) -> np.ndarray:
        try:
            raw = self.embedding_model.encode([text])[0]
            norm = normalize_embedding(raw)
            if norm is not None and len(norm) == self.embedding_dim:
                return norm.astype(np.float32)
        except Exception:
            pass
        return self._zero_vec()

    def _extract_semantic_slots(self, text: str) -> Dict[str, str]:
        low = (text or "").strip().lower()
        if not low:
            return {}

        out: Dict[str, str] = {}
        beverage_terms = {
            "coffee",
            "latte",
            "espresso",
            "tea",
            "matcha",
            "cappuccino",
            "juice",
            "soda",
            "water",
            "milk",
            "beer",
            "wine",
        }

        fav = re.search(r"\bmy\s+favorite\s+([a-z][a-z0-9 _-]{1,28})\s+is\s+([a-z0-9][a-z0-9 ':-]{1,40})", low)
        if fav:
            category = fav.group(1).strip()
            value = fav.group(2).strip(" .!?\"'")
            out[f"favorite:{category}"] = value

        like = re.search(r"\bi\s+(?:really\s+)?(love|like|prefer)\s+([a-z0-9][a-z0-9 ':-]{1,40})", low)
        if like:
            obj = like.group(2).strip(" .!?\"'")
            head = obj.split()[0]
            out[f"stance:{obj}"] = "like"
            if head in beverage_terms and "favorite:drink" not in out:
                out["favorite:drink"] = obj

        dislike = re.search(r"\bi\s+(?:really\s+)?(hate|dislike)\s+([a-z0-9][a-z0-9 ':-]{1,40})", low)
        if dislike:
            obj = dislike.group(2).strip(" .!?\"'")
            out[f"stance:{obj}"] = "dislike"

        return out

    def _extract_query_slot_keys(self, text: str) -> List[str]:
        low = (text or "").strip().lower()
        if not low:
            return []
        keys: List[str] = []
        for m in re.finditer(r"\b(?:my|your)\s+favorite\s+([a-z][a-z0-9 _-]{1,28})", low):
            keys.append(f"favorite:{m.group(1).strip()}")
        if any(x in low for x in ("favorite drink", "favorite beverage")):
            keys.append("favorite:drink")
        if any(x in low for x in ("what do i like", "what's my preference", "what are my preferences")):
            keys.append("__likes_intent__")
        return keys

    def _ensure_embedding_for_claim(self, claim: Dict[str, Any]) -> Optional[np.ndarray]:
        cid = str(claim.get("claim_id", "") or "")
        if not cid:
            return None
        emb = self._claim_embeddings.get(cid)
        if emb is not None:
            return emb
        content = str(claim.get("content", "") or "").strip()
        if not content:
            return None
        emb = self._embed(content)
        self._claim_embeddings[cid] = emb
        self._snapshot_needs_save = True
        return emb

    def _load_snapshot(self) -> None:
        if not os.path.exists(self.snapshot_path):
            return
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if int(data.get("dim", 0) or 0) != self.embedding_dim:
                return
            for row in data.get("claims", []):
                cid = str(row.get("claim_id", ""))
                emb = np.asarray(row.get("embedding", []), dtype=np.float32)
                if cid and emb.ndim == 1 and len(emb) == self.embedding_dim:
                    self._claim_embeddings[cid] = emb
        except Exception:
            logger.warning("[Memory] Failed loading snapshot_v3.json", exc_info=True)

    async def _save_snapshot(self) -> None:
        async with self._snapshot_lock:
            if not self._snapshot_needs_save:
                return
            payload = {
                "version": 3,
                "updated": utcnow_iso(),
                "dim": self.embedding_dim,
                "claims": [
                    {"claim_id": cid, "embedding": emb.tolist() if hasattr(emb, "tolist") else list(emb)}
                    for cid, emb in list(self._claim_embeddings.items())[-self.max_snapshot_items:]
                ],
            }
            tmp = self.snapshot_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.snapshot_path)
            self._snapshot_needs_save = False

    def _purge_ephemeral(self, user_id: str) -> None:
        now = time.time()
        items = [x for x in self._ephemeral.get(user_id, []) if now - x["ts"] <= self._ephemeral_ttl_seconds]
        self._ephemeral[user_id] = items[-self._ephemeral_max_per_user:]

    def stage_memory(self, user_id: str, memory_type: str, content: str, source: str = "staged", scope: str = "conversation") -> None:
        if not content:
            return
        uid = str(user_id or self.user_id)
        self._purge_ephemeral(uid)
        self._ephemeral[uid].append(
            {
                "content": content.strip(),
                "memory_type": (memory_type or "facts").strip().lower(),
                "source": source,
                "scope": self._normalize_scope(scope),
                "ts": time.time(),
                "tokens": list(tokenize(content)),
            }
        )
        if len(self._ephemeral[uid]) > self._ephemeral_max_per_user:
            self._ephemeral[uid] = self._ephemeral[uid][-self._ephemeral_max_per_user :]

    def _ephemeral_matches(self, user_id: str, query: str, scope: str, top_k: int = 3) -> List[str]:
        uid = str(user_id or self.user_id)
        self._purge_ephemeral(uid)
        qt = tokenize(query)
        scored: List[Tuple[float, str]] = []
        for it in self._ephemeral.get(uid, []):
            if it.get("scope") != scope:
                continue
            ct = set(it.get("tokens", []))
            overlap = len(qt.intersection(ct)) / max(1, len(qt))
            if overlap > 0.15:
                scored.append((overlap, it.get("content", "")))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k] if c]

    async def should_store_memory(self, input_text: str, output_text: str, user_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        text = (input_text or "").strip()
        if len(text.split()) < 2:
            return False, None, None
        if self.disable_financial_memory and is_volatile(text):
            return False, None, None
        prompt = (
            "Classify if user message should be stored as stable memory. "
            "Output ONLY JSON: {\"should_store\":bool,\"memory_type\":\"preferences|facts|instructions|episodic\",\"content\":string|null}. "
            "Do not store volatile data. "
            f"User message: {text}"
        )
        try:
            async with asyncio.timeout(8.0):
                resp = await self.ollama_client.chat(
                    model=self.memory_model,
                    messages=[{"role": "user", "content": prompt}],
                    format="json",
                    options={"temperature": 0.0, "max_tokens": 140},
                )
            data = json.loads(resp.get("message", {}).get("content", "") or "{}")
            if not bool(data.get("should_store")):
                return False, None, None
            mtype = str(data.get("memory_type", "facts")).strip().lower()
            if mtype not in VALID_TYPES:
                mtype = "facts"
            content = str(data.get("content", "")).strip()
            if len(content) < 6:
                return False, None, None
            if self.disable_financial_memory and is_volatile(content):
                return False, None, None
            return True, mtype, content
        except Exception:
            return False, None, None

    async def store_memory(
        self,
        content: str,
        user_id: str,
        memory_type: str = "facts",
        source: str = "memory",
        scope: str = "conversation",
        salience: float = 0.5,
    ) -> bool:
        if not content:
            return False
        memory_type = (memory_type or "facts").lower()
        if memory_type not in VALID_TYPES:
            memory_type = "facts"
        scope = self._normalize_scope(scope)
        uid = str(user_id or self.user_id)
        if self.disable_financial_memory and is_volatile(content):
            return False

        ts = utcnow_iso()
        claim_id = hash_text(f"{uid}:{scope}:{memory_type}:{content.strip()}")
        emb = self._embed(content)

        try:
            self._safe_append_jsonl(
                self._legacy_files.get(memory_type, self._legacy_files["facts"]),
                {
                    "ts": ts,
                    "user_id": uid,
                    "scope": scope,
                    "type": memory_type,
                    "content": content.strip(),
                    "source": source,
                    "claim_id": claim_id,
                },
            )
        except Exception:
            pass

        superseded_target = None
        contradiction_with = None
        confidence = 0.82
        content_neg = self._is_negated(content)
        slots = self._extract_semantic_slots(content)
        for c in self._recent_claims_fallback(uid, scope, limit=100):
            if c.get("memory_type") != memory_type:
                continue
            prior_emb = self._ensure_embedding_for_claim(c)
            if prior_emb is None:
                continue
            sim = float(np.dot(prior_emb, emb))
            if sim > 0.92 and c.get("claim_id") != claim_id:
                superseded_target = c.get("claim_id")
                break
            if sim > 0.86 and c.get("claim_id") != claim_id:
                if self._is_negated(c.get("content", "")) != content_neg:
                    contradiction_with = c.get("claim_id")
                    confidence = 0.45
            if slots and c.get("claim_id") != claim_id:
                prior_slots = self._extract_semantic_slots(str(c.get("content", "")))
                for key, val in slots.items():
                    old_val = prior_slots.get(key)
                    if old_val and old_val != val:
                        superseded_target = c.get("claim_id")
                        contradiction_with = c.get("claim_id")
                        confidence = 0.66
                        break
                if superseded_target:
                    break

        self.sql.upsert_claim(
            claim_id=claim_id,
            user_id=uid,
            scope=scope,
            memory_type=memory_type,
            content=content.strip(),
            source=source,
            status="active",
            supersedes_claim_id=superseded_target,
            contradiction_with_claim_id=contradiction_with,
            confidence=confidence,
            salience=salience,
        )
        if superseded_target:
            self.sql.mark_superseded(superseded_target, claim_id)

        self._claim_embeddings[claim_id] = emb
        self._snapshot_needs_save = True

        claim_node_id = f"claim:{claim_id}"
        self.sql.add_node(claim_node_id, uid, scope, "claim", content.strip(), {"memory_type": memory_type})
        for tok in list(tokenize(content))[:12]:
            tnode = f"token:{hash_text(tok)[:16]}"
            self.sql.add_node(tnode, uid, scope, "token", tok)
            self.sql.add_edge(uid, scope, claim_node_id, tnode, "has_token", weight=0.6)
            self.sql.add_edge(uid, scope, tnode, claim_node_id, "token_of", weight=0.6)
        for key, val in slots.items():
            snode = f"slot:{hash_text(key)[:16]}"
            vnode = f"slotval:{hash_text(f'{key}:{val}')[:16]}"
            self.sql.add_node(snode, uid, scope, "slot", key)
            self.sql.add_node(vnode, uid, scope, "slot_value", val, {"slot_key": key})
            self.sql.add_edge(uid, scope, claim_node_id, snode, "about_slot", weight=0.92)
            self.sql.add_edge(uid, scope, claim_node_id, vnode, "has_slot_value", weight=0.95)
            self.sql.add_edge(uid, scope, snode, claim_node_id, "slot_of", weight=0.85)

        event = {
            "event_id": hash_text(f"event:{ts}:{claim_id}:{source}"),
            "ts": ts,
            "user_id": uid,
            "scope": scope,
            "event_type": "claim_upsert",
            "claim_id": claim_id,
            "payload": {
                "memory_type": memory_type,
                "content": content.strip(),
                "source": source,
                "supersedes_claim_id": superseded_target,
                "contradiction_with_claim_id": contradiction_with,
                "confidence": confidence,
            },
        }
        self.events.append(event)
        try:
            self._append_markdown_ledger(
                {
                    "ts": ts,
                    "event_type": "claim_upsert",
                    "claim_id": claim_id,
                    "user_id": uid,
                    "scope": scope,
                    "memory_type": memory_type,
                    "content": content.strip(),
                    "source": source,
                    "salience": float(salience),
                    "confidence": float(confidence),
                    "supersedes_claim_id": superseded_target,
                    "contradiction_with_claim_id": contradiction_with,
                }
            )
            if superseded_target:
                self._append_markdown_ledger(
                    {
                        "ts": ts,
                        "event_type": "claim_status",
                        "claim_id": superseded_target,
                        "user_id": uid,
                        "scope": scope,
                        "status": "superseded",
                    }
                )
        except Exception:
            pass

        try:
            with open(self.today_log_path, "a", encoding="utf-8") as f:
                f.write(f"**Timestamp:** {ts}\n**Scope:** {scope}\n**Type:** {memory_type}\n**Memory:** {content.strip()}\n\n---\n\n")
        except Exception:
            pass

        await self._save_snapshot()
        return True

    def _collect_forget_phrases(self, user_id: str, scope: str) -> List[str]:
        phrases: List[str] = []
        for c in self._recent_claims_fallback(user_id, scope, limit=240):
            if c.get("memory_type") != "instructions":
                continue
            text = (c.get("content") or "").strip()
            up = text.upper()
            if any(up.startswith(p) for p in FORGET_PREFIXES):
                phrase = text.split(":", 1)[1].strip() if ":" in text else text
                phrase = phrase.lower().strip()
                if phrase and phrase not in phrases:
                    phrases.append(phrase)
        return phrases

    async def retrieve_relevant_memories_with_trace(
        self, query: str, user_id: str, min_score: float = 0.20, scope: str = "conversation"
    ) -> Dict[str, Any]:
        uid = str(user_id or self.user_id)
        scope = self._normalize_scope(scope)
        q = (query or "").strip()
        if not q:
            return {"context": None, "trace": {"reason": "empty_query"}}

        staged = self._ephemeral_matches(uid, q, scope=scope, top_k=3)
        q_emb = self._embed(q)
        query_slot_keys = self._extract_query_slot_keys(q)

        active_claims = self._recent_claims_fallback(uid, scope, limit=260)
        if not active_claims and not staged:
            return {"context": None, "trace": {"reason": "no_claims", "scope": scope}}

        seed_rows: List[Tuple[float, str]] = []
        for c in active_claims:
            cid = c.get("claim_id", "")
            emb = self._ensure_embedding_for_claim(c)
            if emb is None:
                continue
            sim = float(np.dot(emb, q_emb))
            if sim >= min_score:
                seed_rows.append((sim, cid))
        seed_rows.sort(key=lambda x: x[0], reverse=True)
        seed_node_ids = [f"claim:{cid}" for _, cid in seed_rows[:8]]

        expanded_node_ids = self.graph.expand(uid, scope, seed_node_ids, hops=1 if len(seed_node_ids) >= 3 else 2)
        expanded_claim_ids = [n.split(":", 1)[1] for n in expanded_node_ids if n.startswith("claim:")]
        if expanded_claim_ids:
            by_id = {c.get("claim_id"): c for c in active_claims}
            candidates = [by_id[cid] for cid in expanded_claim_ids if cid in by_id]
        else:
            candidates = active_claims

        ranked = rank_claims(q_emb, candidates, self._claim_embeddings, min_score=min_score, limit=6)
        semantic_hits: List[Dict[str, Any]] = []
        if query_slot_keys:
            likes_intent = "__likes_intent__" in query_slot_keys
            explicit_keys = [k for k in query_slot_keys if not k.startswith("__")]
            for c in active_claims:
                slots = self._extract_semantic_slots(str(c.get("content", "")))
                hit = any(k in slots for k in explicit_keys)
                if not hit and likes_intent:
                    hit = any(k.startswith("stance:") and v == "like" for k, v in slots.items())
                if hit:
                    row = dict(c)
                    row["rank_score"] = 1.05
                    semantic_hits.append(row)

        phrases = self._collect_forget_phrases(uid, scope)
        results: List[str] = []
        seen = set()
        kept_ranked: List[Dict[str, Any]] = []
        for s_item in staged:
            if s_item and s_item not in seen and not any(p in s_item.lower() for p in phrases):
                results.append(s_item[:220])
                seen.add(s_item)
        for r in semantic_hits + ranked:
            c = (r.get("content") or "").strip()
            if c and c not in seen and not any(p in c.lower() for p in phrases):
                results.append(c[:220])
                seen.add(c)
                kept_ranked.append(
                    {
                        "claim_id": r.get("claim_id", ""),
                        "score": float(r.get("rank_score", 0.0)),
                        "sim": float(r.get("sim", 0.0)),
                        "memory_type": r.get("memory_type", "facts"),
                        "scope": r.get("scope", scope),
                    }
                )
            if len(results) >= 6:
                break

        context = "\n".join([f"- {x}" for x in results[:6]]) if results else None
        return {
            "context": context,
            "trace": {
                "scope": scope,
                "seed_count": len(seed_node_ids),
                "expanded_node_count": len(expanded_node_ids),
                "candidate_count": len(candidates),
                "staged_hits": len(staged),
                "ranked_kept": kept_ranked,
                "forget_filters": len(phrases),
            },
        }

    async def retrieve_relevant_memories(self, query: str, user_id: str, min_score: float = 0.20, scope: str = "conversation") -> Optional[str]:
        out = await self.retrieve_relevant_memories_with_trace(query, user_id, min_score=min_score, scope=scope)
        return out.get("context")

    async def retract_claim(self, user_id: str, claim_id: str, source: str = "retract", scope: str = "conversation") -> bool:
        uid = str(user_id or self.user_id)
        cid = (claim_id or "").strip()
        if not cid:
            return False
        scope = self._normalize_scope(scope)
        claim = self.sql.get_claim(uid, cid)
        if not claim or claim.get("scope") != scope:
            return False
        self.sql.set_claim_status(cid, "retracted")
        event = {
            "event_id": hash_text(f"event:{utcnow_iso()}:{cid}:retract"),
            "ts": utcnow_iso(),
            "user_id": uid,
            "scope": scope,
            "event_type": "claim_retract",
            "claim_id": cid,
            "payload": {"source": source},
        }
        self.events.append(event)
        try:
            self._append_markdown_ledger(
                {
                    "ts": event["ts"],
                    "event_type": "claim_status",
                    "claim_id": cid,
                    "user_id": uid,
                    "scope": scope,
                    "status": "retracted",
                    "source": source,
                }
            )
        except Exception:
            pass
        return True

        return None

    async def list_recent_memories(self, user_id: str, limit: int = 20, scope: str = "conversation") -> List[Dict[str, Any]]:
        uid = str(user_id or self.user_id)
        scope = self._normalize_scope(scope)
        rows = self._recent_claims_fallback(uid, scope, limit=max(1, int(limit)))
        return [
            {
                "ts": r.get("ts_updated", ""),
                "type": r.get("memory_type", "facts"),
                "content": r.get("content", ""),
                "hash": r.get("claim_id", ""),
                "scope": scope,
            }
            for r in rows
        ]

    async def pin_instruction(self, user_id: str, instruction: str, source: str = "pin", scope: str = "conversation") -> bool:
        ins = (instruction or "").strip()
        if not ins:
            return False
        return await self.store_memory(ins, str(user_id or self.user_id), "instructions", source=source, scope=scope, salience=0.9)

    async def forget_phrase(self, user_id: str, phrase: str, source: str = "forget", scope: str = "conversation") -> bool:
        p = (phrase or "").strip()
        if not p:
            return False
        return await self.store_memory(f"FORGET: {p}", str(user_id or self.user_id), "instructions", source=source, scope=scope, salience=0.95)

    async def add_reminder(self, user_id: str, title: str, when: str, details: str = "", scope: str = "task", priority: int = 3) -> Optional[str]:
        uid = str(user_id or self.user_id)
        scope = self._normalize_scope(scope)
        due_ts = self._parse_due_time(when)
        if not due_ts:
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
