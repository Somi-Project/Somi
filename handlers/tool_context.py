from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolContext:
    session_id: str
    last_tool_type: str
    last_query: str
    last_results: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=lambda: time.time())
    last_selected_rid: str = ""
    last_selected_rank: int = 0
    last_selected_url: str = ""
    last_selected_title: str = ""
    last_finance_intent: str = ""


class ToolContextStore:
    def __init__(self, ttl_seconds: int = 900, max_sessions: int = 512):
        self.ttl_seconds = int(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._store: Dict[str, ToolContext] = {}
        self._lock = threading.Lock()

    def _stable_rid(self, title: str, url: str, rank: int) -> str:
        raw = (url or f"{title}|{rank}").encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()[:10]

    def _normalize_result(self, item: Dict[str, Any], rank: int, tool: str) -> Dict[str, Any]:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("description") or item.get("snippet") or "").strip()
        published_at = str(item.get("published_at") or item.get("published") or "").strip()
        rid = str(item.get("rid") or "").strip() or self._stable_rid(title, url, rank)
        return {
            "rank": int(rank),
            "rid": rid,
            "title": title,
            "url": url,
            "snippet": snippet,
            "published_at": published_at,
            "tool": tool,
            "timestamp": time.time(),
        }

    def set(
        self,
        session_id: str,
        tool_type: str,
        query: str,
        results: List[Dict[str, Any]],
        finance_intent: str = "",
    ) -> None:
        sid = str(session_id or "default_user")
        normalized = [
            self._normalize_result(r, idx, tool_type)
            for idx, r in enumerate(results or [], start=1)
            if isinstance(r, dict)
        ]
        with self._lock:
            prev = self._store.get(sid)
            self._store[sid] = ToolContext(
                session_id=sid,
                last_tool_type=str(tool_type or "general"),
                last_query=str(query or ""),
                last_results=normalized,
                last_selected_rid=str(prev.last_selected_rid) if prev else "",
                last_selected_rank=int(prev.last_selected_rank) if prev else 0,
                last_selected_url=str(prev.last_selected_url) if prev else "",
                last_selected_title=str(prev.last_selected_title) if prev else "",
                last_finance_intent=str(finance_intent or (prev.last_finance_intent if prev else "")),
            )
            if len(self._store) > self.max_sessions:
                oldest = sorted(self._store.items(), key=lambda kv: kv[1].timestamp)
                for k, _ in oldest[: len(self._store) - self.max_sessions]:
                    self._store.pop(k, None)

    def mark_selected(
        self,
        session_id: str,
        *,
        rank: int = 0,
        url: str = "",
        rid: str = "",
    ) -> None:
        sid = str(session_id or "default_user")
        with self._lock:
            ctx = self._store.get(sid)
            if not ctx:
                return
            chosen = None
            if rid:
                chosen = next((r for r in ctx.last_results if str(r.get("rid") or "") == str(rid)), None)
            if chosen is None and rank > 0:
                chosen = next((r for r in ctx.last_results if int(r.get("rank", 0)) == int(rank)), None)
            if chosen is None and url:
                chosen = next((r for r in ctx.last_results if str(r.get("url") or "") == str(url)), None)
            if chosen is None and url:
                ctx.last_selected_url = str(url)
                return
            if chosen:
                ctx.last_selected_rid = str(chosen.get("rid") or "")
                ctx.last_selected_rank = int(chosen.get("rank") or 0)
                ctx.last_selected_url = str(chosen.get("url") or "")
                ctx.last_selected_title = str(chosen.get("title") or "")

    def get(self, session_id: str) -> Optional[ToolContext]:
        sid = str(session_id or "default_user")
        with self._lock:
            ctx = self._store.get(sid)
            if not ctx:
                return None
            if (time.time() - float(ctx.timestamp)) > self.ttl_seconds:
                self._store.pop(sid, None)
                return None
            return ctx
