from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agents as agents_mod
from agents import Agent
from runtime.history_compaction import COMPACTION_PREFIX


@dataclass
class StressCheck:
    name: str
    ok: bool
    detail: str


def _tail_log_rows(path: Path, *, user_id: str, limit: int = 120) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("user_id") or "") != str(user_id):
            continue
        rows.append(row)
    return rows


async def run_live_stress() -> Dict[str, Any]:
    # Force compaction to trigger in short simulations.
    agents_mod.HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES = 8
    agents_mod.HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES = 4
    agents_mod.HISTORY_AUTO_COMPACT_TRIGGER_TOKENS = 220
    agents_mod.HISTORY_AUTO_COMPACT_TARGET_TOKENS = 140
    agents_mod.HISTORY_AUTO_COMPACT_MIN_KEEP_MESSAGES = 3

    user_id = "stress_user"
    agent = Agent("Somi", user_id=user_id)

    # Keep original for loop-pressure check.
    original_run_tool_guard = agent._run_tool_with_loop_guard

    # Deterministic runtime stubs for chat-flow simulation.
    async def fake_run_tool_with_loop_guard(*, tool_name: str, args: Dict[str, Any], ctx: Dict[str, Any], active_user_id: str) -> Dict[str, Any]:
        if tool_name == "web.intelligence":
            q = str((args or {}).get("query") or "")
            return {
                "ok": True,
                "formatted": f"Top result for: {q}\n- https://example.com/a\n- https://example.com/b",
                "results": [
                    {"title": "Result A", "url": "https://example.com/a", "category": "news", "volatile": True},
                    {"title": "Result B", "url": "https://example.com/b", "category": "news", "volatile": True},
                ],
                "citation_map": [
                    {"id": 1, "url": "https://example.com/a", "title": "Result A"},
                    {"id": 2, "url": "https://example.com/b", "title": "Result B"},
                ],
                "evidence_contract": {
                    "required_min_sources": 2,
                    "found_sources": 2,
                    "satisfied": True,
                },
            }
        return {"ok": True}

    async def fake_chat_with_model_failover(*, prompt: str, messages: List[Dict[str, Any]], should_search: bool, route: str = "llm_only", memory_intent: bool = False, temperature: float = 0.0, max_tokens: int = 256, tool_events: List[Dict[str, Any]] | None = None) -> str:
        if should_search:
            return "Grounded answer using web context [1]."
        return "Local response with continuity preserved."

    async def fake_memory_ingest_nonblocking(*, active_user_id: str, limit: int = 4) -> None:
        return None

    async def fake_naturalize(raw_content: str, original_prompt: str) -> str:
        return raw_content

    agent._run_tool_with_loop_guard = fake_run_tool_with_loop_guard  # type: ignore[assignment]
    agent._chat_with_model_failover = fake_chat_with_model_failover  # type: ignore[assignment]
    agent._memory_ingest_nonblocking = fake_memory_ingest_nonblocking  # type: ignore[assignment]
    agent._naturalize_search_output = fake_naturalize  # type: ignore[assignment]

    prompts = [
        "latest nvidia ai chip news",
        "can you expand on that",
        "continue with the same",
        "follow up on this",
        "more on this",
    ]
    # Add long filler turns to force compaction.
    filler = "please keep elaborating with practical details and next actions for this topic while preserving prior decisions"
    for i in range(14):
        prompts.append(f"{filler} #{i}")

    outputs: List[str] = []
    for p in prompts:
        out = await agent.generate_response(p, user_id=user_id)
        outputs.append(str(out))

    checks: List[StressCheck] = []

    # Follow-up continuity check using route log.
    route_log = Path("sessions/logs/routing_decisions.log")
    rows = _tail_log_rows(route_log, user_id=user_id, limit=200)
    followup_prompts = {
        "can you expand on that",
        "continue with the same",
        "follow up on this",
        "more on this",
    }
    followup_rows = [r for r in rows if str(r.get("prompt") or "").strip().lower() in followup_prompts]
    followup_web = [r for r in followup_rows if str(r.get("route") or "") == "websearch"]
    checks.append(
        StressCheck(
            name="followup_context_binding",
            ok=len(followup_rows) >= 3 and len(followup_web) >= max(1, len(followup_rows) - 1),
            detail=f"followup_rows={len(followup_rows)};websearch_rows={len(followup_web)}",
        )
    )

    # Context compaction + ledger persistence checks.
    hist = agent._get_history_list(user_id)
    has_compaction = bool(hist and str((hist[0] or {}).get("content") or "").startswith(COMPACTION_PREFIX))
    ledger = agent._state_ledger_for_user(user_id)
    checks.append(
        StressCheck(
            name="context_compaction_triggered",
            ok=has_compaction,
            detail=f"history_len={len(hist)};first_is_compaction={has_compaction}",
        )
    )
    checks.append(
        StressCheck(
            name="state_ledger_persisted",
            ok=bool(int(ledger.get("turn_count") or 0) >= len(prompts)),
            detail=f"turn_count={int(ledger.get('turn_count') or 0)};prompts={len(prompts)}",
        )
    )

    # Evidence enforcement on search answers.
    has_sources = any("Sources:" in x or "[1]" in x for x in outputs[:6])
    checks.append(
        StressCheck(
            name="evidence_output_contract",
            ok=has_sources,
            detail=f"has_sources={has_sources}",
        )
    )

    # Tool-loop pressure check with original loop guard.
    def failing_runtime(tool_name: str, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:  # noqa: ARG001
        raise RuntimeError("simulated loop failure")

    agent.toolbox_runtime.run = failing_runtime  # type: ignore[assignment]
    loop_blocked = False
    loop_block_turn = 0
    for i in range(1, 30):
        try:
            out = await original_run_tool_guard(
                tool_name="web.intelligence",
                args={"query": "repeat"},
                ctx={"source": "stress", "approved": True, "user_id": user_id},
                active_user_id="stress_loop_user",
            )
            if bool((out or {}).get("_loop_blocked")):
                loop_blocked = True
                loop_block_turn = i
                break
        except Exception:
            pass

    checks.append(
        StressCheck(
            name="tool_loop_pressure_guard",
            ok=loop_blocked,
            detail=f"blocked={loop_blocked};turn={loop_block_turn or -1}",
        )
    )

    passed = sum(1 for c in checks if c.ok)
    total = len(checks)
    score = round((passed / total) * 100.0, 2) if total else 0.0

    report = {
        "ok": passed == total,
        "score": score,
        "passed": passed,
        "total": total,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
    }

    out_dir = Path("sessions/evals")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "live_chat_stress_matrix.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = asyncio.run(run_live_stress())
    print(json.dumps(result, indent=2, ensure_ascii=False))
