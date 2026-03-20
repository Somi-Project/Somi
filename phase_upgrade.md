# Somi Phase Upgrade Roadmap

This file tracks the current multi-chapter stabilization and polish push so work survives context compaction cleanly.

## Operating Rules

- Take a backup before every implementation phase.
- Take an additional backup before any non-trivial patchwave inside a phase.
- Run tests after every phase.
- Record the phase focus, changed files, validations, results, and follow-ups.
- Keep fragile verticals like weather, news, and finance stable unless a direct bug is confirmed.

## Chapter A: GUI And Search Polish

### Phase 112
- Reassess the current GUI shell from the CLI and offscreen runtime.
- Identify premium-UX gaps in layout density, control sizing, legibility, and live search/status presentation.
- Polish the theme switcher and premium dashboard interactions.
Status:
- Completed on 2026-03-18.
- Cockpit clusters, live cabin caption, full-window offscreen tests, and runtime logging hygiene are now in place.

### Phase 113
- Refine search answer presentation for the top everyday query classes.
- Tighten lead-summary style, supporting-source curation, and high-confidence wording.
- Expand live GUI artifacts so shell behavior is visible in audit outputs.
Status:
- Completed on 2026-03-18.
- Search answer phrasing is now more intent-aware for travel, planning, and compare-style everyday prompts.

### Phase 114
- Run a broader mixed GUI/search smoke pass.
- Compare current UX/results against Hermes, OpenClaw, DeerFlow patterns and capture remaining deltas.
Status:
- Completed on 2026-03-18.
- The first `everyday100` rerun confirmed there were no low-score rows, but it exposed seasonal-travel, budget, and phone-comparison polish opportunities.

## Chapter B: Stress And Repair

### Phase 115
- Run a 100-query safe everyday stress benchmark across common human search patterns.
- Categorize misses by routing, retrieval, adequacy, answer style, and UI presentation.
Status:
- Completed on 2026-03-18.
- Follow-up search output hygiene restored the benchmark average while keeping `0` low-score rows and a greener combined suite.

### Phase 116
- Put the HUD assets and cockpit shell to work so the GUI feels premium instead of merely themed.
- Replace fragile emoji-only rendering with resilient iconography where needed, tighten live-status density, and validate the shell offscreen.
Status:
- Completed on 2026-03-18.
- The cabin switch is now icon-led and more compact, the research pulse has a live signal meter, and the top strip reflects recent browse activity immediately.

### Phase 117
- Run the next focused live benchmark slice against the most UX-sensitive travel and shopping prompts.
- Fold the findings into a broader Chapter B repair plan for memory, coding, heartbeat, and self-healing stress work.
Status:
- Completed on 2026-03-18.
- Chapter B now has real runtime coverage for heartbeat, gateway, workflow, coding mode, memory session search, browser runtime, and delivery automations.
- The benchmark baseline shifted from missing coverage gaps to `measured=1 / ready=6`, with only medium-severity finality-baseline gaps remaining.

### Phase 118
- Capture finality baselines for coding, research, speech, automation, browser, and memory so the benchmark ledger moves from `ready` to `measured`.
- Persist finality artifacts and feed them back into the benchmark ledger.
- Repair any runtime regressions exposed by the direct CLI and long-running stress loops.
Status:
- Completed on 2026-03-18.
- The benchmark ledger is now fully measured at `7/7` packs with `0` open gaps.
- The safe `everyday100` benchmark rerun stayed green with `0` low-score rows and `4.52` average heuristic score.

## Chapter C: Codex-Mimic Layer

### Phase 119
- Design and implement a coding/control layer for file analysis, editing, sandboxing, repo handling, and repair flows.
- Reuse existing coding and research surfaces where possible.
Status:
- Completed on 2026-03-18.
- Somi now has a Codex-style control plane for workspace inspection, bounded edits, snapshots, verify loops, repo snapshot imports, and git commit/publish orchestration.
- The coding studio now surfaces git state and snapshot counts directly in the premium GUI.

### Phase 120
- Add context-compaction helpers, token-budget controls, and better prompt/runtime management.
- Stress test coding/edit/repair flows end to end.

## Chapter D: Telegram Unification

### Phase 121
- Audit Telegram runtime parity with the desktop shell.
- Unify tool access and agent runtime semantics between GUI and Telegram.
Status:
- Completed on 2026-03-19 via Phase 132 runtime unification work.
- Telegram now shares thread continuity, remote-session trust posture, background task telemetry, and richer reply formatting with the desktop runtime.

### Phase 122
- Refine OCR and document ingestion paths from Telegram.
- Stress test Telegram input/output quality, coding flows, and runtime resilience.
Status:
- Completed on 2026-03-19 via Phase 133.
- Telegram now accepts supported document uploads with provenance notes, anchor previews, and shared thread/task continuity.

## Chapter E: Final Competitive Advantage Run

