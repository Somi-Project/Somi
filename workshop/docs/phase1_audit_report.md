# Phase 1 Integration Audit Report (Updated)

## Outcome
- ✅ **Pass:** Pre-handler intent detection, post-handler build/store/render, and fail-safe fallback are implemented in `agents.py`.
- ✅ **Pass:** Hard constraints are enforced for Agentpedia facts-only distillation, doc gating, research source minimums, one-artifact-per-turn behavior, and `extra_sections[]` handling.
- ✅ **Pass:** Previously identified must-fix issues (missing artifact settings imports, artifact `timestamp`/`session_id` record mismatch, and plan revision continuity) are implemented.
- ✅ **Pass:** Research fallback policy now degrades explicitly/consistently and can optionally show a one-line notice (`ARTIFACT_DEGRADE_NOTICE`).

## Verified integration points in `agents.py`
1. **Pre-handler artifact intent detection:** after `decide_route(...)`, artifact intent is detected with doc-context flagging.
2. **Research route upgrade policy:** when intent is `research_brief` and route is not `websearch`, search is forced for grounding.
3. **Post-handler artifact orchestration:** artifact build → validate/render → append to JSONL store → facts distillation (where eligible).
4. **Fail-closed fallback policy:** on research artifact degradation paths (insufficient sources or search unavailable), output stays as normal answer; optional one-line degrade notice is appended when enabled.

## Research fallback tiers (grounding-safe)
- ✅ **Tier 0 (ideal):** websearch success + sources ≥ `MIN_SOURCES_FOR_RESEARCH_BRIEF` → structured `research_brief` artifact.
- ✅ **Tier 1:** websearch success but sources < minimum → normal answer path (optional degrade notice), no fake brief.
- ✅ **Tier 2:** websearch unavailable → normal answer path (optional degrade notice), no fake brief.
- ✅ **Facts safety:** no artifact build means no research facts are distilled.

## Plan revision guardrails
- ✅ Revision only applies when follow-up intent markers are present.
- ✅ Revision confidence threshold is applied before hydration.
- ✅ Last plan must also pass recency checks (`ARTIFACT_PLAN_REVISION_MAX_AGE_MINUTES`) before revision mode is used.
- ✅ If guardrails fail, system falls back to regular new-plan behavior.

## Hard constraints audit (current state)
- ✅ **Agentpedia facts-only:** Distiller writes only for `research_brief` and `doc_extract`; plan artifacts are not distilled.
- ✅ **Plan never writes to Agentpedia:** `FactDistiller.distill_and_write(...)` returns no writes for `plan`.
- ✅ **`doc_extract` requires doc context:** detector and orchestrator both gate this path.
- ✅ **`research_brief` minimum sources:** orchestrator raises build error if source count is below configured minimum.
- ✅ **One artifact per turn:** when enabled, rendered artifact markdown replaces final content.
- ✅ **Flexible `extra_sections[]` supported:** validators normalize/render extra sections; distiller does not ingest them as facts.

## Distillation purity checks
- ✅ **Research distillation:** only claims with a corresponding citation URL are written.
- ✅ **Doc distillation:** when `DOC_FACTS_REQUIRE_PAGE_REFS=True`, rows without page/doc refs are skipped.

## Storage audit (current state)
- ✅ JSONL artifact store provides `append`, `get_last_by_type`, and `get_by_id`.
- ✅ Base artifact schema includes both `created_at` and `timestamp` (alias).
- ✅ Store append injects `session_id` when missing and backfills `timestamp` if absent.
- ✅ Artifacts remain separate from Agentpedia fact stores.
- ✅ Orchestration logs route/intent/timing metadata without logging full prompt/response payloads.

## Validation notes
- Added/updated smoke coverage for:
  - no plan misfire (`steps of glycolysis`)
  - no doc-extract misfire (`summarize this` without doc)
  - research route-upgrade policy
  - research degrade-safe notice behavior + no non-research distill side-effects
  - doc facts page-ref gate
  - plan revision linking to previous artifact id
- Artifact test suite passes with the expanded cases.
