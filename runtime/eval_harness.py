from __future__ import annotations

import json
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.audit import append_event, audit_path, verify_audit_log
from runtime.history_compaction import build_compaction_summary
from runtime.tool_execution import IdempotencyCache, ToolExecutionPolicy, execute_with_policy
from runtime.golden_scenarios import run_golden_scenarios
from audit.benchmark_baseline import build_benchmark_baseline
from audit.benchmark_packs import list_benchmark_packs
from audit.regression_packs import list_regression_packs
from learning import SkillSuggestionEngine, TrajectoryStore, build_scorecard
from ops import OpsControlPlane
from workshop.toolbox.agent_core.continuity import render_state_ledger_block, update_state_ledger
from workshop.toolbox.agent_core.followup_resolver import FollowUpResolver
from workshop.toolbox.agent_core.tool_context import ToolContext
from workshop.toolbox.agent_core.routing import decide_route
from workshop.toolbox.runtime import InternalToolRuntime, ToolRuntimeError
from workshop.toolbox.stacks import web_intelligence as web_intel
from workflow_runtime import WorkflowManifestStore, WorkflowRunStore


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _check_routes() -> list[CheckResult]:
    rows: list[CheckResult] = []

    route_expectations = [
        ("route_websearch_latest", "search latest inflation data", "websearch"),
        ("route_no_websearch", "no websearch explain recursion", "llm_only"),
        ("route_memory", "what's my name", "local_memory_intent"),
        ("route_image", "create an image of a sunrise", "image_tool"),
        ("route_conversion", "convert 100 usd to ttd", "conversion_tool"),
    ]

    for name, prompt, expected in route_expectations:
        got = decide_route(prompt).route
        rows.append(
            CheckResult(
                name=name,
                ok=(got == expected),
                detail=f"expected={expected};got={got}",
            )
        )

    contextual = decide_route(
        "can you expand on that",
        agent_state={
            "has_tool_context": True,
            "last_tool_type": "general",
            "force_no_followup_binding": False,
            "last_finance_intent": "",
        },
    )
    rows.append(
        CheckResult(
            name="route_contextual_generic_followup",
            ok=(contextual.route == "websearch" and str(contextual.reason) == "contextual_followup_generic"),
            detail=f"route={contextual.route};reason={contextual.reason}",
        )
    )

    return rows


def _check_followup_resolution() -> list[CheckResult]:
    rows: list[CheckResult] = []
    resolver = FollowUpResolver()

    ctx = ToolContext(
        session_id="eval",
        last_tool_type="websearch",
        last_query="latest ai chip news",
        last_results=[
            {"rank": 1, "title": "Alpha", "url": "https://example.com/a"},
            {"rank": 2, "title": "Beta", "url": "https://example.com/b"},
        ],
    )

    ranked = resolver.resolve("open 2", ctx)
    rows.append(
        CheckResult(
            name="followup_rank_resolution",
            ok=bool(ranked and ranked.action == "open_url_and_summarize" and ranked.selected_index == 2),
            detail=f"action={getattr(ranked, 'action', '')};selected_index={getattr(ranked, 'selected_index', 0)}",
        )
    )

    ambiguous = resolver.resolve("that story", ctx)
    rows.append(
        CheckResult(
            name="followup_ambiguous_clarify",
            ok=bool(ambiguous and ambiguous.action == "clarify"),
            detail=f"action={getattr(ambiguous, 'action', '')}",
        )
    )

    return rows