### Phase 123
- Strengthen Somi's search output contract so official/latest answers carry cleaner authority voice, better date handling, and more intentional compare/planning phrasing.
- Improve source selection behavior so user-facing source lists are cleaner and less repetitive.
- Validate the search/output changes with both regression coverage and a live everyday slice.
Status:
- Completed on 2026-03-18.
- Official/government requirement lookups now use stronger official-source voice.
- Latest-answer wording now prefers the best available authoritative date instead of only the top-row date.
- Compare and trip-planning answers now surface cleaner evidence-derived takeaways.
- Phase 123 validation stayed green with `184` passing search tests, `191` passing combined search+GUI tests, and a live `everyday20` slice averaging `4.6`.

### Phase 124
- Add durable research briefs and section bundles to the deep-research path.
- Surface that structure through browse reports and search bundles so longer tasks can stay coherent across UI and runtime layers.
- Validate the new planner artifacts with focused composer/websearch regressions and the broader combined suite.
Status:
- Completed on 2026-03-19.
- `research_compose()` now emits a reusable research brief, subquestions, and section bundles instead of only a flat evidence bundle.
- Deep-browse reports and search bundles now carry planner metadata that future GUI, autonomy, and resume features can reuse.
- Phase 124 validation stayed green with `187` passing search tests and `194` passing combined search+GUI tests.

### Phase 125
- Add a persistent evidence cache and resume path beneath the existing in-memory web caches.
- Reuse canonicalized page/research artifacts so repeated deep-research queries can resume across handler instances instead of recomputing from scratch.
- Validate the cache/resume behavior with both regression coverage and a fresh-handler live probe.
Status:
- Completed on 2026-03-19.
- Deep research now persists evidence bundles, research briefs, section bundles, and canonicalized source URLs into a local TTL-backed evidence store.
- Top-level search can now resume an adequate deep-research bundle from disk, while the lower-level `_deep_browse()` helper stays deterministic unless resume is explicitly enabled.
- Phase 125 validation stayed green with `191` passing search tests, `198` passing combined search+GUI tests, and a live fresh-handler resume artifact showing `second_cached=true`.

### Phase 126
- Add a visible execution timeline to the premium research cockpit so users can follow browse progress without opening logs.
- Sync the latest research pulse into the fallback Research Studio view so the shell stays coherent across panels.
- Validate the new transparency layer with GUI runtime tests, offscreen smoke output, and the combined search+GUI suite.
Status:
- Completed on 2026-03-19.
- The Research Pulse card now renders a compact live execution timeline derived from browse execution events and steps.
- Research Studio now refreshes immediately from the latest browse pulse and mirrors the compact timeline when there is no long-running research job.
- Phase 126 validation stayed green with `191` passing search tests, `199` passing combined search+GUI tests, and a fresh offscreen artifact at `audit/phase126_gui_timeline_smoke.png`.

### Phase 127
- Polish the premium research cockpit so real chat-driven browse reports keep their source and timeline context after compaction.
- Add stronger empty/source states to the Research Pulse card and mirror them into Research Studio fallback text.
- Validate the richer pulse states with GUI regressions, offscreen smoke output, and the full combined suite.
Status:
- Completed on 2026-03-19.
- The compact browse-report path now preserves timeline rows and primary-source previews instead of collapsing everything into a single summary.
- The Research Pulse card now shows dedicated primary-source rows, and Research Studio mirrors those sources when no long-running research job is active.
- Phase 127 validation stayed green with `191` passing search tests, `199` passing combined search+GUI tests, and a fresh offscreen artifact at `audit/phase127_gui_pulse_sources_smoke.png`.

### Phase 130
- Add a durable coding scratchpad and compact resume summary so long coding sessions can survive context reduction cleanly.
- Surface the same compaction state through the coding control plane and Coding Studio.
- Validate the new layer with focused coding/runtime tests and a broader combined suite.
Status:
- Completed on 2026-03-19.
- Coding sessions now persist a structured scratchpad with focus files, constraints, open loops, and next actions.
- The coding control plane now emits a compact resume summary, and Coding Studio surfaces it directly in the welcome view.
- Phase 130 validation stayed green with `205` passing combined tests plus a live scratchpad probe showing a persisted coding resume summary.

### Phase 132
- Make Telegram a first-class front end to the same Somi brain.
- Share thread continuity, background task identity, and richer response formatting between Telegram and the desktop runtime.
- Validate conversation replay, cross-surface resume, and Telegram trust posture.
Status:
- Completed on 2026-03-19.
- Telegram now resolves stable per-conversation thread IDs, reuses active work on follow-ups, and can resume the latest cross-surface thread on `continue`-style prompts.
- Telegram users are now surfaced as remote gateway sessions with paired-owner vs guest trust posture, while queued/running/completed Telegram work is persisted in the shared background task ledger.
- Telegram replies now carry compact research and coding delivery notes so remote output feels closer to the desktop experience.
- Phase 132 validation stayed green with `229` passing combined tests, an import smoke of `telegram_import_ok True`, and a detailed audit summary at `audit/phase132_telegram_runtime_summary.md`.

