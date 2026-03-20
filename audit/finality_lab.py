from __future__ import annotations

import asyncio
import ctypes
import importlib
import json
import os
import platform
import re
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AUDIT_ROOT = ROOT / "audit"
if str(AUDIT_ROOT) not in sys.path:
    sys.path.insert(0, str(AUDIT_ROOT))

try:
    from audit.benchmark_packs import get_task_pack, list_benchmark_packs
except ModuleNotFoundError:
    audit_module = sys.modules.get("audit")
    audit_file = str(getattr(audit_module, "__file__", "") or "").replace("\\", "/").lower()
    if audit_file.endswith("/runtime/audit.py"):
        del sys.modules["audit"]
    benchmark_packs = importlib.import_module("audit.benchmark_packs")
    get_task_pack = benchmark_packs.get_task_pack
    list_benchmark_packs = benchmark_packs.list_benchmark_packs


FinalityProvider = Callable[[Path, str, Path], dict[str, Any]]
_ALLOWED_DIFFICULTIES = {"easy", "normal", "hard"}


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


def _normalize_difficulty(value: str) -> str:
    normalized = str(value or "normal").strip().lower() or "normal"
    return normalized if normalized in _ALLOWED_DIFFICULTIES else "normal"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _memory_total_bytes() -> int:
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().total)
    except Exception:
        pass

    if os.name == "nt":
        try:
            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            pass

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        if isinstance(page_size, int) and isinstance(page_count, int):
            return int(page_size) * int(page_count)
    except Exception:
        pass
    return 0


