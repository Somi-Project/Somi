# memory.py
# Crash-resistant memory system for Somi:
# - JSONL per category (append-only)
# - Snapshot index for fast retrieval (items + embeddings)
# - Same-turn recall staging (RAM buffer)
# - LLM categorization (MEMORY_MODEL) with strict JSON
#
# Upgrades (Feb 2026):
# - Snapshot rebuild from JSONL tail when snapshot missing/empty or embedding mismatch
# - Zero-vector embeddings to keep snapshot alignment safe
# - "Forget tombstones" enforced at retrieval time
# - Telegram support methods: list_recent_memories, pin_instruction, forget_phrase

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


VOLATILE_KEYWORDS = [
    "price", "stock", "bitcoin", "crypto", "ethereum", "solana", "market",
    "weather", "forecast", "current time", "today", "breaking", "news", "scores",
    "live", "now", "latest"
]

FORGET_PREFIXES = ("FORGET:", "FORGET ", "DO NOT USE:", "DONT USE:", "DON'T USE:")


@dataclass
class MemoryItem:
    ts: str
    content: str
    memory_type: str
    source: str
    hash: str


class MemoryManager:
    """
    Memory categories (files):
      - preferences.jsonl
      - facts.jsonl
      - instructions.jsonl
      - episodic.jsonl (short-lived)
    Plus:
      - snapshot.json (compact, latest top-N items + embeddings)

    Retrieval:
      - same-turn RAM staging first
      - then snapshot vector similarity
      - then keyword fallback
      - then "forget tombstone" filtering
    """

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

        # Storage paths
        self.session_dir = os.path.join(self.base_dir, self.user_id)
        self.memory_dir = os.path.join(self.session_dir, "memory")
        os.makedirs(self.memory_dir, exist_ok=True)

        self.files = {
            "preferences": os.path.join(self.memory_dir, "preferences.jsonl"),
            "facts": os.path.join(self.memory_dir, "facts.jsonl"),
            "instructions": os.path.join(self.memory_dir, "instructions.jsonl"),
            "episodic": os.path.join(self.memory_dir, "episodic.jsonl"),
        }

        self.snapshot_path = os.path.join(self.memory_dir, "snapshot.json")
        self.chronicle_path = os.path.join(self.session_dir, "chronicle.md")
        self.daily_logs_dir = os.path.join(self.session_dir, "daily_logs")
        os.makedirs(self.daily_logs_dir, exist_ok=True)
        self.today_log_path = os.path.join(self.daily_logs_dir, f"{date.today().isoformat()}.md")

        if not os.path.exists(self.chronicle_path):
            with open(self.chronicle_path, "w", encoding="utf-8") as f:
                f.write(f"# Somi Memory Chronicle (User: {self.user_id})\n")
                f.write(f"Started: {date.today().isoformat()}\n\n")

        if not os.path.exists(self.today_log_path):
            with open(self.today_log_path, "w", encoding="utf-8") as f:
                f.write(f"# Daily Interactions - {date.today().isoformat()}\n\n")

        # Embedding dimension detection
        self.embedding_dim = 384
        try:
            test_emb = self.embedding_model.encode(["test"])[0]
            self.embedding_dim = int(len(test_emb))
        except Exception:
            self.embedding_dim = 384

        # Snapshot state
        self._snapshot_items: List[Dict[str, Any]] = []
        self._snapshot_embs: Optional[np.ndarray] = None  # shape (N, dim)
        self._snapshot_lock = asyncio.Lock()
        self._snapshot_needs_save = False

        # Same-turn recall buffer
        self._ephemeral = defaultdict(list)  # user_id -> list[dict]
        self._ephemeral_ttl_seconds = 120
        self._ephemeral_max_per_user = 25

        # Maintenance knobs
        self.max_snapshot_items = 800
        self.max_line_items_per_file = 4000
        self.episodic_ttl_days = 30

        # Load snapshot; rebuild if empty/mismatched
        loaded_ok = self._load_snapshot()
        if not loaded_ok or not self._snapshot_items:
            self._rebuild_snapshot_from_jsonl_tail()
        else:
            # Even if snapshot exists, ensure dims/alignment remain sane
            self._ensure_snapshot_alignment()

    # -------------------------
    # Utility / safety helpers
    # -------------------------

    def _atomic_write_json(self, path: str, data: Any) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def _safe_append_jsonl(self, path: str, obj: Dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _normalize_embedding(self, vec: np.ndarray) -> Optional[np.ndarray]:
        v = np.asarray(vec, dtype=np.float32)
        v = np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)
        n = float(np.linalg.norm(v))
        if n <= 1e-10:
            return None
        return v / n

    def _hash(self, s: str) -> str:
        return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()

    def _is_volatile(self, text: str) -> bool:
        t = (text or "").lower()
        return any(k in t for k in VOLATILE_KEYWORDS)

    def _tokenize(self, text: str) -> set[str]:
        text = (text or "").lower()
        text = re.sub(r"[^a-z0-9\s:]+", " ", text)
        toks = [t for t in text.split() if len(t) > 1]
        return set(toks[:64])

    def _zero_vec(self) -> np.ndarray:
        v = np.zeros((self.embedding_dim,), dtype=np.float32)
        return v

    # -------------------------
    # Snapshot load/save/rebuild
    # -------------------------

    def _load_snapshot(self) -> bool:
        if not os.path.exists(self.snapshot_path):
            self._snapshot_items = []
            self._snapshot_embs = None
            return False

        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            items = data.get("items", [])
            embs = data.get("embeddings", [])
            dim = int(data.get("dim", 0) or 0)

            if not isinstance(items, list):
                items = []
            if not isinstance(embs, list):
                embs = []

            # If embedding dim changed, rebuild from JSONL tail
            if dim and dim != self.embedding_dim:
                logger.warning(f"[Memory] Snapshot dim {dim} != current dim {self.embedding_dim}. Rebuilding.")
                self._snapshot_items = []
                self._snapshot_embs = None
                return False

            self._snapshot_items = items

            if embs:
                arr = np.asarray(embs, dtype=np.float32)
                if arr.ndim == 2 and arr.shape[1] == self.embedding_dim:
                    self._snapshot_embs = arr
                else:
                    self._snapshot_embs = None
            else:
                self._snapshot_embs = None

            return True
        except Exception as e:
            logger.warning(f"[Memory] Snapshot load failed: {e}")
            self._snapshot_items = []
            self._snapshot_embs = None
            return False

    def _ensure_snapshot_alignment(self) -> None:
        """
        Guarantees that:
        - _snapshot_embs exists
        - shape[0] == len(_snapshot_items)
        - each row is a usable vector (zero vec allowed)
        """
        n = len(self._snapshot_items)
        if n <= 0:
            self._snapshot_embs = None
            return

        if not isinstance(self._snapshot_embs, np.ndarray) or self._snapshot_embs.ndim != 2:
            self._snapshot_embs = np.vstack([self._zero_vec() for _ in range(n)]).astype(np.float32)
            self._snapshot_needs_save = True
            return

        if self._snapshot_embs.shape[1] != self.embedding_dim:
            self._snapshot_embs = np.vstack([self._zero_vec() for _ in range(n)]).astype(np.float32)
            self._snapshot_needs_save = True
            return

        if self._snapshot_embs.shape[0] != n:
            # Fix by truncating/padding with zero vecs
            if self._snapshot_embs.shape[0] > n:
                self._snapshot_embs = self._snapshot_embs[-n:, :]
            else:
                missing = n - self._snapshot_embs.shape[0]
                pad = np.vstack([self._zero_vec() for _ in range(missing)]).astype(np.float32)
                self._snapshot_embs = np.vstack([self._snapshot_embs, pad])
            self._snapshot_needs_save = True

    def _read_jsonl_tail(self, path: str, max_lines: int) -> List[Dict[str, Any]]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tail = lines[-max_lines:]
            out = []
            for line in tail:
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

    def _rebuild_snapshot_from_jsonl_tail(self, max_per_file: int = 250) -> None:
        """
        Rebuild snapshot from the tail of JSONL files.
        This prevents "dead memory" if snapshot is missing/corrupt/old-dim.
        """
        all_items: List[Dict[str, Any]] = []

        for mtype, path in self.files.items():
            rows = self._read_jsonl_tail(path, max_per_file)
            for obj in rows:
                content = str(obj.get("content", "") or "").strip()
                ts = str(obj.get("ts", "") or "").strip() or datetime.utcnow().isoformat()
                typ = str(obj.get("type", mtype) or mtype).strip().lower()
                h = str(obj.get("hash", "") or "").strip()
                if not content:
                    continue
                if not h:
                    h = self._hash(f"{self.user_id}:{typ}:{content}")
                all_items.append({"ts": ts, "content": content, "type": typ, "hash": h})

        if not all_items:
            self._snapshot_items = []
            self._snapshot_embs = None
            return

        # Sort by timestamp if parseable; otherwise keep stable
        def _ts_key(x: Dict[str, Any]) -> str:
            return str(x.get("ts", ""))

        all_items.sort(key=_ts_key)

        # Deduplicate by hash preserving last occurrence
        dedup: Dict[str, Dict[str, Any]] = {}
        for it in all_items:
            dedup[it["hash"]] = it
        rebuilt = list(dedup.values())
        rebuilt.sort(key=_ts_key)

        # Cap to max_snapshot_items
        rebuilt = rebuilt[-self.max_snapshot_items:]

        # Build aligned embeddings (use normalized embedding or zero vec)
        embs = []
        for it in rebuilt:
            emb = None
            try:
                raw = self.embedding_model.encode([it["content"]])[0]
                norm = self._normalize_embedding(raw)
                if norm is not None and len(norm) == self.embedding_dim:
                    emb = norm.astype(np.float32)
            except Exception:
                emb = None
            if emb is None:
                emb = self._zero_vec()
            embs.append(emb)

        self._snapshot_items = rebuilt
        self._snapshot_embs = np.vstack(embs).astype(np.float32)
        self._snapshot_needs_save = True

        try:
            # Save immediately (atomic) so restart is consistent
            payload = {
                "version": 2,
                "updated": datetime.utcnow().isoformat(),
                "dim": self.embedding_dim,
                "items": self._snapshot_items,
                "embeddings": self._snapshot_embs.tolist(),
            }
            self._atomic_write_json(self.snapshot_path, payload)
            self._snapshot_needs_save = False
            logger.info(f"[Memory] Snapshot rebuilt from JSONL tail ({len(self._snapshot_items)} items).")
        except Exception as e:
            logger.warning(f"[Memory] Snapshot rebuild save failed (non-fatal): {e}")

    async def _save_snapshot(self) -> None:
        async with self._snapshot_lock:
            if not self._snapshot_needs_save:
                return
            self._ensure_snapshot_alignment()

            embs_list = self._snapshot_embs.tolist() if isinstance(self._snapshot_embs, np.ndarray) else []
            payload = {
                "version": 2,
                "updated": datetime.utcnow().isoformat(),
                "dim": self.embedding_dim,
                "items": self._snapshot_items[-self.max_snapshot_items:],
                "embeddings": embs_list[-self.max_snapshot_items:] if embs_list else [],
            }
            self._atomic_write_json(self.snapshot_path, payload)
            self._snapshot_needs_save = False

    # -------------------------
    # Same-turn recall (RAM)
    # -------------------------

    def _purge_ephemeral(self, user_id: str) -> None:
        now = time.time()
        items = self._ephemeral.get(user_id, [])
        if not items:
            return
        kept = [x for x in items if (now - x["ts"]) <= self._ephemeral_ttl_seconds]
        if len(kept) > self._ephemeral_max_per_user:
            kept = kept[-self._ephemeral_max_per_user:]
        self._ephemeral[user_id] = kept

    def stage_memory(self, user_id: str, memory_type: str, content: str, source: str = "staged") -> None:
        if not content or not isinstance(content, str):
            return
        user_id = str(user_id or self.user_id)
        self._purge_ephemeral(user_id)
        item = {
            "content": content.strip(),
            "memory_type": (memory_type or "facts").strip().lower(),
            "source": source,
            "ts": time.time(),
            "tokens": list(self._tokenize(content)),
        }
        self._ephemeral[user_id].append(item)
        if len(self._ephemeral[user_id]) > self._ephemeral_max_per_user:
            self._ephemeral[user_id] = self._ephemeral[user_id][-self._ephemeral_max_per_user:]

    def _ephemeral_matches(self, user_id: str, query: str, top_k: int = 3) -> List[str]:
        user_id = str(user_id or self.user_id)
        self._purge_ephemeral(user_id)
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []
        scored: List[Tuple[float, str]] = []
        for it in self._ephemeral.get(user_id, []):
            c = it.get("content", "")
            c_tokens = set(it.get("tokens", []))
            overlap = len(q_tokens.intersection(c_tokens)) / max(1, len(q_tokens))
            substr_boost = 0.25 if query.lower() in c.lower() else 0.0
            score = overlap + substr_boost
            if score > 0.15:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    # -------------------------
    # LLM decision + categorization
    # -------------------------

    async def should_store_memory(self, input_text: str, output_text: str, user_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Decide if there's a stable memory worth storing.
        Returns: (should_store, memory_type, content)
        memory_type in: preferences, facts, instructions, episodic
        """
        text = (input_text or "").strip()
        if len(text.split()) < 2:
            return False, None, None

        if self.disable_financial_memory and self._is_volatile(text):
            return False, None, None

        prompt = (
            "You are a classifier for personal memory storage.\n"
            "Decide if the user's message contains a stable, useful memory.\n"
            "If yes, return a concise normalized memory statement the assistant can reuse.\n"
            "Output ONLY valid JSON with keys:\n"
            '  {"should_store": bool, "memory_type": "preferences|facts|instructions|episodic", "content": string|null}\n'
            "Rules:\n"
            "- Do NOT store volatile data (prices, weather, news, time-sensitive events).\n"
            "- Store stable preferences, personal facts, standing instructions, and rare useful episodic notes.\n"
            "- Content should be short and directly reusable (e.g., 'Favorite color: blue').\n"
            f'User message: "{text}"\n'
        )

        try:
            async with asyncio.timeout(8.0):
                resp = await self.ollama_client.chat(
                    model=self.memory_model,
                    messages=[{"role": "user", "content": prompt}],
                    format="json",
                    options={"temperature": 0.0, "max_tokens": 140},
                )
            raw = resp.get("message", {}).get("content", "") or ""
            data = json.loads(raw)

            should = bool(data.get("should_store"))
            mtype = data.get("memory_type")
            content = data.get("content")

            if not should or not isinstance(mtype, str) or not isinstance(content, str) or not content.strip():
                return False, None, None

            mtype = mtype.strip().lower()
            if mtype not in ("preferences", "facts", "instructions", "episodic"):
                mtype = "facts"

            # extra guard against volatile
            if self.disable_financial_memory and self._is_volatile(content):
                return False, None, None

            # avoid storing trivial junk
            if len(content.strip()) < 6:
                return False, None, None

            return True, mtype, content.strip()
        except Exception as e:
            logger.debug(f"Memory decision failed (non-fatal): {e}")
            return False, None, None

    # -------------------------
    # Store / retrieve
    # -------------------------

    async def store_memory(self, content: str, user_id: str, memory_type: str = "facts", source: str = "memory") -> bool:
        """
        Persist a memory item (append JSONL) and update snapshot index.
        """
        if not content or not isinstance(content, str):
            return False

        user_id = str(user_id or self.user_id)
        memory_type = (memory_type or "facts").strip().lower()
        if memory_type not in self.files:
            memory_type = "facts"

        if self.disable_financial_memory and self._is_volatile(content):
            return False

        # Dedupe by hash
        item_hash = self._hash(f"{user_id}:{memory_type}:{content.strip()}")
        ts = datetime.utcnow().isoformat()

        rec = MemoryItem(
            ts=ts,
            content=content.strip(),
            memory_type=memory_type,
            source=source,
            hash=item_hash,
        )

        # Append JSONL (durable)
        try:
            obj = {
                "ts": rec.ts,
                "content": rec.content,
                "type": rec.memory_type,
                "source": rec.source,
                "hash": rec.hash,
            }
            self._safe_append_jsonl(self.files[memory_type], obj)
        except Exception as e:
            logger.warning(f"JSONL append failed: {e}")
            return False

        # Daily log + chronicle (best-effort)
        try:
            with open(self.today_log_path, "a", encoding="utf-8") as f:
                f.write(f"**Timestamp:** {ts}\n")
                f.write(f"**Type:** {memory_type}\n")
                f.write(f"**Memory:** {rec.content}\n\n---\n\n")
            with open(self.chronicle_path, "a", encoding="utf-8") as f:
                f.write(f"- {date.today().isoformat()}: [{memory_type}] {rec.content}\n")
        except Exception:
            pass

        # Update snapshot (fast retrieval). Keep strict alignment by always appending a vector.
        emb = None
        try:
            raw = self.embedding_model.encode([rec.content])[0]
            norm = self._normalize_embedding(raw)
            if norm is not None and len(norm) == self.embedding_dim:
                emb = norm.astype(np.float32)
        except Exception:
            emb = None

        if emb is None:
            emb = self._zero_vec()

        async with self._snapshot_lock:
            self._snapshot_items.append({"ts": rec.ts, "content": rec.content, "type": rec.memory_type, "hash": rec.hash})

            if self._snapshot_embs is None:
                self._snapshot_embs = np.asarray([emb], dtype=np.float32)
            else:
                self._snapshot_embs = np.vstack([self._snapshot_embs, emb])

            # cap both together
            if len(self._snapshot_items) > self.max_snapshot_items:
                overflow = len(self._snapshot_items) - self.max_snapshot_items
                self._snapshot_items = self._snapshot_items[overflow:]
                if isinstance(self._snapshot_embs, np.ndarray) and self._snapshot_embs.shape[0] >= overflow:
                    self._snapshot_embs = self._snapshot_embs[overflow:, :]

            self._snapshot_needs_save = True

        await self._save_snapshot()
        return True

    def _collect_forget_phrases(self, max_scan: int = 250) -> List[str]:
        """
        Reads recent instruction memories to extract forget directives.
        """
        phrases: List[str] = []
        try:
            recent = self._snapshot_items[-max_scan:] if self._snapshot_items else []
            for it in reversed(recent):
                if (it.get("type") or "").lower() != "instructions":
                    continue
                c = (it.get("content") or "").strip()
                if not c:
                    continue
                up = c.upper()
                if any(up.startswith(p) for p in FORGET_PREFIXES):
                    # Extract phrase after first colon if possible
                    if ":" in c:
                        phrase = c.split(":", 1)[1].strip()
                    else:
                        phrase = c.split(" ", 1)[-1].strip() if " " in c else ""
                    phrase = phrase.strip().lower()
                    if phrase and phrase not in phrases and len(phrase) >= 2:
                        phrases.append(phrase)
        except Exception:
            pass
        return phrases

    def _apply_forget_filter(self, memories: List[str]) -> List[str]:
        phrases = self._collect_forget_phrases()
        if not phrases:
            return memories
        out = []
        for m in memories:
            low = (m or "").lower()
            if any(p in low for p in phrases):
                continue
            out.append(m)
        return out

    async def retrieve_relevant_memories(self, query: str, user_id: str, min_score: float = 0.20) -> Optional[str]:
        """
        Return a formatted memory context string (top relevant memories).
        """
        user_id = str(user_id or self.user_id)
        q = (query or "").strip()
        if not q:
            return None

        # 1) Same-turn staged RAM matches
        staged = self._ephemeral_matches(user_id, q, top_k=3)

        # 2) Snapshot vector similarity
        vector_hits: List[Tuple[float, str]] = []
        try:
            raw_q = self.embedding_model.encode([q])[0]
            q_emb = self._normalize_embedding(raw_q)
            if q_emb is not None:
                async with self._snapshot_lock:
                    embs = self._snapshot_embs
                    items = list(self._snapshot_items)

                if isinstance(embs, np.ndarray) and embs.size and embs.shape[0] == len(items):
                    sims = np.dot(embs, q_emb.astype(np.float32))
                    if sims.ndim == 1 and sims.size:
                        top_idx = np.argsort(-sims)[:8]
                        for idx in top_idx:
                            score = float(sims[idx])
                            if score < min_score:
                                continue
                            content = items[int(idx)].get("content", "")
                            if content:
                                vector_hits.append((score, content))
        except Exception as e:
            logger.debug(f"Vector retrieval failed (non-fatal): {e}")

        # 3) Keyword fallback across latest items
        keyword_hits: List[Tuple[float, str]] = []
        try:
            q_tokens = self._tokenize(q)
            if q_tokens:
                async with self._snapshot_lock:
                    recent = self._snapshot_items[-220:]
                for it in reversed(recent):
                    c = it.get("content", "")
                    if not c:
                        continue
                    c_tokens = self._tokenize(c)
                    overlap = len(q_tokens.intersection(c_tokens)) / max(1, len(q_tokens))
                    if overlap >= 0.35:
                        keyword_hits.append((overlap, c))
        except Exception:
            pass

        # Merge results, dedupe, and remove junk
        results: List[str] = []
        seen = set()

        def _accept(s: str) -> bool:
            s = (s or "").strip()
            if not s:
                return False
            if len(s) < 6:
                return False
            # avoid extremely generic content
            low = s.lower()
            if low in ("ok", "okay", "sure", "thanks", "noted"):
                return False
            return True

        for c in staged:
            if _accept(c) and c not in seen:
                results.append(c[:220])
                seen.add(c)

        for _, c in sorted(vector_hits, key=lambda x: x[0], reverse=True):
            if len(results) >= 6:
                break
            if _accept(c) and c not in seen:
                results.append(c[:220])
                seen.add(c)

        for _, c in sorted(keyword_hits, key=lambda x: x[0], reverse=True):
            if len(results) >= 6:
                break
            if _accept(c) and c not in seen:
                results.append(c[:220])
                seen.add(c)

        if not results:
            return None

        # Enforce forget directives
        results = self._apply_forget_filter(results)
        if not results:
            return None

        return "\n".join(f"- {r}" for r in results[:6])

    # -------------------------
    # Telegram support methods
    # -------------------------

    async def list_recent_memories(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Returns recent snapshot items (most recent first).
        Safe and fast; doesn't read disk.
        """
        user_id = str(user_id or self.user_id)
        try:
            async with self._snapshot_lock:
                items = list(self._snapshot_items)
            items = items[-max(1, int(limit)):]
            items.reverse()
            out = []
            for it in items:
                out.append({
                    "ts": it.get("ts", ""),
                    "type": it.get("type", "facts"),
                    "content": it.get("content", ""),
                    "hash": it.get("hash", ""),
                })
            return out
        except Exception:
            return []

    async def pin_instruction(self, user_id: str, instruction: str, source: str = "pin") -> bool:
        """
        Stores an instruction as a durable memory item.
        """
        instruction = (instruction or "").strip()
        if not instruction:
            return False
        return await self.store_memory(instruction, user_id=str(user_id or self.user_id), memory_type="instructions", source=source)

    async def forget_phrase(self, user_id: str, phrase: str, source: str = "forget") -> bool:
        """
        Adds a 'forget tombstone' instruction and retrieval will respect it.
        This does NOT delete old JSONL (safer).
        """
        phrase = (phrase or "").strip()
        if not phrase:
            return False
        content = f"FORGET: {phrase}"
        return await self.store_memory(content, user_id=str(user_id or self.user_id), memory_type="instructions", source=source)

    # -------------------------
    # Maintenance
    # -------------------------

    async def curate_daily_digest(self) -> None:
        """
        Optional: summarize today's log into chronicle (best-effort).
        """
        try:
            if not os.path.exists(self.today_log_path):
                return
            with open(self.today_log_path, "r", encoding="utf-8") as f:
                tail = f.read()[-5000:]
            if len(tail) < 300:
                return

            prompt = (
                "Condense the following daily memory log into 5-12 concise bullets of stable facts, preferences, or instructions.\n"
                "Avoid volatile items.\n"
                "Output ONLY markdown bullets.\n\n"
                f"{tail}"
            )
            async with asyncio.timeout(10.0):
                resp = await self.ollama_client.chat(
                    model=self.memory_model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.0, "max_tokens": 240},
                )
            digest = (resp.get("message", {}).get("content", "") or "").strip()
            if digest:
                with open(self.chronicle_path, "a", encoding="utf-8") as f:
                    f.write(f"\n### Digest {date.today().isoformat()}\n{digest}\n")
        except Exception:
            pass

    async def prune_old_memories(self) -> None:
        """
        Keep files bounded and purge old episodic items.
        Conservative to avoid corruption.
        """
        try:
            # Compact oversized JSONL files by keeping last N lines
            for key, path in self.files.items():
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    if len(lines) <= self.max_line_items_per_file:
                        continue
                    keep = lines[-self.max_line_items_per_file:]
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.writelines(keep)
                    os.replace(tmp, path)
                except Exception:
                    continue

            # Episodic TTL purge (rewrite episodic.jsonl only)
            ep_path = self.files["episodic"]
            if os.path.exists(ep_path):
                cutoff = datetime.utcnow() - timedelta(days=self.episodic_ttl_days)
                kept: List[str] = []
                with open(ep_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            ts = obj.get("ts")
                            if ts:
                                dt = datetime.fromisoformat(ts.replace("Z", ""))
                                if dt >= cutoff:
                                    kept.append(line + "\n")
                            else:
                                kept.append(line + "\n")
                        except Exception:
                            kept.append(line + "\n")
                tmp = ep_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(kept[-self.max_line_items_per_file:])
                os.replace(tmp, ep_path)

            await self._save_snapshot()
        except Exception:
            pass