### Phase 133
- Make document workflows dependable and polished for Telegram uploads without adding heavyweight cloud dependencies.
- Add document extraction, provenance notes, and anchor previews for PDFs and text-based uploads.
- Validate document intelligence with focused regressions, the OCR benchmark hook, and the broader combined suite.
Status:
- Completed on 2026-03-19.
- Added `workshop/toolbox/stacks/ocr_core/document_intel.py` so supported document uploads now produce cleaned excerpts, anchor previews, and clear review guidance.
- Telegram can now summarize supported document uploads through the shared runtime path, with provenance notes and handoff-ready background task metadata.
- Phase 133 validation stayed green with an OCR benchmark smoke of `ok=True`, `average_parse_ms=0.277`, `average_score=1.0`, and `233` passing combined tests. Details live in `audit/phase133_document_intelligence_summary.md`.

### Phase 128
- Add a confidence-aware preference graph on top of the existing memory store so Somi has a clearer durable view of user profile and preference facts.
- Surface that graph through frozen memory snapshots and the Control Room memory section.
- Validate the new graph with focused memory regressions and the broader combined suite.
Status:
- Completed on 2026-03-19.
- Memory now aggregates profile and preference facts into a structured preference graph with confidence and evidence counts.
- The Control Room memory view now exposes that preference graph, and frozen memory snapshots preserve it for explainability.
- Phase 128 validation stayed green with `207` passing combined tests plus a live preference-graph probe.

### Phase 137
- Add bounded autonomy profiles to the runtime control plane so Somi can expose initiative levels without weakening human control.
- Surface the active autonomy profile through approval summaries and Control Room operator views.
- Validate the policy layer with focused autonomy tests, a runtime smoke, and the full combined suite.
Status:
- Completed on 2026-03-19.
- Ops Control now persists `active_autonomy_profile`, `autonomy_profiles`, and `autonomy_revisions` alongside the existing runtime rollout state.
- Approval summaries and the Control Room config overview now surface the autonomy profile directly, making safe-autonomy posture visible to operators.
- Phase 137 validation stayed green with `210` passing combined tests plus a runtime smoke artifact at `audit/phase137_autonomy_smoke.md`.

### Phase 138
- Add a persisted background task ledger and recovery loop so Somi can keep useful work alive outside the immediate chat turn.
- Add a lightweight resource-aware budget for background work and surface queue health in Control Room observability.
- Validate the queue, recovery, and budget path with focused background-task tests, a runtime smoke, and the full combined suite.
Status:
- Completed on 2026-03-19.
- Runtime now has a persisted background task ledger with queue, running, retry-ready, and failed states plus artifact and handoff metadata.
- Ops Control now exposes background task create/heartbeat/complete/fail/recover methods, while Control Room shows background queue health and resource budget hints.
- Phase 138 validation stayed green with `215` passing combined tests plus a runtime smoke artifact at `audit/phase138_background_recovery_smoke.md`.

### Phase 139
- Add approval-only skill apprenticeship suggestions so repeated successful work can become reusable skills without silent self-modification.
- Add a trust-aware answer policy so high-stakes queries with thin evidence get stronger caution before the user acts on them.
- Validate the apprenticeship and trust-policy layers with focused tests, a runtime smoke, and the full combined suite.
Status:
- Completed on 2026-03-19.
- Runtime now records repeated work into an apprenticeship ledger, surfaces draft-ready suggestions, and keeps those suggestions approval-gated.
- The answer validator now adds stronger caution for thin-evidence health/legal/financial answers, and Control Room observability now surfaces apprenticeship readiness.
- Phase 139 validation stayed green with `219` passing combined tests plus a runtime smoke artifact at `audit/phase139_skill_trust_smoke.md`.

### Phase 134
- Make Somi's operator diagnostics match the real backup/recovery workflow instead of assuming a separate root-level `backups` folder.
- Add an exportable support-bundle command for fast diagnostics, support handoff, and release-readiness snapshots.
- Validate doctor, support-bundle export, and release-gate behavior with focused regressions and the broader combined suite.
Status:
- Completed on 2026-03-19.
- `ops/backup_verifier.py` now discovers `audit/backups`, validates meaningful phase checkpoints, and reports backup modes and roots.
- `ops/support_bundle.py` now powers `somi support bundle`, giving Somi a persisted JSON/Markdown operator snapshot without needing a full release-gate run.
- Doctor, security audit, and release gate now all report healthy status on the live repo, and Phase 134 validation advanced the combined suite to `238` passing tests with details in `audit/phase134_ops_diagnostics_summary.md`.

