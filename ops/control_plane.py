from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deploy import evaluate_rollout, list_profiles
from runtime.autonomy_profiles import evaluate_autonomy_request, get_autonomy_profile, list_autonomy_profiles
from runtime.background_tasks import BackgroundTaskStore
from runtime.skill_apprenticeship import SkillApprenticeshipLedger


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return raw if isinstance(raw, dict) else dict(default)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def _tail_jsonl(path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
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
    return rows[-max(1, int(limit or 20)) :]


class OpsControlPlane:
    def __init__(self, root_dir: str | Path = "sessions/ops") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root_dir / "runtime_config.json"
        self.events_path = self.root_dir / "events.jsonl"
        self.metrics_path = self.root_dir / "metrics.jsonl"
        self.background_task_store = BackgroundTaskStore(root_dir=self.root_dir / "background_tasks")
        self.skill_apprenticeship = SkillApprenticeshipLedger(root_dir=self.root_dir / "skill_apprenticeship")
        self._ensure_config()

    def _default_config(self) -> dict[str, Any]:
        default_profiles = [profile.to_dict() for profile in list_profiles()]
        default_autonomy_profiles = [profile.to_dict() for profile in list_autonomy_profiles()]
        return {
            "schema_version": 2,
            "active_profile": "local_workstation",
            "profiles": default_profiles,
            "active_autonomy_profile": "balanced",
            "autonomy_profiles": default_autonomy_profiles,
            "revisions": [
                {
                    "revision_id": "bootstrap",
                    "ts": _now_iso(),
                    "actor": "system",
                    "reason": "initial bootstrap",
                    "target_profile": "local_workstation",
                    "applied": True,
                    "evaluation": evaluate_rollout("local_workstation"),
                }
            ],
            "autonomy_revisions": [
                {
                    "revision_id": "autonomy_bootstrap",
                    "ts": _now_iso(),
                    "actor": "system",
                    "reason": "initial bootstrap",
                    "target_profile": "balanced",
                    "applied": True,
                    "evaluation": self._evaluate_autonomy_profile("balanced"),
                }
            ],
        }

    def _evaluate_autonomy_profile(self, profile_id: str) -> dict[str, Any]:
        profile = get_autonomy_profile(profile_id)
        if profile is None:
            return {"ok": False, "issues": ["unknown_autonomy_profile"], "profile": {}}
        check = evaluate_autonomy_request(profile, risk_tier=profile.max_risk_tier)
        return {
            "ok": True,
            "issues": [],
            "profile": profile.to_dict(),
            "policy_check": check,
        }

    def _normalize_config(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        base = self._default_config()
        config = dict(raw or {})
        normalized = dict(base)
        normalized.update(config)
        if not isinstance(normalized.get("profiles"), list) or not list(normalized.get("profiles") or []):
            normalized["profiles"] = base["profiles"]
        else:
            base_profiles = {
                str(item.get("profile_id") or ""): dict(item)
                for item in list(base.get("profiles") or [])
                if isinstance(item, dict)
            }
            merged_profiles: list[dict[str, Any]] = []
            for item in list(normalized.get("profiles") or []):
                if not isinstance(item, dict):
                    continue
                key = str(item.get("profile_id") or "")
                merged_profiles.append({**dict(base_profiles.get(key) or {}), **dict(item)})
            normalized["profiles"] = merged_profiles or base["profiles"]
        if not isinstance(normalized.get("autonomy_profiles"), list) or not list(normalized.get("autonomy_profiles") or []):
            normalized["autonomy_profiles"] = base["autonomy_profiles"]
        else:
            base_autonomy = {
                str(item.get("profile_id") or ""): dict(item)
                for item in list(base.get("autonomy_profiles") or [])
                if isinstance(item, dict)
            }
            merged_autonomy: list[dict[str, Any]] = []
            for item in list(normalized.get("autonomy_profiles") or []):
                if not isinstance(item, dict):
                    continue
                key = str(item.get("profile_id") or "")
                merged_autonomy.append({**dict(base_autonomy.get(key) or {}), **dict(item)})
            normalized["autonomy_profiles"] = merged_autonomy or base["autonomy_profiles"]
        if not isinstance(normalized.get("revisions"), list):
            normalized["revisions"] = list(base["revisions"])
        if not isinstance(normalized.get("autonomy_revisions"), list):
            normalized["autonomy_revisions"] = list(base["autonomy_revisions"])
        normalized["schema_version"] = max(int(base.get("schema_version") or 1), int(normalized.get("schema_version") or 1))
        normalized["active_profile"] = str(normalized.get("active_profile") or base["active_profile"])
        normalized["active_autonomy_profile"] = str(
            normalized.get("active_autonomy_profile") or base["active_autonomy_profile"]
        )
        return normalized

    def _ensure_config(self) -> None:
        base = self._default_config()
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return
        current = _read_json(self.config_path, default=base)
        normalized = self._normalize_config(current)
        if normalized != current:
            self._save_config(normalized)

    def _load_config(self) -> dict[str, Any]:
        return self._normalize_config(_read_json(self.config_path, default=self._default_config()))

    def _save_config(self, payload: dict[str, Any]) -> None:
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)

    def list_profiles(self) -> list[dict[str, Any]]:
        return list(self._load_config().get("profiles") or [])

    def list_autonomy_profiles(self) -> list[dict[str, Any]]:
        return list(self._load_config().get("autonomy_profiles") or [])

    def get_active_profile(self) -> dict[str, Any]:
        config = self._load_config()
        active = str(config.get("active_profile") or "local_workstation")
        profiles = {str(item.get("profile_id") or ""): item for item in list(config.get("profiles") or []) if isinstance(item, dict)}
        selected = dict(profiles.get(active) or {})
        selected["evaluation"] = evaluate_rollout(selected or active)
        return selected

    def get_active_autonomy_profile(self) -> dict[str, Any]:
        config = self._load_config()
        active = str(config.get("active_autonomy_profile") or "balanced")
        profiles = {
            str(item.get("profile_id") or ""): item
            for item in list(config.get("autonomy_profiles") or [])
            if isinstance(item, dict)
        }
        selected = dict(profiles.get(active) or {})
        selected["evaluation"] = self._evaluate_autonomy_profile(str(selected.get("profile_id") or active))
        return selected

    def set_active_profile(
        self,
        profile_id: str,
        *,
        actor: str = "system",
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        config = self._load_config()
        target = str(profile_id or "").strip().lower()
        profiles = {str(item.get("profile_id") or ""): item for item in list(config.get("profiles") or []) if isinstance(item, dict)}
        profile = dict(profiles.get(target) or {})
        evaluation = evaluate_rollout(profile or target)
        applied = bool(evaluation.get("ok", False) or force)
        if applied:
            config["active_profile"] = target
        revision = {
            "revision_id": f"rev_{len(list(config.get('revisions') or [])) + 1}",
            "ts": _now_iso(),
            "actor": str(actor or "system"),
            "reason": str(reason or ""),
            "target_profile": target,
            "applied": applied,
            "forced": bool(force),
            "evaluation": evaluation,
        }
        config.setdefault("revisions", []).append(revision)
        self._save_config(config)
        self.record_event(
            "profile_rollout",
            {
                "target_profile": target,
                "applied": applied,
                "forced": bool(force),
                "evaluation": evaluation,
                "actor": str(actor or "system"),
                "reason": str(reason or ""),
            },
        )
        return revision

    def set_active_autonomy_profile(
        self,
        profile_id: str,
        *,
        actor: str = "system",
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        config = self._load_config()
        target = str(profile_id or "").strip().lower()
        profiles = {
            str(item.get("profile_id") or ""): item
            for item in list(config.get("autonomy_profiles") or [])
            if isinstance(item, dict)
        }
        profile = dict(profiles.get(target) or {})
        evaluation = self._evaluate_autonomy_profile(str(profile.get("profile_id") or target))
        applied = bool(evaluation.get("ok", False) or force)
        if applied:
            config["active_autonomy_profile"] = target
        revision = {
            "revision_id": f"autonomy_rev_{len(list(config.get('autonomy_revisions') or [])) + 1}",
            "ts": _now_iso(),
            "actor": str(actor or "system"),
            "reason": str(reason or ""),
            "target_profile": target,
            "applied": applied,
            "forced": bool(force),
            "evaluation": evaluation,
        }
        config.setdefault("autonomy_revisions", []).append(revision)
        self._save_config(config)
        self.record_event(
            "autonomy_profile_update",
            {
                "target_profile": target,
                "applied": applied,
                "forced": bool(force),
                "evaluation": evaluation,
                "actor": str(actor or "system"),
                "reason": str(reason or ""),
            },
        )
        return revision

    def record_event(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        row = {
            "ts": _now_iso(),
            "type": str(event_type or "event"),
            "payload": dict(payload or {}),
        }
        return _append_jsonl(self.events_path, row)

    def record_policy_decision(
        self,
        *,
        surface: str,
        decision: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "ts": _now_iso(),
            "type": "policy_decision",
            "surface": str(surface or "runtime"),
            "decision": str(decision or "unknown"),
            "reason": str(reason or ""),
            "payload": dict(payload or {}),
        }
        _append_jsonl(self.events_path, row)
        return row

    def record_tool_metric(
        self,
        *,
        tool_name: str,
        success: bool,
        elapsed_ms: int,
        backend: str,
        channel: str,
        risk_tier: str,
        approved: bool,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "ts": _now_iso(),
            "metric_type": "tool",
            "tool_name": str(tool_name or ""),
            "success": bool(success),
            "elapsed_ms": int(elapsed_ms or 0),
            "backend": str(backend or "local"),
            "channel": str(channel or "chat"),
            "risk_tier": str(risk_tier or "LOW"),
            "approved": bool(approved),
            "meta": dict(meta or {}),
        }
        _append_jsonl(self.metrics_path, row)
        return row

    def create_background_task(
        self,
        *,
        user_id: str,
        objective: str,
        task_type: str,
        surface: str = "gui",
        thread_id: str = "",
        max_retries: int = 2,
        artifacts: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.background_task_store.create_task(
            user_id=user_id,
            objective=objective,
            task_type=task_type,
            surface=surface,
            thread_id=thread_id,
            max_retries=max_retries,
            artifacts=artifacts,
            meta=meta,
        )
        self.skill_apprenticeship.record_activity(
            user_id=user_id,
            objective=objective,
            kind=f"background:{task_type}",
            surface=surface,
            success=False,
            tools=[task_type],
            metadata={"thread_id": thread_id, "task_id": row.get("task_id")},
        )
        self.record_event(
            "background_task_created",
            {
                "task_id": row.get("task_id"),
                "task_type": row.get("task_type"),
                "surface": row.get("surface"),
                "status": row.get("status"),
            },
        )
        return row

    def heartbeat_background_task(
        self,
        task_id: str,
        *,
        status: str = "running",
        summary: str = "",
        artifacts: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.background_task_store.heartbeat(
            task_id,
            status=status,
            summary=summary,
            artifacts=artifacts,
            meta=meta,
        )
        self.record_event(
            "background_task_heartbeat",
            {
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "summary": row.get("summary"),
            },
        )
        return row

    def complete_background_task(
        self,
        task_id: str,
        *,
        summary: str = "",
        artifacts: list[dict[str, Any]] | None = None,
        handoff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.background_task_store.complete_task(
            task_id,
            summary=summary,
            artifacts=artifacts,
            handoff=handoff,
        )
        self.skill_apprenticeship.record_activity(
            user_id=str(row.get("user_id") or "default_user"),
            objective=str(row.get("objective") or summary or "background task"),
            kind=f"background:{row.get('task_type') or 'task'}",
            surface=str(row.get("surface") or "gui"),
            success=True,
            tools=[str(row.get("task_type") or "task")],
            metadata={"task_id": row.get("task_id"), "handoff": row.get("handoff") or {}},
        )
        self.record_event(
            "background_task_completed",
            {
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "handoff": row.get("handoff") or {},
            },
        )
        return row

    def fail_background_task(
        self,
        task_id: str,
        *,
        error: str,
        recoverable: bool = True,
        recommended_action: str = "",
    ) -> dict[str, Any]:
        row = self.background_task_store.fail_task(
            task_id,
            error=error,
            recoverable=recoverable,
            recommended_action=recommended_action,
        )
        self.record_event(
            "background_task_failed",
            {
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "last_error": row.get("last_error"),
            },
        )
        return row

    def recover_background_tasks(self, *, stale_after_seconds: int = 900) -> list[dict[str, Any]]:
        rows = self.background_task_store.recover_stalled_tasks(stale_after_seconds=stale_after_seconds)
        if rows:
            self.record_event(
                "background_task_recovery",
                {
                    "recovered_count": len(rows),
                    "task_ids": [str(row.get("task_id") or "") for row in rows[:12]],
                },
            )
        return rows

    def record_model_metric(
        self,
        *,
        model_name: str,
        route: str,
        latency_ms: int,
        status: str = "ok",
        prompt_chars: int = 0,
        output_chars: int = 0,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "ts": _now_iso(),
            "metric_type": "model",
            "model_name": str(model_name or ""),
            "route": str(route or ""),
            "latency_ms": int(latency_ms or 0),
            "status": str(status or "ok"),
            "prompt_chars": int(prompt_chars or 0),
            "output_chars": int(output_chars or 0),
            "meta": dict(meta or {}),
        }
        _append_jsonl(self.metrics_path, row)
        return row

    def snapshot(self, *, event_limit: int = 30, metric_limit: int = 60) -> dict[str, Any]:
        config = self._load_config()
        events = _tail_jsonl(self.events_path, limit=event_limit)
        metrics = _tail_jsonl(self.metrics_path, limit=metric_limit)
        policy_counts: dict[str, int] = {}
        tool_metrics = [row for row in metrics if str(row.get("metric_type") or "") == "tool"]
        model_metrics = [row for row in metrics if str(row.get("metric_type") or "") == "model"]
        for row in events:
            if str(row.get("type") or "") != "policy_decision":
                continue
            decision = str(row.get("decision") or "unknown")
            policy_counts[decision] = policy_counts.get(decision, 0) + 1

        tool_successes = sum(1 for row in tool_metrics if bool(row.get("success", False)))
        tool_failures = max(0, len(tool_metrics) - tool_successes)
        average_model_latency = (
            round(sum(int(row.get("latency_ms") or 0) for row in model_metrics) / max(1, len(model_metrics)), 2)
            if model_metrics
            else 0.0
        )

        return {
            "active_profile": self.get_active_profile(),
            "active_autonomy_profile": self.get_active_autonomy_profile(),
            "config_revision_count": len(list(config.get("revisions") or [])),
            "autonomy_revision_count": len(list(config.get("autonomy_revisions") or [])),
            "background_tasks": self.background_task_store.snapshot(limit=event_limit),
            "skill_apprenticeship": self.skill_apprenticeship.snapshot(limit=min(6, max(2, event_limit // 2))),
            "recent_events": events,
            "recent_metrics": metrics,
            "policy_decision_counts": policy_counts,
            "tool_metrics": {
                "total": len(tool_metrics),
                "successes": tool_successes,
                "failures": tool_failures,
            },
            "model_metrics": {
                "total": len(model_metrics),
                "average_latency_ms": average_model_latency,
            },
        }
