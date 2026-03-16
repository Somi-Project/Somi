from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deploy import evaluate_rollout, list_profiles


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
        self._ensure_config()

    def _ensure_config(self) -> None:
        default_profiles = [profile.to_dict() for profile in list_profiles()]
        base = {
            "schema_version": 1,
            "active_profile": "local_workstation",
            "profiles": default_profiles,
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
        }
        if self.config_path.exists():
            return
        self.config_path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_config(self) -> dict[str, Any]:
        return _read_json(
            self.config_path,
            default={
                "schema_version": 1,
                "active_profile": "local_workstation",
                "profiles": [profile.to_dict() for profile in list_profiles()],
                "revisions": [],
            },
        )

    def _save_config(self, payload: dict[str, Any]) -> None:
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)

    def list_profiles(self) -> list[dict[str, Any]]:
        return list(self._load_config().get("profiles") or [])

    def get_active_profile(self) -> dict[str, Any]:
        config = self._load_config()
        active = str(config.get("active_profile") or "local_workstation")
        profiles = {str(item.get("profile_id") or ""): item for item in list(config.get("profiles") or []) if isinstance(item, dict)}
        selected = dict(profiles.get(active) or {})
        selected["evaluation"] = evaluate_rollout(selected or active)
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
            "config_revision_count": len(list(config.get("revisions") or [])),
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
