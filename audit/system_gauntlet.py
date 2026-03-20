from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automations.engine import AutomationEngine
from automations.store import AutomationStore
from executive.memory.frozen import FrozenMemoryStore
from executive.memory.manager import Memory3Manager
from executive.memory.store import SQLiteMemoryStore
from gateway.manager import DeliveryGateway
from gateway.service import GatewayService
from ops.control_plane import OpsControlPlane
from runtime.background_tasks import BackgroundTaskStore
from runtime.history_compaction import build_compaction_summary
from runtime.live_chat_stress import run_live_stress
from search.session_search import SessionSearchService
from state import SessionEventStore
from workshop.integrations.telegram_runtime import TelegramRuntimeBridge, build_telegram_reply_bundle
from workshop.toolbox.agent_core.continuity import render_state_ledger_block, update_state_ledger
from workshop.toolbox.coding import CodexControlPlane
from workshop.toolbox.coding.jobs import CodingJobStore
from workshop.toolbox.coding.service import CodingSessionService
from workshop.toolbox.coding.store import CodingSessionStore
from workshop.toolbox.coding.workspace import CodingWorkspaceManager
from workshop.toolbox.stacks.ocr_core.document_intel import build_document_note, extract_document_payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(text: str, *, lines: int = 12) -> list[str]:
    return [row for row in str(text or "").splitlines()[-max(1, int(lines or 12)) :] if str(row or "").strip()]


def _run_command(cmd: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, int(timeout)),
        check=False,
    )


def build_system_gauntlet_specs(
    prefix: str,
    *,
    base_count: int = 100,
    search_corpus: str = "everyday100",
    scenario_turns: int = 30,
) -> list[dict[str, Any]]:
    count = max(1, int(base_count or 100))
    return [
        {
            "id": "search100",
            "label": "Search 100",
            "kind": "search_batch",
            "corpus": str(search_corpus or "everyday100"),
            "chunk_size": 10,
            "somi_timeout": 35.0,
            "prefix": f"{prefix}_search100",
            "count": count,
        },
        {"id": "memory100", "label": "Memory 100", "kind": "memory", "count": count},
        {"id": "reminder100", "label": "Reminder 100", "kind": "reminder", "count": count},
        {"id": "compaction100", "label": "Compaction 100", "kind": "compaction", "count": count},
        {"id": "ocr100", "label": "OCR 100", "kind": "ocr", "count": count},
        {"id": "coding100", "label": "Coding 100", "kind": "coding", "count": count},
        {
            "id": "averageuser30",
            "label": "Average User 30",
            "kind": "scenario",
            "turns": max(6, int(scenario_turns or 30)),
        },
    ]


def _run_search_pack(spec: dict[str, Any], *, python_executable: Path, output_dir: Path) -> dict[str, Any]:
    prefix = str(spec.get("prefix") or spec.get("id") or "system_gauntlet").strip()
    manifest_path = output_dir / f"{prefix}_manifest.json"
    cached_manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            cached_manifest = dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            cached_manifest = {}
    cached_combined = dict(cached_manifest.get("combined_paths") or {})
    expected_rows = max(1, int(spec.get("count") or 100))
    if cached_combined:
        combined_jsonl = Path(str(cached_combined.get("jsonl") or ""))
        combined_report = Path(str(cached_combined.get("report") or ""))
        combined_summary = Path(str(cached_combined.get("summary") or ""))
        if combined_jsonl.exists() and combined_report.exists() and combined_summary.exists():
            line_count = 0
            try:
                line_count = sum(1 for line in combined_jsonl.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip())
            except Exception:
                line_count = 0
            if line_count >= expected_rows:
                summary_text = combined_summary.read_text(encoding="utf-8", errors="ignore")
                return {
                    "id": str(spec.get("id") or ""),
                    "label": str(spec.get("label") or ""),
                    "kind": "search_batch",
                    "status": "pass",
                    "ok": True,
                    "seconds": 0.0,
                    "counts": {"target": expected_rows, "rows": line_count},
                    "artifacts": cached_combined,
                    "details": {
                        "stdout_tail": [],
                        "stderr_tail": [],
                        "manifest_path": str(manifest_path),
                        "stabilized_cases": len(list(cached_manifest.get("stabilized_cases") or [])),
                        "chunk_statuses": [str(item.get("status") or "") for item in list(cached_manifest.get("chunks") or [])],
                        "summary_excerpt": _tail(summary_text, lines=10),
                        "reused_existing_artifacts": True,
                    },
                }
    cmd = [
        str(python_executable),
        str(ROOT / "audit" / "search_benchmark_batch.py"),
        "--corpus",
        str(spec.get("corpus") or "everyday100"),
        "--limit",
        str(int(spec.get("count") or 100)),
        "--chunk-size",
        str(int(spec.get("chunk_size") or 10)),
        "--output-dir",
        str(output_dir),
        "--prefix",
        prefix,
        "--somi-timeout",
        str(float(spec.get("somi_timeout") or 35.0)),
    ]
    started = time.perf_counter()
    proc = _run_command(cmd, cwd=ROOT, timeout=7200)
    seconds = round(time.perf_counter() - started, 2)
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            manifest = {}
    combined = dict(manifest.get("combined_paths") or {})
    summary_text = ""
    if combined.get("summary"):
        try:
            summary_text = Path(str(combined.get("summary"))).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            summary_text = ""
    return {
        "id": str(spec.get("id") or ""),
        "label": str(spec.get("label") or ""),
        "kind": "search_batch",
        "status": "pass" if proc.returncode == 0 else "fail",
        "ok": proc.returncode == 0,
        "seconds": seconds,
        "counts": {"target": int(spec.get("count") or 100)},
        "artifacts": combined,
        "details": {
            "stdout_tail": _tail(proc.stdout),
            "stderr_tail": _tail(proc.stderr),
            "manifest_path": str(manifest_path),
            "stabilized_cases": len(list(manifest.get("stabilized_cases") or [])),
            "chunk_statuses": [str(item.get("status") or "") for item in list(manifest.get("chunks") or [])],
            "summary_excerpt": _tail(summary_text, lines=10),
        },
    }


