from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
from typing import Any

from gateway import GatewayService
from state import SessionEventStore
from runtime.background_tasks import BackgroundTaskStore
from runtime.task_graph import load_task_graph
from runtime.task_resume import build_resume_ledger
from workshop.toolbox.agent_core.continuity import derive_thread_id


_RESUME_MARKERS = (
    "continue",
    "resume",
    "keep going",
    "pick up",
    "what's left",
    "whats left",
    "status",
    "where were we",
)
_NEW_THREAD_MARKERS = (
    "new thread",
    "new task",
    "new chat",
    "start over",
    "fresh start",
)
_FOLLOWUP_MARKERS = (
    "also",
    "and",
    "then",
    "next",
    "that one",
    "this one",
    "it",
    "them",
    "those",
    "same",
)
_TELEGRAM_TEXT_LIMIT = 3900
_EXPORT_ROUTE_HINTS = {"coding_mode", "capulet_artifact", "continuity_artifact", "websearch"}


def _clip(value: Any, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_telegram_conversation_id(*, chat_id: Any, message_thread_id: Any = "") -> str:
    chat = str(chat_id or "").strip()
    topic = str(message_thread_id or "").strip()
    if chat and topic:
        return f"{chat}:topic:{topic}"
    return chat


def _is_resume_prompt(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(marker in lowered for marker in _RESUME_MARKERS)


def _is_new_thread_prompt(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(marker in lowered for marker in _NEW_THREAD_MARKERS)


def _looks_followup(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if len(lowered) <= 80 and any(marker in lowered for marker in _FOLLOWUP_MARKERS):
        return True
    return lowered.startswith(("also ", "and ", "then ", "what about ", "how about "))


def _short_thread_label(thread_id: str) -> str:
    clean = re.sub(r"[^a-z0-9]", "", str(thread_id or "").lower())
    return clean[:8] if clean else "current"


def _task_graph_root_from_store(state_store: SessionEventStore) -> Path | None:
    db_path = getattr(state_store, "db_path", None)
    if db_path is None:
        return None
    path = Path(db_path)
    try:
        return path.parent.parent / "task_graph"
    except Exception:
        return None


def _background_root_from_store(state_store: SessionEventStore) -> Path | None:
    db_path = getattr(state_store, "db_path", None)
    if db_path is None:
        return None
    path = Path(db_path)
    try:
        return path.parent.parent / "ops" / "background_tasks"
    except Exception:
        return None


def build_telegram_progress_ack(
    *,
    queue_depth: int,
    reused_thread: bool,
    active_task: bool,
) -> str:
    if active_task:
        return "Got it - queued on your current thread. I'll reply in order."
    if reused_thread:
        return "Got it - continuing your current thread."
    if queue_depth > 1:
        return "Got it - queued. I'll get to this next."
    return "Got it - thinking."


def build_research_capsule(report: dict[str, Any] | None) -> str:
    payload = dict(report or {})
    if not payload:
        return ""
    mode = str(payload.get("mode") or "").strip().lower()
    mode_label = {
        "quick": "Quick browse",
        "quick_web": "Quick browse",
        "deep": "Deep browse",
        "deep_browse": "Deep browse",
        "github": "GitHub browse",
        "direct_url": "Direct page read",
        "official": "Official-source browse",
        "official_direct": "Official-source browse",
    }.get(mode, "Browse")
    headline = " ".join(str(payload.get("progress_headline") or "").split()).strip()
    if not headline:
        steps = [str(item).strip() for item in list(payload.get("execution_steps") or []) if str(item).strip()]
        if steps:
            headline = steps[0]
    if not headline:
        headline = " ".join(str(payload.get("execution_summary") or "").split()).strip()
    try:
        sources_count = max(0, int(payload.get("sources_count") or len(list(payload.get("sources") or []))))
    except Exception:
        sources_count = 0
    try:
        limitations_count = max(0, int(payload.get("limitations_count") or len(list(payload.get("limitations") or []))))
    except Exception:
        limitations_count = 0
    parts = [mode_label]
    if sources_count:
        parts.append(f"{sources_count} source{'s' if sources_count != 1 else ''}")
    if headline:
        parts.append(_clip(headline, limit=120))
    if limitations_count:
        parts.append(f"{limitations_count} caution{'s' if limitations_count != 1 else ''}")
    return " | ".join([part for part in parts if part])


def build_source_preview(report: dict[str, Any] | None, *, limit: int = 3) -> list[str]:
    payload = dict(report or {})
    rows: list[str] = []
    for item in list(payload.get("sources") or []):
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("label") or "").strip()
            url = str(item.get("url") or "").strip()
        else:
            title = ""
            url = str(item or "").strip()
        label = title or url
        if not label:
            continue
        label = re.sub(r"^https?://", "", label, flags=re.IGNORECASE)
        label = label.split("?", 1)[0].split("#", 1)[0].strip("/")
        rows.append(_clip(label, limit=92))
        if len(rows) >= max(1, int(limit or 3)):
            break
    return rows


def _split_long_block(text: str, *, limit: int) -> list[str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return []
    if len(clean) <= limit:
        return [clean]
    parts: list[str] = []
    remaining = clean
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        window = remaining[:limit]
        split_at = max(window.rfind(". "), window.rfind("; "), window.rfind(", "), window.rfind(" "))
        if split_at < int(limit * 0.55):
            split_at = limit
        chunk = remaining[:split_at].strip()
        if not chunk:
            chunk = remaining[:limit].strip()
            split_at = limit
        parts.append(chunk)
        remaining = remaining[split_at:].strip()
    return parts


def _chunk_delivery_sections(sections: list[str], *, limit: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for section in sections:
        text = str(section or "").strip()
        if not text:
            continue
        block_parts = _split_long_block(text, limit=limit)
        for block in block_parts:
            candidate_len = len(block) if not current else current_len + 2 + len(block)
            if current and candidate_len > limit:
                chunks.append("\n\n".join(current))
                current = [block]
                current_len = len(block)
                continue
            current.append(block)
            current_len = candidate_len if len(current) > 1 else len(block)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _document_capsule(payload: dict[str, Any] | None) -> str:
    data = dict(payload or {})
    if not data:
        return ""
    parts = []
    file_name = str(data.get("file_name") or "document").strip()
    document_kind = str(data.get("document_kind") or "").strip()
    if file_name:
        parts.append(file_name)
    if document_kind:
        parts.append(document_kind.upper())
    try:
        page_count = int(data.get("page_count") or 0)
    except Exception:
        page_count = 0
    if page_count:
        parts.append(f"{page_count} page{'s' if page_count != 1 else ''}")
    anchors = [str(item.get("label") or "").strip() for item in list(data.get("anchors") or []) if isinstance(item, dict)]
    capsule = " | ".join([part for part in parts if part]).strip()
    if anchors:
        anchor_preview = ", ".join([anchor for anchor in anchors[:3] if anchor])
        if anchor_preview:
            capsule = f"{capsule} | anchors {anchor_preview}" if capsule else f"Anchors {anchor_preview}"
    return f"Document note: {capsule}" if capsule else ""


def _should_export_delivery(*, route: str, content: str, follow_ups: list[str], document_note: str) -> bool:
    content_len = len(str(content or "").strip())
    follow_len = sum(len(str(item or "").strip()) for item in list(follow_ups or []))
    route_key = str(route or "").strip().lower()
    if content_len > 3200:
        return True
    if content_len + follow_len > 5200:
        return True
    if route_key in _EXPORT_ROUTE_HINTS and content_len > 2400:
        return True
    if document_note and (content_len > 2000 or follow_len > 1400):
        return True
    return False


def _write_delivery_export(
    *,
    content: str,
    route: str,
    thread_id: str,
    task_id: str,
    follow_ups: list[str],
    browse_report: dict[str, Any] | None = None,
    document_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_label = str(route or "chat").strip() or "chat"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Somi Telegram Export",
        "",
        f"- Generated: {stamp}",
        f"- Route: {route_label}",
    ]
    if thread_id:
        lines.append(f"- Thread: {_short_thread_label(thread_id)}")
    if task_id:
        lines.append(f"- Task: {str(task_id)[:10]}")
    document_capsule = _document_capsule(document_payload)
    if document_capsule:
        lines.append(f"- {document_capsule.replace('Document note: ', '')}")
    lines.extend(["", "## Response", "", str(content or "").strip() or "(empty)"])
    source_rows = build_source_preview(browse_report, limit=6)
    if source_rows:
        lines.extend(["", "## Sources", ""])
        lines.extend([f"- {row}" for row in source_rows])
    extra_rows = [str(item or "").strip() for item in list(follow_ups or []) if str(item or "").strip()]
    if extra_rows:
        lines.extend(["", "## Notes", ""])
        lines.extend(extra_rows)
    handle = tempfile.NamedTemporaryFile(prefix="somi_telegram_", suffix=".md", delete=False, mode="w", encoding="utf-8")
    with handle:
        handle.write("\n".join(lines).strip() + "\n")
    return {
        "type": "document",
        "path": handle.name,
        "title": "Somi Telegram export",
        "caption": "Full Somi write-up attached.",
        "cleanup": True,
    }


def build_telegram_delivery_bundle(
    *,
    content: str,
    route: str = "",
    browse_report: dict[str, Any] | None = None,
    thread_id: str = "",
    task_id: str = "",
    document_payload: dict[str, Any] | None = None,
    document_note: str = "",
    continuity_report: dict[str, Any] | None = None,
    limit: int = _TELEGRAM_TEXT_LIMIT,
    create_exports: bool = True,
) -> dict[str, Any]:
    primary = str(content or "").strip()
    extras: list[str] = []
    doc_capsule = _document_capsule(document_payload)
    if doc_capsule:
        extras.append(doc_capsule)
    capsule = build_research_capsule(browse_report)
    if capsule:
        extras.append(f"Research note: {capsule}")
        source_lines = build_source_preview(browse_report, limit=3)
        if source_lines:
            extras.append("Sources:\n" + "\n".join(f"- {line}" for line in source_lines))
    continuity = dict(continuity_report or {})
    surface_names = [str(item).strip() for item in list(continuity.get("surface_names") or []) if str(item).strip()]
    if continuity:
        parts: list[str] = []
        if surface_names:
            parts.append(f"surfaces {', '.join(surface_names)}")
        open_task_count = int(continuity.get("open_task_count") or 0)
        if open_task_count:
            parts.append(f"open tasks {open_task_count}")
        recommended_surface = str(continuity.get("recommended_surface") or "").strip()
        if recommended_surface:
            parts.append(f"best next surface {recommended_surface}")
        latest_route = str(continuity.get("last_route") or "").strip()
        if latest_route:
            parts.append(f"route {latest_route}")
        if parts:
            extras.append("Continuity note: " + " | ".join(parts))
        resume_hint = str(continuity.get("resume_hint") or "").strip()
        if resume_hint:
            extras.append(resume_hint)
    route_key = str(route or "").strip().lower()
    if route_key == "coding_mode":
        extras.append("Coding note: this session stays live on your current thread. Say continue to keep iterating.")
    elif route_key in {"websearch", "continuity_artifact", "capulet_artifact"} and thread_id:
        extras.append(f"Session saved on thread {_short_thread_label(thread_id)}. Say continue to keep going.")
    if task_id:
        extras.append(f"Task note: resume with continue if you want me to keep working on task {str(task_id)[:10]}.")
    if document_note:
        extras.append(str(document_note).strip())

    chunks = _chunk_delivery_sections([primary] + extras, limit=max(400, int(limit or _TELEGRAM_TEXT_LIMIT)))
    if not chunks:
        chunks = [primary or "Somi finished the task, but there was no reply text to send."]
    exports: list[dict[str, Any]] = []
    if create_exports and _should_export_delivery(route=route_key, content=primary, follow_ups=extras, document_note=document_note):
        exports.append(
            _write_delivery_export(
                content=primary,
                route=route_key,
                thread_id=thread_id,
                task_id=task_id,
                follow_ups=extras,
                browse_report=browse_report,
                document_payload=document_payload,
            )
        )
        attachment_hint = "I attached the full write-up as a document so the thread stays readable."
        if len(primary) > 1800:
            lead = _clip(primary, limit=min(1400, max(800, int(limit or _TELEGRAM_TEXT_LIMIT) // 3)))
            chunks = [f"{lead}\n\n{attachment_hint}".strip()]
            extra_chunks = _chunk_delivery_sections(extras, limit=max(400, int(limit or _TELEGRAM_TEXT_LIMIT)))
            chunks.extend(extra_chunks)
        elif "attached" not in chunks[0].lower():
            hint_candidate = f"{chunks[0]}\n\n{attachment_hint}".strip()
            if len(hint_candidate) <= max(400, int(limit or _TELEGRAM_TEXT_LIMIT)):
                chunks[0] = hint_candidate
            else:
                chunks.insert(1, attachment_hint)
    return {
        "primary": chunks[0],
        "follow_ups": chunks[1:],
        "exports": exports,
        "summary": _clip(primary or chunks[0], limit=220),
        "document_capsule": doc_capsule,
        "source_preview": build_source_preview(browse_report, limit=3),
        "continuity": continuity,
    }


def build_telegram_reply_bundle(
    *,
    content: str,
    route: str = "",
    browse_report: dict[str, Any] | None = None,
    thread_id: str = "",
    task_id: str = "",
    limit: int = 3900,
) -> dict[str, str]:
    bundle = build_telegram_delivery_bundle(
        content=content,
        route=route,
        browse_report=browse_report,
        thread_id=thread_id,
        task_id=task_id,
        limit=limit,
        create_exports=False,
    )
    return {
        "primary": str(bundle.get("primary") or ""),
        "follow_up": "\n\n".join([str(item).strip() for item in list(bundle.get("follow_ups") or []) if str(item).strip()]),
        "summary": str(bundle.get("summary") or _clip(content, limit=220)),
    }


class TelegramRuntimeBridge:
    def __init__(self, *, gateway_service: GatewayService, state_store: SessionEventStore) -> None:
        self.gateway_service = gateway_service
        self.state_store = state_store

    def resolve_thread_id(
        self,
        *,
        user_id: str,
        prompt: str,
        conversation_id: str = "",
        active_thread_id: str = "",
        active_conversation_id: str = "",
        active_updated_at: str = "",
    ) -> str:
        text = str(prompt or "").strip()
        if not text:
            return str(active_thread_id or "")

        if _is_new_thread_prompt(text):
            seed = f"{conversation_id} {text}".strip()
            return derive_thread_id(seed or text)

        active_dt = _parse_iso(active_updated_at)
        active_recent = bool(
            active_thread_id
            and active_dt is not None
            and active_dt >= datetime.now(timezone.utc) - timedelta(minutes=90)
        )
        if active_thread_id and active_conversation_id and conversation_id and active_conversation_id != conversation_id:
            active_recent = False

        if _is_resume_prompt(text):
            task_graph_root = _task_graph_root_from_store(self.state_store)
            sessions = self.state_store.list_sessions(user_id=user_id, limit=12)
            if task_graph_root is not None:
                for session in sessions:
                    thread_id = str(session.get("thread_id") or "").strip()
                    if not thread_id:
                        continue
                    graph = load_task_graph(user_id, thread_id, root_dir=task_graph_root)
                    open_tasks = [
                        row
                        for row in list(graph.get("tasks") or [])
                        if isinstance(row, dict) and str(row.get("status") or "open").strip().lower() != "done"
                    ]
                    if open_tasks:
                        return thread_id
            if conversation_id:
                for session in sessions:
                    meta = dict(session.get("metadata") or {})
                    if str(meta.get("conversation_id") or "") == conversation_id:
                        thread_id = str(session.get("thread_id") or "").strip()
                        if thread_id:
                            return thread_id
            if sessions:
                latest = str(sessions[0].get("thread_id") or "").strip()
                if latest:
                    return latest
            if active_thread_id:
                return active_thread_id

        if active_thread_id and (active_recent or _looks_followup(text)):
            return active_thread_id

        seed = f"{conversation_id} {text}".strip()
        return derive_thread_id(seed or text)

    def upsert_surface_session(
        self,
        *,
        user_id: str,
        client_label: str,
        username: str = "",
        chat_type: str = "",
        conversation_id: str = "",
        thread_id: str = "",
        is_owner: bool = False,
        queue_depth: int = 0,
    ) -> dict[str, Any]:
        session_id = f"telegram-{str(user_id or 'default_user').strip()}"
        metadata = {
            "remote_client": True,
            "telegram_user_id": str(user_id or "default_user"),
            "telegram_username": str(username or "").strip(),
            "conversation_id": str(conversation_id or "").strip(),
            "active_thread_id": str(thread_id or "").strip(),
            "queue_depth": max(0, int(queue_depth or 0)),
            "owner": bool(is_owner),
        }
        session = self.gateway_service.register_session(
            user_id=str(user_id or "default_user"),
            surface="telegram",
            client_id=f"telegram-{str(user_id or 'default_user').strip()}",
            client_label=str(client_label or username or user_id or "Telegram User"),
            platform=str(chat_type or "telegram"),
            auth_mode="paired" if is_owner else "remote",
            session_id=session_id,
            metadata=metadata,
        )
        self.gateway_service.update_presence(
            session_id=str(session.get("session_id") or session_id),
            status="online",
            activity="telegram_session",
            detail=_clip(f"{client_label} :: {conversation_id or 'direct'}", limit=160),
            metadata={"thread_id": str(thread_id or "").strip(), "queue_depth": max(0, int(queue_depth or 0))},
        )
        return session

    def latest_route(self, *, user_id: str, thread_id: str) -> str:
        sessions = self.state_store.list_sessions(user_id=user_id, thread_id=thread_id, limit=1)
        if not sessions:
            return ""
        return str(sessions[0].get("last_route") or "").strip()

    def build_thread_capsule(
        self,
        *,
        user_id: str,
        thread_id: str,
        active_thread_id: str = "",
    ) -> dict[str, Any]:
        sessions = self.state_store.list_sessions(user_id=user_id, thread_id=thread_id, limit=8)
        task_graph_root = _task_graph_root_from_store(self.state_store)
        background_root = _background_root_from_store(self.state_store)
        graph = load_task_graph(user_id, thread_id, root_dir=task_graph_root) if task_graph_root is not None and thread_id else {"tasks": []}
        background_snapshot = (
            BackgroundTaskStore(root_dir=background_root).snapshot(user_id=user_id, limit=12)
            if background_root is not None
            else {}
        )
        ledger = build_resume_ledger(
            sessions=sessions,
            background_snapshot=background_snapshot,
            task_graphs={str(thread_id): dict(graph or {})} if thread_id else {},
            active_thread_id=str(active_thread_id or ""),
            limit=1,
        )
        entry = dict((list(ledger.get("entries") or [])[:1] or [{}])[0])
        if not entry:
            surfaces: list[str] = []
            latest_route = ""
            last_seen_at = ""
            for session in sessions:
                meta = dict(session.get("metadata") or {})
                surface = str(meta.get("surface") or meta.get("platform") or "").strip().lower()
                if surface and surface not in surfaces:
                    surfaces.append(surface)
                if str(session.get("last_seen_at") or "") > last_seen_at:
                    last_seen_at = str(session.get("last_seen_at") or "")
                    latest_route = str(session.get("last_route") or "")
            return {
                "thread_id": str(thread_id or ""),
                "surface_names": surfaces,
                "open_task_count": 0,
                "background_count": 0,
                "recommended_surface": surfaces[0] if surfaces else "telegram",
                "resume_hint": f"Continue on thread {thread_id}." if thread_id else "Continue on your current Telegram thread.",
                "last_route": latest_route,
            }
        return entry