### Phase 135
- Add a harder research/planning benchmark pack that measures the queries Somi is supposed to outperform on, not just everyday lookups.
- Add a unified release-candidate runner that can combine search, coding, memory, and Telegram parity validation into one artifact.
- Validate the new release-candidate path with live hard-research runs plus the broader combined suite.
Status:
- Completed on 2026-03-19.
- `audit/safe_search_corpus.py` now ships `researchhard100`, `researchhard25`, and `everyday100` named corpora.
- `audit/release_candidate.py` now runs a combined release-candidate pack across `researchhard100`, coding, memory, and Telegram parity suites.
- Phase 135 validation stayed green with a live `researchhard100` average heuristic score of `4.95`, average Somi time of `3.38s`, and `241` passing combined tests. Details live in `audit/phase135_release_candidate_summary.md`.

### Phase 136
- Add one coordinated full-system gauntlet so search, memory, reminders, compaction, OCR, coding, and mixed-use continuity can be validated together.
- Add a resumable gauntlet CLI so long runs can be resumed from persisted artifacts instead of repeating completed search work.
- Validate the gauntlet itself, then run the full `Search100 + Memory100 + Reminder100 + Compaction100 + OCR100 + Coding100 + AverageUser30` matrix.
Status:
- Completed on 2026-03-19.
- `audit/system_gauntlet.py` now drives the Phase 136 full-system gauntlet and reuses completed search artifacts when rerun.
- `somi.py release gauntlet` now exposes the coordinated stress harness through the main CLI, and `tests/test_system_gauntlet_phase136.py` covers the default pack inventory, subset writer, and CLI flow.
- Phase 136 validation passed with `7/7` gauntlet packs green, a live `Search100` score of `4.52`, a full-system report at `audit/phase136_system_gauntlet_summary.md`, and `244` passing combined tests.

### Phase 140
- Add a first-class phase-backup creator so long upgrade runs stop depending on ad hoc shell copies.
- Exclude nested backups, external repo mirrors, venvs, and bulky generated session artifacts from default checkpoints.
- Refresh `update.md` so the next campaign is aligned to contributor clarity, architecture cleanup, polish, and offline resilience.
Status:
- Completed on 2026-03-19.
- `ops/backup_creator.py` now powers `somi backup create`, which produces focused checkpoints under `audit/backups` without recursing through older backup trees.
- `update.md` now reflects the post-gauntlet baseline and lays out the next campaign phases `141` through `147`.
- Phase 140 validation stayed green with `tests/test_backup_creator_phase140.py`, a live smoke backup at `audit/backups/phase140_smoke_backup_*`, and the summary artifact `audit/phase140_backup_hardening_summary.md`.

### Phase 141
- Add contributor-facing maps for the controller split, toolbox, and the main search/research/coding layers.
- Create one durable architecture path for basic users and developers so newcomers can find the right subsystem quickly.
- Validate the map with docs coverage checks plus a core runtime smoke.
Status:
- Completed on 2026-03-19.
- `docs/architecture/CONTRIBUTOR_MAP.md` now anchors the newcomer path, and the main working layers gained local `README.md` maps.
- Phase 141 validation stayed green with docs coverage regressions, backup verification, and a passing core runtime smoke.

### Phase 142
- Turn contributor docs into a real guardrail by centralizing docs integrity checks and surfacing them in operator diagnostics.
- Add a practical newcomer checklist for first debugging steps and where to add tests.
- Validate the guardrails through focused docs tests plus live doctor and release-gate runs.
Status:
- Completed on 2026-03-19.
- `ops/docs_integrity.py` now powers docs coverage checks, `docs/architecture/NEWCOMER_CHECKLIST.md` now gives a safe first-debugging workflow, and doctor/release gate both surface docs integrity.
- Phase 142 validation stayed green with focused docs-guardrail regressions and live `somi doctor` / `somi release gate` passes.

### Phase 143
- Expand the newcomer map to the top-level platform surfaces so package ownership is clearer before deeper refactors.
- Cover ops, gateway, state, workflow runtime, search, execution backends, agent methods, and tests with local `README.md` maps.
- Re-run docs integrity plus live ops smokes after expanding the required surface area.
Status:
- Completed on 2026-03-19.
- Top-level platform packages now have local maps, and docs integrity now guards those surfaces as part of release quality.
- Phase 143 validation stayed green with expanded docs regressions, backup verification, and live doctor/release-gate passes. Details live in `audit/phase141_143_contributor_clarity_summary.md`.

### Phase 144
- Remove the remaining answer-mixer helper shadowing and tighten the user-facing search-answer contract.
- Smooth out trip-planning phrasing so complete itinerary takeaways read naturally.
- Revalidate the search stack with the full search regression suite and live ops checks.
Status:
- Completed on 2026-03-19.
- `executive/synthesis/answer_mixer.py` now exposes only one canonical definition for the core synthesis helpers, with legacy variants renamed out of the way.
- Trip-planning answers now keep strong itinerary takeaways intact instead of wrapping them in awkward scaffolding.
- Phase 144 validation stayed green with `193` passing search tests and a release-gate pass.