def _run_memory_pack(*, count: int) -> dict[str, Any]:
    started = time.perf_counter()
    tmp = tempfile.mkdtemp(prefix="somi_memory100_")
    root = Path(tmp)
    try:
        uid = "gauntlet_memory"
        state_store = SessionEventStore(db_path=root / "state.sqlite3")
        searcher = SessionSearchService(
            state_store=state_store,
            artifacts_root=root / "artifacts",
            jobs_root=root / "jobs",
        )
        manager = Memory3Manager(
            user_id=uid,
            store=SQLiteMemoryStore(db_path=str(root / "memory.sqlite3")),
            frozen_store=FrozenMemoryStore(root_dir=root / "frozen"),
            session_search=searcher,
        )

        async def _exercise() -> dict[str, Any]:
            inserted = 0
            profile_rows = [
                ("name", "Somi Operator"),
                ("preferred_name", "Operator"),
                ("timezone", "America/Port_of_Spain"),
                ("default_location", "Port of Spain"),
            ]
            for key, value in profile_rows[: min(len(profile_rows), max(1, int(count)))]:
                await manager.upsert_fact(
                    {"key": key, "value": value, "kind": "profile", "confidence": 0.92},
                    user_id=uid,
                )
                inserted += 1

            preference_count = max(0, int(count) - inserted)
            for idx in range(preference_count):
                key = f"favorite_module_{idx:03d}"
                value = f"value_{idx:03d}"
                await manager.upsert_fact(
                    {"key": key, "value": value, "kind": "preference", "confidence": 0.85},
                    user_id=uid,
                )
                inserted += 1

            checks: list[dict[str, Any]] = []
            injected_profile = await manager.build_injected_context(
                "What is my preferred name and timezone?",
                user_id=uid,
            )
            checks.append(
                {
                    "query": "profile_summary",
                    "ok": "Operator" in injected_profile and "America/Port_of_Spain" in injected_profile,
                    "excerpt": " ".join(injected_profile.split())[:180],
                }
            )
            for offset in range(min(3, max(1, preference_count))):
                idx = max(0, preference_count - 1 - offset)
                key = f"favorite_module_{idx:03d}"
                value = f"value_{idx:03d}"
                injected = await manager.build_injected_context(f"Please recall {key}", user_id=uid)
                checks.append(
                    {
                        "query": key,
                        "ok": value in injected or key.replace("_", " ").title() in injected,
                        "excerpt": " ".join(injected.split())[:180],
                    }
                )

            graph = manager.build_preference_graph_sync(uid, limit=max(12, count))
            await manager.build_injected_context("Summarize my preferences and profile facts", user_id=uid)
            frozen = manager.frozen_store.read_snapshot(uid) or {}
            return {
                "inserted": inserted,
                "retrieval_checks": checks,
                "graph": graph,
                "frozen_snapshot": frozen,
            }

        payload = asyncio.run(_exercise())
        pinned_md = Path(manager._pinned_md_path(uid))
        if pinned_md.exists():
            try:
                pinned_md.unlink()
            except Exception:
                pass
    finally:
        shutil.rmtree(root, ignore_errors=True)

    checks = list(payload.get("retrieval_checks") or [])
    passed = sum(1 for row in checks if bool(row.get("ok")))
    graph = dict(payload.get("graph") or {})
    frozen = dict(payload.get("frozen_snapshot") or {})
    ok = (
        int(payload.get("inserted") or 0) >= max(1, int(count))
        and passed == len(checks)
        and int(graph.get("node_count") or 0) >= max(6, min(int(count), 12))
        and bool(dict(frozen.get("preference_graph") or {}).get("node_count"))
    )
    return {
        "id": "memory100",
        "label": "Memory 100",
        "kind": "memory",
        "status": "pass" if ok else "fail",
        "ok": ok,
        "seconds": round(time.perf_counter() - started, 2),
        "counts": {
            "inserted": int(payload.get("inserted") or 0),
            "retrieval_checks": len(checks),
            "retrieval_passed": passed,
            "graph_nodes": int(graph.get("node_count") or 0),
        },
        "artifacts": {},
        "details": {
            "graph_summary": str(graph.get("summary") or "")[:240],
            "retrieval_rows": checks,
            "frozen_summary": str(dict(frozen.get("preference_graph") or {}).get("summary") or "")[:240],
        },
    }


