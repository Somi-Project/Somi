# Phase 1 Contracts Assessment: Value vs Bloat

## Repo findings (validated)

### 1) Main request flow and safest hook points
- The primary turn pipeline is inside `Agent.respond(...)` in `agents.py`: pre-routing command/skill handling → `decide_route(...)` → route-specific tool path (`local_memory_intent`, `conversion_tool`, `websearch`) → prompt assembly + LLM call → memory writeback → history push + return.
- **Safest pre-handler hook**: immediately after routing (`decision = decide_route(...)`) and before route branches execute.
- **Safest post-handler hook**: after `content` is finalized (including numeric guard/memory notices) and before `_push_history_for(...)`/`return content`.

### 2) Router contract today
- Routing is centralized in `handlers/routing.py` and returns a `RouteDecision` dataclass with:
  - `route` (`command|local_memory_intent|conversion_tool|websearch|llm_only`)
  - `tool_veto` (bool)
  - `reason` (str)
  - `signals` (dict, including `intent`, `volatile`, `explicit` when websearch triggers)
- This is already close to the metadata needed for artifact intent gating.

### 3) Existing handler output shapes
- `websearch.search(...)` returns `list[dict]` results with fields like `title`, `url`, `description`, and category/volatility metadata; `agents.py` converts it to **text context** via `format_results(...)`, and also extracts URLs for final answer citation hints.
- RAG content is text-only in this pipeline (`_build_rag_block(...)`) and does not currently provide stable page refs/chunk IDs in final response objects.
- `llm_only` returns a plain text answer from the model (`content` string).

### 4) Agentpedia write surfaces and schema expectations
- Facts ingestion endpoints are database-backed store methods in `handlers/research/science_stores.py`:
  - `VerifiedScienceStore.add_fact(topic, fact, source, confidence, tags)`
  - `ResearchedScienceStore.add_facts([{topic/fact/source/confidence/domain/tags/evidence_snippet}, ...])`
- These APIs are fact-oriented and compatible with a facts-only distillation layer.

### 5) Existing persistence locations (artifact-store candidates)
- Session and logs are already persisted under `sessions/` from `agents.py` (`sessions/logs`, `sessions/<user_id>/...`).
- JSONL persistence patterns already exist in `jobs/journal/*.jsonl`.
- Best low-risk location for new artifacts: `sessions/artifacts/<session_id>.jsonl`.

## Product decision: substance or bloat?

## Verdict
This is **substantive**, not bloat, **if scoped tightly** to your 3-contract Phase 1. It gives Somi:
- Better reliability for intensive tasks (stable artifact shape).
- Better follow-up UX (retrieve and revise prior artifacts).
- Safer long-term autonomy path (facts-only Agentpedia writes, plans excluded).

The bloat risk appears when this becomes too many artifact types too early. Your own “Phase 2 later” boundary is the correct control.

## Should this be a skill or core handler flow?
- **Recommendation: core handler orchestration, not a skill.**
- Why:
  1. You want **automatic NL triggering** without user commands.
  2. It must run on top of existing routes and handler outputs every turn.
  3. It needs fail-safe fallback to the original answer path.
- Skills in this repo are command-oriented (`/skill ...`) and proposal/approval-aware; they are excellent for explicit workflows, but not ideal as always-on response post-processing.

Use a skill later for explicit artifact operations (e.g., “/skill revise_plan”), but not for first-pass autonomous triggering.

## Recommended integration architecture (minimal-change)

### A) Add contracts as a thin package
- New package: `handlers/contracts/` (or `somi/contracts/` if you want a cleaner top-level domain package).
- Keep it pure types + validators + markdown renderers.
- Include only:
  - `research_brief`
  - `doc_extract`
  - `plan`
- Support `content.extra_sections[]` to avoid schema explosion.

### B) Add artifact store (JSONL)
- New module: `handlers/contracts/store.py` with append-only writes.
- File path: `sessions/artifacts/<session_id>.jsonl`.
- Expose:
  - `append(artifact)`
  - `get_last_by_type(session_id, type)`
  - `get_by_id(session_id, artifact_id)`

### C) Add intent detector with strict gates
- New module: `handlers/contracts/intent.py`.
- Inputs: `user_text`, `route`, cheap flags (`has_doc`, maybe `has_search_results`), and optional session hints.
- Output: `{artifact_intent, confidence, reason}`.
- Gate hard:
  - `doc_extract` requires `has_doc=True`.
  - `plan` requires personal/action orientation.
  - prefer `research_brief` on `websearch` + synthesis/citation asks.
  - threshold default `0.75`.

### D) Add normalization adapter (no handler refactors)
- New module: `handlers/contracts/envelopes.py`.
- Convert existing outputs into stable envelopes in orchestration only:
  - `SearchEnvelope(answer_text, sources[])`
  - `DocEnvelope(answer_text, chunks[], page_refs[])`
  - `LLMEnvelope(answer_text)`

### E) Add 3 pipelines
- New package: `handlers/contracts/pipelines/`.
  - `research_triage.py`
  - `doc_intel.py`
  - `planning.py`
- Pipelines should be robust to missing metadata and fail closed (return original response).

### F) Add one orchestration hook in `agents.py`
1. **Pre-handler:** compute flags + detect intent.
2. **Post-handler:** if intent present, normalize → pipeline → strict validate → persist JSONL → render markdown response.
3. On exception: log and return original response unchanged.

### G) Add facts-only distillation bridge
- New module: `handlers/contracts/fact_distiller.py`.
- Write to Agentpedia stores only when provenance is sufficient:
  - Research brief: cited claims only.
  - Doc extract: table items only, and only with page refs.
  - Never write from plan or `extra_sections`.

## Risk and tradeoff analysis
- **Primary risk:** low-quality intent detection can misfire and add noise.
  - Mitigation: high threshold + one-artifact-per-turn + hard gating.
- **Secondary risk:** schema overhead slows iteration.
  - Mitigation: only 3 contracts + `extra_sections` escape hatch.
- **Data integrity risk:** contaminating Agentpedia with advice/recommendations.
  - Mitigation: explicit fact distiller filters + provenance-required writes.

## Recommended rollout strategy
1. Land contracts + store + envelopes behind feature flags.
2. Enable NL intent detection for `research_brief` first.
3. Add `doc_extract` once document context/page refs are reliably available.
4. Add `plan` generation last, but keep Agentpedia writes disabled for plan forever.

## Bottom line
Proceed with Phase 1. This adds real user-facing leverage for intensive tasks and lays groundwork for autonomy without prematurely overengineering. Keep it in core orchestration (not skills) and enforce strict facts-only writeback discipline.
