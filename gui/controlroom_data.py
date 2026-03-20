from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops.framework_freeze import load_latest_framework_freeze
from ops.observability import build_observability_digest
from ops.context_budget import run_context_budget_status
from ops.offline_resilience import run_offline_resilience
from ops.release_gate import load_latest_release_report
from runtime.audit import verify_audit_path
from runtime.task_resume import build_resume_ledger
from runtime.task_graph import load_task_graph
from executive.approvals import build_approval_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _json_text(value: Any, *, limit: int = 1800) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _row(
    item_id: str,
    title: str,
    *,
    status: str = "",
    updated_at: str = "",
    subtitle: str = "",
    detail: str = "",
) -> dict[str, str]:
    return {
        "id": str(item_id or title or "row"),
        "title": str(title or "Untitled"),
        "status": str(status or ""),
        "updated_at": str(updated_at or ""),
        "subtitle": _clip(subtitle, limit=180),
        "detail": str(detail or ""),
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _read_recent_jsonl(path: Path, *, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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
    return rows[-max(1, int(limit or 8)) :]


class ControlRoomSnapshotBuilder:
    def __init__(
        self,
        *,
        state_store,
        ontology,
        memory_manager,
        automation_engine,
        automation_store,
        delivery_gateway,
        tool_registry,
        subagent_registry,
        subagent_status_store,
        workflow_store,
        workflow_manifest_store,
        gateway_service=None,
        ops_control=None,
        jobs_root: str | Path = "jobs",
        artifacts_root: str | Path = "sessions/artifacts",
    ) -> None:
        self.state_store = state_store
        self.ontology = ontology
        self.memory_manager = memory_manager
        self.automation_engine = automation_engine
        self.automation_store = automation_store
        self.delivery_gateway = delivery_gateway
        self.gateway_service = gateway_service
        self.tool_registry = tool_registry
        self.subagent_registry = subagent_registry
        self.subagent_status_store = subagent_status_store
        self.workflow_store = workflow_store
        self.workflow_manifest_store = workflow_manifest_store
        self.ops_control = ops_control
        self.jobs_root = Path(jobs_root)
        self.artifacts_root = Path(artifacts_root)

    def _task_graph_root(self) -> Path | None:
        db_path = getattr(self.state_store, "db_path", None)
        if db_path is None:
            return None
        path = Path(db_path)
        try:
            return path.parent.parent / "task_graph"
        except Exception:
            return None

    def _project_root(self) -> Path:
        db_path = getattr(self.state_store, "db_path", None)
        if db_path is None:
            return PROJECT_ROOT
        path = Path(db_path)
        try:
            return path.parents[2]
        except Exception:
            return PROJECT_ROOT

    def _timeline_detail(self, *, user_id: str, thread_id: str) -> str:
        timeline = self.state_store.load_session_timeline(user_id=user_id, thread_id=thread_id)
        session = dict(timeline.get("session") or {})
        turns = list(timeline.get("turns") or [])
        lines = [
            f"Thread: {thread_id}",
            f"Session ID: {session.get('session_id', '')}",
            f"Turns: {session.get('turn_count', 0)}",
            f"Last route: {session.get('last_route', '--')}",
            f"Last model: {session.get('last_model', '--')}",
            "",
            "Recent replay:",
        ]
        for row in turns[-8:]:
            lines.append(f"Turn {row.get('turn_index', '?')} [{row.get('status', 'unknown')}]")
            lines.append(f"User: {_clip(row.get('user_text'), limit=280)}")
            assistant_text = str(row.get("assistant_text") or "").strip()
            if assistant_text:
                lines.append(f"Assistant: {_clip(assistant_text, limit=320)}")
            events = list(row.get("events") or [])
            for event in events[:6]:
                lines.append(
                    f"  - {event.get('event_type', 'event')}::{event.get('event_name', 'event')} @ {event.get('created_at', '')}"
                )
            lines.append("")
        return "\n".join(line for line in lines if line is not None).strip()

    def _config_rows(
        self,
        *,
        user_id: str,
        thread_id: str,
        agent_name: str,
        model_snapshot: dict[str, Any],
        ontology_counts: dict[str, int],
        gateway_snapshot: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        toolsets = self.tool_registry.list_toolsets(include_empty=True)
        tools = self.tool_registry.list_tools()
        approval_summary = build_approval_summary(self.ops_control, limit=8)
        available = 0
        for item in tools:
            try:
                if bool(self.tool_registry.availability(item).get("ok", True)):
                    available += 1
            except Exception:
                available += 1

        rows = [
            _row(
                "persona",
                "Active Persona",
                status="ready",
                subtitle=str(agent_name or "Somi"),
                detail=_json_text(
                    {
                        "agent_name": agent_name or "Somi",
                        "thread_id": thread_id or "(latest session)",
                        "user_id": user_id,
                    }
                ),
            ),
            _row(
                "models",
                "Runtime Model Stack",
                status=str(model_snapshot.get("MODEL_CAPABILITY_PROFILE") or "default"),
                subtitle=f"default={model_snapshot.get('DEFAULT_MODEL', '--')} | memory={model_snapshot.get('MEMORY_MODEL', '--')}",
                detail=_json_text(model_snapshot),
            ),
            _row(
                "tool_registry",
                "Tool Registry",
                status=f"{available}/{len(tools)} ready",
                subtitle=", ".join(
                    f"{row.get('id', 'toolset')}={row.get('tool_count', 0)}"
                    for row in toolsets
                    if int(row.get("tool_count", 0) or 0) > 0
                )
                or "No toolsets registered",
                detail=_json_text({"tools": tools[:40], "toolsets": toolsets}),
            ),
            _row(
                "ontology",
                "Operational Ontology",
                status="synced" if thread_id else "standby",
                subtitle=", ".join(f"{kind}={count}" for kind, count in sorted(ontology_counts.items())[:8]) or "No ontology objects yet",
                detail=_json_text({"counts_by_kind": ontology_counts}),
            ),
            _row(
                "runtime_profile",
                "Runtime Profile",
                status=str(approval_summary.get("active_profile") or "local_workstation"),
                subtitle=f"allowed={approval_summary.get('allowed', 0)} | blocked={approval_summary.get('blocked', 0)}",
                detail=_json_text(approval_summary),
            ),
            _row(
                "autonomy_profile",
                "Autonomy Profile",
                status=str(approval_summary.get("active_autonomy_profile") or "balanced"),
                subtitle=(
                    f"runtime={approval_summary.get('active_profile') or 'local_workstation'} | "
                    f"policy_events={len(list(approval_summary.get('recent_policy_events') or []))}"
                ),
                detail=_json_text(approval_summary),
            ),
        ]
        if gateway_snapshot:
            rows.append(
                _row(
                    "gateway_surface",
                    "Gateway Control Surface",
                    status="ready" if gateway_snapshot.get("sessions") else "idle",
                    subtitle=(
                        f"sessions={len(gateway_snapshot.get('sessions') or [])} | "
                        f"presence={len(gateway_snapshot.get('presence') or [])} | "
                        f"pairings={len(gateway_snapshot.get('pairings') or [])}"
                    ),
                    detail=_json_text(gateway_snapshot),
                )
            )
            rows.append(
                _row(
                    "node_mesh",
                    "Node Mesh",
                    status="ready" if gateway_snapshot.get("nodes") else "idle",
                    subtitle=(
                        f"nodes={len(gateway_snapshot.get('nodes') or [])} | "
                        f"types={len(dict(gateway_snapshot.get('node_type_counts') or {}))} | "
                        f"capabilities={len(dict(gateway_snapshot.get('capability_registry') or {}))}"
                    ),
                    detail=_json_text(
                        {
                            "nodes": gateway_snapshot.get("nodes") or [],
                            "node_type_counts": gateway_snapshot.get("node_type_counts") or {},
                            "node_status_counts": gateway_snapshot.get("node_status_counts") or {},
                            "capability_registry": gateway_snapshot.get("capability_registry") or {},
                        }
                    ),
                )
            )
        return rows

    def _session_rows(self, *, user_id: str, sessions: list[dict[str, Any]]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for session in sessions:
            thread_id = str(session.get("thread_id") or "")
            rows.append(
                _row(
                    str(session.get("session_id") or thread_id),
                    thread_id or "(unknown thread)",
                    status=str(session.get("last_route") or "idle"),
                    updated_at=str(session.get("last_seen_at") or ""),
                    subtitle=f"{int(session.get('turn_count') or 0)} turns | model={session.get('last_model') or '--'}",
                    detail=self._timeline_detail(user_id=user_id, thread_id=thread_id) if thread_id else _json_text(session),
                )
            )
        return rows

    def _task_rows(self, *, user_id: str, thread_id: str) -> list[dict[str, str]]:
        task_graph_root = self._task_graph_root()
        graph = (
            load_task_graph(user_id, thread_id, root_dir=task_graph_root)
            if thread_id and task_graph_root is not None
            else (load_task_graph(user_id, thread_id) if thread_id else {"tasks": []})
        )
        rows: list[dict[str, str]] = []
        for row in list(graph.get("tasks") or [])[:24]:
            deps = list(row.get("deps") or [])
            detail_lines = [
                f"Task ID: {row.get('task_id', '')}",
                f"Thread: {thread_id}",
                f"Status: {row.get('status', 'open')}",
                f"Priority: {row.get('priority', 3)}",
                f"Source: {row.get('source', 'conversation')}",
            ]
            if deps:
                detail_lines.append(f"Dependencies: {', '.join(deps)}")
            detail_lines.append(f"Updated: {row.get('updated_at', '')}")
            rows.append(
                _row(
                    str(row.get("task_id") or row.get("title") or "task"),
                    str(row.get("title") or "Task"),
                    status=str(row.get("status") or "open"),
                    updated_at=str(row.get("updated_at") or ""),
                    subtitle=", ".join(deps[:3]) if deps else "No dependencies",
                    detail="\n".join(detail_lines),
                )
            )
        return rows

    def _continuity_rows(
        self,
        *,
        user_id: str,
        active_thread_id: str,
        sessions: list[dict[str, Any]],
        background_snapshot: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        task_graphs: dict[str, dict[str, Any]] = {}
        task_graph_root = self._task_graph_root()
        for session in list(sessions or [])[:12]:
            thread_id = str(dict(session or {}).get("thread_id") or "").strip()
            if not thread_id or thread_id in task_graphs:
                continue
            task_graphs[thread_id] = (
                load_task_graph(user_id, thread_id, root_dir=task_graph_root)
                if task_graph_root is not None
                else load_task_graph(user_id, thread_id)
            )
        ledger = build_resume_ledger(
            sessions=list(sessions or []),
            background_snapshot=dict(background_snapshot or {}),
            task_graphs=task_graphs,
            active_thread_id=active_thread_id,
            limit=8,
        )
        rows: list[dict[str, str]] = [
            _row(
                "task_resume_ledger",
                "Task Resume Ledger",
                status=str(ledger.get("status") or "idle"),
                updated_at=str(ledger.get("generated_at") or ""),
                subtitle=_clip(ledger.get("summary") or "No resumable work is queued right now.", limit=180),
                detail=_json_text(ledger),
            )
        ]
        for idx, entry in enumerate(list(ledger.get("entries") or [])[:8], start=1):
            surface_names = list(entry.get("surface_names") or [])
            detail_lines = [
                f"Thread: {entry.get('thread_id') or '--'}",
                f"Status: {entry.get('status') or 'idle'}",
                f"Surfaces: {', '.join(surface_names) or entry.get('primary_surface') or '--'}",
                f"Open tasks: {entry.get('open_task_count', 0)}",
                f"Background tasks: {entry.get('background_count', 0)}",
                f"Last route: {entry.get('last_route') or '--'}",
                f"Resume hint: {entry.get('resume_hint') or '--'}",
            ]
            rows.append(
                _row(
                    f"task_resume_entry:{idx}",
                    str(entry.get("thread_id") or f"Resume {idx}"),
                    status=str(entry.get("status") or "idle"),
                    updated_at=str(entry.get("last_seen_at") or ""),
                    subtitle=_clip(entry.get("summary") or entry.get("resume_hint") or "", limit=180),
                    detail="\n".join(detail_lines),
                )
            )
        return rows

    def _context_rows(self, *, user_id: str) -> list[dict[str, str]]:
        report = run_context_budget_status(self._project_root(), user_id=user_id, limit=8)
        rows: list[dict[str, str]] = [
            _row(
                "context_budget",
                "Context Budget",
                status=str(report.get("status") or "idle"),
                updated_at=str(report.get("generated_at") or ""),
                subtitle=_clip(report.get("summary") or "No context budget data yet", limit=180),
                detail=_json_text(report),
            )
        ]
        for idx, entry in enumerate(list(report.get("entries") or [])[:8], start=1):
            detail_lines = [
                f"Thread: {entry.get('thread_id') or '--'}",
                f"Surface: {entry.get('surface') or '--'}",
                f"Turns: {entry.get('turn_count', 0)}",
                f"Estimated tokens: {entry.get('estimated_tokens', 0)}",
                f"Compactions: {entry.get('compaction_count', 0)}",
                f"Open loops: {entry.get('open_loop_count', 0)}",
                f"Unresolved asks: {entry.get('unresolved_count', 0)}",
                f"Last route: {entry.get('last_route') or '--'}",
                f"Status note: {entry.get('status_note') or '--'}",
            ]
            if entry.get("last_compacted_at"):
                detail_lines.append(f"Last compacted: {entry.get('last_compacted_at')}")
            if entry.get("latest_compaction_summary"):
                detail_lines.append("")
                detail_lines.append("Latest compaction summary:")
                detail_lines.append(str(entry.get("latest_compaction_summary") or ""))
            rows.append(
                _row(
                    f"context_thread:{idx}",
                    str(entry.get("thread_id") or f"Context {idx}"),
                    status=str(entry.get("status") or "idle"),
                    updated_at=str(entry.get("last_seen_at") or entry.get("last_compacted_at") or ""),
                    subtitle=_clip(entry.get("summary") or entry.get("status_note") or "", limit=180),
                    detail="\n".join(detail_lines),
                )
            )
        return rows

    def _subagent_rows(self, *, user_id: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        snapshots = self.subagent_status_store.list_snapshots(user_id=user_id, limit=20)
        for row in snapshots:
            rows.append(
                _row(
                    str(row.get("run_id") or "subagent"),
                    str(row.get("profile_key") or "subagent"),
                    status=str(row.get("status") or "queued"),
                    updated_at=str(row.get("updated_at") or row.get("started_at") or ""),
                    subtitle=_clip(row.get("objective"), limit=140),
                    detail=_json_text(row),
                )
            )
        return rows

    def _workflow_rows(self, *, user_id: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for manifest in self.workflow_manifest_store.list_manifests()[:12]:
            rows.append(
                _row(
                    f"manifest:{manifest.manifest_id}",
                    manifest.name,
                    status="ready",
                    updated_at="",
                    subtitle=f"backend={manifest.backend} | tools={len(manifest.allowed_tools)}",
                    detail=_json_text(manifest.to_dict()),
                )
            )
        for row in self.workflow_store.list_snapshots(user_id=user_id, limit=12):
            rows.append(
                _row(
                    str(row.get("run_id") or "workflow"),
                    str(row.get("manifest_name") or row.get("manifest_id") or row.get("run_id") or "workflow"),
                    status=str(row.get("status") or "completed"),
                    updated_at=str(row.get("updated_at") or row.get("started_at") or ""),
                    subtitle=_clip(row.get("summary") or row.get("thread_id") or "", limit=160),
                    detail=_json_text(row),
                )
            )
        return rows[:24]

    def _action_rows(self, *, user_id: str, thread_id: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        thread_filter = str(thread_id or "")
        for row in self.ontology.list_actions(owner_user_id=user_id, thread_id=thread_filter, limit=32):
            attrs = dict(row.get("attributes") or {})
            approvals = [dict(item) for item in list(attrs.get("approval_chain") or []) if isinstance(item, dict)]
            rows.append(
                _row(
                    str(row.get("object_id") or "action"),
                    str(row.get("label") or attrs.get("action_type") or "Action"),
                    status=str(row.get("status") or "pending"),
                    updated_at=str(row.get("updated_at") or ""),
                    subtitle=f"{attrs.get('target_kind') or '--'} -> {attrs.get('target_id') or '--'}",
                    detail=_json_text({"action": row, "approvals": approvals}),
                )
            )
        return rows

    def _artifact_rows(self, *, user_id: str, thread_id: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        objects = self.ontology.store.list_objects(
            kind="Artifact",
            owner_user_id=user_id,
            thread_id=thread_id if thread_id else None,
            limit=20,
        )
        for row in objects:
            attrs = dict(row.get("attributes") or {})
            rows.append(
                _row(
                    str(row.get("object_id") or "artifact"),
                    str(row.get("label") or "Artifact"),
                    status=str(row.get("status") or "active"),
                    updated_at=str(row.get("updated_at") or ""),
                    subtitle=_clip(attrs.get("artifact_type") or attrs.get("path") or row.get("source") or "", limit=160),
                    detail=_json_text(row),
                )
            )
        if rows:
            return rows

        artifact_file = self.artifacts_root / f"{user_id}.jsonl"
        for idx, entry in enumerate(reversed(_read_recent_jsonl(artifact_file, limit=12)), start=1):
            item_thread = str(entry.get("thread_id") or entry.get("data", {}).get("thread_id") or "")
            if thread_id and item_thread and item_thread != thread_id:
                continue
            rows.append(
                _row(
                    f"artifact_fallback:{idx}",
                    str(entry.get("artifact_type") or entry.get("contract_name") or entry.get("artifact_id") or "Artifact"),
                    status=str(entry.get("status") or "recorded"),
                    updated_at=str(entry.get("updated_at") or entry.get("created_at") or ""),
                    subtitle=_clip(entry.get("summary") or entry.get("current_state_summary") or "", limit=160),
                    detail=_json_text(entry),
                )
            )
        return rows

    def _job_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        history_dir = self.jobs_root / "history"
        if history_dir.exists():
            for path in sorted(history_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:16]:
                payload = _read_json(path)
                if not payload:
                    continue
                job_id = str(payload.get("job_id") or path.stem)
                audit_report = verify_audit_path(Path("sessions/jobs") / job_id / "audit.jsonl")
                detail = {
                    "job": payload,
                    "audit": audit_report,
                }
                rows.append(
                    _row(
                        job_id,
                        str(payload.get("objective") or job_id),
                        status=str(payload.get("state") or "unknown"),
                        updated_at=str(payload.get("updated_at") or payload.get("created_at") or ""),
                        subtitle=f"phase={payload.get('phase') or '--'}",
                        detail=_json_text(detail),
                    )
                )
        return rows

    def _automation_rows(self, *, user_id: str) -> list[dict[str, str]]:
        runs = self.automation_store.list_runs(user_id=user_id, limit=24)
        runs_by_automation: dict[str, list[dict[str, Any]]] = {}
        for row in runs:
            runs_by_automation.setdefault(str(row.get("automation_id") or ""), []).append(row)

        status_page = self.automation_engine.render_status_page(user_id=user_id, limit=12)
        rows: list[dict[str, str]] = []
        for row in self.automation_store.list_automations(user_id=user_id, limit=16):
            automation_id = str(row.get("automation_id") or "")
            recent_runs = runs_by_automation.get(automation_id, [])[:4]
            detail = {
                "automation": row,
                "recent_runs": recent_runs,
                "status_page": status_page,
            }
            rows.append(
                _row(
                    automation_id,
                    str(row.get("name") or automation_id or "automation"),
                    status=str(row.get("status") or "ACTIVE"),
                    updated_at=str(row.get("updated_at") or row.get("last_run_at") or ""),
                    subtitle=f"{row.get('automation_type') or 'task'} via {row.get('target_channel') or 'desktop'} | next {row.get('next_run_at') or '--'}",
                    detail=_json_text(detail),
                )
            )
        return rows

    def _channel_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for channel_name in self.delivery_gateway.list_channels():
            inbox = self.delivery_gateway.list_messages(channel_name, box="inbox", limit=5)
            outbox = self.delivery_gateway.list_messages(channel_name, box="outbox", limit=5)
            queue = self.delivery_gateway.list_messages(channel_name, box="queue", limit=5)
            latest = (outbox or inbox or queue or [{}])[-1]
            detail = {
                "channel": channel_name,
                "counts": {
                    "inbox": len(inbox),
                    "outbox": len(outbox),
                    "queue": len(queue),
                },
                "recent_inbox": inbox,
                "recent_outbox": outbox,
                "recent_queue": queue,
            }
            rows.append(
                _row(
                    channel_name,
                    channel_name,
                    status="ready" if (inbox or outbox or queue) else "idle",
                    updated_at=str(latest.get("delivered_at") or latest.get("created_at") or ""),
                    subtitle=f"inbox={len(inbox)} | outbox={len(outbox)} | queue={len(queue)}",
                    detail=_json_text(detail),
                )
            )
        return rows

    def _memory_rows(self, *, user_id: str) -> list[dict[str, str]]:
        store = self.memory_manager.store
        hygiene = self.memory_manager.run_hygiene_check(user_id)
        profile_rows = store.latest_by_scope(user_id, "profile", limit=6)
        preference_rows = store.latest_by_scope(user_id, "preferences", limit=6)
        summary_row = store.latest_session_summary(user_id) or {}
        pinned_rows = store.pinned_items(user_id, limit=8)
        recent_events = store.recent_events(user_id, limit=10)
        frozen_snapshot = self.memory_manager.frozen_store.read_snapshot(user_id) or {}
        retrieval_trace = store.latest_retrieval_trace(user_id) or {}
        preference_graph = self.memory_manager.build_preference_graph_sync(user_id, limit=12)
        memory_review_builder = getattr(self.memory_manager, "build_memory_review_sync", None)
        try:
            memory_review = memory_review_builder(user_id, limit=6) if callable(memory_review_builder) else {}
        except Exception:
            memory_review = {}
        if not isinstance(memory_review, dict):
            memory_review = {}
        vault_service = getattr(self.memory_manager, "vault", None)
        vault_summary = vault_service.source_summary(user_id) if vault_service is not None else {"total_sources": 0, "total_items": 0}
        vault_sources = vault_service.list_sources(user_id, limit=8) if vault_service is not None else []
        lane_counts = dict(memory_review.get("lane_counts") or {}) if isinstance(memory_review, dict) else {}
        top_lanes = ", ".join(
            f"{name}={count}"
            for name, count in sorted(lane_counts.items(), key=lambda item: (-int(item[1]), str(item[0])))[:3]
            if int(count or 0) > 0
        )
        next_action = str((list(memory_review.get("suggested_actions") or [])[:1] or [""])[0]).replace("_", " ").strip()
        memory_review_subtitle = str(memory_review.get("summary") or "No memory review data yet")
        if top_lanes:
            memory_review_subtitle += f" | lanes={top_lanes}"
        if next_action:
            memory_review_subtitle += f" | next={next_action}"
        return [
            _row(
                "memory_hygiene",
                "Memory Hygiene",
                status="warn" if int(hygiene.get("scan_issue_count") or 0) > 0 or int(memory_review.get("alert_count") or 0) > 0 else "ready",
                updated_at=str(frozen_snapshot.get("updated_at") or ""),
                subtitle=(
                    f"expired={hygiene.get('expired_count', 0)} | "
                    f"issues={hygiene.get('scan_issue_count', 0)} | "
                    f"review={memory_review.get('status', hygiene.get('review_status', 'idle'))}"
                ),
                detail=_json_text(hygiene),
            ),
            _row(
                "memory_review",
                "Memory Review Queue",
                status="warn" if int(memory_review.get("alert_count") or 0) > 0 else ("ready" if memory_review else "idle"),
                updated_at=str(memory_review.get("generated_at") or ""),
                subtitle=_clip(memory_review_subtitle, limit=160),
                detail=_json_text(memory_review),
            ),
            _row(
                "memory_profile",
                "Curated Profile",
                status="ready",
                updated_at="",
                subtitle=", ".join(_clip(row.get("value"), limit=40) for row in profile_rows[:3]) or "No profile facts yet",
                detail=_json_text(profile_rows),
            ),
            _row(
                "memory_preferences",
                "Curated Preferences",
                status="ready",
                updated_at="",
                subtitle=", ".join(_clip(row.get("value"), limit=40) for row in preference_rows[:3]) or "No preferences yet",
                detail=_json_text(preference_rows),
            ),
            _row(
                "memory_preference_graph",
                "Preference Graph",
                status="ready" if int(preference_graph.get("node_count") or 0) > 0 else "idle",
                updated_at=str(preference_graph.get("updated_at") or ""),
                subtitle=_clip(preference_graph.get("summary") or "No preference graph yet", limit=160),
                detail=_json_text(preference_graph),
            ),
            _row(
                "memory_summary",
                "Working Session Summary",
                status="ready" if summary_row else "idle",
                updated_at=str(summary_row.get("updated_at") or ""),
                subtitle=_clip(summary_row.get("text") or "No working session summary yet", limit=160),
                detail=_json_text(summary_row),
            ),
            _row(
                "memory_frozen",
                "Frozen Prompt Snapshot",
                status="ready" if frozen_snapshot else "idle",
                updated_at=str(frozen_snapshot.get("updated_at") or ""),
                subtitle=_clip(frozen_snapshot.get("query") or "No frozen snapshot yet", limit=160),
                detail=_json_text(frozen_snapshot),
            ),
            _row(
                "memory_recent_events",
                "Recent Memory Events",
                status="ready",
                updated_at="",
                subtitle=f"{len(recent_events)} recent events | {len(pinned_rows)} pinned facts",
                detail=_json_text({"pinned": pinned_rows, "recent_events": recent_events}),
            ),
            _row(
                "memory_vault",
                "Knowledge Vault",
                status="ready" if int(vault_summary.get("total_sources") or 0) > 0 else "idle",
                updated_at=str((vault_sources[0] or {}).get("updated_at") or "") if vault_sources else "",
                subtitle=(
                    f"sources={vault_summary.get('total_sources', 0)} | "
                    f"items={vault_summary.get('total_items', 0)} | "
                    f"types={','.join(sorted(dict(vault_summary.get('by_type') or {}).keys())[:3]) or '--'}"
                ),
                detail=_json_text({"summary": vault_summary, "sources": vault_sources}),
            ),
            _row(
                "memory_explainability",
                "Retrieval Explainability",
                status="ready" if retrieval_trace else "idle",
                updated_at=str(retrieval_trace.get("created_at") or ""),
                subtitle=_clip(
                    dict(retrieval_trace.get("trace") or {}).get("query") or frozen_snapshot.get("query") or "No retrieval trace yet",
                    limit=160,
                ),
                detail=_json_text(retrieval_trace),
            ),
        ]

    def _observability_rows(
        self,
        *,
        ops_snapshot: dict[str, Any],
        release_report: dict[str, Any] | None,
        freeze_report: dict[str, Any] | None,
        offline_report: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        tool_metrics = dict(ops_snapshot.get("tool_metrics") or {})
        model_metrics = dict(ops_snapshot.get("model_metrics") or {})
        background_tasks = dict(ops_snapshot.get("background_tasks") or {})
        skill_apprenticeship = dict(ops_snapshot.get("skill_apprenticeship") or {})
        observability = build_observability_digest(ops_snapshot)
        rows.append(
            _row(
                "ops_metrics",
                "Runtime Metrics",
                status="ready" if (tool_metrics or model_metrics) else "idle",
                subtitle=(
                    f"tools={tool_metrics.get('successes', 0)}/{tool_metrics.get('total', 0)} ok | "
                    f"avg_latency_ms={model_metrics.get('average_latency_ms', 0.0)} | "
                    f"alerts={observability.get('alert_count', 0)}"
                ),
                detail=_json_text(ops_snapshot),
            )
        )
        if list(observability.get("tool_hotspots") or []) or list(observability.get("model_hotspots") or []):
            top_tool = dict((list(observability.get("tool_hotspots") or []) or [{}])[0])
            top_model = dict((list(observability.get("model_hotspots") or []) or [{}])[0])
            hotspot_bits: list[str] = []
            if top_tool:
                hotspot_bits.append(
                    f"tool={top_tool.get('tool_name', '--')}:{int(float(top_tool.get('average_latency_ms') or 0.0))}ms"
                )
            if top_model:
                hotspot_bits.append(
                    f"model={top_model.get('model_name', '--')}:{int(float(top_model.get('average_latency_ms') or 0.0))}ms"
                )
            rows.append(
                _row(
                    "latency_hotspots",
                    "Latency Hotspots",
                    status=str(observability.get("status") or "idle"),
                    updated_at=str(observability.get("generated_at") or ""),
                    subtitle=" | ".join(hotspot_bits) or "No active latency hotspots",
                    detail=_json_text(observability),
                )
            )
        if background_tasks:
            counts = dict(background_tasks.get("counts") or {})
            rows.append(
                _row(
                    "background_tasks",
                    "Background Task Queue",
                    status=(
                        "warn"
                        if int(background_tasks.get("retry_ready_count") or 0) > 0 or int(background_tasks.get("failed_count") or 0) > 0
                        else ("running" if int(background_tasks.get("running_count") or 0) > 0 else "idle")
                    ),
                    updated_at=str(background_tasks.get("updated_at") or ""),
                    subtitle=(
                        f"running={background_tasks.get('running_count', 0)} | "
                        f"retry_ready={background_tasks.get('retry_ready_count', 0)} | "
                        f"failed={background_tasks.get('failed_count', 0)}"
                    ),
                    detail=_json_text({"queue": background_tasks, "counts": counts}),
                )
            )
        if list(observability.get("failure_hotspots") or []) or int(observability.get("recovery_pressure") or 0) > 0:
            top_failure = dict((list(observability.get("failure_hotspots") or []) or [{}])[0])
            rows.append(
                _row(
                    "recovery_watchlist",
                    "Recovery Watchlist",
                    status="warn" if int(observability.get("recovery_pressure") or 0) > 0 else str(observability.get("status") or "ready"),
                    updated_at=str(observability.get("generated_at") or ""),
                    subtitle=(
                        f"recovery_pressure={observability.get('recovery_pressure', 0)} | "
                        f"top={top_failure.get('kind', '--')}::{top_failure.get('name', '--')}"
                    ),
                    detail=_json_text(observability),
                )
            )
        if skill_apprenticeship:
            suggestions = list(skill_apprenticeship.get("suggestions") or [])
            rows.append(
                _row(
                    "skill_apprenticeship",
                    "Skill Apprenticeship",
                    status="ready" if suggestions else "idle",
                    updated_at=str(skill_apprenticeship.get("updated_at") or ""),
                    subtitle=(
                        f"approval_required={skill_apprenticeship.get('approval_required_count', 0)} | "
                        f"draft_ready={skill_apprenticeship.get('draft_ready_count', 0)}"
                    ),
                    detail=_json_text(skill_apprenticeship),
                )
            )
        if offline_report:
            rows.append(
                _row(
                    "offline_resilience",
                    "Offline Resilience",
                    status=str(offline_report.get("readiness") or ("ready" if offline_report.get("ok") else "blocked")),
                    subtitle=(
                        f"packs={dict(offline_report.get('knowledge_packs') or {}).get('pack_count', 0)} | "
                        f"agentpedia={offline_report.get('agentpedia_pages_count', 0)} | "
                        f"cache={offline_report.get('evidence_cache_records', 0)}"
                    ),
                    detail=_json_text(offline_report),
                )
            )

        if release_report:
            blockers = list(release_report.get("blockers") or [])
            warnings = list(release_report.get("warnings") or [])
            dashboards = list(release_report.get("subsystem_dashboards") or [])
            diff = dict(release_report.get("diff_to_previous") or {})
            finality = dict(release_report.get("finality_lab") or {})
            champion = dict(release_report.get("champion_scorecard") or {})
            rows.append(
                _row(
                    "release_gate",
                    "Release Gate",
                    status=str(release_report.get("status") or "idle"),
                    updated_at=str(release_report.get("generated_at") or ""),
                    subtitle=(
                        f"score={release_report.get('readiness_score', 0.0)} | "
                        f"blockers={len(blockers)} | warnings={len(warnings)}"
                    ),
                    detail=_json_text(release_report),
                )
            )
            rows.append(
                _row(
                    "subsystem_dashboards",
                    "Subsystem Dashboards",
                    status="ready" if dashboards else "idle",
                    updated_at=str(release_report.get("generated_at") or ""),
                    subtitle=", ".join(
                        f"{row.get('label', 'Subsystem')}={row.get('status', 'idle')}" for row in dashboards[:5]
                    )
                    or "No dashboards captured yet",
                    detail=_json_text(dashboards),
                )
            )
            rows.append(
                _row(
                    "benchmark_diff",
                    "Benchmark Diff",
                    status="ready" if diff.get("ok") else "idle",
                    updated_at=str(dict(diff.get("current") or {}).get("generated_at") or release_report.get("generated_at") or ""),
                    subtitle=(
                        f"readiness_delta={dict(diff.get('summary') or {}).get('readiness_delta', 0.0)} | "
                        f"eval_delta={dict(diff.get('summary') or {}).get('eval_score_delta', 0.0)}"
                    )
                    if diff
                    else "No prior release snapshot to diff against",
                    detail=_json_text(diff or {"message": "No prior release snapshot to diff against."}),
                )
            )
            if finality:
                rows.append(
                    _row(
                        "finality_lab",
                        "Finality Lab",
                        status="ready" if bool(finality.get("available")) else "idle",
                        updated_at=str(finality.get("generated_at") or release_report.get("generated_at") or ""),
                        subtitle=(
                            f"measured={finality.get('measured_count', 0)}/{finality.get('pack_count', 0)} | "
                            f"difficulty={finality.get('difficulty', '--')}"
                        ),
                        detail=_json_text(finality),
                    )
                )
            if champion:
                rows.append(
                    _row(
                        "champion_scorecard",
                        "Champion Scorecard",
                        status="ready",
                        updated_at=str(champion.get("generated_at") or release_report.get("generated_at") or ""),
                        subtitle=(
                            f"ahead={champion.get('ahead_count', 0)} | "
                            f"verdict={champion.get('overall_verdict', '')}"
                        ),
                        detail=_json_text(champion),
                    )
                )
            if freeze_report:
                rows.append(
                    _row(
                        "framework_freeze",
                        "Framework Freeze",
                        status=str(freeze_report.get("core_status") or "idle"),
                        updated_at=str(freeze_report.get("generated_at") or ""),
                        subtitle=(
                            f"core_ready={bool(freeze_report.get('framework_core_ready'))} | "
                            f"packaging_ready={bool(freeze_report.get('packaging_ready'))}"
                        ),
                        detail=_json_text(freeze_report),
                    )
                )
            return rows

        if freeze_report:
            rows.append(
                _row(
                    "framework_freeze",
                    "Framework Freeze",
                    status=str(freeze_report.get("core_status") or "idle"),
                    updated_at=str(freeze_report.get("generated_at") or ""),
                    subtitle=(
                        f"core_ready={bool(freeze_report.get('framework_core_ready'))} | "
                        f"packaging_ready={bool(freeze_report.get('packaging_ready'))}"
                    ),
                    detail=_json_text(freeze_report),
                )
            )

        rows.append(
            _row(
                "release_gate",
                "Release Gate",
                status="idle",
                subtitle="No persisted release report yet",
                detail="Run `python somi.py release gate` to capture a release-readiness snapshot.",
            )
        )
        return rows

    def _error_rows(
        self,
        *,
        user_id: str,
        subagent_rows: list[dict[str, str]],
        workflow_rows: list[dict[str, str]],
        automation_rows: list[dict[str, str]],
        job_rows: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        tool_failures = self.state_store.list_recent_events(user_id=user_id, event_type="tool_failed", limit=10)
        for row in tool_failures:
            rows.append(
                _row(
                    f"tool_failed:{row.get('event_id')}",
                    str(row.get("event_name") or "tool_failed"),
                    status="failed",
                    updated_at=str(row.get("created_at") or ""),
                    subtitle=_clip(row.get("payload"), limit=140),
                    detail=_json_text(row),
                )
            )
        for bucket in (subagent_rows, workflow_rows, automation_rows, job_rows):
            for row in bucket:
                status = str(row.get("status") or "").lower()
                if status in {"failed", "error", "cancelled", "blocked"}:
                    rows.append(dict(row))
        if rows:
            return rows[:24]
        return [
            _row(
                "no_errors",
                "No critical errors",
                status="steady",
                subtitle="Recent tools, workflows, automations, and jobs are healthy.",
                detail="No recent failures were found in the control-room inspection surfaces.",
            )
        ]

    def build(
        self,
        *,
        user_id: str = "default_user",
        thread_id: str = "",
        agent_name: str = "",
        model_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        model_snapshot = dict(model_snapshot or {})
        sessions = self.state_store.list_sessions(user_id=user_id, limit=12)
        active_thread_id = str(thread_id or "")
        if not active_thread_id and sessions:
            active_thread_id = str(sessions[0].get("thread_id") or "")

        if active_thread_id:
            try:
                self.ontology.refresh_thread(user_id=user_id, thread_id=active_thread_id, force=True)
            except Exception:
                pass

        ontology_objects = self.ontology.store.list_objects(owner_user_id=user_id, limit=250)
        ontology_counts: dict[str, int] = {}
        for item in ontology_objects:
            kind = str(item.get("kind") or "Unknown")
            ontology_counts[kind] = ontology_counts.get(kind, 0) + 1
        ops_snapshot = self.ops_control.snapshot(event_limit=12, metric_limit=24) if self.ops_control is not None else {}
        gateway_snapshot = self.gateway_service.snapshot(limit=8) if self.gateway_service is not None else {}
        project_root = self._project_root()
        release_report = load_latest_release_report(project_root)
        freeze_report = load_latest_framework_freeze(project_root)
        offline_report = run_offline_resilience(project_root)
        context_rows = self._context_rows(user_id=user_id)
        observability = build_observability_digest(ops_snapshot)

        config_rows = self._config_rows(
            user_id=user_id,
            thread_id=active_thread_id,
            agent_name=agent_name,
            model_snapshot=model_snapshot,
            ontology_counts=ontology_counts,
            gateway_snapshot=gateway_snapshot,
        )
        session_rows = self._session_rows(user_id=user_id, sessions=sessions)
        task_rows = self._task_rows(user_id=user_id, thread_id=active_thread_id)
        continuity_rows = self._continuity_rows(
            user_id=user_id,
            active_thread_id=active_thread_id,
            sessions=sessions,
            background_snapshot=dict(ops_snapshot.get("background_tasks") or {}),
        )
        subagent_rows = self._subagent_rows(user_id=user_id)
        workflow_rows = self._workflow_rows(user_id=user_id)
        action_rows = self._action_rows(user_id=user_id, thread_id=active_thread_id)
        artifact_rows = self._artifact_rows(user_id=user_id, thread_id=active_thread_id)
        job_rows = self._job_rows()
        automation_rows = self._automation_rows(user_id=user_id)
        channel_rows = self._channel_rows()
        memory_rows = self._memory_rows(user_id=user_id)
        observability_rows = self._observability_rows(
            ops_snapshot=ops_snapshot,
            release_report=release_report,
            freeze_report=freeze_report,
            offline_report=offline_report,
        )
        error_rows = self._error_rows(
            user_id=user_id,
            subagent_rows=subagent_rows,
            workflow_rows=workflow_rows,
            automation_rows=automation_rows,
            job_rows=job_rows,
        )

        overview_lines = [
            "SOMI Agent Studio / Control Room",
            f"Updated: {_now_iso()}",
            f"User: {user_id}",
            f"Active thread: {active_thread_id or '(latest session)'}",
            f"Persona: {agent_name or 'Somi'}",
            f"Model: {model_snapshot.get('DEFAULT_MODEL', '--')}",
            f"Capability profile: {model_snapshot.get('MODEL_CAPABILITY_PROFILE', '--')}",
            f"Runtime profile: {dict(ops_snapshot.get('active_profile') or {}).get('profile_id', '--')}",
            f"Autonomy profile: {dict(ops_snapshot.get('active_autonomy_profile') or {}).get('profile_id', '--')}",
            "",
            "Coverage:",
            f"- Sessions: {len(session_rows)}",
            f"- Tasks: {len(task_rows)}",
            f"- Resume continuity: {len(continuity_rows)}",
            f"- Subagents: {len(subagent_rows)}",
            f"- Workflow surfaces: {len(workflow_rows)}",
            f"- Actions: {len(action_rows)}",
            f"- Artifacts: {len(artifact_rows)}",
            f"- Jobs: {len(job_rows)}",
            f"- Automations: {len(automation_rows)}",
            f"- Channels: {len(channel_rows)}",
            f"- Gateway sessions: {len(gateway_snapshot.get('sessions') or [])}",
            f"- Nodes: {len(gateway_snapshot.get('nodes') or [])}",
            f"- Memory surfaces: {len(memory_rows)}",
            f"- Context surfaces: {len(context_rows)}",
            f"- Observability surfaces: {len(observability_rows)}",
            f"- Recent errors: {0 if error_rows and error_rows[0].get('id') == 'no_errors' else len(error_rows)}",
            f"- Policy decisions: {sum(int(v or 0) for v in dict(ops_snapshot.get('policy_decision_counts') or {}).values())}",
            (
                f"- Background tasks: {int(dict(ops_snapshot.get('background_tasks') or {}).get('running_count') or 0)} running / "
                f"{int(dict(ops_snapshot.get('background_tasks') or {}).get('retry_ready_count') or 0)} retry_ready / "
                f"{int(dict(ops_snapshot.get('background_tasks') or {}).get('failed_count') or 0)} failed"
            ),
            (
                f"- Skill apprenticeship: "
                f"{int(dict(ops_snapshot.get('skill_apprenticeship') or {}).get('approval_required_count') or 0)} approval-needed / "
                f"{int(dict(ops_snapshot.get('skill_apprenticeship') or {}).get('draft_ready_count') or 0)} draft-ready"
            ),
            (
                f"- Context budget: {str((context_rows[0] or {}).get('status') or 'idle')} "
                f"({(context_rows[0] or {}).get('subtitle') or '--'})"
            ),
            (
                f"- Offline resilience: {offline_report.get('readiness', 'blocked')} "
                f"(packs={dict(offline_report.get('knowledge_packs') or {}).get('pack_count', 0)}, "
                f"agentpedia={offline_report.get('agentpedia_pages_count', 0)}, "
                f"cache={offline_report.get('evidence_cache_records', 0)})"
            ),
            (
                f"- Observability: {observability.get('status', 'idle')} "
                f"(alerts={observability.get('alert_count', 0)}, "
                f"recovery_pressure={observability.get('recovery_pressure', 0)})"
            ),
        ]
        if release_report:
            overview_lines.append(f"- Release gate: {release_report.get('status', 'idle')} ({release_report.get('readiness_score', 0.0)})")
        if freeze_report:
            overview_lines.append(
                f"- Framework freeze: {freeze_report.get('core_status', 'idle')} "
                f"(packaging_ready={bool(freeze_report.get('packaging_ready'))})"
            )
        overview_lines.extend(["", "Ontology kinds:"])
        if ontology_counts:
            overview_lines.extend(f"- {kind}: {count}" for kind, count in sorted(ontology_counts.items()))
        else:
            overview_lines.append("- No projected objects yet")

        summary_cards = [
            {"label": "Sessions", "value": str(len(session_rows)), "hint": active_thread_id or "latest"},
            {"label": "Tasks", "value": str(len(task_rows)), "hint": "task graph"},
            {
                "label": "Resume",
                "value": str(max(0, len(continuity_rows) - 1 if continuity_rows else 0)),
                "hint": str((continuity_rows[0] or {}).get("status") or "idle") if continuity_rows else "idle",
            },
            {"label": "Automations", "value": str(len(automation_rows)), "hint": "scheduler"},
            {"label": "Channels", "value": str(len(channel_rows)), "hint": "delivery + gateway"},
            {"label": "Workflows", "value": str(len(workflow_rows)), "hint": "runs + manifests"},
            {
                "label": "Context",
                "value": str(max(0, len(context_rows) - 1 if context_rows else 0)),
                "hint": str((context_rows[0] or {}).get("status") or "idle") if context_rows else "idle",
            },
            {
                "label": "Errors",
                "value": str(0 if error_rows and error_rows[0].get("id") == "no_errors" else len(error_rows)),
                "hint": "recent failures",
            },
        ]

        return {
            "updated_at": _now_iso(),
            "user_id": user_id,
            "thread_id": active_thread_id,
            "overview_text": "\n".join(overview_lines),
            "summary_cards": summary_cards,
            "tabs": {
                "config": config_rows,
                "sessions": session_rows,
                "tasks": task_rows,
                "continuity": continuity_rows,
                "subagents": subagent_rows,
                "workflows": workflow_rows,
                "actions": action_rows,
                "artifacts": artifact_rows,
                "jobs": job_rows,
                "automations": automation_rows,
                "channels": channel_rows,
                "memory": memory_rows,
                "context": context_rows,
                "observability": observability_rows,
                "errors": error_rows,
            },
        }