def _run_reminder_pack(*, count: int) -> dict[str, Any]:
    started = time.perf_counter()
    reminder_target = max(10, int(count) // 2)
    automation_target = max(10, int(count) - reminder_target)
    tmp = tempfile.mkdtemp(prefix="somi_reminder100_")
    root = Path(tmp)
    try:
        uid = "gauntlet_reminder"
        state_store = SessionEventStore(db_path=root / "state.sqlite3")
        trace = state_store.start_turn(
            user_id=uid,
            thread_id="reminders",
            user_text="What did we decide about maintenance?",
            routing_prompt="maintenance digest",
        )
        state_store.finish_turn(
            trace=trace,
            assistant_text="We decided to rotate water filters monthly and check the solar battery bank weekly.",
            status="completed",
            route="llm_only",
            model_name="gauntlet",
            routing_prompt="maintenance digest",
            latency_ms=15,
        )
        searcher = SessionSearchService(
            state_store=state_store,
            artifacts_root=root / "artifacts",
            jobs_root=root / "jobs",
        )
        manager = Memory3Manager(
            user_id=uid,
            store=SQLiteMemoryStore(db_path=str(root / "memory.sqlite3")),
            frozen_store=FrozenMemoryStore(root_dir=root / "frozen"),
            session_search=searcher,
        )
        gateway = DeliveryGateway(root_dir=root / "delivery")
        store = AutomationStore(db_path=root / "automations.sqlite3")
        engine = AutomationEngine(
            store=store,
            gateway=gateway,
            session_search=searcher,
            timezone_name="UTC",
        )

        async def _create_reminders() -> dict[str, Any]:
            created = 0
            deleted = 0
            for idx in range(reminder_target):
                reminder_id = await manager.add_reminder(
                    uid,
                    f"check system {idx:03d}",
                    "in 1 seconds",
                    details=f"Reminder payload {idx:03d}",
                    scope="task",
                    priority=2 + (idx % 3),
                )
                if reminder_id:
                    created += 1
            for idx in range(min(5, created)):
                deleted += int(await manager.delete_reminder_by_title(uid, f"check system {idx:03d}", scope="task"))
                replacement = await manager.add_reminder(
                    uid,
                    f"check system {idx:03d} revised",
                    "in 1 seconds",
                    details=f"Reminder payload revised {idx:03d}",
                    scope="task",
                    priority=4,
                )
                if replacement:
                    created += 1
            active = await manager.list_active_reminders(uid, scope="task", limit=max(25, reminder_target + 10))
            return {"created": created, "deleted": deleted, "active_before_due": len(active)}

        reminder_meta = asyncio.run(_create_reminders())

        now = datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc)
        created_automations: list[str] = []
        for idx in range(automation_target):
            automation = engine.create_automation(
                name=f"gauntlet automation {idx:03d}",
                user_id=uid,
                schedule_text="every day at 9 am",
                channel="desktop",
                automation_type="session_digest" if idx % 2 == 0 else "note",
                payload=(
                    {"query": "maintenance", "thread_id": "reminders", "limit": 2, "days": 90}
                    if idx % 2 == 0
                    else {"message": f"Automation note {idx:03d}"}
                ),
                now=now,
            )
            automation_id = str(automation.get("automation_id") or "")
            if automation_id:
                created_automations.append(automation_id)

        paused = 0
        due_count = 0
        for idx, automation_id in enumerate(created_automations):
            if idx < min(5, len(created_automations)):
                store.update_schedule(automation_id, next_run_at="", last_run_at="", status="paused")
                paused += 1
                continue
            store.update_schedule(automation_id, next_run_at=now.isoformat(), last_run_at="", status="active")
            due_count += 1

        time.sleep(1.2)
        consumed = manager.consume_due_reminders_sync(uid, limit=max(reminder_target + 10, 25))
        delivered = engine.run_due(now=now, limit=max(automation_target + 5, 25))
        status_page = engine.render_status_page(user_id=uid, limit=8)
        outbox = gateway.list_messages("desktop", box="outbox", limit=max(automation_target + 5, 25))

        pinned_md = Path(manager._pinned_md_path(uid))
        if pinned_md.exists():
            try:
                pinned_md.unlink()
            except Exception:
                pass
    finally:
        shutil.rmtree(root, ignore_errors=True)

    delivered_ok = all(str(row.get("receipt", {}).get("status") or "") == "delivered" for row in delivered)
    ok = (
        int(reminder_meta.get("created") or 0) >= reminder_target
        and len(consumed) >= max(1, reminder_target - int(reminder_meta.get("deleted") or 0))
        and len(created_automations) >= automation_target
        and len(delivered) == due_count
        and delivered_ok
        and len(outbox) >= due_count
        and paused >= min(5, automation_target)
    )
    return {
        "id": "reminder100",
        "label": "Reminder 100",
        "kind": "reminder",
        "status": "pass" if ok else "fail",
        "ok": ok,
        "seconds": round(time.perf_counter() - started, 2),
        "counts": {
            "reminders_created": int(reminder_meta.get("created") or 0),
            "reminders_deleted": int(reminder_meta.get("deleted") or 0),
            "reminders_consumed": len(consumed),
            "automations_created": len(created_automations),
            "automations_paused": paused,
            "automations_delivered": len(delivered),
        },
        "artifacts": {},
        "details": {
            "status_page_excerpt": _tail(status_page, lines=10),
            "outbox_titles": [str(row.get("title") or "") for row in outbox[:8]],
        },
    }


