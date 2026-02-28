# Somi Repair Report (Natural-Language → Execution Integration)

This report audits the end-to-end path from human natural-language input to routing, tool/search usage, executive control, contract/artifact generation, memory write-back, and response latency.

## Update Status (patched in current cycle)
- ✅ Fixed governance cancel-path: `cancel` now clears pending approvals in controller flow.
- ✅ Fixed executive throttle hard-fail path: `ExecutiveEngine.tick()` now returns a structured rate-limit response.
- ✅ Hardened artifact index writes:
  - Corrupt index JSON now resets cleanly during update.
  - Empty artifact IDs are ignored in index maps.
  - Index writes now use atomic temp-file replacement.
- ✅ Persisted pending execution tickets to disk and reload on next turn to survive restarts.
- ✅ Switched turn memory write-back to asynchronous background ingestion to reduce response latency.
- ✅ Improved research stack latency by racing Agentpedia and SearXNG concurrently under a total deadline budget.
- ✅ Added regression tests for all above fixes.
- ✅ Added cross-process session file locking for artifact appends/index updates.
- ✅ Added adaptive response/vision timeout profiles to reduce default wait times on lower-context runs.
- ✅ Tightened controller active-item/open-loop capture heuristics to reduce noisy state pollution.
- ✅ Hardened research race path against first-completed task exceptions to prevent accidental stack abort.
- ✅ Hardened artifact index rebuild path to ignore empty ids in historical malformed lines.
- ✅ Closed file-handle hygiene gaps in artifact index and pending-ticket reads.
- ✅ Added durable memory write-behind queue (`sessions/memory_queue`) so async memory ingestion keeps low latency without dropping writes on fast exits.
- ✅ Added correction-loop heuristics so user negative feedback (e.g., “I wanted X instead”) can reroute intent and be persisted to memory.
- ✅ Tightened correction-loop trigger to avoid false-positive reroutes on plain short “no” responses.
- ✅ Added speed/determinism middle ground for research race: short grace window + deterministic provider preference when both sources are available.

## Remaining Priority Issues
- Optional enhancement: add non-POSIX fallback for cross-process locks on platforms without `fcntl`.
- Optional enhancement: expose timeout profile overrides in user-facing config for easier tuning.
- Optional enhancement: semantic similarity dedupe for open-loop titles beyond exact-text matching.

## Strategic Conflict Notes (important)
- **Latency vs durability**: async memory write-back improves response speed but increases risk of losing latest memory facts if process exits immediately after response.
- **Strict loop filtering vs recall**: tighter controller heuristics reduce noisy state capture but may miss some short/implicit user intents unless phrasing is explicit.
- **Research race vs deterministic source preference**: first-success race lowers latency but can vary provider/source ordering between runs.

## Conflict Status (after latest patch)
- **Latency vs durability**: mitigated with durable queue-backed write-behind (enqueue sync, ingest async).
- **Strict tracking vs recall**: now includes explicit correction-loop signals to recover when user says output intent was wrong.
- **Research speed vs determinism**: now uses short grace collection and stable provider preference when both providers return quickly.

## Strategic Follow-up Note
- Artifact creation now consistently uses `routing_prompt` for query context so corrected-intent turns produce aligned contracts.

Scope reviewed:
- `agents.py` mainframe orchestration
- executive layer (`executive/*`)
- autonomy/governance controller (`runtime/controller.py` + state)
- contract layer (`handlers/contracts/*`)
- research subsection around websearch (`handlers/research/*`, plus integration points in `handlers/websearch.py`)

Per your request, this report **does not propose changes to core websearch behavior** (finance/weather/news/general routing internals), except where research integration causes reliability/latency issues.

---

## 1) High-Risk Functional Bugs / Logic Gaps

## A. `cancel` approval signal is detected but never actually cancels pending approval
**Where:** `runtime/controller.py`

- `_detect_approval()` accepts `"cancel"` as an approval signal.
- `_classify()` maps any non-`approve & run` signal to `CHAT_WITH_SUGGESTION`.
- `handle_turn()` has no explicit cancellation path to clear pending approvals.

**Impact:**
- User types "cancel" expecting a safety-stop, but pending approval hash remains in state.
- This is a governance UX bug and can create trust/safety confusion.