### Phase 145
- Polish the GUI interaction layer so premium theme controls and research pulse messaging feel intentional during live use.
- Fix the premium theme registry labels and improve browse-pulse fallback copy.
- Validate the shell through runtime GUI tests rather than only stylesheet checks.
Status:
- Completed on 2026-03-19.
- The premium theme switch now exposes real emoji labels cleanly, and the research pulse now falls back to progress/execution context when a full summary is not available yet.
- Phase 145 validation stayed green with `8` passing GUI tests.

### Phase 146
- Add non-destructive artifact hygiene reporting so long upgrade cycles stay observable and sustainable.
- Surface generated-artifact budgets in doctor and release gate.
- Tune the default budgets against Somi's current working set and re-run ops diagnostics.
Status:
- Completed on 2026-03-19.
- `ops/artifact_hygiene.py` now tracks generated `audit` and `sessions` surfaces, and both doctor and release gate report that signal.
- Phase 146 validation stayed green with focused ops regressions, `somi doctor --json`, and `somi release gate --json --no-write`, ending in `status=pass` and `readiness_score=100.0`.

### Phase 147
- Add bundled local knowledge packs and degraded-network search fallback so Somi stays useful when live retrieval is weak or unavailable.
- Surface offline readiness and knowledge provenance through doctor, release gate, Control Room, and the main CLI.
- Validate local-pack loading, search fallback, and the live offline posture.
Status:
- Completed on 2026-03-19.
- `workshop/toolbox/stacks/research_core/local_packs.py` now loads bundled knowledge packs, `ops/offline_resilience.py` now reports fallback readiness, and `workshop/toolbox/stacks/web_core/websearch.py` now reuses local packs and Agentpedia before giving up.
- `somi.py` now exposes `somi offline status`, Control Room observability shows offline resilience directly, and doctor/release gate include the same signal.
- Phase 147 validation stayed green with `216` passing combined tests plus live `doctor`, `offline status`, and `release gate` JSON passes.

### Phase 148
- Add an operator observability digest so Somi can explain runtime hotspots,
  recovery pressure, and policy friction in human-readable terms.
- Surface that digest through a new CLI, the support bundle, and the Control
  Room observability tab.
- Filter out synthetic eval noise so live diagnostics stay credible.
Status:
- Completed on 2026-03-19.
- `ops/observability.py` now builds a runtime-health digest, `somi.py` now
  exposes `observability snapshot`, and Control Room now shows `Latency
  Hotspots` plus `Recovery Watchlist`.
- `ops/support_bundle.py` now captures observability state and
  recommendations, and the live digest suppresses synthetic eval/test noise plus
  expected heartbeat-channel policy chatter.
- Phase 148 validation stayed green with `22` focused tests, `222` passing
  combined tests, and live `observability snapshot` / `support bundle` checks.

### Phase 149
- Give everyday answer types clearer structure so compare, planning, travel,
  explain, and official-lookups feel premium instead of generic.
- Add regressions for the new answer contracts and re-run the broader search
  and GUI validation slice.
Status:
- Completed on 2026-03-19.
- `executive/synthesis/answer_mixer.py` now emits clearer everyday answer
  scaffolds like `Quick take:`, `Trip shape:`, and `Short answer:`.
- Phase 149 validation stayed green with `196` focused search tests, `223`
  passing combined tests, and the audit artifact
  `audit/phase149_structured_answers_summary.md`.

### Phase 150
- Add a memory review layer that surfaces promotion candidates, stale items,
  conflicts, and cleanup watch items instead of treating memory as a passive
  fact store.
- Wire the new review state into memory hygiene, frozen snapshots, memory
  doctor, and the Control Room.
Status:
- Completed on 2026-03-19.
- `executive/memory/review.py` now powers the review digest, and
  `gui/controlroom_data.py` now exposes a `Memory Review Queue`.
- Phase 150 validation stayed green with `5` focused memory tests, `226`
  passing combined tests, and live `doctor` / `release gate` passes. Details
  live in `audit/phase150_memory_review_summary.md`.

### Phase 151
- Add a shared resume ledger so GUI, background tasks, and Telegram can all
  point at the same resumable work instead of each keeping their own partial
  continuity view.
- Surface the continuity state in Control Room, support diagnostics, and
  Telegram's resume behavior.
Status:
- Completed on 2026-03-19.
- `runtime/task_resume.py` now powers a cross-surface `Task Resume Ledger`,
  `gui/controlroom_data.py` now exposes a `continuity` tab, and
  `ops/support_bundle.py` now captures continuity recommendations.

### Phase 152
- Make Telegram delivery feel like the same runtime as the GUI instead of a
  reduced side channel.
- Add Telegram-safe long-answer delivery, route-aware follow-up notes, and
  exported markdown handoff files for research/coding/document work.
