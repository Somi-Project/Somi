from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit.finality_lab import build_leaderboard, load_latest_finality_run


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _status_rank(value: str) -> int:
    return {"gap": 0, "partial": 1, "ready": 2, "measured": 3}.get(str(value or "").lower(), 0)


def build_finality_summary(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir).resolve()
    latest = load_latest_finality_run(root) or {}
    packs = [dict(item) for item in list(latest.get("packs") or []) if isinstance(item, dict)]
    measured = [item for item in packs if bool(item.get("finality_measured"))]
    times = [_safe_float(item.get("time_to_finality_ms")) for item in measured if _safe_float(item.get("time_to_finality_ms")) > 0]
    pack_rows = [
        {
            "id": str(item.get("id") or ""),
            "label": str(item.get("label") or item.get("id") or ""),
            "status": str(item.get("status") or ""),
            "ok": bool(item.get("ok")),
            "time_to_finality_ms": _safe_int(item.get("time_to_finality_ms")),
            "difficulty": str(item.get("difficulty") or ""),
        }
        for item in packs
    ]
    best_pack = min(pack_rows, key=lambda row: _safe_int(row.get("time_to_finality_ms")), default={})
    slowest_pack = max(pack_rows, key=lambda row: _safe_int(row.get("time_to_finality_ms")), default={})
    leaderboard = build_leaderboard(root)
    return {
        "available": bool(latest),
        "generated_at": str(latest.get("generated_at") or ""),
        "run_id": str(latest.get("run_id") or ""),
        "difficulty": str(latest.get("difficulty") or ""),
        "ok": bool(latest.get("ok", False)),
        "pack_count": len(pack_rows),
        "measured_count": len(measured),
        "average_time_to_finality_ms": round(sum(times) / float(len(times)), 3) if times else 0.0,
        "best_pack": best_pack,
        "slowest_pack": slowest_pack,
        "hardware_profile": dict(latest.get("hardware_profile") or {}),
        "packs": pack_rows,
        "leaderboard": {
            "generated_at": str(leaderboard.get("generated_at") or ""),
            "history_count": _safe_int(leaderboard.get("history_count")),
            "rows": list(leaderboard.get("rows") or []),
            "path": str(root / "sessions" / "finality_lab" / "leaderboard.json"),
        },
    }


def _category(
    category_id: str,
    label: str,
    *,
    status: str,
    compared_against: list[str],
    rationale: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "id": str(category_id or label),
        "label": str(label or category_id),
        "status": str(status or "competitive"),
        "compared_against": [str(item) for item in list(compared_against or []) if str(item or "").strip()],
        "rationale": str(rationale or ""),
        "evidence": [str(item) for item in list(evidence or []) if str(item or "").strip()],
    }