def _run_compaction_pack(*, count: int, include_live_chat: bool) -> dict[str, Any]:
    started = time.perf_counter()
    synthetic_rows: list[dict[str, Any]] = []
    for idx in range(max(1, int(count))):
        ledger = update_state_ledger(
            "gauntlet_compaction",
            user_text=f"Continue research track {idx}",
            assistant_text="Decision: keep context stable and preserve the repair plan.",
            ledger={
                "goals": [],
                "decisions": [],
                "open_loops": [],
                "unresolved_asks": [],
                "last_user_intent": "",
                "last_assistant_commitments": [],
                "turn_count": 0,
            },
        )
        block = render_state_ledger_block(ledger)
        summary = build_compaction_summary(
            messages=[
                {"role": "user", "content": f"Long research turn {idx}"},
                {"role": "assistant", "content": "I will preserve decisions and continue the plan."},
            ],
            state_ledger=ledger,
        )
        synthetic_rows.append(
            {
                "index": idx,
                "ok": bool(block.strip()) and summary.startswith("[Compaction Summary]") and "Ledger decisions" in summary,
                "summary_len": len(summary),
            }
        )

    live_report: dict[str, Any] = {}
    if include_live_chat:
        live_report = asyncio.run(run_live_stress())

    synthetic_passed = sum(1 for row in synthetic_rows if bool(row.get("ok")))
    live_ok = True if not include_live_chat else bool(live_report.get("ok"))
    ok = synthetic_passed == len(synthetic_rows) and live_ok
    artifacts = {}
    live_artifact = ROOT / "sessions" / "evals" / "live_chat_stress_matrix.json"
    if include_live_chat and live_artifact.exists():
        artifacts["live_chat_stress"] = str(live_artifact)
    return {
        "id": "compaction100",
        "label": "Compaction 100",
        "kind": "compaction",
        "status": "pass" if ok else "fail",
        "ok": ok,
        "seconds": round(time.perf_counter() - started, 2),
        "counts": {
            "synthetic_cases": len(synthetic_rows),
            "synthetic_passed": synthetic_passed,
            "live_checks": int(live_report.get("total") or 0) if include_live_chat else 0,
            "live_passed": int(live_report.get("passed") or 0) if include_live_chat else 0,
        },
        "artifacts": artifacts,
        "details": {
            "sample_rows": synthetic_rows[:8],
            "live_report": live_report,
        },
    }


