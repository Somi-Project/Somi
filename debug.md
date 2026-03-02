# Phase 7 Debug Notes

## Completed checks
- Added optional remote read-only calendar providers (Google/MS Graph) in fail-closed token-consumer mode.
- Added artifact-store sharding + optional primary mirroring.
- Added goal-link confirmation queue.
- Added sparse-data bootstrap relaxation mode for clustering to avoid empty early UX.
- Reduced memory pressure in Phase 7 JSONL ingestion by bounded tail-byte reads (`PHASE7_JSONL_TAIL_READ_BYTES`).
- Hardened goal-link resolution to update the latest goal_model revision for the goal.
- Upgraded Executive GUI queue UX from ID-only flow to table-selection flow with row-select approve/reject support.
- Added queue table scaling ergonomics:
  - client-side text filter
  - structured status preset (`pending|approved|rejected|all`)
  - structured date-range filtering (`from` / `to` YYYY-MM-DD)
  - table sorting on columns
- Added queue action affordance:
  - Approve/Reject buttons disabled until a valid proposal id is selected/entered.
- Added lifecycle telemetry:
  - queue depth trend (`current_depth`, `max_depth_seen`, samples)
  - approval/rejection counts + approval latency stats
  - shard file growth (`current_files`, `max_files_seen`, samples)
- Added GUI-oriented test coverage for proposal-id validator and date parser helpers (skips when PyQt6 missing).

## Simulation + audit loops
1. Loop 1 (suite): full Phase 7 + heartbeat tests passed.
2. Loop 2 (runtime smoke): py_compile + queue/provider simulations passed.
3. Loop 3 (structured filter hardening): status/date filters + API list-by-status patched; regression tests passed.

## Remaining merge-risk items
1. Optional future enhancement: persisted filter presets and saved queue views.
2. OAuth refresh/exchange remains intentionally deferred to future modular auth/email layer work.

# Proactivity Layer Debug Audit (current cycle)

## Audit pass 1: implementation + failures discovered
- Added a new proactivity package (`executive/proactivity/`) with deterministic scoring, routing, preference compilation, feedback parsing, brief/alert utilities, cache, notifier, validators, and metrics.
- Added regression test suite `tests/test_proactivity_layer.py` for routing thresholds, interrupt budget, timing deferral, grouping, escalation resets, stagnation detection, quality gating, preference TTL/precedence, brief window settings, alert dedupe, and NL feedback parsing.
- First test run surfaced two defects:
  1. Interrupt-budget test fixture used an unrealistically small budget (`10`) so first notify could never pass.
  2. `duration="today"` expiry logic incorrectly used *current day* end instead of the update day end, causing temporary suppressions to leak.

## Patch pass 1
- Updated test fixture budget to `50` so first high-SSI notify is allowed and second is downgraded.
- Fixed `preferences._expiry()` for `duration="today"` to expire at the end of the update’s local day.

## Re-audit pass 2
- Re-ran proactivity tests; one assertion expectation was stale:
  - `today` suppression test was evaluated on the next day and expected still-disabled state.
- Adjusted the test timestamp to same-day window where the suppression should be active.

## Final status
- Proactivity test suite passes cleanly.
- Spot-check strategic non-execution invariant still passes.
- No hangs/freezes observed in this cycle; all logic paths are deterministic and side-effect scoped to artifacts/messages.

# Proactivity Layer Re-Audit (simulate → audit → plan → patch)

## Simulation
- Re-ran targeted proactivity + non-execution guard tests to establish baseline behavior.

## Audit findings
1. Timezone handling in preference timestamps/expiry mixed naive+local conversions and could drift across zones.
2. `snooze` intent output existed but effective preference compilation did not consistently apply it as a temporary suppression.
3. Router downgrade logic could over-log when `brief_windows` was absent from caller prefs instead of using safe defaults.
4. Brief date field used host-local timezone instead of requested timezone.
5. Alerts dedupe lacked suppression TTL; duplicate content could re-alert indefinitely or never reset.
6. NL feedback time parsing supported `set ... to` but was weak for equivalent phrasing like `move morning brief to 9`.

## Plan
- Normalize preference timestamps to timezone-aware UTC, then convert safely for `today` end-of-day behavior.
- Treat snooze as a temporary suppression mode with TTL semantics.
- Make router brief fallback robust when window config is missing.
- Fix brief artifact date timezone source.
- Add TTL-based alert fingerprint suppression.
- Expand parser coverage and add regression tests for new edge cases.