- Validate the upgraded channel behavior through focused Telegram/document
  regressions, import checks, and the broader runtime suite.
Status:
- Completed on 2026-03-19.
- `workshop/integrations/telegram_runtime.py` now builds Telegram delivery
  bundles with compact primary replies, follow-up sections, document capsules,
  and optional markdown exports for oversized results.
- `workshop/integrations/telegram.py` now sends those bundled replies through
  both normal chat and document-ingestion paths, including exported files and
  attachment delivery.
- Phase 152 validation stayed green with `11` focused tests, a passing
  `py_compile` check, `246` passing combined tests, and the audit summary
  `audit/phase152_telegram_parity_summary.md`.

### Phase 153
- Raise answer finality so freshness, confidence, and evidence quality are
  explicit before the user has to inspect source rows.
- Carry trust-aware output signals through the browse report, the chat capsule,
  and the Research Pulse.
- Validate the trust layer with focused validator/GUI tests plus the broader
  runtime suite.
Status:
- Completed on 2026-03-19.
- `runtime/answer_validator.py` now adds freshness-date and thin-evidence
  checks plus a reusable trust summary contract.
- `agent_methods/response_methods.py`, `gui/aicoregui.py`,
  `gui/chatpanel.py`, and `somicontroller_parts/status_methods.py` now surface
  that trust signal in the user-facing runtime.
- Phase 153 validation stayed green with `10` focused tests, a passing
  `py_compile` check, `251` passing combined tests, and the audit summary
  `audit/phase153_output_finality_summary.md`.

### Phase 154
- Add a real context-budget subsystem so long-running work exposes compaction
  health instead of failing silently after enough turns.
- Surface the same signal through the CLI, Control Room, doctor, support
  bundle, and release gate.
- Filter synthetic stress/eval sessions out of the live operator posture.
Status:
- Completed on 2026-03-19.
- `ops/context_budget.py` now measures per-thread pressure and compaction
  health, `somi.py` now exposes `context status`, and Control Room now ships a
  dedicated `Context` tab.
- Doctor, support bundle, and release gate now reuse the same context-budget
  report, while synthetic sessions are ignored so the live repo stays clean.
- Phase 154 validation stayed green with `256` passing mixed regression tests,
  clean live `context status`, `doctor`, and `release gate` runs, and the
  audit summary `audit/phase154_context_budget_summary.md`.

### Phase 155
- Remove stale backup-verifier sample paths so operator diagnostics stop
  reporting fake missing files.
- Revalidate doctor/release readiness after the verifier cleanup.
Status:
- Completed on 2026-03-19.
- `ops/backup_verifier.py` now validates `somi.py` instead of the removed
  `somicontroller.py`, so recent checkpoints resolve as clean
  `framework_backup` reports with no missing critical files.
- Phase 155 validation stayed green with focused ops diagnostics tests plus
  clean live `doctor` and `release gate` runs, recorded in
  `audit/phase155_backup_verifier_summary.md`.

### Phase 159
- Finish the unified task-envelope work so Telegram and the desktop shell carry
  the same task identity, handoff hints, and continuation posture.
- Extend Telegram delivery bundles with continuity notes and preferred-surface
  guidance.
- Validate the richer continuity bundle with targeted Telegram/runtime tests
  plus a mixed policy/runtime pack.
Status:
- Completed on 2026-03-19.
- `runtime/task_resume.py` now stores `recommended_surface`, while
  `workshop/integrations/telegram_runtime.py` and
  `workshop/integrations/telegram.py` now propagate continuity notes,
  background-task counts, and resume hints through Telegram chat and document
  flows.
- Phase 159 validation stayed green with `12` focused tests, a passing
  `py_compile` check, and the audit summary
  `audit/phase159_164_runtime_and_federation_summary.md`.

### Phase 161
- Push the coding control plane toward a more Codex-like patch loop with
  symbol-aware repo maps, bounded change plans, and explicit edit-risk scoring.
- Surface the same coding guidance in Coding Studio instead of hiding it in the
  backend.
- Validate the upgraded coding loop through focused coding/GUI tests and a
  mixed runtime pack.
Status:
- Completed on 2026-03-19.
- `workshop/toolbox/coding/change_plan.py` now builds bounded change plans and
  edit-risk scores, `workshop/toolbox/coding/repo_map.py` now extracts
  lightweight symbols, and the control plane / Coding Studio now surface that
  guidance directly.
- Phase 161 validation stayed green with `5` focused coding tests, `15` mixed
  runtime tests, and the audit summary
  `audit/phase159_164_runtime_and_federation_summary.md`.

### Phase 163
- Create the plugin federation core so Somi can normalize external `SKILL.md`
  bundles into local descriptors instead of living in a separate skill
  ecosystem.
- Add trust tiers, inferred tool requirements, and approval expectations to the
  imported-skill contract.