**Repair:**
1. Add explicit intent `CANCEL_PENDING` in `_classify()` for `approval_signal == "cancel"`.
2. In Stage D, clear `state.pending_approvals` (or selected ticket) and return deterministic confirmation.
3. Add test: `cancel` removes pending approval and does not execute.

---

## B. Executive rate-limit exceptions can hard-fail `tick()`
**Where:** `executive/engine.py`, `executive/budgets.py`, `runtime/ratelimit.py`

- `tick()` calls `self.budgets.allow_intent()`.
- `SlidingRateLimit.hit()` raises `RateLimitError` when exceeded.
- `tick()` does not catch this exception.

**Impact:**
- Under burst usage, the executive path can throw uncaught exceptions (surface crash/error instead of graceful throttling message).

**Repair:**
1. Catch `RateLimitError` in `tick()` and return structured throttling payload (`{"error": "rate_limited", ...}`).
2. Include retry-after hint using remaining window.
3. Add tests for repeated `tick()` calls > max budget.

---

## C. Contract index update silently degrades on JSON read failure
**Where:** `handlers/contracts/store.py`

- In `_update_index()`, JSON load failure uses `except Exception: idx = idx`, which is effectively a no-op.
- Resulting behavior can keep stale/partial in-memory index state and overwrite without explicit recovery.

**Impact:**
- Potential index inconsistency, especially after partial write/corruption.
- Retrieval (`get_last`, `get_by_id`) can become slower or return unexpected fallback behavior.

**Repair:**
1. Replace with explicit reset + rebuild trigger (`idx = {"session_id":..., "contracts":{}, "by_id":{}}`).
2. Use atomic write for index file (`.tmp` then replace) like queue implementation.
3. Add corruption recovery test (invalid JSON index).

---

## D. Empty contract/artifact keys can pollute index maps
**Where:** `handlers/contracts/store.py`, `handlers/contracts/base.py`

- `_update_index()` records entries even if `contract_name` or `artifact_id` is empty string.

**Impact:**
- `contracts[""]` / `by_id[""]` keys may be written.
- Last-artifact lookup behavior becomes brittle for malformed writes.

**Repair:**
1. Guard index writes: only write `contracts[cid]` if `cid`; only write `by_id[aid]` if `aid`.
2. Add validation assertion before append/index.

---

## 2) Freeze / Stall Risks (User-Perceived Hangs)

## A. Main LLM timeout too high for consumer hardware
**Where:** `agents.py`

- Main generation timeout is `120s`.
- Vision timeout is `180s`.

**Impact:**
- On CPU or low-VRAM fallback, user can experience long "frozen" turns.

**Repair:**
1. Introduce adaptive timeout profiles (`fast/standard/quality`) tied to hardware mode.
2. Default interactive mode target: first token/response path under 8–12s for consumer machines.
3. Add "working..." intermediate status emission for GUI/telegram bridges.

---

## B. Research fallback chain can stack multiple slow stages
**Where:** `handlers/websearch.py` research integration (`_research_stack`)

Current order:
1) Agentpedia
2) SearXNG
3) DDG fallback

Each can involve network + parsing + retries.

**Impact:**
- A single research query can cascade into long sequential latency.
- Looks like freeze, especially when providers are degraded.

**Repair (without touching core websearch handlers):**
1. Add global elapsed-time budget for research stack (e.g., 8–12s total).
2. Run Agentpedia and SearXNG concurrently; first sufficient result wins.
3. Skip DDG fallback if elapsed budget exhausted.

---

## C. Memory write-back blocks response completion path
**Where:** `agents.py` + `handlers/memory/manager.py`

- After generation, `ingest_turn()` runs inline before return.
- `ingest_turn()` may trigger extraction/embedding/summary work.

**Impact:**
- User waits for memory persistence even when answer is already ready.

**Repair:**
1. Return user content first; move memory ingestion to background task queue with bounded semaphore.
2. If background fails, log + continue (no user-facing delay).
3. Keep synchronous only for explicit "remember this" intents.

---

## 3) Autonomy / Governance Integration Weak Spots

## A. Approval state is in-memory in `Agent`, but governance state is on-disk
**Where:** `agents.py`, `runtime/user_state.py`, `runtime/controller.py`

- Pending tool ticket object is kept in `self._pending_tickets_by_user` (process memory).
- Approval hashes live in persisted user state.