## Patch summary
- Patched `preferences.py` for timezone-safe parse/expiry/active checks and stronger mode application (including `snooze`, deterministic `enable`).
- Patched `router.py` downgrade path to honor default brief windows when absent and keep message/day gating deterministic.
- Patched `briefs.py` date generation to use requested timezone.
- Patched `alerts.py` with suppression TTL per topic/fingerprint.
- Patched `feedback_intent.py` with improved time parsing and `move ... brief to` handling.
- Expanded `tests/test_proactivity_layer.py` for: all-window-disabled routing, snooze temporary behavior, alert suppression TTL behavior, and move-time parsing.

## Re-audit
- Full targeted suite now passes after patching.
- Behavior remains non-executing (no action execution paths added).

# Proactivity Config Modularization Audit

## Simulation
- Ran targeted tests for proactivity routing + heartbeat behavior after introducing config-level proactivity toggles.

## Audit findings
1. Proactivity behavior was effectively always on because limits/defaults were hardcoded in runtime modules.
2. Heartbeat auto-brief first-interaction behavior did not respect a global proactivity kill-switch.
3. Router had no global gate to force `log_only` when proactive messaging is disabled.

## Plan
- Add modular proactivity controls in `config/settings.py`.
- Wire settings into proactivity defaults and router gates.
- Gate heartbeat automatic brief behavior behind global proactivity settings while preserving explicit user commands.
- Add tests for global off behavior.

## Patch
- Added `PROACTIVITY_ENABLED`, `PROACTIVITY_ALLOW_AUTOMATIC_MESSAGES`, and proactivity daily budget defaults in settings.
- Routed preference default limits to settings-backed values.
- Added router global gate and settings-backed fallback limits.
- Updated heartbeat engine to block only automatic first-interaction brief when global proactivity is disabled.
- Added tests validating global-off behavior in both proactivity router and heartbeat auto-brief path.

## Re-audit
- Targeted suites pass; behavior remains deterministic and non-executing.

# Romeo/Juliet Naming Refactor Audit

## Simulation
- Performed a hard rename pass to remove numbered labels from active executive/heartbeat code paths.
- Re-ran strategic/life-modeling/heartbeat/proactivity/executive test slices.

## Audit findings
1. Numbered labels were embedded in settings constants, strategic router symbols, agent signal keys, and heartbeat guardrail fields.
2. The old naming leaked into debug trigger metadata (`matched_phrases`) and filesystem debounce/telemetry file names.
3. Manual debugging docs did not explain new naming or where to inspect failures.

## Plan
- Replace numbered labels in active code paths with Romeo/Juliet names (no compatibility aliasing).
- Update strategic routing and agent signal key names consistently.
- Rename execution guardrail key to a non-numbered field.
- Update executive and heartbeat READMEs for manual debugging.

## Patch summary
- Replaced lifecycle settings and runtime references from numbered labels to `MONTAGUE_*` names.
- Replaced strategic routing references from `phase8_*` semantics to `capulet_*` semantics.
- Replaced execution guardrail field `phase5_required_for_execution` with `duel_approval_required` in active emit/normalize paths.
- Updated executive README and added heartbeat README with naming map + debugging checklists.

## Re-audit
- Targeted test suites pass after refactor.
- No compatibility shims were added, as requested.

# Triple Debug Cycle (simulate → audit → plan → patch) after Romeo/Juliet migration

## Loop 1
### Simulate
- Ran targeted heartbeat/life-modeling/strategic/proactivity/executive suites.

### Audit
- Proactivity router had two robustness gaps:
  1. `thresholds` access assumed key presence and could raise on sparse prefs.
  2. Interrupt budget default was hardcoded and did not honor settings runtime value.

### Plan
- Make router tolerant of missing threshold dictionaries.
- Bind default budget to settings dynamically.
- Add regression tests.

### Patch
- Added safe `thresholds = prefs.get("thresholds", {})` handling in route gating.
- Converted `InterruptBudget` to dynamic default via `__post_init__` using `PROACTIVITY_DAILY_INTERRUPT_BUDGET`.
- Added tests for missing thresholds and settings-driven budget default.

### Re-simulate
- `tests/test_proactivity_layer.py` + `tests/test_phase6_heartbeat.py` all pass.

## Loop 2
### Simulate
- Ran broader integration slice including strategic/life-modeling/calendar/agent feedback/executive/store tests.

### Audit
- `next_brief_window` could raise when malformed brief time strings appear in preferences/artifacts.

### Plan
- Make time parsing fail-safe and skip malformed windows.
- Add regression test for invalid time values.

### Patch
- Hardened `next_brief_window` parsing with guarded int conversion + range checks.
- Added `test_next_brief_window_ignores_invalid_times`.