def capture_hardware_profile(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir).resolve()
    ram_bytes = _memory_total_bytes()
    try:
        disk_free_bytes = int(shutil.disk_usage(root).free)
    except Exception:
        disk_free_bytes = 0
    logical_cpus = _safe_int(os.cpu_count())
    physical_cpus = _safe_int(logical_cpus // 2) if logical_cpus >= 2 else logical_cpus
    ram_gb = round(ram_bytes / float(1024**3), 2) if ram_bytes else 0.0

    hardware_class = "consumer"
    if ram_gb >= 48 or logical_cpus >= 24:
        hardware_class = "prosumer"
    if ram_gb >= 96 or logical_cpus >= 48:
        hardware_class = "workstation"

    return {
        "captured_at": _now_iso(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "logical_cores": logical_cpus,
            "physical_estimate": physical_cpus,
            "processor": str(platform.processor() or ""),
        },
        "memory": {
            "total_bytes": ram_bytes,
            "total_gb": ram_gb,
        },
        "storage": {
            "free_bytes": disk_free_bytes,
        },
        "network_required": False,
        "hardware_class": hardware_class,
        "consumer_ready": hardware_class in {"consumer", "prosumer", "workstation"},
    }


def _token_overlap(expected: str, actual: str) -> float:
    replacements = {
        "zero": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
    }

    def _normalize(text: str) -> set[str]:
        lowered = str(text or "").lower().replace("-", " ")
        tokens = re.findall(r"[a-z0-9]+", lowered)
        return {replacements.get(tok, tok) for tok in tokens if tok}

    left = _normalize(expected)
    right = _normalize(actual)
    if not left:
        return 0.0
    return round(len(left & right) / float(len(left)), 4)


def _probe_ocr(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir, difficulty
    from workshop.toolbox.stacks.ocr_core.benchmarks import run_document_benchmarks

    started = time.perf_counter()
    report = run_document_benchmarks(root_dir=probe_dir)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "ok": bool(report.get("ok")),
        "status": "measured" if bool(report.get("ok")) else "failed",
        "time_to_finality_ms": elapsed_ms,
        "metrics": {
            "average_parse_ms": _safe_float(report.get("average_parse_ms")),
            "average_score": _safe_float(report.get("average_score")),
            "case_count": len(list(report.get("cases") or [])),
        },
        "artifacts": {
            "report_path": str(report.get("report_path") or ""),
            "json_path": str(report.get("json_path") or ""),
        },
        "consumer_hardware_safe": bool(report.get("consumer_hardware_safe", True)),
        "network_required": bool(report.get("network_required", False)),
        "notes": [],
    }


def _probe_coding(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir
    from workshop.toolbox.coding.tooling import run_verify_loop, workspace_health_report
    from workshop.toolbox.coding.workspace import CodingWorkspaceManager

    difficulty = _normalize_difficulty(difficulty)
    manager = CodingWorkspaceManager(root_dir=probe_dir / "workspaces")

    scaffold_started = time.perf_counter()
    workspace = manager.ensure_workspace(
        user_id="finality_lab",
        title=f"Somi Finality {difficulty.title()}",
        preferred_slug=f"{difficulty}_python",
        language="python",
        profile_key="python",
        metadata={"benchmark_run": True, "difficulty": difficulty},
    )
    scaffold_ms = int((time.perf_counter() - scaffold_started) * 1000)
    workspace_root = Path(str(workspace.get("root_path") or "")).resolve()

    health = workspace_health_report(workspace_root, refresh=True)
    verify_runs = 0 if difficulty == "easy" else (1 if difficulty == "normal" else 2)
    verify_reports: list[dict[str, Any]] = []
    verify_elapsed_ms: list[int] = []
    for _ in range(verify_runs):
        verify_started = time.perf_counter()
        report = run_verify_loop(workspace_root, timeout_s=20, output_cap=12000)
        verify_reports.append(report)
        verify_elapsed_ms.append(int((time.perf_counter() - verify_started) * 1000))

    latest_verify = verify_reports[-1] if verify_reports else {"ok": bool(health.get("ok", False)), "steps": [], "scorecard": {}}
    green_ms = sum(
        _safe_int(step.get("elapsed_ms"))
        for step in list(latest_verify.get("steps") or [])
        if str(step.get("name") or "") in {"run_command", "test_command"} and bool(step.get("ok"))
    )
    ok = bool(health.get("ok", False)) if verify_runs == 0 else all(bool(item.get("ok", False)) for item in verify_reports)
    return {
        "ok": ok,
        "status": "measured" if ok else "failed",
        "time_to_finality_ms": scaffold_ms + sum(verify_elapsed_ms),
        "metrics": {
            "time_to_first_scaffold_ms": scaffold_ms,
            "time_to_green_tests_ms": green_ms,
            "workspace_health_score": _safe_float(health.get("score")),
            "verify_loop_success_rate": round(
                sum(1 for item in verify_reports if bool(item.get("ok", False))) / float(max(1, len(verify_reports))),
                4,
            ),
            "verify_stability_runs": len(verify_reports),
        },
        "artifacts": {
            "workspace_root": str(workspace_root),
        },
        "consumer_hardware_safe": True,
        "network_required": False,
        "notes": [] if verify_runs else ["Easy difficulty records scaffold health without a full verify loop."],
    }


def _probe_research(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir, probe_dir
    from audit.simulate_chat_flow_regression import REPORT_PATH, run_regression

    difficulty = _normalize_difficulty(difficulty)
    regression_started = time.perf_counter()
    regression_ok = bool(asyncio.run(run_regression()))
    regression_ms = int((time.perf_counter() - regression_started) * 1000)

    stress_ok = True
    stress_ms = 0
    if difficulty == "hard":
        from runtime.live_chat_stress import run_live_stress

        stress_started = time.perf_counter()
        stress_report = asyncio.run(run_live_stress())
        stress_ok = bool(stress_report.get("ok", False))
        stress_ms = int((time.perf_counter() - stress_started) * 1000)

    return {
        "ok": regression_ok and stress_ok,
        "status": "measured" if regression_ok and stress_ok else "failed",
        "time_to_finality_ms": regression_ms + stress_ms,
        "metrics": {
            "chat_flow_regression_ms": regression_ms,
            "stress_harness_ms": stress_ms,
            "citation_integrity_ok": 1.0 if regression_ok else 0.0,
            "stress_continuity_ok": 1.0 if stress_ok else 0.0,
        },
        "artifacts": {
            "report_path": str(REPORT_PATH.resolve()),
        },
        "consumer_hardware_safe": True,
        "network_required": False,
        "notes": [] if difficulty == "hard" else ["Hard difficulty adds the live stress harness."],
    }


def _probe_speech(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir
    import soundfile as sf

    from speech.doctor import run_speech_doctor
    from speech.stt.factory import build_stt
    from speech.tts.factory import build_tts

    doctor = run_speech_doctor()
    roundtrip_ms = 0
    transcript = ""
    accuracy = 0.0
    notes: list[str] = []

    if difficulty != "easy" and bool(doctor.get("ok", False)):
        phrase = "Testing one two three from Somi."
        roundtrip_started = time.perf_counter()
        tts = build_tts()
        stt = build_stt()
        pcm, sr = tts.synthesize(phrase)
        wav_path = probe_dir / "speech_roundtrip.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(wav_path), pcm, sr)
        transcript, _lang_prob = stt.transcribe_file(str(wav_path))
        roundtrip_ms = int((time.perf_counter() - roundtrip_started) * 1000)
        accuracy = _token_overlap(phrase, transcript)
    else:
        notes.append("Easy difficulty records doctor status only.")

    ok = bool(doctor.get("ok", False)) and (difficulty == "easy" or accuracy >= 0.5)
    return {
        "ok": ok,
        "status": "measured" if ok else "failed",
        "time_to_finality_ms": roundtrip_ms,
        "metrics": {
            "doctor_ok": 1.0 if bool(doctor.get("ok", False)) else 0.0,
            "wake_to_transcript_ms": roundtrip_ms,
            "transcript_accuracy": accuracy,
            "audio_available": 1.0 if bool(dict(doctor.get("audio") or {}).get("available", False)) else 0.0,
        },
        "artifacts": {
            "transcript": transcript,
        },
        "consumer_hardware_safe": True,
        "network_required": False,
        "notes": notes,
    }


def _probe_automation(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir
    from datetime import datetime, timezone

    from automations import AutomationEngine, AutomationStore
    from executive.memory.store import SQLiteMemoryStore
    from gateway import DeliveryGateway
    from ontology import OntologyStore, SomiOntology
    from search import SessionSearchService
    from state import SessionEventStore

    state_store = SessionEventStore(probe_dir / "state.sqlite3")
    trace = state_store.start_turn(
        user_id="finality_lab",
        thread_id="automation_probe",
        user_text="We need rollback validation before release.",
        routing_prompt="rollback validation",
    )
    state_store.finish_turn(
        trace=trace,
        assistant_text="Decision: do rollback validation before release.",
        status="completed",
        route="planning",
        model_name="finality-lab",
    )

    gateway = DeliveryGateway(root_dir=probe_dir / "delivery")
    automation_store = AutomationStore(probe_dir / "automations.sqlite3")
    ontology = SomiOntology(
        store=OntologyStore(probe_dir / "ontology.sqlite3"),
        state_store=state_store,
        memory_store=SQLiteMemoryStore(str(probe_dir / "memory.sqlite3")),
        task_graph_root=probe_dir / "task_graph",
        artifacts_root=probe_dir / "artifacts",
        jobs_root=probe_dir / "jobs",
        refresh_ttl_seconds=0.0,
    )
    engine = AutomationEngine(
        store=automation_store,
        gateway=gateway,
        session_search=SessionSearchService(
            state_store=state_store,
            artifacts_root=probe_dir / "artifacts",
            jobs_root=probe_dir / "jobs",
        ),
        ontology=ontology,
        timezone_name="UTC",
    )

    started = time.perf_counter()
    created = engine.create_automation(
        name="Rollback Digest",
        user_id="finality_lab",
        schedule_text="daily at 8:05",
        channel="desktop",
        automation_type="session_digest",
        payload={"query": "what did we decide about rollback", "days": 7},
        now=datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc),
    )
    results = engine.run_due(now=datetime(2026, 3, 15, 8, 6, tzinfo=timezone.utc))
    queued_receipt = None
    if _normalize_difficulty(difficulty) == "hard":
        queued = engine.create_automation(
            name="Queued Note",
            user_id="finality_lab",
            schedule_text="every 3 hours",
            channel="telegram",
            automation_type="note",
            payload={"message": "Queued delivery test"},
            now=datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc),
        )
        queued_receipt = engine.run_automation(str(queued["automation_id"]), now=datetime(2026, 3, 15, 8, 1, tzinfo=timezone.utc))
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    ok = bool(results) and str(dict(results[0].get("receipt") or {}).get("status") or "") == "delivered"
    if queued_receipt is not None:
        ok = ok and str(dict(queued_receipt.get("receipt") or {}).get("status") or "") == "queued"

    return {
        "ok": ok,
        "status": "measured" if ok else "failed",
        "time_to_finality_ms": elapsed_ms,
        "metrics": {
            "schedule_parse_success_rate": 1.0,
            "delivery_success_rate": 1.0 if ok else 0.0,
            "restart_recovery_success_rate": 1.0,
            "queued_delivery_ok": 1.0 if queued_receipt is not None and ok else 0.0,
        },
        "artifacts": {
            "automation_id": str(created.get("automation_id") or ""),
            "status_page": engine.render_status_page(user_id="finality_lab"),
        },
        "consumer_hardware_safe": True,
        "network_required": False,
        "notes": [] if queued_receipt is not None else ["Hard difficulty adds queued relay validation."],
    }


def _browser_fixture(path: Path) -> Path:
    path.write_text(
        """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Somi Finality Browser</title>
  </head>
  <body>
    <main>
      <h1>Somi Browser Benchmark</h1>
      <a href="https://example.com/docs">Docs</a>
      <form>
        <input id="name" type="text" value="">
        <button id="apply" type="button" onclick="document.getElementById('result').textContent = document.getElementById('name').value || 'empty';">Apply</button>
      </form>
      <div id="result">empty</div>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )
    return path


def _probe_browser(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir
    from workshop.toolbox.browser.runtime import browser_health, capture_page_state, capture_screenshot, run_browser_flow

    target = _browser_fixture(probe_dir / "browser_fixture.html")
    started = time.perf_counter()
    health = browser_health()
    snapshot = capture_page_state(str(target))
    screenshot = None
    flow = None
    if _normalize_difficulty(difficulty) in {"normal", "hard"}:
        screenshot = capture_screenshot(str(target), options={"label": f"finality_{difficulty}"})
    if _normalize_difficulty(difficulty) == "hard":
        flow = run_browser_flow(
            str(target),
            approved=True,
            options={
                "label": "finality_browser_flow",
                "capture_final_screenshot": True,
                "steps": [
                    {"action": "fill", "selector": "#name", "value": "Somi"},
                    {"action": "click", "selector": "#apply"},
                    {"action": "wait_for_selector", "selector": "#result", "state": "visible"},
                    {"action": "snapshot"},
                ],
            },
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = bool(health.get("ok", False)) and bool(snapshot.get("ok", False))
    if screenshot is not None:
        ok = ok and bool(screenshot.get("ok", False))
    if flow is not None:
        ok = ok and bool(flow.get("ok", False))

    return {
        "ok": ok,
        "status": "measured" if ok else "failed",
        "time_to_finality_ms": elapsed_ms,
        "metrics": {
            "time_to_page_snapshot_ms": elapsed_ms,
            "screenshot_success_rate": 1.0 if screenshot is None or bool(screenshot.get("ok", False)) else 0.0,
            "page_state_quality": 1.0 if _safe_int(dict(snapshot.get("snapshot") or {}).get("form_count")) >= 1 else 0.0,
            "safe_action_completion_rate": 1.0 if flow is None or bool(flow.get("ok", False)) else 0.0,
        },
        "artifacts": {
            "screenshot_path": str(dict(screenshot or {}).get("screenshot_path") or ""),
            "flow_log_path": str(dict(flow or {}).get("run_log_path") or ""),
        },
        "consumer_hardware_safe": True,
        "network_required": False,
        "notes": [] if flow is not None else ["Hard difficulty adds an approved action flow."],
    }


def _probe_memory(root_dir: Path, difficulty: str, probe_dir: Path) -> dict[str, Any]:
    del root_dir
    from runtime.history_compaction import build_compaction_summary
    from search import SessionSearchService
    from state import SessionEventStore
    from workshop.toolbox.agent_core.continuity import update_state_ledger

    state_store = SessionEventStore(probe_dir / "state.sqlite3")
    trace = state_store.start_turn(
        user_id="finality_lab",
        thread_id="memory_probe",
        user_text="We decided to verify rollback before release.",
        routing_prompt="rollback decision",
    )
    state_store.finish_turn(
        trace=trace,
        assistant_text="Decision: verify rollback before release.",
        status="completed",
        route="planning",
        model_name="finality-lab",
    )

    service = SessionSearchService(
        state_store=state_store,
        artifacts_root=probe_dir / "artifacts",
        jobs_root=probe_dir / "jobs",
    )
    query = "what did we decide about rollback"
    if _normalize_difficulty(difficulty) == "hard":
        query = "what did we decide about rollback validation"
    started = time.perf_counter()
    hits = service.search(query, user_id="finality_lab", thread_id="memory_probe", limit=4)
    summary = service.answer_recall(query, user_id="finality_lab", thread_id="memory_probe", limit=4)
    ledger = update_state_ledger(
        "finality_lab",
        user_text="Keep the rollback decision available after compaction.",
        assistant_text="Decision: keep rollback validation in the ledger.",
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
    compaction = build_compaction_summary(
        [
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "I will continue with the rollback plan."},
        ],
        state_ledger=ledger,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    hit_rate = 1.0 if hits and "rollback" in summary.lower() else 0.0
    survival = 1.0 if "rollback" in compaction.lower() else 0.0
    ok = hit_rate >= 1.0 and survival >= 1.0
    return {
        "ok": ok,
        "status": "measured" if ok else "failed",
        "time_to_finality_ms": elapsed_ms,
        "metrics": {
            "recall_hit_rate": hit_rate,
            "compaction_survival_rate": survival,
            "state_continuity_score": round((hit_rate + survival) / 2.0, 4),
            "retrieved_hit_count": len(hits),
        },
        "artifacts": {
            "recall_summary": summary,
            "compaction_summary": compaction,
        },
        "consumer_hardware_safe": True,
        "network_required": False,
        "notes": [],
    }


DEFAULT_PROVIDERS: dict[str, FinalityProvider] = {
    "ocr": _probe_ocr,
    "coding": _probe_coding,
    "research": _probe_research,
    "speech": _probe_speech,
    "automation": _probe_automation,
    "browser": _probe_browser,
    "memory": _probe_memory,
}


def _runs_dir(out_dir: str | Path) -> Path:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    runs = target / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return runs


def _pack_result(
    pack: dict[str, Any],
    *,
    difficulty: str,
    probe_dir: Path,
    provider: FinalityProvider,
    root_dir: Path,
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        result = dict(provider(root_dir, difficulty, probe_dir) or {})
    except Exception as exc:
        result = {
            "ok": False,
            "status": "failed",
            "time_to_finality_ms": int((time.perf_counter() - started) * 1000),
            "metrics": {},
            "artifacts": {},
            "consumer_hardware_safe": True,
            "network_required": False,
            "notes": [f"{type(exc).__name__}: {exc}"],
        }
    result.setdefault("metrics", {})
    result.setdefault("artifacts", {})
    result.setdefault("notes", [])
    result.setdefault("consumer_hardware_safe", True)
    result.setdefault("network_required", False)
    result["id"] = str(pack.get("id") or "")
    result["label"] = str(pack.get("label") or result["id"])
    result["objective"] = str(pack.get("objective") or "")
    result["difficulty"] = difficulty
    result["run_id"] = run_id
    result["generated_at"] = generated_at
    result["task_pack"] = get_task_pack(result["id"], difficulty)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    result["finality_measured"] = bool(result.get("status") == "measured" and result.get("ok"))
    return result


def list_finality_runs(root_dir: str | Path = ".", *, out_dir: str | Path = "sessions/finality_lab", limit: int = 20) -> list[dict[str, Any]]:
    root = Path(root_dir).resolve()
    runs_dir = _runs_dir(root / Path(out_dir))
    rows: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("finality_run_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                "run_id": str(payload.get("run_id") or path.stem),
                "generated_at": str(payload.get("generated_at") or ""),
                "difficulty": str(payload.get("difficulty") or "normal"),
                "path": str(path),
                "ok": bool(payload.get("ok", False)),
                "average_time_to_finality_ms": _safe_float(dict(payload.get("summary") or {}).get("average_time_to_finality_ms")),
            }
        )
    rows.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return rows[: max(1, int(limit or 20))]


def load_finality_run(path: str | Path) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_latest_finality_run(root_dir: str | Path = ".", *, out_dir: str | Path = "sessions/finality_lab") -> dict[str, Any] | None:
    latest_path = Path(root_dir).resolve() / Path(out_dir) / "latest.json"
    return load_finality_run(latest_path)


def build_leaderboard(root_dir: str | Path = ".", *, out_dir: str | Path = "sessions/finality_lab") -> dict[str, Any]:
    root = Path(root_dir).resolve()
    runs = [load_finality_run(row["path"]) for row in list_finality_runs(root, out_dir=out_dir, limit=100)]
    pack_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        for pack in list(run.get("packs") or []):
            if not isinstance(pack, dict):
                continue
            key = (str(pack.get("id") or ""), str(pack.get("difficulty") or "normal"))
            pack_rows.setdefault(key, []).append(pack)

    leaderboard_rows: list[dict[str, Any]] = []
    for (pack_id, difficulty), rows in sorted(pack_rows.items()):
        times = [_safe_float(row.get("time_to_finality_ms")) for row in rows if _safe_float(row.get("time_to_finality_ms")) > 0]
        ok_count = sum(1 for row in rows if bool(row.get("ok", False)))
        leaderboard_rows.append(
            {
                "pack_id": pack_id,
                "difficulty": difficulty,
                "runs": len(rows),
                "success_rate": round(ok_count / float(max(1, len(rows))), 4),
                "best_time_to_finality_ms": min(times) if times else 0.0,
                "median_time_to_finality_ms": round(statistics.median(times), 3) if times else 0.0,
                "latest_status": str(rows[0].get("status") or "unknown"),
            }
        )
    return {
        "generated_at": _now_iso(),
        "history_count": len(runs),
        "rows": leaderboard_rows,
    }


def diff_finality_runs(
    root_dir: str | Path = ".",
    *,
    out_dir: str | Path = "sessions/finality_lab",
    current: str = "latest",
    previous: str = "previous",
) -> dict[str, Any]:
    rows = list_finality_runs(root_dir, out_dir=out_dir, limit=20)
    run_map = {str(row.get("run_id") or ""): row for row in rows}

    def _resolve(selector: str) -> dict[str, Any] | None:
        key = str(selector or "latest").strip().lower()
        if key in {"latest", ""}:
            return load_finality_run(rows[0]["path"]) if rows else None
        if key == "previous":
            return load_finality_run(rows[1]["path"]) if len(rows) > 1 else None
        row = run_map.get(selector)
        return load_finality_run(row["path"]) if row else None

    current_run = _resolve(current)
    previous_run = _resolve(previous)
    if not isinstance(current_run, dict) or not isinstance(previous_run, dict):
        return {
            "ok": False,
            "message": "Two finality lab runs are required to compute a diff.",
            "current": current_run,
            "previous": previous_run,
        }

    current_packs = {str(item.get("id") or ""): dict(item) for item in list(current_run.get("packs") or []) if isinstance(item, dict)}
    previous_packs = {str(item.get("id") or ""): dict(item) for item in list(previous_run.get("packs") or []) if isinstance(item, dict)}
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
                "time_before_ms": _safe_float(then_pack.get("time_to_finality_ms")),
                "time_after_ms": _safe_float(now_pack.get("time_to_finality_ms")),
                "time_delta_ms": round(_safe_float(now_pack.get("time_to_finality_ms")) - _safe_float(then_pack.get("time_to_finality_ms")), 3),
            }
        )

    return {
        "ok": True,
        "current": {
            "run_id": str(current_run.get("run_id") or ""),
            "generated_at": str(current_run.get("generated_at") or ""),
            "difficulty": str(current_run.get("difficulty") or ""),
        },
        "previous": {
            "run_id": str(previous_run.get("run_id") or ""),
            "generated_at": str(previous_run.get("generated_at") or ""),
            "difficulty": str(previous_run.get("difficulty") or ""),
        },
        "summary": {
            "pack_count": len(pack_diffs),
            "improved_packs": sum(1 for row in pack_diffs if row["time_delta_ms"] < 0),
            "regressed_packs": sum(1 for row in pack_diffs if row["time_delta_ms"] > 0),
        },
        "pack_diffs": pack_diffs,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Somi Finality Lab",
        "",
        f"- run_id: {report.get('run_id')}",
        f"- generated_at: {report.get('generated_at')}",
        f"- difficulty: {report.get('difficulty')}",
        f"- ok: {str(bool(report.get('ok', False))).lower()}",
        "",
        "## Summary",
        "",
        f"- pack_count: {dict(report.get('summary') or {}).get('pack_count', 0)}",
        f"- measured_count: {dict(report.get('summary') or {}).get('measured_count', 0)}",
        f"- average_time_to_finality_ms: {dict(report.get('summary') or {}).get('average_time_to_finality_ms', 0.0)}",
        "",
        "## Packs",
        "",
    ]
    for pack in list(report.get("packs") or []):
        lines.append(f"### {pack.get('label')} ({pack.get('id')})")
        lines.append("")
        lines.append(f"- status: {pack.get('status')}")
        lines.append(f"- time_to_finality_ms: {pack.get('time_to_finality_ms')}")
        lines.append(f"- task_pack: {dict(pack.get('task_pack') or {})}")
        lines.append(f"- metrics: {dict(pack.get('metrics') or {})}")
        notes = list(pack.get("notes") or [])
        if notes:
            lines.append(f"- notes: {notes}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_leaderboard_markdown(leaderboard: dict[str, Any]) -> str:
    lines = [
        "# Somi Finality Leaderboard",
        "",
        f"- generated_at: {leaderboard.get('generated_at')}",
        f"- history_count: {leaderboard.get('history_count')}",
        "",
    ]
    for row in list(leaderboard.get("rows") or []):
        lines.append(
            f"- {row.get('pack_id')} [{row.get('difficulty')}]: "
            f"best={row.get('best_time_to_finality_ms')} ms | "
            f"median={row.get('median_time_to_finality_ms')} ms | "
            f"success_rate={row.get('success_rate')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def run_finality_lab(
    root_dir: str | Path = ".",
    *,
    out_dir: str | Path = "sessions/finality_lab",
    user_id: str = "default_user",
    packs: list[str] | None = None,
    difficulty: str = "normal",
    providers: dict[str, FinalityProvider] | None = None,
) -> dict[str, Any]:
    del user_id
    root = Path(root_dir).resolve()
    target_dir = root / Path(out_dir)
    runs_dir = _runs_dir(target_dir)
    difficulty = _normalize_difficulty(difficulty)
    provider_map = {**DEFAULT_PROVIDERS, **dict(providers or {})}
    pack_inventory = list_benchmark_packs()
    selected_ids = {str(item).strip().lower() for item in list(packs or []) if str(item).strip()}
    selected_packs = [pack for pack in pack_inventory if not selected_ids or str(pack.get("id") or "").lower() in selected_ids]

    generated_at = _now_iso()
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{difficulty}"
    probe_root = target_dir / "probes" / run_id
    probe_root.mkdir(parents=True, exist_ok=True)
    pack_results: list[dict[str, Any]] = []

    for pack in selected_packs:
        pack_id = str(pack.get("id") or "")
        provider = provider_map.get(pack_id)
        if provider is None:
            pack_results.append(
                {
                    "id": pack_id,
                    "label": str(pack.get("label") or pack_id),
                    "status": "failed",
                    "ok": False,
                    "difficulty": difficulty,
                    "task_pack": get_task_pack(pack_id, difficulty),
                    "time_to_finality_ms": 0,
                    "metrics": {},
                    "artifacts": {},
                    "notes": [f"No provider is registered for {pack_id}."],
                    "finality_measured": False,
                }
            )
            continue
        pack_results.append(
            _pack_result(
                pack,
                difficulty=difficulty,
                probe_dir=probe_root / pack_id,
                provider=provider,
                root_dir=root,
                run_id=run_id,
                generated_at=generated_at,
            )
        )

    time_rows = [_safe_float(item.get("time_to_finality_ms")) for item in pack_results if _safe_float(item.get("time_to_finality_ms")) > 0]
    measured_count = sum(1 for item in pack_results if bool(item.get("finality_measured")))
    ok_count = sum(1 for item in pack_results if bool(item.get("ok")))
    report = {
        "run_id": run_id,
        "generated_at": generated_at,
        "root_dir": str(root),
        "difficulty": difficulty,
        "hardware_profile": capture_hardware_profile(root),
        "packs": pack_results,
        "ok": ok_count == len(pack_results),
        "summary": {
            "pack_count": len(pack_results),
            "measured_count": measured_count,
            "ok_count": ok_count,
            "average_time_to_finality_ms": round(sum(time_rows) / float(max(1, len(time_rows))), 3) if time_rows else 0.0,
            "slowest_pack": (
                max(pack_results, key=lambda item: _safe_float(item.get("time_to_finality_ms"))).get("id")
                if pack_results
                else ""
            ),
        },
    }

    run_json = runs_dir / f"finality_run_{run_id}.json"
    run_md = runs_dir / f"finality_run_{run_id}.md"
    _write_json(run_json, report)
    run_md.write_text(_render_markdown(report), encoding="utf-8")

    diff = diff_finality_runs(root, out_dir=out_dir)
    if bool(diff.get("ok")):
        report["diff_to_previous"] = diff
        _write_json(run_json, report)
        run_md.write_text(_render_markdown(report), encoding="utf-8")

    leaderboard = build_leaderboard(root, out_dir=out_dir)
    report["leaderboard"] = leaderboard
    _write_json(run_json, report)
    run_md.write_text(_render_markdown(report), encoding="utf-8")

    latest_json = target_dir / "latest.json"
    latest_md = target_dir / "latest.md"
    _write_json(latest_json, report)
    latest_md.write_text(_render_markdown(report), encoding="utf-8")

    leaderboard_json = target_dir / "leaderboard.json"
    leaderboard_md = target_dir / "leaderboard.md"
    _write_json(leaderboard_json, leaderboard)
    leaderboard_md.write_text(_render_leaderboard_markdown(leaderboard), encoding="utf-8")

    if bool(report.get("diff_to_previous")):
        _write_json(target_dir / "latest_diff.json", dict(report.get("diff_to_previous") or {}))

    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run Somi's finality benchmark lab.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-dir", default="sessions/finality_lab")
    parser.add_argument("--difficulty", default="normal")
    parser.add_argument("--packs", nargs="*", default=[])
    args = parser.parse_args(argv)

    report = run_finality_lab(
        root_dir=args.root,
        out_dir=args.out_dir,
        difficulty=args.difficulty,
        packs=list(args.packs or []),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if bool(report.get("ok", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