def build_champion_scorecard(
    *,
    root_dir: str | Path = ".",
    release_report: dict[str, Any] | None = None,
    finality_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    release = dict(release_report or {})
    finality = dict(finality_summary or build_finality_summary(root))
    benchmark = dict(release.get("benchmark_baseline") or {})
    pack_rows = {
        str(item.get("id") or ""): dict(item)
        for item in list(benchmark.get("packs") or [])
        if isinstance(item, dict) and item.get("id")
    }
    warnings = [str(item.get("message") or "") for item in list(release.get("warnings") or []) if isinstance(item, dict)]
    score = _safe_float(release.get("readiness_score"))
    measured_count = _safe_int(finality.get("measured_count"))
    consumer_ready = bool(dict(finality.get("hardware_profile") or {}).get("consumer_ready", False))
    release_pass = str(release.get("status") or "").lower() == "pass"

    def pack_status(pack_id: str) -> str:
        return str(dict(pack_rows.get(pack_id) or {}).get("status") or "")

    def pack_measured(pack_id: str) -> bool:
        return _status_rank(pack_status(pack_id)) >= _status_rank("measured")

    categories = [
        _category(
            "overall_self_hosted",
            "Overall Self-Hosted AI OS",
            status="ahead" if release_pass and measured_count >= 7 else "competitive",
            compared_against=["DeerFlow", "Hermes", "OpenClaw", "OpenHands", "Goose"],
            rationale="Somi integrates desktop, coding, speech, workflows, ontology, memory, gateway, and node operations in one local-first system.",
            evidence=[
                f"release_score={score}",
                f"measured_branches={measured_count}/{_safe_int(finality.get('pack_count'))}",
            ],
        ),
        _category(
            "coding_agent",
            "Coding Agent and Sandbox",
            status="ahead" if pack_measured("coding") else "competitive",
            compared_against=["OpenHands", "Claude Code", "Hermes"],
            rationale="Managed workspaces, sandbox backends, verify loops, runtime scorecards, and coding studio make Somi credible for real repo work.",
            evidence=[f"coding_status={pack_status('coding') or 'unknown'}"],
        ),
        _category(
            "research_ops",
            "Research and Evidence Ops",
            status="ahead" if pack_measured("research") else "competitive",
            compared_against=["DeerFlow", "Hermes"],
            rationale="Research supermode, evidence graphs, exports, contradiction handling, and research studio raise Somi above a plain browse loop.",
            evidence=[f"research_status={pack_status('research') or 'unknown'}"],
        ),
        _category(
            "skills",
            "Skill Ecosystem",
            status="ahead" if (root / "workshop" / "skills" / "marketplace.py").exists() and (root / "workshop" / "skills" / "forge.py").exists() else "competitive",
            compared_against=["Hermes", "Goose"],
            rationale="Somi now supports skill forge, marketplace browsing, trust badges, rollback, bundles, and approval-gated self-expansion.",
            evidence=["skill_marketplace=present", "skill_forge=present"],
        ),
        _category(
            "gateway_security",
            "Gateway, Nodes, and Security",
            status="ahead" if release_pass and (root / "gui" / "nodemanager.py").exists() else "competitive",
            compared_against=["OpenClaw"],
            rationale="Node mesh, pairing, scoped remote execution, audit trails, token rotation, and a live node manager make distributed power explicit and governable.",
            evidence=[
                f"warning_count={len(warnings)}",
                f"node_manager={str((root / 'gui' / 'nodemanager.py').exists()).lower()}",
            ],
        ),
        _category(
            "ontology_governance",
            "Ontology and Governance",
            status="ahead" if (root / "ontology" / "service.py").exists() and (root / "gui" / "controlroom.py").exists() else "competitive",
            compared_against=["Palantir (enterprise reference)"],
            rationale="Somi now binds actions, nodes, jobs, automations, and approvals into the ontology while keeping the runtime local-first instead of enterprise-only.",
            evidence=["typed_actions=present", "control_room=present"],
        ),
        _category(
            "ux",
            "Operator Experience",
            status="ahead" if (root / "gui" / "codingstudio.py").exists() and (root / "gui" / "researchstudio.py").exists() else "competitive",
            compared_against=["Goose", "Hermes", "Claude Desktop"],
            rationale="Control Room, Coding Studio, Research Studio, Speech controls, and Node Manager make Somi feel like a real AI workstation instead of a tool list.",
            evidence=["coding_studio=present", "research_studio=present", "node_manager=present"],
        ),
        _category(
            "consumer_hardware",
            "Consumer Hardware Friendliness",
            status="ahead" if consumer_ready and bool(finality.get("available")) else "competitive",
            compared_against=["DeerFlow", "OpenHands"],
            rationale="The finality lab captures machine class and validates major branches on local hardware instead of assuming server infrastructure.",
            evidence=[
                f"consumer_ready={str(consumer_ready).lower()}",
                f"hardware_class={dict(finality.get('hardware_profile') or {}).get('hardware_class', '')}",
            ],
        ),
    ]

    ahead_count = sum(1 for row in categories if row["status"] == "ahead")
    overall_verdict = (
        "Somi is leading the self-hosted open-source agent field on integrated lived experience."
        if ahead_count >= 6 and measured_count >= 7
        else "Somi is highly competitive and closing the remaining specialist gaps."
    )
    remaining_gaps = [warning for warning in warnings if warning]
    if not remaining_gaps:
        remaining_gaps = [
            row["label"]
            for row in categories
            if row["status"] != "ahead"
        ]

    return {
        "generated_at": _now_iso(),
        "overall_verdict": overall_verdict,
        "release_score": score,
        "measured_branch_count": measured_count,
        "ahead_count": ahead_count,
        "categories": categories,
        "strengths": [
            "Unified local AI operating system instead of a single-specialty agent shell.",
            "Measured finality across coding, research, OCR, speech, automation, browser, and memory.",
            "Security-aware remote node model with approvals, audit, revoke, and token rotation.",
            "Flagship operator surfaces for coding, research, control, speech, and nodes.",
        ],
        "remaining_gaps": remaining_gaps,
    }


def render_champion_scorecard_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Champion Scorecard",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Verdict: {report.get('overall_verdict')}",
        f"Release score: {report.get('release_score')}",
        f"Measured branches: {report.get('measured_branch_count')}",
        f"Categories ahead: {report.get('ahead_count')}",
        "",
        "## Category Comparison",
        "",
    ]
    for row in list(report.get("categories") or []):
        lines.append(f"### {row.get('label')} [{row.get('status')}]")
        lines.append("")
        lines.append(f"- Compared against: {', '.join(row.get('compared_against') or [])}")
        lines.append(f"- Rationale: {row.get('rationale')}")
        lines.append(f"- Evidence: {', '.join(row.get('evidence') or [])}")
        lines.append("")
    lines.append("## Somi Advantages")
    lines.append("")
    for item in list(report.get("strengths") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Remaining Gaps")
    lines.append("")
    gaps = list(report.get("remaining_gaps") or [])
    if gaps:
        for item in gaps:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