### Re-simulate
- Proactivity + heartbeat + strategic slices pass.

## Loop 3
### Simulate
- Attempted full `pytest -q` collection.
- Collection failed in audio/speech script tests due missing optional dependency (`numpy`) in environment.
- Ran wide non-audio suite (`tests` + smoke, ignoring scripts/speech tools) and found one functional failure.

### Audit
- `_extract_user_correction` returned raw-case tail text, but downstream tests and normalization assumptions expect normalized lower-case correction payload.

### Plan
- Normalize extracted correction tail to lower-case before return.

### Patch
- Updated `Agent._extract_user_correction` to return normalized lower-case correction note/payload.

### Re-simulate
- `tests/test_agent_feedback_loop.py` and related regression slices pass.

## Greyzone / open design choices
1. **Brief candidate accounting**: router enforces max-messages/day via `can_message`, but inclusion accounting is not explicitly consumed by a final brief-delivery step in this layer. This is acceptable for now but should be finalized once a canonical brief dispatcher is wired.
2. **Correction normalization policy**: lower-casing improves deterministic matching/tests but may lose case-sensitive intent tokens in rare edge prompts; revisit if preserving exact casing becomes product-critical.
3. **Optional deps in full suite**: audio/speech script test collection currently requires `numpy`; this is an environment/package policy issue, not a logic failure in executive/proactivity paths.

# Brief Candidate Accounting Closure

## Simulate
- Re-ran proactivity + heartbeat + strategic slices after implementing explicit brief-candidate accounting.

## Audit
- Previous router behavior decided `include_in_next_brief` but did not provide an explicit consumption hook for final brief delivery, leaving reservation accounting implicit.

## Plan
- Add explicit candidate reservation accounting in router budget.
- Expose canonical consumption method for brief dispatcher integration.
- Add regression coverage for reserve/consume semantics.

## Patch
- Added `brief_candidate_count_by_day` tracking in `InterruptBudget`.
- Added `can_queue_brief_candidate`, `queue_brief_candidate`, `pending_brief_candidates`, and `mark_brief_delivered` methods.
- Updated router downgrade path to reserve candidate slots when returning `include_in_next_brief`.
- Added `SignalRouter.mark_brief_delivered(...)` as the dispatcher-facing consumption hook.
- Added `test_brief_candidate_accounting_and_delivery_consumption` to validate reserve/log/consume lifecycle.

## Re-audit
- Targeted suites pass and accounting now has an explicit finalization API for downstream brief dispatcher wiring.

## Greyzone
- The canonical dispatcher caller is still external to `executive/proactivity`; final integration point should call `SignalRouter.mark_brief_delivered(...)` after each sent brief artifact/message.

# Pillar Audit Pass (UX / Latency / Quality / Functionality / Security)

## Simulate
- Re-ran proactivity + heartbeat + strategic slices to validate current behavior under renamed lifecycle paths.

## Audit
- **UX + Functionality risk**: repeated routing of the same signal could reserve multiple `include_in_next_brief` candidate slots, reducing room for distinct high-value items and causing artificial budget pressure.
- **Latency/quality implication**: noisy duplicate reservation increases churn in brief candidate accounting and can indirectly suppress better candidates later in the same day.

## Plan
- Add deterministic de-dup semantics for brief-candidate reservations keyed by signal identity.
- Keep routing outcome stable (`include_in_next_brief`) for duplicates, but avoid consuming extra daily capacity.
- Add targeted regression tests for dedupe + capacity behavior.

## Patch
- Added per-day candidate key tracking (`brief_candidate_keys_by_day`) to `InterruptBudget`.
- Updated queue checks to treat duplicate candidate keys as non-consuming.
- Updated downgrade path to use a deterministic candidate key derived from signal fields (`topic/project_id/goal_id/signal_type/entity_id`).
- Extended tests:
  - distinct candidates consume capacity and cap out
  - duplicate candidates do not consume additional capacity

## Re-audit
- All targeted slices pass.
- Candidate accounting now better aligns with pillars:
  - UX: fewer duplicate brief entries crowding daily budget
  - Latency: less redundant accounting churn
  - Quality: preserves budget for distinct, higher-value items
  - Functionality: deterministic reserve/consume semantics remain intact
  - Security: no new execution paths or privilege changes introduced

# Repeat Reliability Loop (simulate → audit → plan → repair)

## Loop A
### Simulate
- Ran proactivity/heartbeat/strategic/executive regression slice.

### Audit
- Interoperability risk found: proactivity router assumes valid IANA timezone names and can raise `ZoneInfoNotFoundError` if caller passes malformed timezone values.
- Impact: potential runtime exceptions in routing/date-window code paths (user-experience + framework reliability risk).