Status:
- Completed on 2026-03-19.
- `skills_local/federation.py` now provides descriptor parsing, trust-tiered
  import, registry storage, and execution-policy review for imported markdown
  skills.
- Phase 163 validation stayed green with `3` focused federation tests and the
  combined audit summary `audit/phase159_164_runtime_and_federation_summary.md`.

### Phase 164
- Add real adapter and review flows on top of the federation core so imported
  skills can be previewed, origin-tagged, and promoted from experimental to
  reviewed.
- Document the plugin-federation path for contributors.
Status:
- Completed on 2026-03-19.
- `skills_local/adapters.py` now provides review and approval helpers, while
  `docs/architecture/PLUGIN_FEDERATION.md` documents the review/promotion flow
  and best-effort origin tagging for outside ecosystems.
- Phase 164 validation stayed green with `5` focused adapter/federation tests,
  `20` mixed runtime tests, and live `release gate` readiness at `100.0`.

### Phase 162
- Deepen the autonomy profiles so they capture step, time, retry, and
  load-aware execution budgets instead of only basic risk posture.
- Route those budgets into action-policy decisions so autonomy slows down or
  stops under stress without weakening model cognition.
Status:
- Completed on 2026-03-19.
- `runtime/autonomy_profiles.py` now exposes load-aware autonomy budgets,
  `runtime/action_policy.py` now respects those budgets from runtime context,
  and `ops/control_plane.py` now backfills the new fields into persisted
  autonomy-profile config.
- Phase 162 validation stayed green with `11` focused autonomy/action-policy
  tests, `21` mixed runtime tests, a passing `py_compile` check, and live
  `doctor` output recorded in `audit/phase162_autonomy_budget_summary.md`.

### Phase 165
- Reduce premium-shell overlap and cramped states by making the cockpit layout
  more responsive at normal desktop widths.
- Validate the shell with offscreen renders and the focused GUI suite.
Status:
- Completed on 2026-03-19.
- `somicontroller_parts/layout_methods.py` now gives the hero strip a calmer
  two-row layout and splits the quick-action cockpit into two dashboard rows,
  with comparison renders captured in `audit/phase165_gui_shell_before.png`,
  `audit/phase165_gui_shell_after.png`, and
  `audit/phase165_gui_shell_narrow.png`.
- Phase 165 validation stayed green with `10` focused GUI tests and the audit
  summary `audit/phase165_166_gui_and_cleanup_summary.md`.

### Phase 166
- Eliminate the lingering unclosed-socket noise in memory-heavy regression
  slices.
- Ensure Ollama compatibility wrappers close their underlying transports
  cleanly.
Status:
- Completed on 2026-03-19.
- `runtime/ollama_compat.py` now closes nested `httpx` clients correctly, and
  `executive/memory/embedder.py` now uses explicit cleanup for default Ollama
  client calls.
- Phase 166 validation stayed green with `2` focused cleanup tests and a
  warning-sensitive memory rerun recorded in
  `audit/phase165_166_gui_and_cleanup_summary.md`.
- `workshop/integrations/telegram_runtime.py` now prefers open-task threads for
  resume prompts, and Phase 151 validation stayed green with `240` passing
  combined tests plus live `doctor` / `release gate` passes. Details live in
  `audit/phase151_task_continuity_summary.md`.

### Phase 167
- Make the project easier for basic users and developers to navigate without
  reading the whole repo.
- Fill the remaining high-signal README gaps across major top-level folders and
  refresh the runtime / GUI maps.
Status:
- Completed on 2026-03-19.
- Added quick-entry readmes for `docs/`, `learning/`, `subagents/`,
  `deploy/`, and `ontology/`, and refreshed `gui/README.md` plus
  `runtime/README.md`.
- Phase 167 validation stayed green with live `doctor` and `release gate`
  passes, a clean docs-integrity report, and the audit summary
  `audit/phase167_docs_clarity_summary.md`.

### Phase 168
- Repair the benchmark/finality loop so focused search slices behave
  deterministically and healthy loop-guard warnings do not flood the logs.
Status:
- Completed on 2026-03-19.
- `audit/search_benchmark_batch.py`, `audit/system_gauntlet.py`, and
  `audit/safe_search_corpus.py` now propagate limits correctly, and
  `agent_methods/history_methods.py` now dedupes warning-level tool-loop logs
  per user and warning key.
- Phase 168 validation stayed green with focused gauntlet and loop-warning
  tests plus a passing search-limit smoke, summarized in
  `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 169
- Reconfirm Somi's competitive baseline by fixing the one live runtime
  regression still blocking the finality gauntlet.
Status:
- Completed on 2026-03-19.
- `agents.py` now binds `_tool_loop_warning_cache` into the live extracted-agent
  method context, and `tests/test_tool_loop_warning_phase168.py` now exercises
  the real `Agent` loop guard instead of only the shimmed helper path.
- Phase 169 validation stayed green with a restored `7/7` competitive gauntlet
  pass and the same audit summary
  `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 170