def _check_tool_execution() -> list[CheckResult]:
    rows: list[CheckResult] = []

    # Retry simulation for transient failure.
    state = {"calls": 0}

    def flaky(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("temporarily unavailable")
        return {"ok": True, "args": dict(args or {})}

    policy_retry = ToolExecutionPolicy(
        timeout_seconds=1.0,
        max_attempts=2,
        retry_backoff_seconds=0.01,
        idempotency_ttl_seconds=10.0,
        retryable_error_markers=("temporarily unavailable",),
    )
    out = execute_with_policy(fn=flaky, args={"x": 1}, ctx={}, policy=policy_retry)
    rows.append(
        CheckResult(
            name="tool_retry_transient",
            ok=bool(out.value.get("ok")) and out.attempts == 2,
            detail=f"attempts={out.attempts};calls={state['calls']}",
        )
    )

    # Timeout simulation.
    def slow(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.2)
        return {"ok": True}

    policy_timeout = ToolExecutionPolicy(
        timeout_seconds=0.05,
        max_attempts=1,
        retry_backoff_seconds=0.0,
        idempotency_ttl_seconds=10.0,
        retryable_error_markers=("timeout",),
    )
    timeout_ok = False
    try:
        execute_with_policy(fn=slow, args={}, ctx={}, policy=policy_timeout)
    except Exception as exc:
        timeout_ok = isinstance(exc, TimeoutError)
    rows.append(
        CheckResult(
            name="tool_timeout_enforced",
            ok=timeout_ok,
            detail="timeout expected",
        )
    )

    # Idempotency cache simulation.
    cache = IdempotencyCache()
    counter = {"calls": 0}

    def deterministic(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        counter["calls"] += 1
        return {"ok": True, "n": counter["calls"]}

    policy_idem = ToolExecutionPolicy(
        timeout_seconds=1.0,
        max_attempts=1,
        retry_backoff_seconds=0.0,
        idempotency_ttl_seconds=10.0,
        retryable_error_markers=("timeout",),
    )

    first = execute_with_policy(
        fn=deterministic,
        args={"job": 1},
        ctx={"user_id": "eval"},
        policy=policy_idem,
        cache=cache,
        idempotency_key="idem-1",
    )
    second = execute_with_policy(
        fn=deterministic,
        args={"job": 1},
        ctx={"user_id": "eval"},
        policy=policy_idem,
        cache=cache,
        idempotency_key="idem-1",
    )

    rows.append(
        CheckResult(
            name="tool_idempotency_cache",
            ok=(first.from_cache is False and second.from_cache is True and counter["calls"] == 1),
            detail=f"calls={counter['calls']};second_cache={second.from_cache}",
        )
    )

    return rows


def _check_audit_chain() -> list[CheckResult]:
    rows: list[CheckResult] = []
    job_id = "eval_harness_audit"
    path = audit_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    append_event(job_id, "start", {"step": 1})
    append_event(job_id, "middle", {"step": 2})
    verified = verify_audit_log(job_id)
    rows.append(
        CheckResult(
            name="audit_chain_valid",
            ok=bool(verified.get("ok")),
            detail=f"issues={len(verified.get('issues') or [])}",
        )
    )

    # Tamper with the first record and expect verification to fail.
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines:
        first = json.loads(lines[0])
        data = dict(first.get("data") or {})
        data["step"] = 999
        first["data"] = data
        lines[0] = json.dumps(first, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tampered = verify_audit_log(job_id)
    rows.append(
        CheckResult(
            name="audit_chain_detects_tamper",
            ok=not bool(tampered.get("ok")),
            detail=f"issues={len(tampered.get('issues') or [])}",
        )
    )

    return rows



def _check_state_ledger_and_compaction() -> list[CheckResult]:
    rows: list[CheckResult] = []

    seed = {
        "goals": [],
        "decisions": [],
        "open_loops": [],
        "unresolved_asks": [],
        "last_user_intent": "",
        "last_assistant_commitments": [],
        "turn_count": 0,
    }
    ledger = update_state_ledger(
        "eval_user",
        user_text="My goal is maintain context continuity across follow-up turns.",
        assistant_text="Decision: persist a conversation state ledger each turn.",
        ledger=seed,
    )

    ledger_block = render_state_ledger_block(ledger)
    rows.append(
        CheckResult(
            name="ledger_block_has_context",
            ok=("Conversation State Ledger" in ledger_block and "goals" in ledger_block),
            detail=f"chars={len(ledger_block)}",
        )
    )

    summary = build_compaction_summary(
        [
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "I will continue with the prior plan."},
        ],
        state_ledger=ledger,
    )
    rows.append(
        CheckResult(
            name="compaction_includes_ledger",
            ok=("Ledger goals" in summary and "Ledger decisions" in summary),
            detail=f"chars={len(summary)}",
        )
    )

    return rows


def _check_evidence_contract() -> list[CheckResult]:
    rows: list[CheckResult] = []

    citations = [
        {"id": 1, "title": "A", "url": "https://example.com/a", "domain": "example.com"},
        {"id": 2, "title": "B", "url": "https://example.com/b", "domain": "example.com"},
    ]
    contract = web_intel._build_evidence_contract(
        query="research topic",
        signals={"intent": "research"},
        route_hint="websearch",
        citations=citations,
    )
    rows.append(
        CheckResult(
            name="evidence_threshold_enforced",
            ok=(
                int(contract.get("required_min_sources", 0)) == 3
                and int(contract.get("found_sources", 0)) == 2
                and bool(contract.get("satisfied", True)) is False
            ),
            detail=(
                f"required={contract.get('required_min_sources')};"
                f"found={contract.get('found_sources')};"
                f"satisfied={contract.get('satisfied')}"
            ),
        )
    )

    contract_text = web_intel._render_contract_block(
        evidence_contract=contract,
        citation_map=citations,
    )
    rows.append(
        CheckResult(
            name="evidence_degrade_notice",
            ok=("degrade_notice" in contract_text and "Citation Map" in contract_text),
            detail=f"chars={len(contract_text)}",
        )
    )

    return rows


def _check_runtime_policy_enforcement() -> list[CheckResult]:
    rows: list[CheckResult] = []

    class _RegistryStub:
        def __init__(self, entry: dict[str, Any]) -> None:
            self._entry = dict(entry)

        def find(self, tool_name: str) -> dict[str, Any] | None:
            if tool_name == str(self._entry.get("name")):
                return dict(self._entry)
            return None

    def _fake_loader(self, tool_name: str, entry: dict[str, Any] | None = None):  # noqa: ARG001
        def _run(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
            return {"ok": True, "tool": tool_name}

        return _run

    approval_entry = {
        "name": "approval.tool",
        "version": "0.1.0",
        "path": "unused",
        "policy": {"read_only": False, "risk_tier": "LOW", "requires_approval": True},
    }
    rt_approval = InternalToolRuntime(registry=_RegistryStub(approval_entry))
    rt_approval._load_module = types.MethodType(_fake_loader, rt_approval)

    approval_blocked = False
    try:
        rt_approval.run("approval.tool", {}, ctx={"approved": False})
    except ToolRuntimeError:
        approval_blocked = True

    rows.append(
        CheckResult(
            name="runtime_policy_requires_approval",
            ok=approval_blocked,
            detail=f"blocked={approval_blocked}",
        )
    )

    risk_entry = {
        "name": "risk.tool",
        "version": "0.1.0",
        "path": "unused",
        "policy": {"read_only": True, "risk_tier": "HIGH", "requires_approval": False},
    }
    rt_risk = InternalToolRuntime(registry=_RegistryStub(risk_entry))
    rt_risk._load_module = types.MethodType(_fake_loader, rt_risk)

    risk_blocked = False
    try:
        rt_risk.run("risk.tool", {}, ctx={"approved": True, "max_risk_tier": "LOW"})
    except ToolRuntimeError:
        risk_blocked = True

    rows.append(
        CheckResult(
            name="runtime_policy_risk_guard",
            ok=risk_blocked,
            detail=f"blocked={risk_blocked}",
        )
    )

    return rows



def _check_runtime_schema_and_breaker() -> list[CheckResult]:
    rows: list[CheckResult] = []

    class _RegistryStub:
        def __init__(self, entry: dict[str, Any]) -> None:
            self._entry = dict(entry)

        def find(self, tool_name: str) -> dict[str, Any] | None:
            if tool_name == str(self._entry.get("name")):
                return dict(self._entry)
            return None

    def _fake_loader(self, tool_name: str, entry: dict[str, Any] | None = None):  # noqa: ARG001
        def _run(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
            return {"ok": True, "tool": tool_name}

        return _run

    schema_entry = {
        "name": "schema.eval.tool",
        "version": "0.1.0",
        "path": "unused",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "policy": {"read_only": True, "risk_tier": "LOW", "requires_approval": False},
    }

    rt_schema = InternalToolRuntime(registry=_RegistryStub(schema_entry))
    rt_schema._load_module = types.MethodType(_fake_loader, rt_schema)

    schema_blocked = False
    try:
        rt_schema.run("schema.eval.tool", {}, ctx={"approved": False})
    except ToolRuntimeError:
        schema_blocked = True

    rows.append(
        CheckResult(
            name="runtime_schema_required_guard",
            ok=schema_blocked,
            detail=f"blocked={schema_blocked}",
        )
    )

    breaker_entry = {
        "name": "breaker.eval.tool",
        "version": "0.1.0",
        "path": "unused",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "policy": {"read_only": True, "risk_tier": "LOW", "requires_approval": False},
    }

    def _failing_loader(self, tool_name: str, entry: dict[str, Any] | None = None):  # noqa: ARG001
        def _run(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
            raise RuntimeError("boom")

        return _run

    rt_breaker = InternalToolRuntime(registry=_RegistryStub(breaker_entry))
    rt_breaker._load_module = types.MethodType(_failing_loader, rt_breaker)

    shared_ctx = {
        "approved": False,
        "user_id": "eval_breaker",
        "tool_circuit_breaker_threshold": 2,
        "tool_circuit_breaker_cooldown_seconds": 120,
    }

    for _ in range(2):
        try:
            rt_breaker.run("breaker.eval.tool", {}, ctx=shared_ctx)
        except ToolRuntimeError:
            pass

    breaker_blocked = False
    try:
        rt_breaker.run("breaker.eval.tool", {}, ctx=shared_ctx)
    except ToolRuntimeError as exc:
        breaker_blocked = "temporarily paused by runtime circuit breaker" in str(exc)

    rows.append(
        CheckResult(
            name="runtime_circuit_breaker_guard",
            ok=breaker_blocked,
            detail=f"blocked={breaker_blocked}",
        )
    )

    return rows


def _check_generated_golden_scenarios() -> list[CheckResult]:
    rows: list[CheckResult] = []
    try:
        out = run_golden_scenarios()
        ok = bool(out.get("ok"))
        passed = int(out.get("passed") or 0)
        total = int(out.get("total") or 0)
        score = float(out.get("score") or 0.0)
        rows.append(
            CheckResult(
                name="generated_golden_scenarios",
                ok=ok,
                detail=f"passed={passed};total={total};score={score}",
            )
        )
        if not ok:
            for item in list(out.get("results") or [])[:5]:
                rows.append(
                    CheckResult(
                        name=f"golden::{str(item.get('name') or 'unknown')}",
                        ok=bool(item.get("ok")),
                        detail=str(item.get("detail") or ""),
                    )
                )
    except Exception as exc:
        rows.append(CheckResult(name="generated_golden_scenarios", ok=False, detail=f"error={type(exc).__name__}: {exc}"))
    return rows


def _check_learning_loop() -> list[CheckResult]:
    rows: list[CheckResult] = []
    eval_root = Path("sessions/evals")
    trajectory_store = TrajectoryStore(root_dir=eval_root / "trajectory_samples")
    ops_control = OpsControlPlane(root_dir=eval_root / "ops_samples")
    workflow_store = WorkflowRunStore(root_dir=eval_root / "workflow_samples")
    manifest_store = WorkflowManifestStore(root_dir=eval_root / "workflow_manifests")

    trajectory_store.record_turn(
        user_id="eval_user",
        thread_id="learning",
        session_id="eval::learning",
        turn_id=1,
        turn_index=1,
        prompt="Find the latest local AI tooling update.",
        response="Sources: https://example.com/update",
        route="websearch",
        model_name="eval-model",
        latency_ms=120,
        tool_events=[{"tool": "web.intelligence", "status": "ok", "detail": "citation_map"}],
    )
    trajectory_store.record_turn(
        user_id="eval_user",
        thread_id="learning",
        session_id="eval::learning",
        turn_id=2,
        turn_index=2,
        prompt="Actually make that shorter.",
        response="Shorter answer.",
        route="llm_only",
        model_name="eval-model",
        latency_ms=90,
        tool_events=[],
    )

    ops_control.record_tool_metric(
        tool_name="web.intelligence",
        success=True,
        elapsed_ms=40,
        backend="local",
        channel="chat",
        risk_tier="LOW",
        approved=False,
    )
    ops_control.record_model_metric(
        model_name="eval-model",
        route="websearch",
        latency_ms=120,
        status="completed",
        prompt_chars=40,
        output_chars=32,
    )

    manifest_store.save(
        {
            "manifest_id": "learning_manifest",
            "name": "Learning Manifest",
            "description": "Successful research workflow",
            "allowed_tools": ["web.intelligence"],
            "script": "tools.call('web.intelligence', {'query': 'learning'})",
        }
    )
    workflow_store.write_snapshot(
        {
            "run_id": "workflow-learning-1",
            "user_id": "eval_user",
            "thread_id": "learning",
            "manifest_id": "learning_manifest",
            "manifest_name": "Learning Manifest",
            "status": "completed",
            "summary": "Collected a grounded update.",
            "updated_at": _now_iso(),
        }
    )

    scorecard = build_scorecard(trajectory_store=trajectory_store, ops_control=ops_control, user_id="eval_user")
    suggestions = SkillSuggestionEngine(
        workflow_store=workflow_store,
        manifest_store=manifest_store,
        output_path=eval_root / "sample_skill_suggestions.json",
    ).generate(user_id="eval_user", limit=4)

    rows.append(
        CheckResult(
            name="learning_scorecard_shape",
            ok=(
                "latency_avg_ms" in scorecard
                and "tool_success_rate" in scorecard
                and "user_correction_rate" in scorecard
                and "factual_grounding_rate" in scorecard
            ),
            detail=f"scorecard_keys={sorted(scorecard.keys())}",
        )
    )
    rows.append(
        CheckResult(
            name="learning_skill_suggestions",
            ok=bool(suggestions and suggestions[0].get("skill_id")),
            detail=f"suggestions={len(suggestions)}",
        )
    )
    return rows


def _check_regression_pack_inventory() -> list[CheckResult]:
    packs = list_regression_packs()
    found = {str(item.get("id") or "") for item in packs}
    expected = {"web", "finance", "reminder", "artifact", "automation", "subagent"}
    return [
        CheckResult(
            name="regression_pack_inventory",
            ok=expected.issubset(found),
            detail=f"found={sorted(found)}",
        )
    ]


def _check_benchmark_pack_inventory() -> list[CheckResult]:
    packs = list_benchmark_packs()
    found = {str(item.get("id") or "") for item in packs}
    expected = {"ocr", "coding", "research", "speech", "automation", "browser", "memory"}
    return [
        CheckResult(
            name="benchmark_pack_inventory",
            ok=expected.issubset(found),
            detail=f"found={sorted(found)}",
        )
    ]


def run_eval_harness() -> dict[str, Any]:
    checks: list[CheckResult] = []
    checks.extend(_check_routes())
    checks.extend(_check_followup_resolution())
    checks.extend(_check_tool_execution())
    checks.extend(_check_audit_chain())
    checks.extend(_check_state_ledger_and_compaction())
    checks.extend(_check_evidence_contract())
    checks.extend(_check_runtime_policy_enforcement())
    checks.extend(_check_runtime_schema_and_breaker())
    checks.extend(_check_generated_golden_scenarios())
    checks.extend(_check_learning_loop())
    checks.extend(_check_regression_pack_inventory())
    checks.extend(_check_benchmark_pack_inventory())

    passed = sum(1 for c in checks if c.ok)
    total = len(checks)
    score = round((passed / total) * 100.0, 2) if total else 0.0
    real_scorecard = build_scorecard(user_id="default_user")
    real_skill_suggestions = SkillSuggestionEngine().generate(user_id="default_user", limit=6)
    regression_packs = list_regression_packs()
    benchmark_packs = list_benchmark_packs()
    benchmark_baseline = build_benchmark_baseline(user_id="default_user")

    report = {
        "ok": passed == total,
        "score": score,
        "passed": passed,
        "total": total,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
        "scorecard": real_scorecard,
        "skill_suggestions": real_skill_suggestions,
        "regression_packs": regression_packs,
        "benchmark_packs": benchmark_packs,
        "benchmark_baseline": benchmark_baseline,
        "gap_ledger": list(benchmark_baseline.get("gap_ledger") or []),
    }

    out_dir = Path("sessions/evals")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "latest_eval_harness.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_eval_harness()
    print(json.dumps(result, indent=2, ensure_ascii=False))













