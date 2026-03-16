from __future__ import annotations

from copy import deepcopy
from typing import Any


def _task_pack(label: str, tasks: list[str]) -> dict[str, Any]:
    return {"label": label, "tasks": list(tasks)}


BENCHMARK_PACKS: tuple[dict[str, Any], ...] = (
    {
        "id": "ocr",
        "label": "OCR",
        "objective": "Measure document extraction speed, structure quality, and escalation behavior.",
        "required_tools": ["ocr.extract"],
        "required_modules": ["workshop.toolbox.stacks.ocr_stack"],
        "required_paths": ["config/ocr_templates.json", "workshop/tools/ocr_quick_test.py"],
        "benchmark_hooks": ["workshop/tools/ocr_quick_test.py"],
        "task_packs": {
            "easy": _task_pack("Fixture parse", ["parse a known fixture", "report structured confidence"]),
            "normal": _task_pack("Structured extraction", ["run the OCR benchmark suite", "capture coverage and escalation"]),
            "hard": _task_pack("Document intelligence", ["run the OCR benchmark suite", "persist benchmark report", "summarize extraction weaknesses"]),
        },
        "target_metrics": [
            "time_to_first_text_ms",
            "time_to_final_structured_output_ms",
            "structured_accuracy",
            "escalation_rate",
            "consumer_hardware_ram_mb",
        ],
        "polish_targets": [
            "structured fallback clarity",
            "table and form handling",
            "confidence and escalation reporting",
        ],
    },
    {
        "id": "coding",
        "label": "Coding",
        "objective": "Measure time-to-finality for scaffold, patch, test, and verify loops.",
        "required_tools": ["coding.workspace", "coding.fs", "coding.python", "coding.runtime"],
        "required_modules": ["workshop.toolbox.coding.service", "workshop.toolbox.coding.workspace"],
        "required_paths": ["workshop/tools/registry.json", "tests/test_coding_studio_phase6.py"],
        "benchmark_hooks": ["tests/test_coding_tools_phase3.py", "tests/test_coding_mode_phase5.py"],
        "task_packs": {
            "easy": _task_pack("Scaffold and inspect", ["create a managed workspace", "capture environment health"]),
            "normal": _task_pack("Verify loop", ["create a managed workspace", "run the workspace verify loop", "score the result"]),
            "hard": _task_pack("Stability pass", ["create a managed workspace", "run the verify loop twice", "compare stability across runs"]),
        },
        "target_metrics": [
            "time_to_first_scaffold_ms",
            "time_to_green_tests_ms",
            "retry_count",
            "patch_success_rate",
            "workspace_health_score",
        ],
        "polish_targets": [
            "patch reliability",
            "test summary quality",
            "environment reporting",
        ],
    },
    {
        "id": "research",
        "label": "Research",
        "objective": "Measure grounded-answer latency, evidence quality, and graceful degradation.",
        "required_tools": ["web.intelligence"],
        "required_modules": ["workshop.toolbox.stacks.web_intelligence", "audit.simulate_chat_flow_regression"],
        "required_paths": ["audit/simulate_chat_flow_regression.py", "runtime/live_chat_stress.py"],
        "benchmark_hooks": ["audit/simulate_chat_flow_regression.py", "runtime/live_chat_stress.py"],
        "task_packs": {
            "easy": _task_pack("Chat flow regression", ["run the research chat-flow regression", "persist the report"]),
            "normal": _task_pack("Grounded research loop", ["run the research chat-flow regression", "measure time to grounded completion"]),
            "hard": _task_pack("Research endurance", ["run the research chat-flow regression", "run the live stress harness", "compare follow-up continuity"]),
        },
        "target_metrics": [
            "time_to_grounded_answer_ms",
            "source_diversity",
            "followup_binding_success_rate",
            "degrade_notice_quality",
        ],
        "polish_targets": [
            "evidence synthesis",
            "faster stopping when enough evidence exists",
            "follow-up source handling",
        ],
    },
    {
        "id": "speech",
        "label": "Speech",
        "objective": "Measure wake-to-transcript latency, transcript quality, and runtime stability.",
        "required_tools": [],
        "required_modules": ["speech.doctor", "speech.tts.factory", "speech.stt.local_whisper"],
        "required_paths": ["speech/tools/test_tts_local.py", "speech/tools/test_stt_local.py"],
        "benchmark_hooks": ["speech/tools/test_tts_local.py", "speech/tools/test_stt_local.py", "speech/tools/doctor.py"],
        "task_packs": {
            "easy": _task_pack("Doctor and synth", ["run speech doctor", "synthesize a local phrase"]),
            "normal": _task_pack("Roundtrip speech", ["run speech doctor", "roundtrip TTS to STT", "score transcript overlap"]),
            "hard": _task_pack("Speech endurance", ["run speech doctor", "roundtrip TTS to STT", "capture latency and transcript quality"]),
        },
        "target_metrics": [
            "wake_to_transcript_ms",
            "transcript_accuracy",
            "barge_in_reliability",
            "runtime_stability_minutes",
        ],
        "polish_targets": [
            "voice selection UX",
            "barge-in quality",
            "GUI diagnostics",
        ],
    },
    {
        "id": "automation",
        "label": "Automation",
        "objective": "Measure schedule parse reliability, delivery continuity, and restart recovery.",
        "required_tools": [],
        "required_modules": ["automations.engine", "gateway.manager", "heartbeat.service"],
        "required_paths": ["automations/engine.py", "gateway/manager.py", "heartbeat/service.py"],
        "benchmark_hooks": ["tests/test_delivery_automations_phase9.py"],
        "task_packs": {
            "easy": _task_pack("Schedule parse", ["parse a human schedule", "record the next run"]),
            "normal": _task_pack("Delivery cycle", ["create an automation", "run the due automation", "verify delivery receipt"]),
            "hard": _task_pack("Automation continuity", ["create a desktop automation", "create a queued relay automation", "verify run records and ontology links"]),
        },
        "target_metrics": [
            "schedule_parse_success_rate",
            "delivery_success_rate",
            "restart_recovery_success_rate",
            "failed_run_repair_time_ms",
        ],
        "polish_targets": [
            "failed job repair flows",
            "operator status clarity",
            "restart continuity",
        ],
    },
    {
        "id": "browser",
        "label": "Browser",
        "objective": "Measure browser-state capture speed, screenshot reliability, and safe action readiness.",
        "required_tools": ["browser.runtime", "browser.action"],
        "required_modules": ["workshop.toolbox.browser.runtime", "playwright.sync_api"],
        "required_paths": ["tests/test_browser_phase7.py", "workshop/tools/registry.json"],
        "benchmark_hooks": ["tests/test_browser_phase7.py"],
        "task_packs": {
            "easy": _task_pack("Snapshot capture", ["capture local page state", "report link and form counts"]),
            "normal": _task_pack("Snapshot and screenshot", ["capture local page state", "persist a screenshot", "record browser health"]),
            "hard": _task_pack("Safe action flow", ["capture local page state", "run an approved local form flow", "persist a final screenshot"]),
        },
        "target_metrics": [
            "time_to_page_snapshot_ms",
            "screenshot_success_rate",
            "page_state_quality",
            "safe_action_completion_rate",
        ],
        "polish_targets": [
            "page-state clarity",
            "local screenshot stability",
            "approval-aware action ergonomics",
        ],
    },
    {
        "id": "memory",
        "label": "Memory",
        "objective": "Measure recall quality, compaction resilience, and state continuity.",
        "required_tools": [],
        "required_modules": ["search.session_search", "executive.memory.manager", "runtime.history_compaction"],
        "required_paths": ["search/session_search.py", "runtime/history_compaction.py", "tests/test_memory_session_search_phase7.py"],
        "benchmark_hooks": ["tests/test_memory_session_search_phase7.py", "runtime/eval_harness.py"],
        "task_packs": {
            "easy": _task_pack("Recall lookup", ["persist a decision", "retrieve it with session search"]),
            "normal": _task_pack("Recall and compaction", ["persist a decision", "retrieve it with session search", "build a compaction summary"]),
            "hard": _task_pack("Continuity stress", ["persist a decision", "exercise natural-language fallback recall", "build a compaction summary"]),
        },
        "target_metrics": [
            "recall_hit_rate",
            "compaction_survival_rate",
            "prompt_memory_injection_quality",
            "state_continuity_score",
        ],
        "polish_targets": [
            "hybrid retrieval",
            "memory explainability",
            "cross-session recall precision",
        ],
    },
)


def list_benchmark_packs() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in BENCHMARK_PACKS]


def get_benchmark_pack(pack_id: str) -> dict[str, Any]:
    normalized = str(pack_id or "").strip().lower()
    for item in BENCHMARK_PACKS:
        if str(item.get("id") or "").strip().lower() == normalized:
            return deepcopy(item)
    raise KeyError(f"Unknown benchmark pack: {pack_id}")


def get_task_pack(pack_id: str, difficulty: str = "normal") -> dict[str, Any]:
    pack = get_benchmark_pack(pack_id)
    task_packs = dict(pack.get("task_packs") or {})
    normalized = str(difficulty or "normal").strip().lower() or "normal"
    if normalized not in {"easy", "normal", "hard"}:
        normalized = "normal"
    chosen = dict(task_packs.get(normalized) or task_packs.get("normal") or {})
    chosen["difficulty"] = normalized
    return chosen
