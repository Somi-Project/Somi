from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CORRECTION_MARKERS = (
    "actually",
    "that's wrong",
    "that is wrong",
    "not what i asked",
    "not what i meant",
    "incorrect",
    "i meant",
    "instead",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any, *, max_len: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 3)].rstrip() + "..."


def _safe_part(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())[:100] or "default"


def infer_grounding(route: str, content: str, tool_events: list[dict[str, Any]] | None = None) -> bool:
    route_name = str(route or "").strip().lower()
    if route_name not in {"websearch", "normal", "search_only", "planning"}:
        return False
    text = str(content or "")
    if "http://" in text or "https://" in text:
        return True
    if "Sources:" in text or "Source:" in text:
        return True
    for row in list(tool_events or []):
        detail = str(row.get("detail") or "").lower()
        if "source" in detail or "citation" in detail:
            return True
    return False


class TrajectoryStore:
    def __init__(self, root_dir: str | Path = "sessions/trajectories") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, *, user_id: str, thread_id: str) -> Path:
        return self.root_dir / f"{_safe_part(user_id)}__{_safe_part(thread_id)}.jsonl"

    def record_turn(
        self,
        *,
        user_id: str,
        thread_id: str,
        session_id: str,
        turn_id: int,
        turn_index: int,
        prompt: str,
        response: str,
        route: str,
        model_name: str,
        latency_ms: int,
        tool_events: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "recorded_at": _now_iso(),
            "user_id": str(user_id or "default_user"),
            "thread_id": str(thread_id or "general"),
            "session_id": str(session_id or ""),
            "turn_id": int(turn_id or 0),
            "turn_index": int(turn_index or 0),
            "prompt": _safe(prompt, max_len=1200),
            "response": _safe(response, max_len=2400),
            "route": str(route or ""),
            "model_name": str(model_name or ""),
            "latency_ms": int(latency_ms or 0),
            "tool_events": list(tool_events or []),
            "metadata": dict(metadata or {}),
            "grounded": infer_grounding(str(route or ""), str(response or ""), list(tool_events or [])),
        }
        path = self.path_for(user_id=str(user_id or "default_user"), thread_id=str(thread_id or "general"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def load(self, *, user_id: str, thread_id: str, limit: int = 200) -> list[dict[str, Any]]:
        path = self.path_for(user_id=user_id, thread_id=thread_id)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
        return rows[-max(1, int(limit or 200)) :]

    def list_threads(self, *, user_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.root_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            payloads = self.load(
                user_id=path.stem.split("__", 1)[0],
                thread_id=path.stem.split("__", 1)[1] if "__" in path.stem else "general",
                limit=1,
            )
            if not payloads:
                continue
            latest = payloads[-1]
            if user_id and str(latest.get("user_id") or "") != str(user_id):
                continue
            rows.append(
                {
                    "user_id": str(latest.get("user_id") or ""),
                    "thread_id": str(latest.get("thread_id") or ""),
                    "last_recorded_at": str(latest.get("recorded_at") or ""),
                    "turn_count": int(latest.get("turn_index") or 0),
                }
            )
        return rows[: max(1, int(limit or 40))]

    def replay(self, *, user_id: str, thread_id: str, limit: int = 40) -> dict[str, Any]:
        rows = self.load(user_id=user_id, thread_id=thread_id, limit=limit)
        correction_turns = 0
        transcript: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            next_prompt = str(rows[idx + 1].get("prompt") or "").lower() if idx + 1 < len(rows) else ""
            corrected = any(marker in next_prompt for marker in CORRECTION_MARKERS)
            if corrected:
                correction_turns += 1
            transcript.append(
                {
                    "turn_index": int(row.get("turn_index") or 0),
                    "prompt": str(row.get("prompt") or ""),
                    "response": str(row.get("response") or ""),
                    "route": str(row.get("route") or ""),
                    "model_name": str(row.get("model_name") or ""),
                    "latency_ms": int(row.get("latency_ms") or 0),
                    "grounded": bool(row.get("grounded", False)),
                    "corrected_by_next_user": corrected,
                }
            )
        return {
            "user_id": str(user_id or "default_user"),
            "thread_id": str(thread_id or "general"),
            "turn_count": len(rows),
            "correction_turns": correction_turns,
            "transcript": transcript,
        }