### Plan
- Add safe timezone resolver with fallback to UTC.
- Apply resolver in daily-key accounting and brief-window scheduling.
- Add tests for invalid timezone handling.

### Repair
- Added `_safe_zone(timezone)` helper in `executive/proactivity/router.py`.
- Replaced direct `ZoneInfo(timezone)` calls with safe fallback usage.
- Added tests:
  - `test_router_invalid_timezone_falls_back_to_utc`
  - `test_next_brief_window_invalid_timezone_falls_back_to_utc`

### Re-simulate
- Proactivity/heartbeat/strategic/executive slices pass.

## Loop B
### Simulate
- Ran additional life-modeling + feedback regression slices.

### Audit
- No additional functional bugs/hangs/freezes observed in targeted lanes.
- No new interoperability regressions from timezone fallback patch.

### Plan
- Keep patch set focused (no speculative changes).

### Repair
- No further code changes required.

### Re-simulate
- Additional regression slices pass.

## Merge readiness
- Current branch is merge-ready for the patched scope (proactivity routing reliability + timezone interoperability).
- Remaining optional full-suite blocker remains external dependency (`numpy`) in optional audio/speech collection, unchanged from prior environment notes.

# Pre-merge Hard Audit Pass

## Simulate
- Ran proactivity + heartbeat + strategic regression slices again before merge.

## Audit
- Found a subtle UX/functionality bug in candidate dedupe:
  - Router dedupe key always used `topic|project|goal|signal_type|entity`.
  - If identity fields were missing, multiple distinct candidates for same topic (e.g., weather) could collapse into one reserved slot.
  - Result: under-counting queued brief candidates and possible missed diversity in brief content.

## Plan
- Deduplicate only when a stable identity exists.
- Preserve dedupe for explicit IDs/entity-bound signals.
- Avoid dedupe for identity-less candidates.
- Add regression test proving non-dedupe behavior for identity-less signals.

## Repair
- Updated `SignalRouter._candidate_key` to:
  - prefer explicit `candidate_id`
  - otherwise dedupe only when one of project/goal/signal_type/entity exists
  - return `None` when no stable identity exists (no dedupe)
- Added `test_brief_candidate_without_identity_does_not_dedupe`.

## Re-simulate
- Proactivity/heartbeat/strategic slices pass.
- This patch improves brief diversity and prevents silent under-reservation of candidate slots.

# Zero-Issue Audit Pass (latest)

## Simulate
- Ran broad targeted regression slices for proactivity, heartbeat, strategic, life-modeling, agent feedback, and executive engine.

## Audit
- Found a subtle interoperability/functional issue in brief candidate accounting:
  - after **partial** brief delivery (`consumed_candidates < pending`), candidate key cache remained partially stale.
  - this could suppress legitimate re-queue of a previously consumed candidate identity because consumed key membership was unknown.

## Plan
- Make post-delivery key-cache behavior deterministic and safe without false suppression.
- Add regression test for partial-delivery semantics.

## Repair
- Updated `InterruptBudget.mark_brief_delivered(...)` to reset per-day candidate-key cache on delivery events, preventing stale-key suppression after partial consume.
- Added `test_partial_brief_delivery_clears_stale_candidate_keys`.

## Re-simulate
- Broad targeted slices all pass.

## Merge readiness
- Merge-ready for audited scope; no blocking logic issues found in exercised lanes.

# Critical Pre-Merge Audit Pass (safety-focused)

## Scope and intent
- Performed a high-confidence audit with emphasis on future safety-critical reliability: deterministic behavior, non-executing guardrails, proactivity routing correctness, and interoperability across strategic/life-modeling/heartbeat lanes.

## Simulation
- Ran full non-audio regression corpus:
  - `pytest -q tests tests_runtime_smoke.py --ignore=scripts --ignore=speech/tools`

## Result
- 200 passed, 4 skipped.
- No failing assertions in proactivity, heartbeat, strategic routing, contracts, artifact store, executive orchestration, or runtime smoke paths.

## Manual code-risk checks reviewed
1. Proactivity candidate accounting remains deterministic with explicit reserve/consume hooks.
2. Timezone handling in proactivity router is fail-safe via UTC fallback for invalid zone identifiers.
3. No execution leakage introduced in proactive paths; guardrails still require execution approval fields in contracts.
4. Renamed Montague/Capulet signal paths remain consistent across routing and agent orchestration.

## Residual risk statement
- No blocking logic defects were found in exercised lanes during this pass.
- Optional audio/speech tests remain intentionally excluded in this run due environment dependency profile and are outside this audit scope.