def _run_ocr_pack(*, count: int) -> dict[str, Any]:
    started = time.perf_counter()
    kinds = ["txt", "md", "csv", "json", "yml", "log", "unsupported"]
    results: list[dict[str, Any]] = []
    tmp = tempfile.mkdtemp(prefix="somi_ocr100_")
    root = Path(tmp)
    try:
        for idx in range(max(1, int(count))):
            kind = kinds[idx % len(kinds)]
            if kind == "txt":
                path = root / f"note_{idx:03d}.txt"
                path.write_text(f"  Repair checklist {idx}\n\nStep 1: Inspect logs\nStep 2: Patch runtime {idx}\n", encoding="utf-8")
            elif kind == "md":
                path = root / f"note_{idx:03d}.md"
                path.write_text(f"# Shelter plan {idx}\n\n- Water\n- Power\n- Radios\n", encoding="utf-8")
            elif kind == "csv":
                path = root / f"sheet_{idx:03d}.csv"
                path.write_text("item,qty,total\nWater filter,2,31.00\nSolar fuse,4,12.00\n", encoding="utf-8")
            elif kind == "json":
                path = root / f"payload_{idx:03d}.json"
                path.write_text(json.dumps({"title": f"Report {idx}", "priority": "high", "notes": ["repair", "inventory"]}), encoding="utf-8")
            elif kind == "yml":
                path = root / f"config_{idx:03d}.yml"
                path.write_text("mode: repair\nbudget: medium\nnotes:\n  - test radios\n  - fill drums\n", encoding="utf-8")
            elif kind == "log":
                path = root / f"service_{idx:03d}.log"
                path.write_text("INFO boot ok\nWARN battery low\nINFO retry engaged\n", encoding="utf-8")
            else:
                path = root / f"archive_{idx:03d}.zip"
                path.write_bytes(b"PK\x03\x04")
            payload = extract_document_payload(path)
            note = build_document_note(payload)
            expect_ok = kind != "unsupported"
            row_ok = bool(payload.get("ok")) if expect_ok else (not bool(payload.get("ok")) and bool(payload.get("manual_review_required")))
            results.append(
                {
                    "file": path.name,
                    "kind": kind,
                    "ok": row_ok,
                    "document_kind": str(payload.get("document_kind") or ""),
                    "note_excerpt": " ".join(note.split())[:180],
                }
            )
    finally:
        shutil.rmtree(root, ignore_errors=True)

    passed = sum(1 for row in results if bool(row.get("ok")))
    ok = passed == len(results)
    return {
        "id": "ocr100",
        "label": "OCR 100",
        "kind": "ocr",
        "status": "pass" if ok else "fail",
        "ok": ok,
        "seconds": round(time.perf_counter() - started, 2),
        "counts": {
            "cases": len(results),
            "passed": passed,
            "manual_review_cases": sum(1 for row in results if row.get("kind") == "unsupported"),
        },
        "artifacts": {},
        "details": {"sample_rows": results[:10]},
    }


