from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from state import SessionEventStore


def _parse_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(text: Any, *, limit: int = 260) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def _tokenize(text: Any, *, max_items: int = 12) -> list[str]:
    out: list[str] = []
    for tok in re.findall(r"[a-z0-9_/-]{3,}", str(text or "").lower()):
        if tok in out:
            continue
        out.append(tok)
        if len(out) >= max_items:
            break
    return out


def _json_text(value: Any, *, limit: int = 3200) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
    return _clip(text, limit=limit)


@dataclass(frozen=True)
class SessionSearchHit:
    source_kind: str
    source_id: str
    user_id: str
    thread_id: str
    created_at: str
    score: float
    title: str
    snippet: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionSearchService:
    def __init__(
        self,
        *,
        state_store: SessionEventStore | None = None,
        artifacts_root: str | Path = "sessions/artifacts",
        jobs_root: str | Path = "jobs",
        max_artifact_rows: int = 80,
        max_job_rows: int = 80,
    ) -> None:
        self.state_store = state_store or SessionEventStore()
        self.artifacts_root = Path(artifacts_root)
        self.jobs_root = Path(jobs_root)
        self.max_artifact_rows = max(10, int(max_artifact_rows or 80))
        self.max_job_rows = max(10, int(max_job_rows or 80))

    def _window_days_for_query(self, query: str, default_days: int = 30) -> int:
        q = str(query or "").lower()
        if "today" in q:
            return 2
        if "yesterday" in q:
            return 3
        if "last week" in q or "this week" in q:
            return 10
        if "last month" in q:
            return 45
        return max(1, int(default_days or 30))

    def _time_ok(self, created_at: str, *, days: int) -> bool:
        if int(days or 0) <= 0:
            return True
        dt = _parse_ts(created_at)
        if dt is None:
            return True
        return dt >= (_utc_now() - timedelta(days=max(1, int(days))))

    def _score_text(self, query: str, text: str, *, base: float = 0.0) -> float:
        q_tokens = _tokenize(query, max_items=16)
        if not q_tokens:
            return base
        hay = str(text or "").lower()
        overlap = sum(1 for tok in q_tokens if tok in hay)
        return base + (float(overlap) / max(1.0, float(len(q_tokens))))

    def _artifact_files(self, user_id: str) -> list[Path]:
        files: list[Path] = []
        user_file = self.artifacts_root / f"{user_id}.jsonl"
        if user_file.exists():
            files.append(user_file)
        life_modeling = self.artifacts_root / "life_modeling"
        if life_modeling.exists():
            files.extend(sorted(life_modeling.glob("*.jsonl")))
        return files[:12]

    def _iter_recent_jsonl_rows(self, path: Path, *, max_rows: int) -> list[dict[str, Any]]:
        rows: deque[dict[str, Any]] = deque(maxlen=max_rows)
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        rows.append(data)
        except Exception:
            return []
        return list(rows)

    def _search_artifacts(
        self,
        *,
        query: str,
        user_id: str,
        thread_id: str | None,
        limit: int,
        days: int,
    ) -> list[SessionSearchHit]:
        out: list[SessionSearchHit] = []
        for path in self._artifact_files(user_id):
            for row in reversed(self._iter_recent_jsonl_rows(path, max_rows=self.max_artifact_rows)):
                item_thread = str(row.get("thread_id") or row.get("data", {}).get("thread_id") or "")
                if thread_id and item_thread and item_thread != str(thread_id):
                    continue
                created_at = str(row.get("updated_at") or row.get("created_at") or row.get("timestamp") or "")
                if not self._time_ok(created_at, days=days):
                    continue
                title = str(
                    row.get("artifact_type")
                    or row.get("contract_name")
                    or row.get("title")
                    or row.get("artifact_id")
                    or "artifact"
                )
                snippet = _json_text(
                    row.get("current_state_summary")
                    or row.get("summary")
                    or row.get("content")
                    or row.get("data")
                    or row,
                    limit=420,
                )
                score = self._score_text(query, f"{title} {snippet}", base=0.22)
                if score <= 0.22:
                    continue
                out.append(
                    SessionSearchHit(
                        source_kind="artifact",
                        source_id=str(row.get("artifact_id") or f"{path.name}:{len(out)}"),
                        user_id=user_id,
                        thread_id=item_thread,
                        created_at=created_at,
                        score=score,
                        title=_clip(title, limit=120),
                        snippet=_clip(snippet, limit=260),
                        metadata={"path": str(path), "status": str(row.get("status") or "")},
                    )
                )
                if len(out) >= limit:
                    return out
        return out

    def _search_jobs(
        self,
        *,
        query: str,
        user_id: str,
        limit: int,
        days: int,
    ) -> list[SessionSearchHit]:
        del user_id
        out: list[SessionSearchHit] = []
        history_dir = self.jobs_root / "history"
        if history_dir.exists():
            for path in sorted(history_dir.glob("*.json"), reverse=True)[: self.max_job_rows]:
                try:
                    row = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                created_at = str(row.get("updated_at") or row.get("created_at") or row.get("ts") or "")
                if created_at and not self._time_ok(created_at, days=days):
                    continue
                title = str(row.get("objective") or row.get("job_id") or path.stem)
                snippet = _json_text(row.get("result") or row, limit=360)
                score = self._score_text(query, f"{title} {snippet}", base=0.18)
                if score <= 0.18:
                    continue
                out.append(
                    SessionSearchHit(
                        source_kind="job_summary",
                        source_id=str(row.get("job_id") or path.stem),
                        user_id="",
                        thread_id="",
                        created_at=created_at,
                        score=score,
                        title=_clip(title, limit=120),
                        snippet=_clip(snippet, limit=240),
                        metadata={"path": str(path), "phase": str(row.get("phase") or "")},
                    )
                )
                if len(out) >= limit:
                    return out

        journal_dir = self.jobs_root / "journal"
        if journal_dir.exists():
            for path in sorted(journal_dir.glob("*.jsonl"), reverse=True)[:12]:
                rows = self._iter_recent_jsonl_rows(path, max_rows=max(10, self.max_job_rows // 2))
                for row in reversed(rows):
                    created_at = str(row.get("created_at") or row.get("ts") or "")
                    if created_at and not self._time_ok(created_at, days=days):
                        continue
                    title = str(row.get("event") or row.get("name") or path.stem)
                    snippet = _json_text(row, limit=320)
                    score = self._score_text(query, f"{title} {snippet}", base=0.12)
                    if score <= 0.12:
                        continue
                    out.append(
                        SessionSearchHit(
                            source_kind="job_journal",
                            source_id=f"{path.stem}:{len(out)}",
                            user_id="",
                            thread_id="",
                            created_at=created_at,
                            score=score,
                            title=_clip(title, limit=120),
                            snippet=_clip(snippet, limit=220),
                            metadata={"path": str(path)},
                        )
                    )
                    if len(out) >= limit:
                        return out
        return out

    def _search_state(
        self,
        *,
        query: str,
        user_id: str,
        thread_id: str | None,
        limit: int,
        days: int,
    ) -> list[SessionSearchHit]:
        rows = self.state_store.search_text(query, user_id=user_id, thread_id=thread_id, limit=max(4, limit * 2))
        if not rows:
            tokens = _tokenize(query, max_items=5)
            fallbacks = []
            if tokens:
                fallbacks.append(" OR ".join(tokens))
                fallbacks.append(" ".join(tokens[:3]))
                fallbacks.extend(tokens[:2])
            seen_queries: set[str] = set()
            for fallback_query in fallbacks:
                fq = str(fallback_query or "").strip()
                if not fq or fq in seen_queries:
                    continue
                seen_queries.add(fq)
                rows = self.state_store.search_text(fq, user_id=user_id, thread_id=thread_id, limit=max(4, limit * 2))
                if rows:
                    break
        out: list[SessionSearchHit] = []
        for row in rows:
            created_at = str(row.get("created_at") or "")
            if not self._time_ok(created_at, days=days):
                continue
            source_kind = "conversation" if str(row.get("source_type") or "") == "turn" else "event"
            source_id = str(row.get("source_id") or "")
            snippet = _clip(row.get("snippet"), limit=260)
            title = "Conversation turn" if source_kind == "conversation" else str(row.get("source_type") or "event")
            out.append(
                SessionSearchHit(
                    source_kind=source_kind,
                    source_id=source_id,
                    user_id=str(row.get("user_id") or user_id),
                    thread_id=str(row.get("thread_id") or thread_id or ""),
                    created_at=created_at,
                    score=float(row.get("score") or 0.0),
                    title=title,
                    snippet=snippet,
                    metadata={"session_id": str(row.get("session_id") or "")},
                )
            )
            if len(out) >= limit:
                break
        return out

    def search(
        self,
        query: str,
        *,
        user_id: str,
        thread_id: str | None = None,
        limit: int = 8,
        days: int | None = None,
    ) -> list[SessionSearchHit]:
        q = str(query or "").strip()
        if not q:
            return []
        effective_days = self._window_days_for_query(q, default_days=int(days or 30))
        requested_limit = max(1, int(limit or 8))

        hits = []
        hits.extend(self._search_state(query=q, user_id=user_id, thread_id=thread_id, limit=requested_limit, days=effective_days))
        hits.extend(self._search_artifacts(query=q, user_id=user_id, thread_id=thread_id, limit=requested_limit, days=effective_days))
        hits.extend(self._search_jobs(query=q, user_id=user_id, limit=requested_limit, days=effective_days))

        ranked = sorted(
            hits,
            key=lambda item: (
                -float(item.score),
                _parse_ts(item.created_at) or datetime.min.replace(tzinfo=timezone.utc),
            ),
        )
        deduped: list[SessionSearchHit] = []
        seen: set[tuple[str, str]] = set()
        for item in ranked:
            key = (item.source_kind, item.source_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= requested_limit:
                break
        return deduped

    def summarize(
        self,
        query: str,
        *,
        user_id: str,
        thread_id: str | None = None,
        limit: int = 5,
        days: int | None = None,
    ) -> str:
        hits = self.search(query, user_id=user_id, thread_id=thread_id, limit=limit, days=days)
        if not hits:
            return "[Session Search]\n- No indexed matches found."

        lines = ["[Session Search]"]
        for item in hits[: max(1, int(limit))]:
            when = item.created_at[:10] if item.created_at else "unknown date"
            lines.append(f"- {when} | {item.source_kind}: {item.snippet}")
        return "\n".join(lines)

    def answer_recall(
        self,
        query: str,
        *,
        user_id: str,
        thread_id: str | None = None,
        limit: int = 6,
        days: int | None = None,
    ) -> str:
        hits = self.search(query, user_id=user_id, thread_id=thread_id, limit=limit, days=days)
        if not hits:
            return "I couldn't find matching prior session records for that yet."

        q = str(query or "").lower()
        label = "Possible prior decisions" if "decid" in q else "Best prior matches"
        lines = [f"{label}:"]
        for item in hits[: max(1, int(limit))]:
            when = item.created_at[:10] if item.created_at else "unknown date"
            detail = f"{item.title}: {item.snippet}" if item.title and item.title != "Conversation turn" else item.snippet
            lines.append(f"- {when} [{item.source_kind}] {detail}")
        return "\n".join(lines)
