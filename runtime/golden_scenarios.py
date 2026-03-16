from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from runtime.answer_validator import validate_and_repair_answer
from runtime.history_compaction import COMPACTION_PREFIX, build_compaction_summary
from runtime.tool_loop_detection import ToolLoopConfig, detect_tool_loop, record_tool_call, record_tool_call_outcome
from workshop.toolbox.agent_core.continuity import render_state_ledger_block, update_state_ledger
from workshop.toolbox.agent_core.routing import decide_route


@dataclass
class GoldenResult:
    name: str
    ok: bool
    detail: str


def _routing_cases() -> List[GoldenResult]:
    prompts = [
        ("search latest inflation data", "websearch"),
        ("no websearch explain recursion", "llm_only"),
        ("what's my name", "local_memory_intent"),
        ("create an image of a sunrise", "image_tool"),
        ("convert 100 usd to ttd", "conversion_tool"),
        ("latest weather in tokyo", "websearch"),
        ("latest bitcoin price", "websearch"),
        ("news about nvidia", "websearch"),
        ("show me stock market cap for amd", "websearch"),
        ("summarize this URL https://example.com", "websearch"),
        ("plan a migration strategy", "llm_only"),
        ("compare numpy vs pandas", "llm_only"),
        ("check online newest who guidelines", "websearch"),
        ("from now on remember this preference", "local_memory_intent"),
        ("please look up exchange rate usd to eur", "websearch"),
        ("no internet explain qubits", "llm_only"),
        ("make me an image of ocean waves", "image_tool"),
        ("what is the forecast tomorrow", "websearch"),
        ("what are current headlines", "websearch"),
        ("tell me a joke", "llm_only"),
    ]

    rows: List[GoldenResult] = []
    for idx, (prompt, expected) in enumerate(prompts, start=1):
        got = decide_route(prompt).route
        rows.append(GoldenResult(name=f"route_case_{idx}", ok=(got == expected), detail=f"expected={expected};got={got}"))

    # Contextual follow-up routes.
    for idx, prompt in enumerate([
        "can you expand on that",
        "continue with the same",
        "follow up on this",
        "go deeper on that",
        "next step for this",
        "recap that",
        "elaborate on that",
        "more on this",
    ], start=1):
        dec = decide_route(
            prompt,
            agent_state={
                "has_tool_context": True,
                "last_tool_type": "general",
                "force_no_followup_binding": False,
                "last_finance_intent": "",
            },
        )
        rows.append(
            GoldenResult(
                name=f"route_contextual_case_{idx}",
                ok=(dec.route == "websearch" or str(dec.reason or "") == "capulet_strategic"),
                detail=f"route={dec.route};reason={dec.reason}",
            )
        )

    return rows


def _compaction_cases() -> List[GoldenResult]:
    rows: List[GoldenResult] = []

    for idx in range(1, 11):
        ledger = update_state_ledger(
            "golden_user",
            user_text=f"My goal is ship phase {idx}",
            assistant_text="Decision: keep continuity and verify each step.",
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
            [
                {"role": "user", "content": f"continue phase {idx}"},
                {"role": "assistant", "content": "Next: run checks and finalize."},
            ],
            state_ledger=ledger,
        )
        ok = ("Conversation State Ledger" in block) and summary.startswith(COMPACTION_PREFIX) and ("Ledger goals" in summary)
        rows.append(GoldenResult(name=f"compaction_case_{idx}", ok=ok, detail=f"summary_len={len(summary)}"))

    return rows


def _loop_cases() -> List[GoldenResult]:
    rows: List[GoldenResult] = []
    cfg = ToolLoopConfig(
        enabled=True,
        history_size=30,
        warning_threshold=3,
        critical_threshold=5,
        global_circuit_breaker_threshold=6,
        detect_generic_repeat=True,
        detect_no_progress=True,
        detect_ping_pong=True,
    )

    # no-progress streak -> warning/critical
    history: List[Dict[str, Any]] = []
    args = {"query": "test"}
    for _ in range(6):
        record_tool_call(history, tool_name="web.intelligence", args=args, cfg=cfg)
        record_tool_call_outcome(history, tool_name="web.intelligence", args=args, result={"ok": False, "error": "same"}, cfg=cfg)

    result = detect_tool_loop(history, tool_name="web.intelligence", args=args, cfg=cfg)
    rows.append(GoldenResult(name="loop_no_progress_critical", ok=(result.stuck and result.level == "critical"), detail=f"level={result.level};detector={result.detector}"))

    # generic repeat
    history2: List[Dict[str, Any]] = []
    for _ in range(4):
        record_tool_call(history2, tool_name="image.tooling", args={"action": "generate"}, cfg=cfg)
    result2 = detect_tool_loop(history2, tool_name="image.tooling", args={"action": "generate"}, cfg=cfg)
    rows.append(GoldenResult(name="loop_generic_repeat_warning", ok=(result2.stuck and result2.level in {"warning", "critical"}), detail=f"level={result2.level};detector={result2.detector}"))

    # create additional deterministic checks for coverage.
    for idx in range(1, 7):
        h: List[Dict[str, Any]] = []
        for _ in range(3 + idx):
            record_tool_call(h, tool_name="tool.x", args={"x": idx}, cfg=cfg)
            record_tool_call_outcome(h, tool_name="tool.x", args={"x": idx}, result={"ok": False, "same": True}, cfg=cfg)
        r = detect_tool_loop(h, tool_name="tool.x", args={"x": idx}, cfg=cfg)
        rows.append(GoldenResult(name=f"loop_case_{idx}", ok=r.stuck, detail=f"level={r.level};count={r.count}"))

    return rows


def _validator_cases() -> List[GoldenResult]:
    rows: List[GoldenResult] = []

    for idx in range(1, 11):
        content = "This is definitely correct."
        repaired, issues = validate_and_repair_answer(
            content=content,
            intent="research",
            should_search=True,
            evidence_contract={"required_min_sources": 3, "found_sources": 1},
            citation_map=[{"url": f"https://example.com/{idx}"}],
        )
        ok = bool(issues) and ("Evidence note:" in repaired)
        rows.append(GoldenResult(name=f"validator_case_{idx}", ok=ok, detail=f"issues={len(issues)}"))

    return rows


def run_golden_scenarios() -> Dict[str, Any]:
    rows: List[GoldenResult] = []
    rows.extend(_routing_cases())
    rows.extend(_compaction_cases())
    rows.extend(_loop_cases())
    rows.extend(_validator_cases())

    passed = sum(1 for r in rows if r.ok)
    total = len(rows)
    score = round((passed / total) * 100.0, 2) if total else 0.0
    return {
        "ok": passed == total,
        "passed": passed,
        "total": total,
        "score": score,
        "results": [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in rows],
    }
