from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway.federation import FederatedEnvelopeStore
from ops.continuity_recovery import build_continuity_recovery_snapshot
from ops.hardware_tiers import build_hardware_tier_snapshot
from ops.offline_resilience import run_offline_resilience
from workflow_runtime.manifests import WorkflowManifestStore
from workflow_runtime.runner import RestrictedWorkflowRunner
from workflow_runtime.store import WorkflowRunStore


@dataclass
class DrillCheck:
    name: str
    ok: bool
    detail: str


class _NoToolRuntime:
    def run(self, tool_name: str, args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        return {"ok": False, "error": f"tool_not_available:{tool_name}"}


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_recovery_drill(
    root_dir: str | Path = ".",
    *,
    runtime_mode: str = "survival",
    scenario: str = "blackout",
) -> dict[str, Any]:
    root = Path(root_dir)
    checks: list[DrillCheck] = []

    hardware = build_hardware_tier_snapshot(str(root), runtime_mode=runtime_mode)
    offline = run_offline_resilience(root)
    continuity = build_continuity_recovery_snapshot(
        root,
        runtime_mode=runtime_mode,
        query="restore shelter power and purify water after blackout",
        limit=4,
    )

    checks.append(
        DrillCheck(
            name="survival_mode_profile",
            ok=str(dict(hardware.get("profile") or {}).get("tier") or "") == "survival",
            detail=f"tier={dict(hardware.get('profile') or {}).get('tier', '')};context={dict(hardware.get('profile') or {}).get('context_profile', '')}",
        )
    )
    checks.append(
        DrillCheck(
            name="offline_resilience_ready",
            ok=bool(offline.get("ok", False)) and int(dict(offline.get("knowledge_packs") or {}).get("pack_count") or 0) >= 4,
            detail=f"readiness={offline.get('readiness', '')};packs={dict(offline.get('knowledge_packs') or {}).get('pack_count', 0)}",
        )
    )
    checks.append(
        DrillCheck(
            name="continuity_domains_ready",
            ok=bool(continuity.get("continuity_ready")) and int(continuity.get("workflow_count") or 0) >= 4,
            detail=f"domains={','.join(list(continuity.get('domains') or []))};workflows={continuity.get('workflow_count', 0)}",
        )
    )

    workflow_store = WorkflowRunStore(root / "sessions" / "recovery_drill_workflows")
    manifest_store = WorkflowManifestStore(root / "workflow_runtime" / "manifests")
    manifest = manifest_store.load("continuity_power_recovery")
    workflow_report: dict[str, Any] = {}
    if manifest is not None:
        runner = RestrictedWorkflowRunner(runtime=_NoToolRuntime(), run_store=workflow_store)
        workflow_report = runner.run_manifest(
            manifest,
            user_id="recovery_drill",
            thread_id="continuity.blackout",
            inputs={"critical_loads": ["lighting", "radios", "water treatment"]},
            metadata={"scenario": str(scenario or "blackout")},
        )
        reloaded = workflow_store.load_snapshot(str(workflow_report.get("run_id") or ""))
        checks.append(
            DrillCheck(
                name="workflow_resume_snapshot",
                ok=str(workflow_report.get("status") or "") == "completed" and isinstance(reloaded, dict),
                detail=f"status={workflow_report.get('status', '')};reloaded={bool(isinstance(reloaded, dict))}",
            )
        )
    else:
        checks.append(
            DrillCheck(
                name="workflow_resume_snapshot",
                ok=False,
                detail="manifest_missing=continuity_power_recovery",
            )
        )

    exchange = FederatedEnvelopeStore(root / "state" / "node_exchange")
    outbound = exchange.publish(
        node_id="relay_blackout_alpha",
        lane="knowledge",
        subject="blackout shelter status",
        body="Critical loads restored. Water treatment remains priority one.",
        capabilities=["knowledge_sync", "task_sync"],
        metadata={"scenario": scenario},
    )
    inbound = exchange.ingest(
        node_id="relay_blackout_alpha",
        lane="task",
        subject="confirm battery rotation",
        body="Need the next battery rotation window.",
        capabilities=["task_sync"],
        metadata={"scenario": scenario},
    )
    archived = exchange.acknowledge(direction="inbox", node_id="relay_blackout_alpha", envelope_id=str(inbound.get("envelope_id") or ""))
    checks.append(
        DrillCheck(
            name="node_exchange_round_trip",
            ok=bool(outbound) and bool(archived),
            detail=f"outbound={bool(outbound)};archived={bool(archived)}",
        )
    )

    passed = sum(1 for item in checks if item.ok)
    report = {
        "ok": passed == len(checks),
        "scenario": str(scenario or "blackout"),
        "runtime_mode": str(runtime_mode or "survival"),
        "passed": passed,
        "total": len(checks),
        "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
        "hardware_profile": hardware,
        "offline_resilience": offline,
        "continuity": continuity,
        "workflow_report": workflow_report,
    }
    _write_report(root / "audit" / "phase176_recovery_drill.json", report)
    return report


def format_recovery_drill(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Recovery Drill]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- scenario: {report.get('scenario', 'blackout')}",
        f"- runtime_mode: {report.get('runtime_mode', 'survival')}",
        f"- passed: {report.get('passed', 0)}/{report.get('total', 0)}",
    ]
    for item in list(report.get("checks") or []):
        lines.append(
            f"- {item.get('name', '')}: {'ok' if bool(item.get('ok')) else 'fail'} ({item.get('detail', '')})"
        )
    return "\n".join(lines)
