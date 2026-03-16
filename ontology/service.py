from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from executive.memory.store import SQLiteMemoryStore
from runtime.task_graph import load_task_graph
from state import SessionEventStore

from .schema import OntologyLink, OntologyObject, normalize_status
from .store import OntologyStore


def _clip(text: Any, *, limit: int = 140) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


class SomiOntology:
    def __init__(
        self,
        *,
        store: OntologyStore | None = None,
        state_store: SessionEventStore | None = None,
        memory_store: SQLiteMemoryStore | None = None,
        automation_store=None,
        gateway_service=None,
        task_graph_root: str | Path = "sessions/task_graph",
        artifacts_root: str | Path = "sessions/artifacts",
        jobs_root: str | Path = "jobs",
        refresh_ttl_seconds: float = 2.0,
    ) -> None:
        self.store = store or OntologyStore()
        self.state_store = state_store or SessionEventStore()
        self.memory_store = memory_store or SQLiteMemoryStore()
        self.automation_store = automation_store
        self.gateway_service = gateway_service
        self.task_graph_root = str(task_graph_root)
        self.artifacts_root = Path(artifacts_root)
        self.jobs_root = Path(jobs_root)
        self.refresh_ttl_seconds = max(0.0, float(refresh_ttl_seconds or 0.0))
        self._last_refresh: dict[str, float] = {}

    def _key(self, user_id: str, thread_id: str) -> str:
        return f"{str(user_id)}::{str(thread_id)}"

    def _user_object_id(self, user_id: str) -> str:
        return f"user:{user_id}"

    def _conversation_object_id(self, user_id: str, thread_id: str) -> str:
        return f"conversation:{user_id}:{thread_id}"

    def _task_object_id(self, task_id: str) -> str:
        return f"task:{task_id}"

    def _goal_object_id(self, title: str) -> str:
        return f"goal:{title.strip().lower()}"

    def _reminder_object_id(self, reminder_id: str) -> str:
        return f"reminder:{reminder_id}"

    def _artifact_object_id(self, artifact_id: str) -> str:
        return f"artifact:{artifact_id}"

    def _job_object_id(self, job_id: str) -> str:
        return f"job:{job_id}"

    def _system_object_id(self, name: str) -> str:
        return f"system:{name}"

    def _channel_object_id(self, name: str) -> str:
        return f"channel:{name}"

    def _automation_object_id(self, automation_id: str) -> str:
        return f"automation:{automation_id}"

    def _node_object_id(self, node_id: str) -> str:
        return f"node:{node_id}"

    def _action_object_id(self, target_id: str, action_type: str) -> str:
        return f"action:{target_id}:{action_type}"

    def _runbook_spec(self, kind: str) -> list[dict[str, Any]]:
        specs = {
            "Task": [
                {"action_type": "task_review", "label": "Review Task", "risk_level": "low", "requires_approval": False, "runbook_id": "task.review"},
                {"action_type": "task_complete", "label": "Mark Task Done", "risk_level": "medium", "requires_approval": True, "runbook_id": "task.complete"},
            ],
            "Artifact": [
                {"action_type": "artifact_publish", "label": "Publish Artifact", "risk_level": "medium", "requires_approval": True, "runbook_id": "artifact.publish"},
            ],
            "Job": [
                {"action_type": "job_replay", "label": "Replay Job", "risk_level": "medium", "requires_approval": True, "runbook_id": "job.replay"},
            ],
            "Automation": [
                {"action_type": "automation_pause", "label": "Pause Automation", "risk_level": "medium", "requires_approval": True, "runbook_id": "automation.pause"},
            ],
            "Node": [
                {"action_type": "node_revoke", "label": "Revoke Node", "risk_level": "high", "requires_approval": True, "runbook_id": "node.revoke"},
            ],
        }
        return [dict(item) for item in list(specs.get(str(kind or ""), []))]

    def _iter_recent_jsonl(self, path: Path, *, max_rows: int = 40) -> list[dict[str, Any]]:
        rows: deque[dict[str, Any]] = deque(maxlen=max_rows)
        if not path.exists():
            return []
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

    def _upsert_baseline_systems(self, *, user_id: str, thread_id: str) -> None:
        systems = [
            ("state_plane", "online"),
            ("workflow_runtime", "online"),
            ("heartbeat", "online"),
        ]
        channels = [
            ("desktop", "enabled"),
            ("telegram", "queued"),
        ]
        for name, status in systems:
            self.store.upsert_object(
                OntologyObject(
                    object_id=self._system_object_id(name),
                    kind="System",
                    label=name,
                    status=status,
                    owner_user_id=user_id,
                    thread_id="",
                    source="baseline",
                    attributes={"thread_id": thread_id},
                )
            )
        for name, status in channels:
            self.store.upsert_object(
                OntologyObject(
                    object_id=self._channel_object_id(name),
                    kind="Channel",
                    label=name,
                    status=status,
                    owner_user_id=user_id,
                    thread_id="",
                    source="baseline",
                    attributes={"thread_id": thread_id},
                )
            )

    def refresh_thread(self, *, user_id: str, thread_id: str, force: bool = False) -> None:
        cache_key = self._key(user_id, thread_id)
        now = time.monotonic()
        if not force and (now - float(self._last_refresh.get(cache_key, 0.0) or 0.0)) < self.refresh_ttl_seconds:
            return

        timeline = self.state_store.load_session_timeline(user_id=str(user_id), thread_id=str(thread_id))
        session = dict(timeline.get("session") or {})
        turns = list(timeline.get("turns") or [])
        graph = load_task_graph(str(user_id), str(thread_id), root_dir=self.task_graph_root)
        reminders = self.memory_store.active_reminders(str(user_id), scope="task", limit=200)
        goal_ids = self.memory_store.fts_search(str(user_id), "goal", limit=120)
        goals = []
        for row in self.memory_store.get_items_by_ids(str(user_id), goal_ids):
            if row.get("type") == "fact" and row.get("mkey") == "goal" and row.get("status") == "active":
                value = str(row.get("value") or "").strip()
                if value and not value.lower().startswith("retracted:"):
                    goals.append(value)

        self.store.delete_scope(owner_user_id=str(user_id), thread_id=str(thread_id), kinds=["Conversation", "Task", "Artifact", "Action"])
        self.store.delete_scope(owner_user_id=str(user_id), thread_id="", kinds=["Goal", "Reminder", "Job", "System", "Channel", "Automation", "Node"])

        user_object_id = self._user_object_id(str(user_id))
        conversation_object_id = self._conversation_object_id(str(user_id), str(thread_id))

        self.store.upsert_object(
            OntologyObject(
                object_id=user_object_id,
                kind="User",
                label=str(user_id),
                status="active",
                owner_user_id=str(user_id),
                thread_id="",
                source="projection",
                attributes={"thread_count": 1},
            )
        )

        convo_attributes = {
            "session_id": str(session.get("session_id") or ""),
            "turn_count": len(turns),
            "last_route": str(session.get("last_route") or ""),
            "last_model": str(session.get("last_model") or ""),
            "last_user_text": str((turns[-1] or {}).get("user_text") or "") if turns else "",
            "last_assistant_text": str((turns[-1] or {}).get("assistant_text") or "") if turns else "",
        }
        self.store.upsert_object(
            OntologyObject(
                object_id=conversation_object_id,
                kind="Conversation",
                label=_clip(convo_attributes.get("last_user_text") or thread_id, limit=120) or str(thread_id),
                status="active" if turns else "idle",
                owner_user_id=str(user_id),
                thread_id=str(thread_id),
                source="state_store",
                attributes=convo_attributes,
            )
        )
        self.store.upsert_link(
            OntologyLink(
                from_id=user_object_id,
                relation="participates_in",
                to_id=conversation_object_id,
                owner_user_id=str(user_id),
                thread_id=str(thread_id),
            )
        )

        for row in list(graph.get("tasks") or []):
            task_object_id = self._task_object_id(str(row.get("task_id") or "task"))
            self.store.upsert_object(
                OntologyObject(
                    object_id=task_object_id,
                    kind="Task",
                    label=_clip(row.get("title"), limit=140),
                    status=normalize_status("Task", row.get("status")),
                    owner_user_id=str(user_id),
                    thread_id=str(thread_id),
                    source="task_graph",
                    attributes={
                        "deps": list(row.get("deps") or []),
                        "priority": int(row.get("priority") or 3),
                        "source": str(row.get("source") or "conversation"),
                    },
                )
            )
            self.store.upsert_link(
                OntologyLink(
                    from_id=conversation_object_id,
                    relation="has_task",
                    to_id=task_object_id,
                    owner_user_id=str(user_id),
                    thread_id=str(thread_id),
                )
            )

        for title in goals[:50]:
            goal_object_id = self._goal_object_id(title)
            self.store.upsert_object(
                OntologyObject(
                    object_id=goal_object_id,
                    kind="Goal",
                    label=_clip(title, limit=140),
                    status="open",
                    owner_user_id=str(user_id),
                    thread_id="",
                    source="memory_store",
                    attributes={"title": title},
                )
            )
            self.store.upsert_link(
                OntologyLink(
                    from_id=user_object_id,
                    relation="owns_goal",
                    to_id=goal_object_id,
                    owner_user_id=str(user_id),
                    thread_id=str(thread_id),
                )
            )

        for row in reminders[:80]:
            reminder_id = str(row.get("id") or "")
            self.store.upsert_object(
                OntologyObject(
                    object_id=self._reminder_object_id(reminder_id),
                    kind="Reminder",
                    label=_clip(row.get("title"), limit=140),
                    status=normalize_status("Reminder", row.get("status")),
                    owner_user_id=str(user_id),
                    thread_id="",
                    source="memory_store",
                    attributes={
                        "due_ts": str(row.get("due_ts") or ""),
                        "scope": str(row.get("scope") or "task"),
                        "priority": int(row.get("priority") or 3),
                    },
                )
            )
            self.store.upsert_link(
                OntologyLink(
                    from_id=user_object_id,
                    relation="owns_reminder",
                    to_id=self._reminder_object_id(reminder_id),
                    owner_user_id=str(user_id),
                    thread_id=str(thread_id),
                )
            )

        artifact_path = self.artifacts_root / f"{user_id}.jsonl"
        for row in reversed(self._iter_recent_jsonl(artifact_path, max_rows=50)):
            item_thread = str(row.get("thread_id") or "")
            if item_thread and item_thread != str(thread_id):
                continue
            artifact_id = str(row.get("artifact_id") or "")
            if not artifact_id:
                continue
            summary = _clip(
                row.get("current_state_summary")
                or row.get("summary")
                or row.get("content")
                or row.get("data")
                or row.get("artifact_type")
                or artifact_id,
                limit=220,
            )
            self.store.upsert_object(
                OntologyObject(
                    object_id=self._artifact_object_id(artifact_id),
                    kind="Artifact",
                    label=_clip(row.get("artifact_type") or row.get("contract_name") or artifact_id, limit=120),
                    status=normalize_status("Artifact", row.get("status") or "unknown"),
                    owner_user_id=str(user_id),
                    thread_id=str(thread_id),
                    source="artifacts",
                    attributes={
                        "artifact_id": artifact_id,
                        "summary": summary,
                        "tags": list(row.get("tags") or []),
                    },
                )
            )
            self.store.upsert_link(
                OntologyLink(
                    from_id=conversation_object_id,
                    relation="produced_artifact",
                    to_id=self._artifact_object_id(artifact_id),
                    owner_user_id=str(user_id),
                    thread_id=str(thread_id),
                )
            )

        jobs_history = self.jobs_root / "history"
        if jobs_history.exists():
            for path in sorted(jobs_history.glob("*.json"), reverse=True)[:40]:
                try:
                    row = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                job_id = str(row.get("job_id") or path.stem)
                self.store.upsert_object(
                    OntologyObject(
                        object_id=self._job_object_id(job_id),
                        kind="Job",
                        label=_clip(row.get("objective") or job_id, limit=140),
                        status=normalize_status("Job", row.get("state")),
                        owner_user_id=str(user_id),
                        thread_id="",
                        source="jobs",
                        attributes={
                            "phase": str(row.get("phase") or ""),
                            "result": row.get("result") or {},
                        },
                    )
                )
                self.store.upsert_link(
                    OntologyLink(
                        from_id=user_object_id,
                        relation="owns_job",
                        to_id=self._job_object_id(job_id),
                        owner_user_id=str(user_id),
                        thread_id=str(thread_id),
                    )
                )

        if self.automation_store is not None:
            try:
                automation_rows = self.automation_store.list_automations(user_id=str(user_id), limit=40)
            except Exception:
                automation_rows = []
            for row in automation_rows:
                automation_id = str(row.get("automation_id") or "")
                if not automation_id:
                    continue
                self.store.upsert_object(
                    OntologyObject(
                        object_id=self._automation_object_id(automation_id),
                        kind="Automation",
                        label=_clip(row.get("name") or automation_id, limit=140),
                        status=normalize_status("Automation", row.get("status") or "active"),
                        owner_user_id=str(user_id),
                        thread_id="",
                        source="automation_store",
                        attributes={
                            "automation_type": str(row.get("automation_type") or ""),
                            "target_channel": str(row.get("target_channel") or ""),
                            "next_run_at": str(row.get("next_run_at") or ""),
                        },
                    )
                )
                self.store.upsert_link(
                    OntologyLink(
                        from_id=user_object_id,
                        relation="owns_automation",
                        to_id=self._automation_object_id(automation_id),
                        owner_user_id=str(user_id),
                        thread_id=str(thread_id),
                    )
                )

        if self.gateway_service is not None:
            try:
                node_rows = self.gateway_service.list_nodes(limit=40)
            except Exception:
                node_rows = []
            for row in node_rows:
                node_id = str(row.get("node_id") or "")
                if not node_id:
                    continue
                self.store.upsert_object(
                    OntologyObject(
                        object_id=self._node_object_id(node_id),
                        kind="Node",
                        label=_clip(row.get("client_label") or node_id, limit=140),
                        status=normalize_status("Node", row.get("status") or "pending_pair"),
                        owner_user_id=str(user_id),
                        thread_id="",
                        source="gateway",
                        attributes={
                            "node_type": str(row.get("node_type") or ""),
                            "platform": str(row.get("platform") or ""),
                            "trust_level": str(row.get("trust_level") or ""),
                            "capabilities": list(row.get("capabilities") or []),
                        },
                    )
                )
                self.store.upsert_link(
                    OntologyLink(
                        from_id=user_object_id,
                        relation="controls_node",
                        to_id=self._node_object_id(node_id),
                        owner_user_id=str(user_id),
                        thread_id=str(thread_id),
                    )
                )

        self._upsert_baseline_systems(user_id=str(user_id), thread_id=str(thread_id))
        self._sync_runbook_actions(user_id=str(user_id), thread_id=str(thread_id))
        self._last_refresh[cache_key] = now

    def _sync_runbook_actions(self, *, user_id: str, thread_id: str) -> None:
        targets: list[dict[str, Any]] = []
        targets.extend(self.store.list_objects(kind="Task", owner_user_id=str(user_id), thread_id=str(thread_id), limit=80))
        targets.extend(self.store.list_objects(kind="Artifact", owner_user_id=str(user_id), thread_id=str(thread_id), limit=80))
        targets.extend(self.store.list_objects(kind="Job", owner_user_id=str(user_id), thread_id="", limit=80))
        targets.extend(self.store.list_objects(kind="Automation", owner_user_id=str(user_id), thread_id="", limit=80))
        targets.extend(self.store.list_objects(kind="Node", owner_user_id=str(user_id), thread_id="", limit=80))
        for row in targets:
            target_id = str(row.get("object_id") or "")
            target_kind = str(row.get("kind") or "")
            for spec in self._runbook_spec(target_kind):
                action_id = self._action_object_id(target_id, str(spec.get("action_type") or "action"))
                attrs = {
                    "target_id": target_id,
                    "target_kind": target_kind,
                    "action_type": str(spec.get("action_type") or ""),
                    "risk_level": str(spec.get("risk_level") or "low"),
                    "requires_approval": bool(spec.get("requires_approval", False)),
                    "runbook_id": str(spec.get("runbook_id") or ""),
                    "approval_chain": [],
                }
                self.store.upsert_object(
                    OntologyObject(
                        object_id=action_id,
                        kind="Action",
                        label=str(spec.get("label") or spec.get("action_type") or "Action"),
                        status="pending",
                        owner_user_id=str(user_id),
                        thread_id=str(thread_id),
                        source="runbook_projection",
                        attributes=attrs,
                    )
                )
                self.store.upsert_link(
                    OntologyLink(
                        from_id=target_id,
                        relation="can_run_action",
                        to_id=action_id,
                        owner_user_id=str(user_id),
                        thread_id=str(thread_id),
                    )
                )

    def list_actions(self, *, owner_user_id: str, thread_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        return self.store.list_objects(kind="Action", owner_user_id=str(owner_user_id), thread_id=thread_id, limit=limit)

    def record_action_approval(self, action_id: str, *, actor: str, decision: str, note: str = "") -> dict[str, Any]:
        row = self.store.get_object(str(action_id or ""))
        if not row or str(row.get("kind") or "") != "Action":
            raise ValueError(f"Unknown ontology action: {action_id}")
        attrs = dict(row.get("attributes") or {})
        chain = [dict(item) for item in list(attrs.get("approval_chain") or []) if isinstance(item, dict)]
        chain.append({"actor": str(actor or "operator"), "decision": str(decision or "approved"), "note": str(note or ""), "timestamp": time.time()})
        attrs["approval_chain"] = chain
        row["attributes"] = attrs
        row["status"] = "approved" if str(decision or "").strip().lower() in {"approve", "approved", "allow"} else "denied"
        return self.store.upsert_object(row)

    def search(
        self,
        query: str,
        *,
        owner_user_id: str,
        thread_id: str | None = None,
        kind: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        return self.store.search(
            query,
            owner_user_id=str(owner_user_id),
            thread_id=thread_id,
            kind=kind,
            limit=limit,
        )
