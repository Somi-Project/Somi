from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.backup_verifier import verify_recent_backups
from ops.artifact_hygiene import run_artifact_hygiene
from ops.champion_scorecard import build_champion_scorecard, build_finality_summary
from ops.context_budget import run_context_budget_status
from ops.doctor import run_somi_doctor
from ops.docs_integrity import run_docs_integrity
from ops.offline_resilience import run_offline_resilience
from ops.replay_harness import run_replay_harness
from ops.security_audit import run_security_audit


DEFAULT_REPORTS_DIR = Path("sessions/release_gate")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return text.strip("-") or "snapshot"


@contextmanager
def _pushd(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _pack_map(baseline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or ""): dict(item)
        for item in list(baseline.get("packs") or [])
        if isinstance(item, dict) and item.get("id")
    }


def _dashboard_row(
    item_id: str,
    label: str,
    *,
    status: str,
    subtitle: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(item_id or label),
        "label": str(label or "Dashboard"),
        "status": str(status or "idle"),
        "subtitle": str(subtitle or ""),
        "detail": dict(detail or {}),
    }


def build_subsystem_dashboards(
    *,
    doctor: dict[str, Any],
    docs_integrity: dict[str, Any],
    artifact_hygiene: dict[str, Any],
    offline_resilience: dict[str, Any],
    context_budget: dict[str, Any] | None = None,
    security: dict[str, Any],
    backups: dict[str, Any],
    eval_report: dict[str, Any],
    replay: dict[str, Any],
    benchmark_baseline: dict[str, Any],
    finality_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    context_budget = dict(context_budget or {})
    severity_counts = dict(dict(security.get("summary") or {}).get("severity_counts") or {})
    high_findings = _safe_int(severity_counts.get("HIGH")) + _safe_int(severity_counts.get("CRITICAL"))
    medium_findings = _safe_int(severity_counts.get("MEDIUM"))
    pack_rows = _pack_map(benchmark_baseline)

    dashboards = [
        _dashboard_row(
            "runtime_core",
            "Runtime Core",
            status="ready" if bool(eval_report.get("ok")) and bool(replay.get("ok")) else "blocked",
            subtitle=(
                f"eval={_safe_int(eval_report.get('passed'))}/{_safe_int(eval_report.get('total'))} | "
                f"replay_issues={_safe_int(dict(replay.get('summary') or {}).get('issue_count'))}"
            ),
            detail={"eval": eval_report, "replay": replay},
        ),
        _dashboard_row(
            "security",
            "Security and Policy",
            status="blocked" if high_findings else ("warn" if medium_findings or not bool(security.get("ok")) else "ready"),
            subtitle=(
                f"critical_or_high={high_findings} | medium={medium_findings} | "
                f"findings={len(list(security.get('findings') or []))}"
            ),
            detail=security,
        ),
        _dashboard_row(
            "backups",
            "Backups and Recovery",
            status="blocked" if _safe_int(backups.get("verified_count")) <= 0 else ("warn" if _safe_int(backups.get("verified_count")) < 3 else "ready"),
            subtitle=(
                f"verified={_safe_int(backups.get('verified_count'))} | "
                f"recent={_safe_int(backups.get('recent_count'))}"
            ),
            detail=backups,
        ),
        _dashboard_row(
            "doctor",
            "Framework Doctor",
            status="ready" if bool(doctor.get("ok")) else "blocked",
            subtitle=(
                f"tools={_safe_int(dict(doctor.get('tools') or {}).get('available_count'))}/"
                f"{_safe_int(dict(doctor.get('tools') or {}).get('total'))} | "
                f"repairs={len(list(doctor.get('applied_repairs') or []))}"
            ),
            detail=doctor,
        ),
        _dashboard_row(
            "docs",
            "Contributor Docs",
            status="ready" if bool(docs_integrity.get("ok")) else "warn",
            subtitle=(
                f"missing={len(list(docs_integrity.get('missing_files') or []))} | "
                f"broken_links={len(list(docs_integrity.get('broken_links') or []))}"
            ),
            detail=docs_integrity,
        ),
        _dashboard_row(
            "artifacts",
            "Artifact Hygiene",
            status="ready" if bool(artifact_hygiene.get("ok")) else "warn",
            subtitle=(
                f"warnings={len(list(artifact_hygiene.get('warnings') or []))} | "
                f"candidates={len(list(artifact_hygiene.get('cleanup_candidates') or []))}"
            ),
            detail=artifact_hygiene,
        ),
        _dashboard_row(
            "offline_resilience",
            "Offline Resilience",
            status="ready" if bool(offline_resilience.get("ok")) and str(offline_resilience.get("readiness") or "") == "ready" else ("warn" if bool(offline_resilience.get("ok")) else "blocked"),
            subtitle=(
                f"packs={dict(offline_resilience.get('knowledge_packs') or {}).get('pack_count', 0)} | "
                f"agentpedia={offline_resilience.get('agentpedia_pages_count', 0)} | "
                f"cache={offline_resilience.get('evidence_cache_records', 0)}"
            ),
            detail=offline_resilience,
        ),
        _dashboard_row(
            "context_budget",
            "Context Budget",
            status="warn" if str(context_budget.get("status") or "") == "warn" else ("watch" if str(context_budget.get("status") or "") == "watch" else str(context_budget.get("status") or "idle")),
            subtitle=(
                f"compacted={context_budget.get('compacted_session_count', 0)} | "
                f"pressure={context_budget.get('pressure_count', 0)} | "
                f"tokens={context_budget.get('estimated_tokens', 0)}"
            ),
            detail=context_budget,
        ),
        _dashboard_row(
            "finality_lab",
            "Finality Lab",
            status="ready" if bool(finality_summary.get("available")) and bool(finality_summary.get("ok", False)) else ("warn" if bool(finality_summary.get("available")) else "blocked"),
            subtitle=(
                f"run={str(finality_summary.get('run_id') or '--')} | "
                f"measured={_safe_int(finality_summary.get('measured_count'))}/{_safe_int(finality_summary.get('pack_count'))}"
            ),
            detail=finality_summary,
        ),
    ]

    for pack_id in ("coding", "ocr", "research", "speech", "automation", "browser", "memory"):
        pack = dict(pack_rows.get(pack_id) or {})
        if not pack:
            continue
        status = str(pack.get("status") or "unknown")
        ui_status = "ready" if status in {"measured", "ready"} else ("warn" if status == "partial" else "blocked")
        dashboards.append(
            _dashboard_row(
                f"pack_{pack_id}",
                str(pack.get("label") or pack_id.title()),
                status=ui_status,
                subtitle=f"status={status} | readiness={_safe_float(pack.get('readiness_score')):.2f}",
                detail=pack,
            )
        )
    return dashboards


def _collect_blockers(
    *,
    doctor: dict[str, Any],
    docs_integrity: dict[str, Any],
    artifact_hygiene: dict[str, Any],
    offline_resilience: dict[str, Any],
    context_budget: dict[str, Any] | None = None,
    security: dict[str, Any],
    backups: dict[str, Any],
    eval_report: dict[str, Any],
    replay: dict[str, Any],
    benchmark_baseline: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    context_budget = dict(context_budget or {})
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    severity_counts = dict(dict(security.get("summary") or {}).get("severity_counts") or {})
    high_findings = _safe_int(severity_counts.get("HIGH")) + _safe_int(severity_counts.get("CRITICAL"))
    medium_findings = _safe_int(severity_counts.get("MEDIUM"))

    if not bool(doctor.get("ok")):
        blockers.append({"type": "doctor", "message": "Framework doctor reported release-blocking issues."})
    if not bool(eval_report.get("ok")):
        blockers.append({"type": "eval", "message": "Eval harness did not pass all checks."})
    if not bool(replay.get("ok")):
        blockers.append({"type": "replay", "message": "Replay harness found timeline integrity issues."})
    if _safe_int(backups.get("verified_count")) <= 0:
        blockers.append({"type": "backup", "message": "No verified recovery checkpoint is available."})
    if high_findings:
        blockers.append({"type": "security", "message": f"Security audit reported {high_findings} HIGH/CRITICAL finding(s)."})

    for pack in list(benchmark_baseline.get("packs") or []):
        status = str(pack.get("status") or "unknown")
        label = str(pack.get("label") or pack.get("id") or "Pack")
        if status == "gap":
            blockers.append({"type": "benchmark_pack", "message": f"{label} has a benchmark gap that blocks release readiness."})
        elif status in {"partial", "ready"}:
            warnings.append({"type": "benchmark_pack", "message": f"{label} is not yet fully measured for finality."})

    if medium_findings:
        warnings.append({"type": "security", "message": f"Security audit reported {medium_findings} MEDIUM finding(s)."})
    if _safe_int(backups.get("verified_count")) < 3 and _safe_int(backups.get("verified_count")) > 0:
        warnings.append({"type": "backup", "message": "Fewer than three verified backups are available for confident rollback."})
    if not bool(docs_integrity.get("ok")):
        warnings.append(
            {
                "type": "docs",
                "message": (
                    "Contributor docs integrity has gaps "
                    f"(missing={len(list(docs_integrity.get('missing_files') or []))}, "
                    f"broken_links={len(list(docs_integrity.get('broken_links') or []))})."
                ),
            }
        )
    if not bool(artifact_hygiene.get("ok")):
        warnings.append(
            {
                "type": "artifacts",
                "message": (
                    "Generated artifact hygiene is over budget "
                    f"(warnings={len(list(artifact_hygiene.get('warnings') or []))}, "
                    f"cleanup_candidates={len(list(artifact_hygiene.get('cleanup_candidates') or []))})."
                ),
            }
        )
    if not bool(offline_resilience.get("ok")) or str(offline_resilience.get("readiness") or "") != "ready":
        warnings.append(
            {
                "type": "offline_resilience",
                "message": (
                    "Offline resilience is not fully ready "
                    f"(readiness={offline_resilience.get('readiness', 'blocked')}, "
                    f"missing={len(list(offline_resilience.get('missing_categories') or []))}, "
                    f"fallback_order={len(list(offline_resilience.get('fallback_order') or []))})."
                ),
            }
        )
    if str(context_budget.get("status") or "") == "warn":
        warnings.append(
            {
                "type": "context_budget",
                "message": (
                    "Context budget pressure is high "
                    f"(pressure={context_budget.get('pressure_count', 0)}, "
                    f"compacted={context_budget.get('compacted_session_count', 0)}, "
                    f"tokens={context_budget.get('estimated_tokens', 0)})."
                ),
            }
        )

    return blockers, warnings


def _read_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _history_dir(root_dir: str | Path) -> Path:
    return Path(root_dir) / DEFAULT_REPORTS_DIR


def list_release_reports(root_dir: str | Path = ".", *, limit: int = 12) -> list[dict[str, Any]]:
    reports_dir = _history_dir(root_dir)
    if not reports_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("release_report_*.json")):
        payload = _read_report(path)
        if payload is None:
            continue
        rows.append(
            {
                "report_id": str(payload.get("report_id") or path.stem),
                "label": str(payload.get("label") or ""),
                "generated_at": str(payload.get("generated_at") or ""),
                "status": str(payload.get("status") or ""),
                "readiness_score": _safe_float(payload.get("readiness_score")),
                "path": str(path),
            }
        )
    rows.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return rows[: max(1, int(limit or 12))]


def _resolve_report(root_dir: str | Path, name: str) -> dict[str, Any] | None:
    rows = list_release_reports(root_dir, limit=50)
    if not rows:
        return None
    selector = str(name or "latest").strip().lower()
    if selector in {"latest", ""}:
        return _read_report(Path(rows[0]["path"]))
    if selector == "previous":
        return _read_report(Path(rows[1]["path"])) if len(rows) > 1 else None
    for row in rows:
        if selector in {str(row.get("report_id") or "").lower(), str(row.get("label") or "").lower(), Path(str(row.get("path") or "")).stem.lower()}:
            return _read_report(Path(row["path"]))
    return None


def load_latest_release_report(root_dir: str | Path = ".") -> dict[str, Any] | None:
    return _resolve_report(root_dir, "latest")


def diff_release_reports(
    root_dir: str | Path = ".",
    *,
    current: str = "latest",
    previous: str = "previous",
) -> dict[str, Any]:
    current_report = _resolve_report(root_dir, current)
    previous_report = _resolve_report(root_dir, previous)
    if current_report is None or previous_report is None:
        return {
            "ok": False,
            "message": "Two persisted release reports are required to compute a diff.",
            "current": current_report,
            "previous": previous_report,
        }

    current_packs = _pack_map(dict(current_report.get("benchmark_baseline") or {}))
    previous_packs = _pack_map(dict(previous_report.get("benchmark_baseline") or {}))
    pack_diffs: list[dict[str, Any]] = []
    for pack_id in sorted(set(current_packs) | set(previous_packs)):
        now_pack = dict(current_packs.get(pack_id) or {})
        then_pack = dict(previous_packs.get(pack_id) or {})
        pack_diffs.append(
            {
                "pack_id": pack_id,
                "label": str(now_pack.get("label") or then_pack.get("label") or pack_id),
                "status_before": str(then_pack.get("status") or ""),
                "status_after": str(now_pack.get("status") or ""),
                "readiness_before": _safe_float(then_pack.get("readiness_score")),
                "readiness_after": _safe_float(now_pack.get("readiness_score")),
                "readiness_delta": round(_safe_float(now_pack.get("readiness_score")) - _safe_float(then_pack.get("readiness_score")), 2),
            }
        )

    return {
        "ok": True,
        "current": {
            "report_id": current_report.get("report_id"),
            "label": current_report.get("label"),
            "generated_at": current_report.get("generated_at"),
            "readiness_score": current_report.get("readiness_score"),
            "status": current_report.get("status"),
        },
        "previous": {
            "report_id": previous_report.get("report_id"),
            "label": previous_report.get("label"),
            "generated_at": previous_report.get("generated_at"),
            "readiness_score": previous_report.get("readiness_score"),
            "status": previous_report.get("status"),
        },
        "summary": {
            "readiness_delta": round(_safe_float(current_report.get("readiness_score")) - _safe_float(previous_report.get("readiness_score")), 2),
            "blocker_delta": len(list(current_report.get("blockers") or [])) - len(list(previous_report.get("blockers") or [])),
            "warning_delta": len(list(current_report.get("warnings") or [])) - len(list(previous_report.get("warnings") or [])),
            "eval_score_delta": round(
                _safe_float(dict(current_report.get("eval") or {}).get("score"))
                - _safe_float(dict(previous_report.get("eval") or {}).get("score")),
                2,
            ),
        },
        "pack_diffs": pack_diffs,
    }


def _render_release_markdown(report: dict[str, Any]) -> str:
    finality = dict(report.get("finality_lab") or {})
    champion = dict(report.get("champion_scorecard") or {})
    lines = [
        "# Release Gate",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Label: {report.get('label')}",
        f"Status: {report.get('status')}",
        f"Readiness score: {report.get('readiness_score')}",
        "",
        "## Summary",
        "",
        f"- Blockers: {len(list(report.get('blockers') or []))}",
        f"- Warnings: {len(list(report.get('warnings') or []))}",
        f"- Eval score: {dict(report.get('eval') or {}).get('score', 0.0)}",
        f"- Replay issues: {dict(dict(report.get('replay') or {}).get('summary') or {}).get('issue_count', 0)}",
        f"- Verified backups: {dict(report.get('backups') or {}).get('verified_count', 0)}",
        f"- Artifact warnings: {len(list(dict(report.get('artifact_hygiene') or {}).get('warnings') or []))}",
        f"- Finality measured: {finality.get('measured_count', 0)}/{finality.get('pack_count', 0)}",
        "",
        "## Subsystems",
        "",
    ]
    for row in list(report.get("subsystem_dashboards") or []):
        lines.append(f"### {row.get('label')} ({row.get('status')})")
        lines.append("")
        lines.append(f"- {row.get('subtitle')}")
        lines.append("")
    blockers = list(report.get("blockers") or [])
    warnings = list(report.get("warnings") or [])
    lines.append("## Blockers")
    lines.append("")
    if blockers:
        for row in blockers:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Warnings")
    lines.append("")
    if warnings:
        for row in warnings:
            lines.append(f"- {row.get('message')}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Champion Summary")
    lines.append("")
    if champion:
        lines.append(f"- Verdict: {champion.get('overall_verdict')}")
        lines.append(f"- Categories ahead: {champion.get('ahead_count', 0)}")
        lines.append("- Leading areas:")
        for item in list(champion.get("strengths") or [])[:4]:
            lines.append(f"  - {item}")
    else:
        lines.append("- No champion scorecard captured yet.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_release_gate(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Release Gate]",
        f"- status: {report.get('status')}",
        f"- readiness_score: {report.get('readiness_score')}",
        f"- blockers: {len(list(report.get('blockers') or []))}",
        f"- warnings: {len(list(report.get('warnings') or []))}",
        f"- eval_score: {dict(report.get('eval') or {}).get('score', 0.0)}",
        f"- verified_backups: {dict(report.get('backups') or {}).get('verified_count', 0)}",
        f"- artifact_warnings: {len(list(dict(report.get('artifact_hygiene') or {}).get('warnings') or []))}",
        f"- finality_measured: {dict(report.get('finality_lab') or {}).get('measured_count', 0)}/{dict(report.get('finality_lab') or {}).get('pack_count', 0)}",
    ]
    blockers = list(report.get("blockers") or [])
    warnings = list(report.get("warnings") or [])
    if blockers:
        lines.append("")
        lines.append("Blockers:")
        for row in blockers[:12]:
            lines.append(f"- {row.get('message')}")
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for row in warnings[:12]:
            lines.append(f"- {row.get('message')}")
    return "\n".join(lines).strip() + "\n"


def format_release_diff(report: dict[str, Any]) -> str:
    if not bool(report.get("ok")):
        return "[Somi Release Diff]\n- unable to compute diff\n"
    summary = dict(report.get("summary") or {})
    lines = [
        "[Somi Release Diff]",
        f"- current: {dict(report.get('current') or {}).get('report_id', '--')}",
        f"- previous: {dict(report.get('previous') or {}).get('report_id', '--')}",
        f"- readiness_delta: {summary.get('readiness_delta', 0.0)}",
        f"- blocker_delta: {summary.get('blocker_delta', 0)}",
        f"- warning_delta: {summary.get('warning_delta', 0)}",
        f"- eval_score_delta: {summary.get('eval_score_delta', 0.0)}",
        "",
        "Pack deltas:",
    ]
    for row in list(report.get("pack_diffs") or [])[:12]:
        lines.append(
            f"- {row.get('label')}: {row.get('status_before')} -> {row.get('status_after')} "
            f"({row.get('readiness_delta', 0.0):+.2f})"
        )
    return "\n".join(lines).strip() + "\n"


def run_release_gate(
    root_dir: str | Path = ".",
    *,
    user_id: str = "default_user",
    label: str = "",
    write_report: bool = True,
    include_eval: bool = True,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    report_label = str(label or root.name or "somi")
    with _pushd(root):
        from audit.benchmark_baseline import build_benchmark_baseline
        from runtime.eval_harness import run_eval_harness

        doctor = run_somi_doctor(root, apply_repairs=False)
        docs_integrity = run_docs_integrity(root)
        artifact_hygiene = run_artifact_hygiene(root)
        offline_resilience = run_offline_resilience(root)
        context_budget = run_context_budget_status(root)
        security = run_security_audit(root)
        backups = verify_recent_backups(root / "backups", limit=5)
        benchmark_baseline = build_benchmark_baseline(root, user_id=user_id)
        replay = run_replay_harness(root, user_id=user_id)
        eval_report = run_eval_harness() if include_eval else {"ok": True, "score": 0.0, "passed": 0, "total": 0, "checks": []}
        finality_summary = build_finality_summary(root)

    blockers, warnings = _collect_blockers(
        doctor=doctor,
        docs_integrity=docs_integrity,
        artifact_hygiene=artifact_hygiene,
        offline_resilience=offline_resilience,
        context_budget=context_budget,
        security=security,
        backups=backups,
        eval_report=eval_report,
        replay=replay,
        benchmark_baseline=benchmark_baseline,
    )
    dashboards = build_subsystem_dashboards(
        doctor=doctor,
        docs_integrity=docs_integrity,
        artifact_hygiene=artifact_hygiene,
        offline_resilience=offline_resilience,
        context_budget=context_budget,
        security=security,
        backups=backups,
        eval_report=eval_report,
        replay=replay,
        benchmark_baseline=benchmark_baseline,
        finality_summary=finality_summary,
    )
    champion_scorecard = build_champion_scorecard(
        root_dir=root,
        release_report={
            "status": "pass" if not blockers and not warnings else ("warn" if not blockers else "fail"),
            "readiness_score": 0.0,
            "warnings": warnings,
            "benchmark_baseline": benchmark_baseline,
        },
        finality_summary=finality_summary,
    )

    score = 100.0
    score -= min(40.0, len(blockers) * 12.5)
    score -= min(18.0, len(warnings) * 3.0)
    score = max(0.0, round(score, 2))
    status = "pass" if not blockers and not warnings else ("warn" if not blockers else "fail")
    report_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_slug(report_label)}"

    report = {
        "report_id": report_id,
        "generated_at": _now_iso(),
        "root_dir": str(root),
        "label": report_label,
        "status": status,
        "ok": status != "fail",
        "readiness_score": score,
        "doctor": doctor,
        "docs_integrity": docs_integrity,
        "artifact_hygiene": artifact_hygiene,
        "offline_resilience": offline_resilience,
        "context_budget": context_budget,
        "security": security,
        "backups": backups,
        "benchmark_baseline": benchmark_baseline,
        "finality_lab": finality_summary,
        "replay": replay,
        "eval": eval_report,
        "subsystem_dashboards": dashboards,
        "blockers": blockers,
        "warnings": warnings,
    }
    report["champion_scorecard"] = build_champion_scorecard(
        root_dir=root,
        release_report=report,
        finality_summary=finality_summary,
    )

    if write_report:
        out_dir = _history_dir(root)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"release_report_{report_id}.json"
        md_path = out_dir / f"release_report_{report_id}.md"
        latest_json_path = out_dir / "latest_release_gate.json"
        latest_md_path = out_dir / "latest_release_gate.md"
        payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        markdown = _render_release_markdown(report)
        json_path.write_text(payload, encoding="utf-8")
        md_path.write_text(markdown, encoding="utf-8")
        latest_json_path.write_text(payload, encoding="utf-8")
        latest_md_path.write_text(markdown, encoding="utf-8")

        previous = _resolve_report(root, "previous")
        if previous is not None:
            diff = diff_release_reports(root, current="latest", previous="previous")
            report["diff_to_previous"] = diff
            json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            latest_json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