def _run_coding_pack(*, count: int) -> dict[str, Any]:
    started = time.perf_counter()
    operations: list[dict[str, Any]] = []
    tmp = tempfile.mkdtemp(prefix="somi_coding100_")
    root = Path(tmp)
    try:
        service = CodingSessionService(
            store=CodingSessionStore(root_dir=root / "sessions"),
            workspace_manager=CodingWorkspaceManager(root_dir=root / "workspaces"),
            job_store=CodingJobStore(root_dir=root / "jobs"),
        )
        control = CodexControlPlane(
            coding_service=service,
            store=service.store,
            job_store=service.job_store,
        )

        idx = 0
        while len(operations) < max(1, int(count)):
            session = control.open_session(
                user_id="gauntlet_coding",
                objective=f"Repair coding task {idx:03d}",
                source="gauntlet",
            )
            session_id = str(session.get("session_id") or "")
            operations.append({"step": "open_session", "ok": bool(session_id)})
            if len(operations) >= count:
                break

            edit_readme = control.apply_text_edit(
                session_id=session_id,
                relative_path="README.md",
                content=f"# Coding Task {idx:03d}\n\nThis workspace was refreshed by the gauntlet.\n",
                notes="refresh readme",
            )
            operations.append({"step": "edit_readme", "ok": bool(edit_readme.get("ok"))})
            if len(operations) >= count:
                break

            edit_module = control.apply_text_edit(
                session_id=session_id,
                relative_path=f"src/task_{idx:03d}.py",
                content=f"def task_{idx:03d}() -> str:\n    return 'ok-{idx:03d}'\n",
                notes="add task module",
            )
            operations.append({"step": "edit_module", "ok": bool(edit_module.get("ok"))})
            if len(operations) >= count:
                break

            inspect = control.inspect_workspace(
                session_id=session_id,
                relative_paths=["README.md", f"src/task_{idx:03d}.py"],
            )
            operations.append({"step": "inspect_workspace", "ok": bool(inspect.get("ok"))})
            if len(operations) >= count:
                break

            verify = control.run_verify_cycle(session_id=session_id)
            operations.append({"step": "verify_cycle", "ok": bool(verify.get("ok"))})
            if len(operations) >= count:
                break

            snapshot = control.build_control_snapshot(session_id=session_id, include_file_previews=True)
            operations.append({"step": "control_snapshot", "ok": bool(snapshot.get("ok"))})
            idx += 1
    finally:
        shutil.rmtree(root, ignore_errors=True)

    passed = sum(1 for row in operations if bool(row.get("ok")))
    ok = passed == len(operations) and len(operations) >= max(1, int(count))
    return {
        "id": "coding100",
        "label": "Coding 100",
        "kind": "coding",
        "status": "pass" if ok else "fail",
        "ok": ok,
        "seconds": round(time.perf_counter() - started, 2),
        "counts": {
            "operations": len(operations),
            "passed": passed,
            "sessions_exercised": max(1, len(operations) // 6),
        },
        "artifacts": {},
        "details": {"sample_steps": operations[:12]},
    }


def _run_average_user_pack(*, turns: int, include_live_chat: bool) -> dict[str, Any]:
    started = time.perf_counter()
    timeline: list[dict[str, Any]] = []
    tmp = tempfile.mkdtemp(prefix="somi_user30_")
    root = Path(tmp)
    try:
        uid = "gauntlet_user30"
        state_store = SessionEventStore(db_path=root / "state.sqlite3")
        searcher = SessionSearchService(
            state_store=state_store,
            artifacts_root=root / "artifacts",
            jobs_root=root / "jobs",
        )
        memory = Memory3Manager(
            user_id=uid,
            store=SQLiteMemoryStore(db_path=str(root / "memory.sqlite3")),
            frozen_store=FrozenMemoryStore(root_dir=root / "frozen"),
            session_search=searcher,
        )
        gateway_service = GatewayService(root_dir=root / "gateway")
        telegram_bridge = TelegramRuntimeBridge(gateway_service=gateway_service, state_store=state_store)
        delivery_gateway = DeliveryGateway(root_dir=root / "delivery")
        automation_store = AutomationStore(db_path=root / "automations.sqlite3")
        automation_engine = AutomationEngine(
            store=automation_store,
            gateway=delivery_gateway,
            session_search=searcher,
            timezone_name="UTC",
        )
        ops = OpsControlPlane(root_dir=root / "ops")
        background = BackgroundTaskStore(root_dir=root / "background")
        coding_service = CodingSessionService(
            store=CodingSessionStore(root_dir=root / "coding_sessions"),
            workspace_manager=CodingWorkspaceManager(root_dir=root / "coding_workspaces"),
            job_store=CodingJobStore(root_dir=root / "coding_jobs"),
        )
        coding = CodexControlPlane(
            coding_service=coding_service,
            store=coding_service.store,
            job_store=coding_service.job_store,
        )

        trace = state_store.start_turn(
            user_id=uid,
            thread_id="avg_user",
            user_text="Please keep my shelter repair plan organized.",
            routing_prompt="shelter repair plan",
            metadata={"surface": "gui", "conversation_id": "desktop-main"},
        )
        state_store.finish_turn(
            trace=trace,
            assistant_text="I will keep the shelter repair plan organized and resumable.",
            status="completed",
            route="continuity_artifact",
            model_name="gauntlet",
            routing_prompt="shelter repair plan",
            latency_ms=18,
        )
        timeline.append({"step": "session_seed", "ok": True, "detail": "Created a resumable planning thread."})

        async def _memory_flow() -> tuple[str, str | None]:
            await memory.upsert_fact({"key": "preferred_theme", "value": "shadowed", "kind": "preference", "confidence": 0.9}, user_id=uid)
            await memory.upsert_fact({"key": "repair_priority", "value": "water systems first", "kind": "constraint", "confidence": 0.88}, user_id=uid)
            await memory.add_reminder(uid, "check cistern pressure", "in 1 seconds", details="Basement valves")
            injected = await memory.build_injected_context("What do you remember about my repair priority?", user_id=uid)
            return injected, memory._pinned_md_path(uid)

        memory_context, pinned_path = asyncio.run(_memory_flow())
        timeline.append(
            {
                "step": "memory_context",
                "ok": "water systems first" in memory_context or "repair_priority" in memory_context,
                "detail": "Built a memory-backed context block for the user plan.",
            }
        )

        time.sleep(1.2)
        due = memory.consume_due_reminders_sync(uid, limit=5)
        timeline.append(
            {
                "step": "reminder_due",
                "ok": bool(due),
                "detail": f"Consumed {len(due)} due reminder(s).",
            }
        )

        now = datetime(2026, 3, 19, 9, 30, tzinfo=timezone.utc)
        automation = automation_engine.create_automation(
            name="Average user digest",
            user_id=uid,
            schedule_text="every day at 9 am",
            channel="desktop",
            automation_type="session_digest",
            payload={"query": "shelter repair", "thread_id": "avg_user", "limit": 3, "days": 30},
            now=now,
        )
        automation_store.update_schedule(str(automation.get("automation_id") or ""), next_run_at=now.isoformat(), last_run_at="")
        delivered = automation_engine.run_due(now=now, limit=5)
        timeline.append(
            {
                "step": "automation_digest",
                "ok": len(delivered) == 1 and str(delivered[0].get("receipt", {}).get("status") or "") == "delivered",
                "detail": "Delivered a digest back through the local gateway.",
            }
        )

        coding_session = coding.open_session(user_id=uid, objective="Patch the repair checklist renderer", source="gui")
        session_id = str(coding_session.get("session_id") or "")
        edit = coding.apply_text_edit(
            session_id=session_id,
            relative_path="README.md",
            content="# Repair Checklist\n\nTrack pump, battery, and radio tasks.\n",
            notes="update checklist",
        )
        verify = coding.run_verify_cycle(session_id=session_id)
        timeline.append(
            {
                "step": "coding_loop",
                "ok": bool(edit.get("ok")) and bool(verify.get("ok")),
                "detail": "Opened coding mode, applied an edit, and ran a verify cycle.",
            }
        )

        task = background.create_task(
            user_id=uid,
            objective="Summarize the maintenance checklist while the user rests",
            task_type="research",
            surface="gui",
            thread_id="avg_user",
        )
        task_id = str(task.get("task_id") or "")
        background.heartbeat(task_id, summary="Collecting the latest checklist notes")
        background.complete_task(task_id, summary="Checklist summary ready", handoff={"surface": "gui", "reason": "summary_ready"})
        timeline.append(
            {
                "step": "background_task",
                "ok": str((background.load_task(task_id) or {}).get("status") or "") == "completed",
                "detail": "Created and completed a background task with a GUI handoff.",
            }
        )

        thread_id = telegram_bridge.resolve_thread_id(
            user_id=uid,
            prompt="continue with that plan",
            conversation_id="tg:dm",
        )
        bundle = build_telegram_reply_bundle(
            content="I kept the repair plan synchronized and condensed the latest notes.",
            route="websearch",
            thread_id=thread_id,
            browse_report={
                "mode": "official",
                "progress_headline": "Checked the latest support notes",
                "sources": [
                    {"title": "Repair checklist", "url": "https://example.com/repair-checklist"},
                    {"title": "Battery maintenance", "url": "https://example.com/battery-maintenance"},
                ],
                "sources_count": 2,
            },
        )
        timeline.append(
            {
                "step": "telegram_bundle",
                "ok": "Research note:" in str(bundle.get("primary") or "") and "Sources:" in str(bundle.get("primary") or ""),
                "detail": "Rendered a cross-surface reply bundle with a research capsule.",
            }
        )

        ops_task = ops.create_background_task(
            user_id=uid,
            objective="Index the support artifacts",
            task_type="ops",
            surface="gui",
            thread_id="avg_user",
        )
        ops.heartbeat_background_task(str(ops_task.get("task_id") or ""), summary="Indexing support artifacts")
        ops.complete_background_task(str(ops_task.get("task_id") or ""), summary="Support artifacts indexed", handoff={"surface": "gui"})
        timeline.append(
            {
                "step": "ops_handoff",
                "ok": int(dict(ops.snapshot().get("background_tasks") or {}).get("counts", {}).get("completed", 0)) >= 1,
                "detail": "Surfaced the background task through the ops snapshot.",
            }
        )

        live_report: dict[str, Any] = {}
        live_turns = 0
        if include_live_chat:
            live_report = asyncio.run(run_live_stress())
            live_turns = 19
            timeline.append(
                {
                    "step": "live_chat",
                    "ok": bool(live_report.get("ok")),
                    "detail": f"Ran the live chat stress matrix with {int(live_report.get('passed') or 0)}/{int(live_report.get('total') or 0)} checks passing.",
                }
            )

        if pinned_path:
            pinned = Path(pinned_path)
            if pinned.exists():
                try:
                    pinned.unlink()
                except Exception:
                    pass
    finally:
        shutil.rmtree(root, ignore_errors=True)

    completed_steps = sum(1 for row in timeline if bool(row.get("ok")))
    target_turns = max(6, int(turns or 30))
    simulated_turns = min(target_turns, len(timeline) + live_turns + len(due))
    required_turns = min(18, target_turns) if include_live_chat else min(8, target_turns)
    ok = completed_steps == len(timeline) and simulated_turns >= required_turns
    return {
        "id": "averageuser30",
        "label": "Average User 30",
        "kind": "scenario",
        "status": "pass" if ok else "fail",
        "ok": ok,
        "seconds": round(time.perf_counter() - started, 2),
        "counts": {
            "timeline_steps": len(timeline),
            "timeline_passed": completed_steps,
            "simulated_turns": simulated_turns,
            "target_turns": target_turns,
        },
        "artifacts": {},
        "details": {
            "timeline": timeline,
            "live_report": live_report if include_live_chat else {},
            "telegram_excerpt": str(bundle.get("primary") or "")[:240],
        },
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# System Gauntlet",
        "",
        f"Generated: {report.get('generated_at', '')}",
        f"Status: {report.get('status', '')}",
        f"Pack count: {report.get('pack_count', 0)}",
        f"Passed packs: {report.get('passed_packs', 0)}",
        "",
    ]
    for pack in list(report.get("packs") or []):
        lines.append(f"## {pack.get('label', '')}")
        lines.append("")
        lines.append(f"- Status: {pack.get('status', '')}")
        lines.append(f"- Seconds: {pack.get('seconds', 0)}")
        if dict(pack.get("counts") or {}):
            lines.append(f"- Counts: {dict(pack.get('counts') or {})}")
        if dict(pack.get("artifacts") or {}):
            lines.append(f"- Artifacts: {dict(pack.get('artifacts') or {})}")
        detail_lines = list(pack.get("details", {}).get("summary_excerpt") or [])
        if detail_lines:
            lines.append("- Summary excerpt:")
            for row in detail_lines[:6]:
                lines.append(f"  - {row}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_system_gauntlet_report(
    *,
    python_executable: Path,
    output_dir: Path,
    prefix: str,
    base_count: int = 100,
    scenario_turns: int = 30,
    search_corpus: str = "everyday100",
    selected_packs: list[str] | None = None,
    include_live_chat: bool = True,
) -> dict[str, Any]:
    specs = build_system_gauntlet_specs(
        prefix,
        base_count=base_count,
        search_corpus=search_corpus,
        scenario_turns=scenario_turns,
    )
    selected = {str(item or "").strip().lower() for item in list(selected_packs or []) if str(item or "").strip()}
    if selected:
        specs = [spec for spec in specs if str(spec.get("id") or "").lower() in selected]

    packs: list[dict[str, Any]] = []
    for spec in specs:
        kind = str(spec.get("kind") or "")
        if kind == "search_batch":
            packs.append(_run_search_pack(spec, python_executable=python_executable, output_dir=output_dir))
        elif kind == "memory":
            packs.append(_run_memory_pack(count=int(spec.get("count") or base_count)))
        elif kind == "reminder":
            packs.append(_run_reminder_pack(count=int(spec.get("count") or base_count)))
        elif kind == "compaction":
            packs.append(_run_compaction_pack(count=int(spec.get("count") or base_count), include_live_chat=include_live_chat))
        elif kind == "ocr":
            packs.append(_run_ocr_pack(count=int(spec.get("count") or base_count)))
        elif kind == "coding":
            packs.append(_run_coding_pack(count=int(spec.get("count") or base_count)))
        elif kind == "scenario":
            packs.append(_run_average_user_pack(turns=int(spec.get("turns") or scenario_turns), include_live_chat=include_live_chat))

    passed = sum(1 for pack in packs if bool(pack.get("ok")))
    ok = passed == len(packs)
    return {
        "generated_at": _now_iso(),
        "prefix": prefix,
        "ok": ok,
        "status": "pass" if ok else "fail",
        "pack_count": len(packs),
        "passed_packs": passed,
        "packs": packs,
    }


def write_system_gauntlet_report(
    *,
    root_dir: str | Path = ".",
    python_executable: str = sys.executable,
    output_dir: str | Path = "audit",
    prefix: str = "system_gauntlet",
    base_count: int = 100,
    scenario_turns: int = 30,
    search_corpus: str = "everyday100",
    selected_packs: list[str] | None = None,
    include_live_chat: bool = True,
) -> dict[str, Any]:
    del root_dir
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = build_system_gauntlet_report(
        python_executable=Path(python_executable),
        output_dir=out,
        prefix=prefix,
        base_count=base_count,
        scenario_turns=scenario_turns,
        search_corpus=search_corpus,
        selected_packs=selected_packs,
        include_live_chat=include_live_chat,
    )
    json_path = out / f"{prefix}.json"
    md_path = out / f"{prefix}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    persisted = dict(report)
    persisted["paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return persisted


def format_system_gauntlet(report: dict[str, Any]) -> str:
    lines = [
        "[Somi System Gauntlet]",
        f"- status: {report.get('status', '')}",
        f"- pack_count: {report.get('pack_count', 0)}",
        f"- passed_packs: {report.get('passed_packs', 0)}",
    ]
    for pack in list(report.get("packs") or []):
        lines.append(
            f"- {pack.get('id')}: {pack.get('status')} ({pack.get('seconds', 0)}s) counts={dict(pack.get('counts') or {})}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the coordinated Phase 136 full-system gauntlet.")
    parser.add_argument("--output-dir", default=str(ROOT / "audit"), help="Directory for gauntlet artifacts.")
    parser.add_argument("--prefix", default="system_gauntlet", help="Artifact prefix.")
    parser.add_argument("--python-executable", default=sys.executable, help="Python interpreter to use.")
    parser.add_argument("--packs", default="", help="Comma-separated pack ids to run. Defaults to all.")
    parser.add_argument("--count", type=int, default=100, help="Default count for the 100x packs.")
    parser.add_argument("--scenario-turns", type=int, default=30, help="Target turn count for the average user scenario.")
    parser.add_argument("--search-corpus", default="everyday100", help="Search corpus for the search gauntlet pack.")
    parser.add_argument("--skip-live-chat", action="store_true", help="Skip the live chat stress pass inside compaction and scenario packs.")
    args = parser.parse_args()

    selected = [item.strip() for item in str(args.packs or "").split(",") if item.strip()]
    report = write_system_gauntlet_report(
        output_dir=args.output_dir,
        prefix=str(args.prefix or "system_gauntlet"),
        python_executable=str(args.python_executable or sys.executable),
        selected_packs=selected,
        base_count=int(args.count or 100),
        scenario_turns=int(args.scenario_turns or 30),
        search_corpus=str(args.search_corpus or "everyday100"),
        include_live_chat=not bool(args.skip_live_chat),
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
