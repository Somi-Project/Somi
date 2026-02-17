from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .graph import GraphExpander
from .retrieval import rank_claims
from .store import EventStore, SQLiteMemoryStore
from .utils import hash_text, is_volatile, normalize_embedding, tokenize, utcnow_iso

logger = logging.getLogger(__name__)

FORGET_PREFIXES = ("FORGET:", "FORGET ", "DO NOT USE:", "DONT USE:", "DON'T USE:")
VALID_TYPES = {"preferences", "facts", "instructions", "episodic"}
VALID_SCOPES = {"global", "profile", "task", "conversation", "vision"}


class MemoryManager:
    def __init__(
        self,
        embedding_model,
        ollama_client,
        memory_model_name: str,
        user_id: str = "default_user",
        base_dir: str = "sessions",
        disable_financial_memory: bool = True,
    ):
        self.embedding_model = embedding_model
        self.ollama_client = ollama_client
        self.memory_model = memory_model_name
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
        self._migration_marker = os.path.join(self.memory_dir, ".migration_v3_done")
        self._legacy_files = {
            "preferences": os.path.join(self.memory_dir, "preferences.jsonl"),
            "facts": os.path.join(self.memory_dir, "facts.jsonl"),
            "instructions": os.path.join(self.memory_dir, "instructions.jsonl"),
            "episodic": os.path.join(self.memory_dir, "episodic.jsonl"),
        }

        self.embedding_dim = 384
        try:
            self.embedding_dim = int(len(self.embedding_model.encode(["test"])[0]))
        except Exception:
            pass

        self._claim_embeddings: Dict[str, np.ndarray] = {}
        self._snapshot_lock = asyncio.Lock()
        self._snapshot_needs_save = False

        self._ephemeral = defaultdict(list)
        self._ephemeral_ttl_seconds = 120
        self._ephemeral_max_per_user = 25

        self.max_snapshot_items = 1000
        self.max_line_items_per_file = 4000
        self.episodic_ttl_days = 30
        self._load_snapshot()
        self._migrate_legacy_jsonl_if_needed()

    def _safe_append_jsonl(self, path: str, obj: Dict[str, Any]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def _read_jsonl_tail(self, path: str, max_lines: int = 400) -> List[Dict[str, Any]]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-max_lines:]
            out: List[Dict[str, Any]] = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def _migrate_legacy_jsonl_if_needed(self) -> None:
        if os.path.exists(self._migration_marker):
            return
        migrated = 0
        for mtype, path in self._legacy_files.items():
            for obj in self._read_jsonl_tail(path, max_lines=1200):
                content = str(obj.get("content", "") or "").strip()
                if not content:
                    continue
                uid = str(obj.get("user_id", self.user_id) or self.user_id)
                scope = self._normalize_scope(str(obj.get("scope", "conversation") or "conversation"))
                claim_id = hash_text(f"{uid}:{scope}:{mtype}:{content}")
                self.sql.upsert_claim(
                    claim_id=claim_id,
                    user_id=uid,
                    scope=scope,
                    memory_type=mtype,
                    content=content,
                    source=str(obj.get("source", "legacy_jsonl")),
                    status="active",
                    supersedes_claim_id=None,
                    confidence=0.55,
                    salience=0.45,
                )
                if claim_id not in self._claim_embeddings:
                    self._claim_embeddings[claim_id] = self._embed(content)
                migrated += 1
        if migrated:
            self._snapshot_needs_save = True
            try:
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
            except Exception:
                pass
        with open(self._migration_marker, "w", encoding="utf-8") as f:
            f.write(utcnow_iso())

    def _normalize_scope(self, scope: Optional[str]) -> str:
        s = (scope or "conversation").strip().lower()
        return s if s in VALID_SCOPES else "conversation"

    # ---------------- PATCHED: supports seconds ----------------
    def _parse_due_time(self, when: str) -> Optional[str]:
        raw = (when or "").strip().lower()
        if not raw:
            return None
        try:
            if "t" in raw and ":" in raw and len(raw) >= 16:
                return datetime.fromisoformat(raw.replace("z", "")).isoformat()
        except Exception:
            pass

        now = datetime.utcnow()
        parts = raw.split()
        if len(parts) == 3 and parts[0] == "in" and parts[1].isdigit():
            n = int(parts[1])
            unit = parts[2]
            if unit.startswith("sec"):
                return (now + timedelta(seconds=n)).isoformat()
            if unit.startswith("min"):
                return (now + timedelta(minutes=n)).isoformat()
            if unit.startswith("hour"):
                return (now + timedelta(hours=n)).isoformat()
            if unit.startswith("day"):
                return (now + timedelta(days=n)).isoformat()
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
        for c in self.sql.recent_claims(uid, scope, limit=100):
            if c.get("memory_type") != memory_type:
                continue
            prior_emb = self._claim_embeddings.get(c.get("claim_id", ""))
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
            with open(self.today_log_path, "a", encoding="utf-8") as f:
                f.write(f"**Timestamp:** {ts}\n**Scope:** {scope}\n**Type:** {memory_type}\n**Memory:** {content.strip()}\n\n---\n\n")
        except Exception:
            pass

        await self._save_snapshot()
        return True

    def _collect_forget_phrases(self, user_id: str, scope: str) -> List[str]:
        phrases: List[str] = []
        for c in self.sql.recent_claims(user_id, scope, limit=240):
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

        active_claims = self.sql.recent_claims(uid, scope, limit=260)
        if not active_claims and not staged:
            return {"context": None, "trace": {"reason": "no_claims", "scope": scope}}

        seed_rows: List[Tuple[float, str]] = []
        for c in active_claims:
            cid = c.get("claim_id", "")
            emb = self._claim_embeddings.get(cid)
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

        phrases = self._collect_forget_phrases(uid, scope)
        results: List[str] = []
        seen = set()
        kept_ranked: List[Dict[str, Any]] = []
        for s_item in staged:
            if s_item and s_item not in seen and not any(p in s_item.lower() for p in phrases):
                results.append(s_item[:220])
                seen.add(s_item)
        for r in ranked:
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
        return True

    async def supersede_claim(
        self,
        user_id: str,
        old_claim_id: str,
        new_content: str,
        memory_type: str = "facts",
        source: str = "supersede",
        scope: str = "conversation",
    ) -> bool:
        uid = str(user_id or self.user_id)
        old_cid = (old_claim_id or "").strip()
        scope = self._normalize_scope(scope)
        if not old_cid or not (new_content or "").strip():
            return False
        claim = self.sql.get_claim(uid, old_cid)
        if not claim or claim.get("scope") != scope:
            return False
        mtype = (memory_type or claim.get("memory_type", "facts") or "facts")
        ok = await self.store_memory(new_content, user_id=uid, memory_type=mtype, source=source, scope=scope)
        if not ok:
            return False
        new_cid = hash_text(f"{uid}:{scope}:{mtype.lower()}:{new_content.strip()}")
        self.sql.mark_superseded(old_cid, new_cid)
        event = {
            "event_id": hash_text(f"event:{utcnow_iso()}:{old_cid}:supersede"),
            "ts": utcnow_iso(),
            "user_id": uid,
            "scope": scope,
            "event_type": "claim_supersede",
            "claim_id": old_cid,
            "payload": {"by_claim_id": new_cid, "source": source},
        }
        self.events.append(event)
        return True

    async def list_recent_memories(self, user_id: str, limit: int = 20, scope: str = "conversation") -> List[Dict[str, Any]]:
        uid = str(user_id or self.user_id)
        scope = self._normalize_scope(scope)
        rows = self.sql.recent_claims(uid, scope, limit=max(1, int(limit)))
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
        rid = hash_text(f"reminder:{uid}:{scope}:{title}:{due_ts}")
        self.sql.add_reminder(rid, uid, scope, title.strip(), (details or "").strip(), due_ts, priority=int(priority))
        self.events.append(
            {
                "event_id": hash_text(f"event:{utcnow_iso()}:{rid}:reminder_create"),
                "ts": utcnow_iso(),
                "user_id": uid,
                "scope": scope,
                "event_type": "reminder_create",
                "claim_id": None,
                "payload": {"reminder_id": rid, "title": title.strip(), "due_ts": due_ts},
            }
        )
        return rid

    async def consume_due_reminders(self, user_id: str, limit: int = 3) -> List[Dict[str, str]]:
        uid = str(user_id or self.user_id)
        due = self.sql.due_reminders(uid, utcnow_iso(), limit=max(1, int(limit)))
        out: List[Dict[str, str]] = []
        for r in due:
            rid = str(r.get("reminder_id", ""))
            if not rid:
                continue
            self.sql.mark_reminder_fired(rid)
            out.append(
                {
                    "reminder_id": rid,
                    "title": str(r.get("title", "")),
                    "details": str(r.get("details", "")),
                    "due_ts": str(r.get("due_ts", "")),
                    "scope": str(r.get("scope", "task")),
                }
            )
            self.events.append(
                {
                    "event_id": hash_text(f"event:{utcnow_iso()}:{rid}:reminder_fire"),
                    "ts": utcnow_iso(),
                    "user_id": uid,
                    "scope": str(r.get("scope", "task")),
                    "event_type": "reminder_fire",
                    "claim_id": None,
                    "payload": {"reminder_id": rid, "title": str(r.get("title", ""))},
                }
            )
        return out

    async def ack_reminder(self, user_id: str, reminder_id: str, action: str = "done", snooze_minutes: int = 0) -> bool:
        uid = str(user_id or self.user_id)
        rid = (reminder_id or "").strip()
        if not rid:
            return False
        snooze_until = None
        if action == "snooze" and int(snooze_minutes) > 0:
            snooze_until = (datetime.utcnow() + timedelta(minutes=int(snooze_minutes))).isoformat()
        self.sql.ack_reminder(rid, action=action, snooze_until_ts=snooze_until)
        self.events.append(
            {
                "event_id": hash_text(f"event:{utcnow_iso()}:{rid}:reminder_ack"),
                "ts": utcnow_iso(),
                "user_id": uid,
                "scope": "task",
                "event_type": "reminder_ack",
                "claim_id": None,
                "payload": {"reminder_id": rid, "action": action, "snooze_until": snooze_until},
            }
        )
        return True

    # ---------------- NEW: list active reminders ----------------
    async def list_active_reminders(self, user_id: str, scope: str = "task", limit: int = 25) -> List[Dict[str, Any]]:
        uid = str(user_id or self.user_id)
        sc = self._normalize_scope(scope)
        try:
            return self.sql.active_reminders(uid, scope=sc, limit=max(1, int(limit)))
        except Exception:
            return []

    # ---------------- NEW: delete reminders by title ----------------
    async def delete_reminder_by_title(self, user_id: str, title: str, scope: str = "task") -> int:
        uid = str(user_id or self.user_id)
        sc = self._normalize_scope(scope)
        t = (title or "").strip()
        if not t:
            return 0
        try:
            n = int(self.sql.delete_reminder_by_title(uid, scope=sc, title=t) or 0)
        except Exception:
            n = 0
        if n > 0:
            self.events.append(
                {
                    "event_id": hash_text(f"event:{utcnow_iso()}:{uid}:{sc}:{hash_text(t)}:reminder_delete"),
                    "ts": utcnow_iso(),
                    "user_id": uid,
                    "scope": sc,
                    "event_type": "reminder_delete",
                    "claim_id": None,
                    "payload": {"title": t, "count": n},
                }
            )
        return n

    async def upsert_goal(
        self,
        user_id: str,
        title: str,
        objective: str = "",
        scope: str = "task",
        target_ts: Optional[str] = None,
        progress: float = 0.0,
        confidence: float = 0.6,
    ) -> str:
        uid = str(user_id or self.user_id)
        sc = self._normalize_scope(scope)
        gid = hash_text(f"goal:{uid}:{sc}:{title.strip()}")
        self.sql.upsert_goal(
            gid,
            uid,
            sc,
            title.strip(),
            objective.strip(),
            target_ts=target_ts,
            progress=progress,
            confidence=confidence,
        )
        self.events.append(
            {
                "event_id": hash_text(f"event:{utcnow_iso()}:{gid}:goal_upsert"),
                "ts": utcnow_iso(),
                "user_id": uid,
                "scope": sc,
                "event_type": "goal_upsert",
                "claim_id": None,
                "payload": {"goal_id": gid, "title": title.strip(), "progress": float(progress), "confidence": float(confidence)},
            }
        )
        return gid

    async def list_active_goals(self, user_id: str, scope: str = "task", limit: int = 6) -> List[Dict[str, Any]]:
        uid = str(user_id or self.user_id)
        return self.sql.active_goals(uid, scope=self._normalize_scope(scope), limit=max(1, int(limit)))

    async def build_goal_context(self, user_id: str, scope: str = "task", limit: int = 3) -> Optional[str]:
        goals = await self.list_active_goals(user_id, scope=scope, limit=limit)
        if not goals:
            return None
        lines = []
        for g in goals[:limit]:
            lines.append(
                f"- {g.get('title','Goal')} (progress {int(float(g.get('progress',0.0))*100)}%, confidence {float(g.get('confidence',0.6)):.2f})"
            )
        return "\n".join(lines)

    # ---------------- NEW: delete goal by title ----------------
    async def delete_goal_by_title(self, user_id: str, title: str, scope: str = "task") -> bool:
        uid = str(user_id or self.user_id)
        sc = self._normalize_scope(scope)
        t = (title or "").strip()
        if not t:
            return False
        try:
            deleted = bool(self.sql.delete_goal_by_title(uid, scope=sc, title=t))
        except Exception:
            deleted = False
        if deleted:
            self.events.append(
                {
                    "event_id": hash_text(f"event:{utcnow_iso()}:{uid}:{sc}:{hash_text(t)}:goal_delete"),
                    "ts": utcnow_iso(),
                    "user_id": uid,
                    "scope": sc,
                    "event_type": "goal_delete",
                    "claim_id": None,
                    "payload": {"title": t},
                }
            )
        return deleted

    async def curate_daily_digest(self) -> None:
        return

    async def prune_old_memories(self) -> None:
        await self._save_snapshot()