- Strengthen the offline knowledge-pack contract so local recovery content is
  more durable, inspectable, and integrity-aware.
Status:
- Completed on 2026-03-19.
- `workshop/toolbox/stacks/research_core/local_packs.py` now tracks schema,
  variant, trust, updated-at, and per-document hashes, and the bundled
  manifests now carry the same metadata explicitly.
- Phase 170 validation stayed green with focused offline-resilience tests and
  the combined audit summary `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 171
- Add a distribution-sovereignty layer so store or OS policy pressure remains
  an edge concern instead of mutating Somi Core.
Status:
- Completed on 2026-03-19.
- `gateway/surface_policy.py` now models edge-only policy signals and
  sovereignty snapshots for managed surfaces versus direct/self-hosted ones.
- Phase 171 validation stayed green with focused sovereignty tests and the
  combined audit summary `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 172
- Make Somi hardware-adaptive from very weak systems to high-end workstations
  without lowering the framework ceiling.
Status:
- Completed on 2026-03-19.
- `ops/hardware_tiers.py` now classifies survival/low/balanced/high hardware
  tiers and feeds survival-mode advice into offline resilience.
- Phase 172 validation stayed green with focused hardware-tier tests and the
  combined audit summary `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 173
- Turn the bundled offline packs into a first-class catalog that operators can
  inspect and query directly.
Status:
- Completed on 2026-03-19.
- `ops/offline_pack_catalog.py` now exposes preferred-variant ordering and
  local preview hits, while `somi.py` now provides `offline catalog`.
- Phase 173 validation stayed green with focused catalog/offline tests and the
  combined audit summary `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 174
- Add a durable node-exchange contract so Somi can evolve into a real
  store-and-forward continuity node.
Status:
- Completed on 2026-03-19.
- `gateway/federation.py` now provides inbox/outbox/archive envelopes and
  `somi.py` now provides `offline federation`.
- Phase 174 validation stayed green with focused federation tests and the
  combined audit summary `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 175
- Expand bundled offline usefulness from generic docs into real recovery
  domains and continuity workflows.
Status:
- Completed on 2026-03-19.
- Added continuity packs for sanitation, health, food, and power plus
  continuity workflow manifests, `ops/continuity_recovery.py`, and
  `somi offline continuity`.
- Phase 175 validation stayed green with focused continuity/offline tests and
  the combined audit summary `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 176
- Prove the new continuity stack works together under survival-mode
  assumptions.
Status:
- Completed on 2026-03-19.
- `audit/recovery_drill.py` now runs a blackout-style drill covering survival
  hardware mode, offline resilience, continuity workflows, resumable workflow
  snapshots, and node-exchange round trips, and `somi.py` now exposes
  `offline drill`.
- Phase 176 validation stayed green with focused recovery-drill tests, a live
  drill pass, and the combined audit summary
  `audit/phase168_176_resilience_and_finality_summary.md`.

### Phase 177
- Finish merge-readiness hardening with a final GUI polish and hygiene pass.
Status:
- Completed on 2026-03-19.
- Fixed the premium theme switch glyph source so it now uses stable
  symbol escapes instead of corrupted mojibake strings.
- Tightened `.gitignore` for generated audit/runtime debris and cleared
  transient recovery-drill state.
- Final validation stayed green with:
  - `audit/phase176_final_merge_ready.json` showing `7/7` passing packs
  - `358` passing tests under `tests/`
  - `10` passing focused GUI tests
  - `somi doctor` green and `somi release gate` `pass`
  - `audit/phase177_merge_ready_summary.md`

### Phase 178
- Restore chat-first GUI priority and eliminate the startup chat-worker
  immersion break.
Status:
- Completed on 2026-03-19.
- `somicontroller_parts/layout_methods.py` now collapses the old
  intelligence and heartbeat panes into a single `Ops Stream`, keeps the
  splitter biased toward chat, and trims the lower quick-action band.
- `gui/chatpanel.py` now disables default-button leakage for auxiliary
  controls, manages pending startup sends with a single retry timer, and
  filters stale startup boilerplate from persisted history.
- `somicontroller_parts/runtime_methods.py` now prewarms the chat worker at
  startup and only announces readiness once the worker is genuinely ready.
- later patchwaves in Phase 178 also folded speech into the right rail and
  collapsed Research Pulse into one compact feed so the side console stops
  feeling cramped.
- Phase 178 validation stayed green with focused GUI/runtime suites and the
  audit summary `audit/phase178_gui_chat_priority_summary.md`.

## Completion Criteria

- GUI feels premium, fast, and legible across light, shadowed, and dark modes.
- Search answers are consistently polished across the top everyday query types.
- Stress benchmarks surface no major broken categories.
- Core systems have repeatable repair paths and passing regression coverage.
- Desktop and Telegram experiences feel like one coherent Somi runtime.