**Impact:**
- After restart, hash may exist but ticket object is gone.
- User may approve and get confusing "no pending ticket found" behavior.

**Repair:**
1. Persist pending ticket payload securely (staging file keyed by ticket hash).
2. On startup/reload, reconcile pending hashes with ticket objects; prune or restore.
3. Provide explicit response: "pending approval expired after restart" when unrecoverable.

---

## B. Over-broad state updates add noise to active/open loops
**Where:** `runtime/controller.py`

- Any text containing "project/task/learning/problem" can upsert active item.
- Any text containing "pending" can create open loop.

**Impact:**
- State pollution from normal chat.
- Increased proactive nudges not aligned to true user intent.

**Repair:**
1. Gate updates behind stronger intent phrase checks.
2. Use minimum token/semantic confidence before creating loops.
3. Add cap + dedupe by semantic similarity, not exact text slice.

---

## 4) Contract Layer Robustness Gaps

## A. Artifact append/index lock scope is single-process only
**Where:** `handlers/contracts/store.py`

- Uses `threading.Lock()`, not inter-process file lock.

**Impact:**
- Multi-process GUI + bot setups can interleave writes, corrupting index/read offsets.

**Repair:**
1. Add cross-process lock (portalocker/filelock/fcntl-based strategy).
2. Keep atomic append+index update transaction semantics.

---

## B. Artifact generation failures for research brief are handled, but not classified for observability
**Where:** `agents.py`, `handlers/contracts/orchestrator.py`

- Exceptions are logged and degraded message appended.
- No structured counter/metric for failure reasons.

**Impact:**
- Hard to tune thresholds (`MIN_SOURCES_FOR_RESEARCH_BRIEF`) and spot regressions.

**Repair:**
1. Add structured telemetry counters by failure code (`insufficient_sources`, `insufficient_doc_context`, etc.).
2. Emit per-turn route/intent/artifact decision debug object (opt-in).

---

## 5) Latency Optimization Plan (Consumer Hardware First)

## Priority 0 (Quick Wins, low-risk)
1. **Asynchronous memory write-behind** after response return.
2. **Lower default interactive timeout** from 120s to profile-driven (e.g., 40s standard).
3. **Early-answer strategy:** if search context unavailable within short budget, return partial answer + offer "continue research".
4. **Skip expensive context blocks** when prompt is short/simple (single-step routing + no artifact).

## Priority 1 (Medium effort, high impact)
1. **Parallelize independent pre-LLM tasks** in `agents.py`:
   - memory context build
   - due reminders check
   - RAG retrieval
   - skill registry snapshot
2. **Research stack deadline control:** total wall-clock deadline and concurrent provider race.
3. **Prompt size governor:** hard cap on assembled system prompt chars before model call.

## Priority 2 (Deeper architecture)
1. **Streaming response tokens** in GUI/telegram adapters to reduce perceived latency.
2. **Persistent job queue** for non-critical post-turn tasks (memory distillation, artifact indexing, summarization).
3. **Telemetry-based adaptive routing** (if last N tool calls timed out, downgrade to faster local answer path).

---

## 6) Suggested Test Additions (Targeted)

1. `test_cancel_clears_pending_approval()` in runtime governance tests.
2. `test_executive_tick_rate_limited_returns_structured_error()`.
3. `test_artifact_store_index_rebuild_on_corrupt_index()`.
4. `test_artifact_store_ignores_empty_contract_or_id_keys()`.
5. `test_generate_response_returns_before_memory_background_task_completes()` (after async write-behind refactor).
6. `test_research_stack_respects_total_deadline_and_returns_best_effort()`.

---

## 7) Rollout Strategy (Safe, Incremental)

1. **Governance correctness first** (cancel behavior + rate-limit handling).
2. **Contract store hardening** (index guards, atomic writes, corruption recovery).
3. **Latency changes behind feature flags** (`FAST_INTERACTIVE_MODE`, `ASYNC_MEMORY_WRITEBACK`).
4. Observe logs/metrics for one release cycle.
5. Then enable by default for consumer builds.

---

## 8) What I Did *Not* Change

- Did not patch core websearch routing/finance/weather/news implementations.
- Only assessed research-related integration and orchestration behavior where it impacts freezes/latency.
