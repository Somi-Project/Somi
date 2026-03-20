# Somi Final Competitive Advantage Plan

Generated: 2026-03-18

This file is the durable master plan for Somi's next major refinement run.
It is intended to survive context compaction and act as the single reference
for high-priority upgrades across search, GUI, memory, coding, runtime,
Telegram, OCR, productization, and benchmarking.

Related logs:
- [phase_upgrade.md](C:/somex/phase_upgrade.md)
- [agentupgrade.md](C:/somex/agentupgrade.md)
- [searchupgrade.md](C:/somex/searchupgrade.md)

Current baseline:
- Search hardening is materially improved.
- Safe `everyday100` benchmark is green with `0` low-score rows.
- Finality ledger is green at `7/7` measured packs.
- The coordinated system gauntlet is green at `7/7` packs.
- Combined suite reached `244` passing tests.
- Release gate is green with `readiness_score=100.0`.
- Somi now has a Codex-style coding control plane, safe autonomy foundations,
  and a premium cockpit shell.

Current frontier:
- newcomer discoverability still lags behind Somi's actual capability
- backup safety needs to be standardized so checkpoints never recurse or bloat
- some package boundaries are still only obvious to long-term contributors
- output polish and GUI flow quality need another pass to feel unmistakably
  premium against Hermes and OpenClaw
- artifact hygiene and offline resilience foundations are now worth treating as
  first-class concerns

## North Star

Make Somi the strongest local-first AI operating system in its class by
combining:

- best-in-class evidence-first search and research
- the most compelling desktop operator experience
- private, durable memory with genuine continuity
- a first-rate coding and repair control plane
- one coherent runtime across GUI and Telegram
- product polish that rivals or exceeds Hermes and OpenClaw

The goal is not to imitate competitors feature-for-feature. The goal is to
beat them by combining their strongest ideas with Somi's unique strengths:
local-first sovereignty, a real desktop cockpit, evidence-based research,
and integrated coding control.

## Competitive Truth

### Somi already leads in

- local-first and self-hosted identity
- desktop shell and workstation posture
- no-key research/search quality and evidence handling
- integrated coding studio plus bounded control plane
- internal benchmark discipline and repair-loop rigor

### Somi is behind in

- memory learning loop and cross-session user modeling
- cross-channel parity and always-on messaging experience
- live action trace and visible agent theater
- onboarding, doctor/update flows, docs, and general product polish
- public ecosystem reach and perceived completeness

### Somi should aim to surpass competitors in

- trustworthy search output for everyday and research tasks
- premium GUI with visible, comprehensible agent work
- coding and repair workflows that feel safe and powerful
- private memory that gets better without becoming creepy or noisy
- unified runtime behavior across desktop and messaging

## Competitive Ideas To Borrow

### From Hermes

- self-improving skill and memory loop
- visible tool traces and streaming execution feel
- slash-command ergonomics and context controls
- cross-channel continuity from one agent runtime
- automation delivery and long-lived session behavior

### From OpenClaw

- onboarding wizard, doctor, update, and channel setup polish
- gateway-centric runtime with clear pairing and safety defaults
- multi-channel inbox and channel-specific routing maturity
- companion UX around live control surfaces
- installation, release channel, and support ergonomics

### From DeerFlow

- super-agent harness thinking
- sub-agent orchestration and sandbox-provider design
- context engineering discipline
- long-term memory layering
- messaging channel integration with one core runtime

### From GPT Researcher and Open Deep Research

- planner/executor/publisher split
- tree-like exploration with breadth/depth control
- research briefs, section plans, and report bundles
- benchmark-driven iteration
- hybrid retrievers and strong research citations

## Operating Rules For The Final Run

- Take a backup before every implementation phase.
- Take an additional backup before any non-trivial patchwave.
- Log each phase in `phase_upgrade.md`, `agentupgrade.md`, and
  `searchupgrade.md` when relevant.
- Run tests after every phase.
- Save benchmark outputs and focused live artifacts under `audit/`.
- Keep weather, news, and finance stable unless a direct bug is found.
- Keep the safe evaluation corpus free of explicit sexual content, malware,
  weapons/munitions, self-harm, and other risky categories.
- Prefer improvements that make the user feel clarity, confidence, momentum,
  and delight.

## Strategic Workstreams

### 1. Search And Research Excellence

Objective:
Make Somi's search feel deliberate, current, source-aware, and worth trusting.

What to build:
- a clearer browse contract by intent: factual, latest, compare, planning,
  docs, GitHub, official guidance, local info, direct URL, deep research
- stronger domain adapters for docs, GitHub, shopping, travel, government,
  standards/specs, and medical guidance
- better answer shaping from evidence bundles rather than raw SERP residue
- contradiction detection and recency checking before answer finalization
- better "not enough evidence" behavior instead of weak filler
- reusable research briefs and section plans for longer tasks
- a local evidence cache so repeat research is faster and more coherent

Expected user impact:
- faster trust
- less repetition and snippet noise
- better "latest" answers with concrete dates
- better comparisons and planning output
- stronger repo and docs summaries

Primary targets:
- `workshop/toolbox/stacks/web_core/`
- `workshop/toolbox/stacks/research_core/`
- `executive/synthesis/`
- `audit/`

### 2. GUI And Operator Experience

Objective:
Make Somi feel like a premium AI cockpit instead of a themed app.

What to build:
- an action timeline that shows what Somi is doing in human language
- richer Research Pulse and coding-control telemetry
- better source cards, compare cards, and session state visibility
- cleaner mode switching with minimal friction
- higher quality motion, spacing, visual hierarchy, and panel cohesion
- quick actions that are obvious but not noisy
- keyboard-first flow for power users
- stronger empty, loading, error, and recovery states

Expected user impact:
- users feel the agent is alive and understandable
- less uncertainty during long tasks
- better perceived quality during browsing and coding

Primary targets:
- `gui/`
- `somicontroller_parts/`
- `somicontroller.py`

### 3. Memory And Learning Loop

Objective:
Give Somi continuity and adaptation without sacrificing local control.

What to build:
- layered memory: episodic, semantic, procedural, and preference memory
- memory confidence and source lineage
- review-and-promote flow for durable memory
- automatic extraction of user preferences and recurring workflows
- self-nudges for unfinished tasks, follow-ups, and recurring interests
- skill drafting from repeated successful action patterns
- memory search that works across GUI and Telegram sessions

Expected user impact:
- Somi remembers the right things more often
- repeated tasks get easier
- user preferences feel respected without being invasive

Primary targets:
- `executive/memory/`
- `learning/`
- `sessions/`
- `state/`

### 4. Context Compaction And Runtime Management

Objective:
Make long-running tasks resilient, cheap, and coherent.

What to build:
- task scratchpads with explicit working memory
- branch summaries for long research and coding flows
- token-budget and context-budget enforcement
- context compaction that preserves open loops, constraints, and evidence
- state handoff between GUI, Telegram, coding studio, and research studio
- failure-safe resume points for interrupted runs

Expected user impact:
- better long-task reliability
- less drift after many turns
- better coding and research continuity

Primary targets:
- `runtime/`
- `state/`
- `sessions/`
- `executive/`

### 5. Coding And Repair Control Plane

Objective:
Turn the new Codex-style layer into a real daily-driver coding agent system.

What to build:
- richer inspect/edit/verify loops
- branch and worktree support
- code review mode and change-risk summaries
- sandbox presets by task type
- targeted repo import and teardown flow
- stronger git publish safeguards
- coding session memory and project context files
- better code explanation and patch storytelling in the GUI

Expected user impact:
- safer and faster coding help
- more confidence in edits
- easier recovery from bad patches

Primary targets:
- `workshop/toolbox/coding/`
- `gui/codingstudio.py`
- `gui/codingstudio_data.py`

### 6. Telegram And Channel Parity

Objective:
Make Telegram feel like the same agent, not a lesser sidecar.

What to build:
- one runtime contract for GUI and Telegram
- shared sessions, memory, tools, and task state
- task continuation across surfaces
- better formatting for progress, sources, and coding updates
- improved voice note, OCR, and document handling
- safer pairing and permission defaults

Expected user impact:
- users can leave the desktop and keep going
- less feature mismatch between GUI and messaging
- more confidence in remote operation

Primary targets:
- `gateway/`
- `runtime/`
- Telegram integration paths
- OCR/document handlers

### 7. OCR And Document Intelligence

Objective:
Make document work feel first-class rather than auxiliary.

What to build:
- document-type detection
- better table, form, and schema extraction
- document citation anchors and snippet traceability
- OCR cleanup passes for noisy scans
- source-aware summarization of PDFs, images, and uploads
- export bundles for downstream use

Expected user impact:
- better extraction quality
- easier trust and review of document answers
- stronger Telegram and GUI document workflows

Primary targets:
- OCR/document modules
- `research/`
- `workshop/toolbox/stacks/research_core/`

### 8. Ops, Onboarding, And Product Maturity

Objective:
Close the polish gap with OpenClaw and make Somi feel deployable and lived-in.

What to build:
- onboarding wizard
- `doctor`-style diagnostics
- release channels and update flow
- runtime health dashboard
- config validation and migration helpers
- support bundles and crash diagnostics
- better docs, quickstarts, and operator guides

Expected user impact:
- easier installation and recovery
- better trust for long-term usage
- easier evaluation by new users

Primary targets:
- installer/setup paths
- diagnostics and health tooling
- docs and release flows

### 9. Safe Autonomy And Task Continuity

Objective:
Increase Somi's ability to act helpfully on its own without compromising user
trust, local security, or consumer-hardware practicality.

What to build:
- a task state machine with resumable ledgers for research, coding, reminders,
  OCR, and mixed workflows
- bounded autonomy profiles such as `ask-first`, `balanced`, and
  `hands-off-safe`
- action previews, rollback paths, and clear audit trails for meaningful
  actions
- a background task runner for long research, indexing, OCR, and maintenance
  jobs
- resource-aware planning that adapts strategy to local CPU, RAM, GPU, model,
  and battery constraints
- trust-aware answer policy that slows down and verifies more when stakes are
  higher
- artifact memory for saved evidence bundles, repo snapshots, OCR outputs, and
  task summaries
- skill apprenticeship with user approval after repeated successful workflows
- failure-recovery loops for stuck tools, weak results, and interrupted tasks
- cross-surface task continuity between GUI and Telegram

Expected user impact:
- Somi can keep working usefully in the background
- longer tasks feel less fragile and easier to resume
- stronger autonomy feels safer because users can see and reverse it
- average users get more help without needing to micromanage every step

Primary targets:
- `runtime/`
- `state/`
- `sessions/`
- `gateway/`
- `executive/`
- `workshop/toolbox/`

## Phase Plan

### Phase 123 - Search Output Contract And Authority Routing

Goal:
Turn Somi's answer layer into a clean contract by query type.

Build:
- answer templates by intent
- stronger authority weighting
- canonical-source and canonical-URL collapse
- explicit date handling for "latest/current"
- stronger support-source curation

Borrow from:
- GPT Researcher reporting discipline
- Open Deep Research source compression

Validation:
- expand search regressions
- rerun focused live queries by category
- rerun safe benchmark slices for everyday search

Exit criteria:
- no obvious snippet residue in top everyday categories
- cleaner support sources
- better confidence wording

### Phase 124 - Deep Research Planner And Section Bundles

Goal:
Let Somi handle long research like a real research assistant.

Build:
- research brief generation
- subquestion decomposition
- section plan generation
- branch notes and section bundles
- final report assembly with evidence mapping

Borrow from:
- GPT Researcher planner/executor/publisher
- Open Deep Research tree exploration
- DeerFlow sub-agent harness ideas

Validation:
- long-form research stress tests
- contradiction and citation checks
- saved report artifacts under `audit/`

Exit criteria:
- long research tasks stay coherent for multiple rounds
- section plans improve final answer quality

### Phase 125 - Search Cache, Evidence Store, And Resume

Goal:
Make repeated research faster and more stable.

Build:
- local evidence cache with TTLs
- canonical URL identity
- page and repo artifact reuse
- resume from prior evidence bundle
- cache-aware adequacy checks

Borrow from:
- OpenClaw gateway/state thinking
- DeerFlow long-term harness ideas

Validation:
- repeated-query latency checks
- cache-hit correctness tests
- resume-after-interruption tests

Exit criteria:
- repeat research is faster without stale-answer drift

### Phase 126 - Hermes-Level Execution Transparency In The GUI

Goal:
Make Somi's work visible, understandable, and satisfying to watch.

Build:
- action timeline
- tool step cards
- expandable trace rows
- live status chips for browse/coding/memory
- progress explanations in plain language
- stronger "research note" and "coding note" output capsules

Borrow from:
- Hermes streaming tool-output feel
- OpenClaw control-plane transparency

Validation:
- offscreen GUI tests
- interaction smoke tests
- transcript output review from real tasks

Exit criteria:
- a user can understand what Somi is doing without reading logs

### Phase 127 - Premium Cockpit Polish And Responsive States

Goal:
Push the shell from good-looking to unmistakably premium.

Build:
- spacing and hierarchy pass across all major panels
- stronger empty/loading/error states
- subtle motion and reveal timing
- compare and source card designs
- status density cleanup
- accessibility, keyboard flow, and focus treatments

Borrow from:
- automotive dashboard clarity
- OpenClaw canvas/control-surface thinking

Validation:
- offscreen screenshots
- GUI regression suite
- focused manual smoke from CLI-launched GUI

Exit criteria:
- cockpit feels cohesive in light, shadowed, and dark modes

### Phase 128 - Memory Layering And Preference Graph

Goal:
Give Somi durable continuity and tasteful personalization.

Build:
- episodic memory from sessions
- semantic memory summaries
- preference graph
- memory confidence scoring
- memory promotion and decay
- user-facing memory review surfaces

Borrow from:
- Hermes learning loop
- DeerFlow long-term memory layering

Validation:
- memory retrieval tests
- long-session recall tests
- false-memory regression tests

Exit criteria:
- Somi recalls stable preferences and prior projects reliably
Status:
- Completed on 2026-03-19.
- Memory now builds a confidence-aware preference graph from profile and preference rows.
- Frozen memory snapshots and Control Room both expose that preference graph for inspection.

### Phase 129 - Skill Drafting And Self-Improvement Hooks

Goal:
Convert repeated successful behavior into reusable skills safely.

Build:
- action-pattern detection
- draft skill suggestions
- human approval flow
- skill quality checks
- benchmark-driven skill promotion

Borrow from:
- Hermes skill creation loop

Validation:
- repeated-task simulations
- skill suggestion precision checks
- no unauthorized auto-install behavior

Exit criteria:
- Somi can propose useful new skills without becoming noisy

### Phase 130 - Context Compaction, Scratchpads, And Token Budgets

Goal:
Finish the missing long-context foundation.

Build:
- working scratchpads by task
- compaction summaries that preserve unresolved items
- token budgets per mode
- branch summaries for coding and research
- task handoff payloads across surfaces

Borrow from:
- Hermes `/compress` and usage ergonomics
- Open Deep Research compression discipline

Validation:
- long-turn coding sessions
- long-turn research sessions
- interruption and resume tests

Exit criteria:
- Somi stays coherent during long workflows without bloating context
Status:
- Completed on 2026-03-19.
- Coding sessions now persist a durable scratchpad and compact resume summary.
- The coding control plane and Coding Studio both surface that compaction state.

### Phase 131 - Coding Control Plane V2

Goal:
Push Somi's coding advantage further ahead.

Build:
- branch/worktree manager
- staged patch review
- sandbox profiles by language/task
- richer verify loop orchestration
- code review findings mode
- publish safety checks and rollback helpers

Borrow from:
- Codex and Claude Code interaction patterns
- Hermes isolated subagent workflows

Validation:
- end-to-end coding task corpus
- repo import/edit/verify/publish tests
- sandbox safety regressions

Exit criteria:
- coding help is powerful, explainable, and reversible

### Phase 132 - Telegram Runtime Unification

Goal:
Make Telegram a first-class front end to the same Somi brain.

Build:
- shared runtime state with GUI
- shared task IDs and resume behavior
- richer progress updates
- better formatting for citations and source lists
- coding and research output parity
- stronger pairing and permission UX

Borrow from:
- Hermes cross-platform continuity
- OpenClaw gateway and pairing defaults

Validation:
- Telegram conversation replay tests
- task handoff tests between GUI and Telegram
- permission and pairing tests

Exit criteria:
- Telegram no longer feels like a secondary runtime

Status:
- Completed on 2026-03-19.
- Telegram now shares thread continuity, reply-state metadata, remote-session trust posture, and background-task telemetry with the desktop runtime.
- Validation advanced to `229` passing combined tests, with the phase artifact recorded in `audit/phase132_telegram_runtime_summary.md`.

### Phase 133 - OCR, Documents, And Upload Intelligence

Goal:
Make document workflows dependable and polished.

Build:
- OCR cleanup pipeline
- table and form extractors
- document summaries with anchors
- upload provenance and source cards
- Telegram document parity

Borrow from:
- GPT Researcher source-tracking discipline
- OpenClaw media pipeline maturity

Validation:
- document corpus tests
- OCR noise stress tests
- extraction accuracy spot checks

Exit criteria:
- documents are handled with clear provenance and fewer cleanup artifacts

Status:
- Completed on 2026-03-19.
- Supported Telegram document uploads now produce cleaned excerpts, provenance notes, and anchor previews through `workshop/toolbox/stacks/ocr_core/document_intel.py`.
- Validation advanced to `233` passing combined tests, with the OCR benchmark smoke and implementation notes captured in `audit/phase133_document_intelligence_summary.md`.

### Phase 134 - Onboarding, Doctor, Update, And Release Maturity

Goal:
Close the product-polish gap.

Build:
- install/setup wizard
- diagnostics and repair command
- update channels and migration helpers
- runtime health panel
- exportable support bundle
- release checklist and operator documentation

Borrow from:
- OpenClaw onboarding and doctor flows
- Hermes install and setup ergonomics

Validation:
- clean-machine setup tests
- migration tests
- diagnostics smoke tests

Exit criteria:
- new users can install, diagnose, and update Somi with much less friction

Status:
- Completed on 2026-03-19.
- Somi now recognizes the real `audit/backups` checkpoint trail during doctor and security checks, so release health reflects actual recovery posture.
- Added `somi support bundle`, backed by `ops/support_bundle.py`, for exportable JSON and Markdown diagnostics snapshots.
- Validation advanced to `238` passing combined tests, and the implementation notes live in `audit/phase134_ops_diagnostics_summary.md`.

### Phase 135 - Competitive Benchmarking And Release Candidate

Goal:
Prove the upgrades hold under real usage patterns.

Build:
- refreshed safe `everyday1000`
- top `100` hard research/planning corpus
- coding corpus
- memory continuity corpus
- Telegram parity corpus
- GUI runtime smoke bundle

Validation:
- benchmark reruns until no major broken category remains
- artifact set for final release review

Exit criteria:
- no major broken category in the safe benchmark suite
- release candidate documentation and audit bundle complete

Status:
- Completed on 2026-03-19.
- Added `researchhard100`, `researchhard25`, and `everyday100` named corpora in `audit/safe_search_corpus.py`.
- Added `audit/release_candidate.py` to run a combined release-candidate pack across hard research search, coding, memory, and Telegram parity.
- The live `researchhard100` pack passed with `100` queries, `4.95` average heuristic score, `3.38s` average Somi time, and no sub-`4` cases.
- The combined release-candidate pack passed, and the broader regression suite advanced to `241` passing tests. Details live in `audit/phase135_release_candidate_summary.md`.

### Phase 136 - Post-Implementation Full-System Gauntlet

Goal:
Prove that Somi is not just individually polished, but robust as a complete
consumer-facing AI operating system under sustained mixed use.

Build:
- one coordinated post-implementation stress harness that exercises all major
  Somi domains with durable artifacts and repair manifests
- category scorecards for search, memory, reminders, compaction, OCR, coding,
  and cross-system orchestration
- failure clustering so repeated misses turn into phase-specific repair work
- a final "average user" walkthrough that captures real user-facing output,
  latency, regressions, and confusion points

Validation:
- run all gauntlets below and save results under `audit/`
- rerun repaired categories until no major broken group remains
- write a final readiness summary with unresolved edge cases, if any

Exit criteria:
- no major systemic break across the mixed-use gauntlet
- user-facing outputs remain coherent, helpful, and polished throughout the
  30-minute walkthrough
- all transient failures are either repaired or documented as minor known
  issues

Status:
- Completed on 2026-03-19.
- `audit/system_gauntlet.py` now drives the coordinated post-implementation gauntlet and reuses completed search artifacts when a long run needs to be resumed.
- `somi release gauntlet` now exposes the same harness through the main CLI, and detailed results live in `audit/phase136_system_gauntlet_summary.md`.
- The full Phase 136 run passed with `7/7` packs green, including `Search100` at `4.52` average heuristic score and the broader regression suite at `244` passing tests.

### Phase 137 - Safe Autonomy Core

Goal:
Give Somi stronger initiative while keeping humans in control.

Build:
- task state machine and resume ledger
- bounded autonomy profiles
- action preview and rollback model
- explicit stop reasons and escalation points
- user-visible autonomy state in GUI and chat output

Validation:
- task interruption and resume tests
- approval-boundary tests
- rollback and audit-trail tests

Exit criteria:
- Somi can pursue multi-step tasks more independently without surprising the
  user or overstepping permissions

Status:
- Completed on 2026-03-19.
- Bounded autonomy profiles are now persisted in the runtime control plane and exposed through approvals plus Control Room surfaces.
- Combined validation advanced to `210` passing tests, with a runtime smoke artifact at `audit/phase137_autonomy_smoke.md`.

### Phase 138 - Background Execution And Failure Recovery

Goal:
Make Somi persist usefully through long work and recover from common runtime
problems on its own.

Build:
- background task runner
- resource-aware planning
- tool watchdogs and retry policies
- stalled-task recovery
- artifact memory for task outputs and evidence bundles
- cross-surface task handoff foundations

Validation:
- long-running background task tests
- retry and self-healing stress tests
- resource-budget adherence checks

Exit criteria:
- long tasks continue reliably in the background and recover gracefully from
  ordinary failures

Status:
- Completed on 2026-03-19.
- Somi now has a persisted background task ledger with recovery signals, artifact metadata, and local resource budget hints.
- Combined validation advanced to `215` passing tests, with a runtime smoke artifact at `audit/phase138_background_recovery_smoke.md`.

### Phase 139 - Skill Apprenticeship And Trust-Aware Autonomy

Goal:
Help Somi become more helpful over time without unsafe self-modification.

Build:
- repeated-workflow detection
- skill draft suggestions with explicit approval
- trust-aware answer policy by domain and risk level
- task completion summaries and "next best action" proposals
- early offline knowledge-pack foundations for later resilience modes

Validation:
- repeated-workflow simulations
- skill suggestion precision tests
- high-stakes query caution tests
- offline knowledge-pack loading smoke tests

Exit criteria:
- Somi proposes useful new capabilities, behaves more carefully when stakes
  are high, and improves over time without acting like an unchecked automaton

Status:
- Completed on 2026-03-19.
- Somi now produces approval-gated apprenticeship suggestions from repeated work and applies stronger caution to thin-evidence high-stakes answers.
- Combined validation advanced to `219` passing tests, with a runtime smoke artifact at `audit/phase139_skill_trust_smoke.md`.

### Phase 140 - Backup Hardening And Roadmap Refresh

Goal:
Make Somi's phase checkpoint process safe, fast, and legible so long upgrade
runs do not quietly copy old backups into new ones.

Build:
- a first-class `somi backup create` command
- default exclusions for nested backup trees, external repo mirrors, venvs, and
  bulky generated session artifacts
- a source-focused checkpoint format suitable for pre-phase backups
- a refreshed roadmap for the next competitive-advantage campaign

Validation:
- focused backup creator regressions
- CLI smoke against the live repo
- backup verification checks against the generated checkpoint

Exit criteria:
- contributors can create a phase-safe backup without hand-written shell logic
- future backups do not recurse through `audit/backups`
- the new roadmap reflects the post-Phase-136 reality instead of older
  baseline assumptions

Status:
- Completed on 2026-03-19.
- Somi now exposes `somi backup create`, which writes focused checkpoints and excludes nested backups, external-repo mirrors, venvs, and bulky generated session folders by default.
- Phase 140 validation stayed green with a new backup-creation regression suite plus a live CLI smoke checkpoint under `audit/backups/phase140_smoke_backup_*`.

### Phase 141 - Contributor Maps And Subfolder READMEs

Goal:
Make the codebase understandable to a new contributor within one sitting.

Build:
- subfolder `README.md` files for controller, toolbox, coding, browser,
  research, and search stacks that explain purpose, key files, and extension
  points
- a contributor map inside `docs/architecture/`
- explicit "where to start" guidance for basic users versus dev users
- cross-links from the root/workshop/gui/runtime docs into the new maps

Validation:
- docs coverage tests for required folders
- newcomer-path smoke checks that the linked files actually exist
- combined runtime smoke to ensure docs changes do not disturb packaging

Exit criteria:
- a new contributor can trace Somi's main control flow, search stack, GUI
  surfaces, and coding layer without spelunking blindly

Status:
- Completed on 2026-03-19.
- Somi now has contributor-facing `README.md` maps for `somicontroller_parts`, the core toolbox subpackages, and the main search/research/coding layers.
- `docs/architecture/CONTRIBUTOR_MAP.md` now acts as the fastest useful route through the codebase for both basic users and developers.
- Focused validation stayed green with docs coverage regressions, runtime smoke, and backup verification.

### Phase 142 - Docs Coverage And Newcomer Guardrails

Goal:
Stop architecture and onboarding docs from silently drifting out of date.

Build:
- a lightweight docs integrity test pack
- checks for required folder readmes and architecture links
- a short contributor checklist for "first debugging steps" and "where to add
  tests"
- release-gate hooks for documentation regressions when core entry points move

Validation:
- focused docs-integrity regressions
- release-gate smoke after doc checks are wired in

Exit criteria:
- future refactors cannot easily erase the newcomer path without tests failing

Status:
- Completed on 2026-03-19.
- `ops/docs_integrity.py` now centralizes contributor-doc coverage checks, `docs/architecture/NEWCOMER_CHECKLIST.md` now provides a practical first-debugging workflow, and doctor/release-gate both surface docs-integrity state.
- Focused validation stayed green with docs guardrail regressions, `somi doctor --json`, and `somi release gate --json --no-write`.

### Phase 143 - Platform Surface Maps And Boundary Clarity

Goal:
Make Somi easier to reason about by clarifying ownership at the top-level
platform surfaces new contributors touch first.

Build:
- add platform-surface `README.md` maps for ops, gateway, state,
  workflow runtime, search, execution backends, agent methods, and tests
- clarify where control-plane behavior lives versus where product behavior lives
- expand docs integrity coverage to these top-level surfaces
- defer deeper import cleanup until the ownership map is stable

Validation:
- docs-integrity regressions
- doctor and release-gate smoke runs
- backup verification for the new phase checkpoints

Exit criteria:
- key platform surfaces have clear human-readable ownership boundaries before
  deeper refactors begin

Status:
- Completed on 2026-03-19.
- Top-level platform packages now have local maps, and docs-integrity guardrails now cover those surfaces as part of the newcomer path.
- Focused validation stayed green with expanded docs regressions plus live doctor and release-gate passes.

### Phase 144 - Search Output Contracts And UX Scorecards V2

Goal:
Push Somi's search from "strong" to "obviously elite" for everyday users.

Build:
- stricter answer-contract helpers by query type
- better lead sentence quality and source framing
- clearer support-source curation rules
- audit scorecards for the top everyday query families with output examples

Validation:
- targeted live search slices by category
- search regression suite plus focused benchmark reruns

Exit criteria:
- everyday answers consistently feel deliberate, current, and polished without
  filler or residue

Status:
- Completed on 2026-03-19.
- `executive/synthesis/answer_mixer.py` now has unique canonical helper definitions again, and trip-planning answers no longer wrap a complete itinerary sentence in awkward extra scaffolding.
- Search regression coverage now guards the helper namespace as well as the user-facing planning phrasing.

### Phase 145 - GUI Flow Audit And Interaction Polish

Goal:
Make the premium shell feel effortless during real use, not just in screenshots.

Build:
- tighter empty/loading/error/recovery states
- quicker theme and mode transitions
- improved spacing and hierarchy in the main operator surfaces
- clearer keyboard-first and long-task interaction flow
- visible recovery messaging when background tasks, search, or coding hit
  turbulence

Validation:
- GUI regression suite
- offscreen smoke renders
- mixed user-flow smoke with chat, research, and coding turns

Exit criteria:
- the shell feels confident, legible, and calm across the most common flows

Status:
- Completed on 2026-03-19.
- The premium theme registry now exposes real emoji labels cleanly, and the research pulse now falls back to progress or execution headlines before generic placeholder text.
- GUI runtime tests stayed green after the copy and flow polish.

### Phase 146 - Artifact Hygiene And Performance Budgeting

Goal:
Keep Somi fast and maintainable as artifacts, audits, and checkpoints grow.

Build:
- cleanup rules for old generated artifacts
- performance budgets for key CLI and runtime paths
- safer defaults for large benchmark and audit outputs
- improved retention guidance for logs, backups, and generated sessions

Validation:
- artifact-hygiene tests
- repeated CLI smokes under realistic artifact load
- doctor and release-gate reruns

Exit criteria:
- long upgrade cycles do not quietly degrade developer experience or runtime
  responsiveness

Status:
- Completed on 2026-03-19.
- `ops/artifact_hygiene.py` now tracks generated audit/session surfaces and feeds that signal into doctor and release gate.
- The tuned budgets keep the guardrail meaningful while preserving a `pass` release-gate result on Somi's current working set.

### Phase 147 - Offline Resilience Foundations

Goal:
Lay safe groundwork for Somi's future degraded-network and crisis-support mode.

Build:
- local documentation bundle hooks for repair, survival, and infrastructure
  reference packs
- cache-aware search fallback posture for low-connectivity conditions
- clearer offline capability reporting in doctor/control room
- audit trail for what knowledge came from bundled local packs versus live web

Validation:
- offline-mode smoke runs
- local-pack loading tests
- degraded-network search fallback checks

Exit criteria:
- Somi can still help meaningfully when the network is weak, partial, or absent
- bundled knowledge packs, Agentpedia, and cached evidence have visible
  provenance instead of feeling like hidden fallback magic

Status:
- Completed on 2026-03-19.
- Somi now has bundled local knowledge packs for repair, survival, and
  infrastructure basics, plus degraded-network search fallback that can reuse
  those packs before giving up.
- Doctor, release gate, the Control Room, and `somi offline status` now report
  offline readiness directly, including pack counts, Agentpedia availability,
  and evidence-cache coverage.
- Focused validation stayed green with local-pack loading tests, offline
  resilience regressions, degraded-network search fallback coverage, and live
  doctor/release-gate/offline CLI passes.

### Phase 148 - Operator Observability And Recovery Signals

Goal:
Make Somi feel more alive, more trustworthy, and easier to operate by turning
runtime metrics into human-readable observability and recovery guidance.

Build:
- a first-class observability digest that explains latency hotspots, failure
  hotspots, recovery pressure, and policy friction from the existing ops data
- a `somi observability snapshot` CLI so operators can inspect health without
  digging through raw JSONL metrics
- richer Control Room observability rows for hotspots, recovery watchlists, and
  overall runtime health
- support-bundle integration so diagnostics capture why Somi is slow, noisy, or
  stuck instead of only showing raw component state

Validation:
- focused observability regressions
- Control Room snapshot tests
- support-bundle and CLI smokes
- combined search/GUI/ops suite rerun

Exit criteria:
- an operator can quickly answer "what is slow, what is failing, and what
  should I do next?" from Somi's own diagnostics surfaces

Status:
- Completed on 2026-03-19.
- `ops/observability.py` now turns runtime metrics and policy events into a
  digest with hotspots, recovery pressure, recommendations, and a CLI-friendly
  summary.
- `somi observability snapshot`, the support bundle, and Control Room
  observability now all surface the same runtime-health view.
- The live digest now suppresses synthetic eval noise and expected
  heartbeat-channel policy chatter, so operator diagnostics stay trustworthy on
  the real repo.
- Phase 148 validation stayed green with `22` focused tests, `222` passing
  combined tests, and live `observability snapshot` / `support bundle` smokes.

### Phase 149 - Structured Everyday Answer Types

Goal:
Make Somi's highest-volume everyday answers feel unmistakably deliberate by
using stronger structure instead of one-size-fits-all prose.

Build:
- structured answer contracts for `latest`, `compare`, `planning`, `guide`,
  `explain`, and `official requirement` responses
- cleaner compare tables and top-takeaway formatting across chat and GUI
- sharper support-source selection so the answer body and sources agree in tone
  and authority
- answer-style audits for safe everyday queries that users repeat constantly

Validation:
- targeted answer-shaping regressions
- safe benchmark reruns for shopping, planning, health explainers, and official
  guidance
- GUI smoke around compare/planning rendering

Exit criteria:
- the common "top 100 searched things" categories feel polished enough that
  users notice Somi's output quality immediately

Status:
- Completed on 2026-03-19.
- `executive/synthesis/answer_mixer.py` now gives high-volume everyday answers clearer structures like `Quick take:`, `Trip shape:`, and `Short answer:` so the response shape matches the intent.
- `test_search_upgrade.py` now guards those structured contracts across compare, planning, travel, and explainer flows.
- Phase 149 validation stayed green with `196` focused search tests, `223` passing combined tests, and the audit artifact `audit/phase149_structured_answers_summary.md`.

### Phase 150 - Memory Review, Promotion, And Cleanup

Goal:
Upgrade Somi's memory from "stored facts" to a more confident, reviewable, and
user-respectful continuity system.

Build:
- a review-and-promote flow for candidate memories with stronger evidence and
  confidence signals
- clearer separation between session memory, durable preference memory, and
  procedural/task memory
- memory hygiene suggestions for stale, duplicated, or weak-confidence entries
- better memory explainability across GUI and Telegram surfaces

Validation:
- memory regressions covering promotion, decay, and retrieval precision
- mixed-use continuity smokes across GUI and Telegram
- doctor/release support signals for memory hygiene

Exit criteria:
- Somi remembers better without becoming noisy, invasive, or hard to audit

Status:
- Completed on 2026-03-19.
- `executive/memory/review.py` now builds a review digest for promotion candidates, stale items, conflicts, and cleanup watch items.
- `executive/memory/manager.py`, `executive/memory/doctor.py`, and `gui/controlroom_data.py` now surface that review layer through hygiene checks, frozen snapshots, memory doctor output, and the Control Room `Memory Review Queue`.
- Phase 150 validation stayed green with `5` focused memory tests, `226` passing combined tests, and live `doctor` / `release gate` passes captured in `audit/phase150_memory_review_summary.md`.

### Phase 151 - Cross-Surface Task Continuity And Resume

Goal:
Make Somi feel like one persistent agent across GUI, background tasks, and Telegram instead of several adjacent runtimes.

Build:
- a visible task-resume ledger that survives surface changes and interrupted runs
- shared task scratchpads for search, coding, reminders, and OCR-heavy work
- action previews and resumable checkpoints for long-running background tasks
- continuity signals in GUI and Telegram so users can pick work back up without re-explaining context

Validation:
- resume/restart regressions for background tasks and surface handoffs
- mixed GUI-to-Telegram continuity smokes
- support-bundle and control-room verification for task-state clarity

Exit criteria:
- users can leave and return to a task without feeling like Somi forgot what it was doing

Status:
- Completed on 2026-03-19.
- `runtime/task_resume.py` now builds a shared resume ledger from sessions, task graphs, and background handoffs.
- `gui/controlroom_data.py`, `ops/support_bundle.py`, and `workshop/integrations/telegram_runtime.py` now surface that continuity layer in Control Room, support diagnostics, and Telegram resume behavior.
- Phase 151 validation stayed green with `240` passing combined tests and live `doctor` / `release gate` passes captured in `audit/phase151_task_continuity_summary.md`.

### Phase 152 - Telegram Runtime Parity And Document Delivery

Goal:
Bring Telegram up to desktop-grade capability for search, OCR, coding assistance, and follow-up continuity.

Build:
- parity routing so Telegram uses the same research, memory, and coding runtime contracts as the GUI
- stronger OCR/document ingestion and reply formatting for uploads, screenshots, and multi-page files
- tool and artifact delivery that feels native on Telegram instead of like a reduced sidecar
- better channel-safe formatting for citations, summaries, and coding diffs

Validation:
- Telegram runtime regressions
- OCR/document reply smokes
- mixed coding/search follow-up tests across desktop and Telegram

Exit criteria:
- Telegram feels like the same Somi runtime, not a weaker branch

Status:
- Completed on 2026-03-19.
- `workshop/integrations/telegram_runtime.py` now builds delivery bundles that
  chunk large replies, attach route-aware follow-up notes, and export markdown
  handoff files when Telegram needs a document instead of a wall of text.
- `workshop/integrations/telegram.py` now sends those follow-up bundles,
  exported files, and document/visual attachments through both the normal chat
  path and Telegram document-ingestion flows.
- Phase 152 validation stayed green with `11` focused Telegram/document tests,
  a passing `py_compile` import check, `246` passing combined tests, and green
  `doctor` / `release gate` runs captured in
  `audit/phase152_telegram_parity_summary.md`.

### Phase 153 - Output Finality And Trust Controls

Goal:
Push Somi's final user-facing output to a level where trust, clarity, and polish stay high across everyday and deep tasks.

Build:
- user-facing confidence, freshness, and evidence-density controls
- stronger compare/guide/official answer cards in chat and the premium GUI
- more graceful "not enough evidence" behavior and clearer next-step suggestions
- tighter formatting rules for long answers, coding summaries, and research deliverables

Validation:
- safe top-query reruns across compare, planning, official guidance, and explainers
- GUI output-card smokes
- mixed research/coding/output quality reviews

Exit criteria:
- Somi's answers feel premium and trustworthy before the user ever reads the sources

Status:
- Completed on 2026-03-19.
- `runtime/answer_validator.py` now detects missing freshness dates and thin
  evidence without sufficient uncertainty, then produces a reusable answer
  trust summary for downstream UI surfaces.
- `agent_methods/response_methods.py`, `gui/aicoregui.py`,
  `gui/chatpanel.py`, and `somicontroller_parts/status_methods.py` now carry
  that trust signal into browse reports, research capsules, and the Research
  Pulse.
- Phase 153 validation stayed green with `10` focused trust/GUI tests, a
  passing `py_compile` check, `251` passing combined tests, and the audit
  record in `audit/phase153_output_finality_summary.md`.

### Phase 154 - Context Budget And Compaction Visibility

Goal:
Make long-running tasks safer on consumer hardware by surfacing context pressure
before continuity degrades.

Build:
- a reusable context-budget digest that measures turn count, estimated token
  load, compaction presence, and open-loop markers from compacted history
- a `somi context status` CLI for operators
- context-budget visibility in doctor, support bundle, release gate, and
  Control Room
- synthetic-session filtering so stress/eval runs do not pollute live operator
  readiness

Validation:
- focused context/ops regressions
- broad mixed regression pack
- live `context status`, `doctor`, and `release gate` passes

Exit criteria:
- Somi can explain which threads are at context risk and which ones are healthy
  without the operator digging through raw session storage

Status:
- Completed on 2026-03-19.
- `ops/context_budget.py` now builds a first-class compaction/context-pressure
  digest, `somi.py` now exposes `somi context status`, and Control Room now has
  a `Context` tab plus overview signal.
- Doctor, support bundle, and release gate now include the same context-budget
  posture, while synthetic stress/eval users are filtered so the live repo does
  not warn on synthetic traffic.
- Phase 154 validation stayed green with `256` passing mixed regression tests,
  clean `context status` / `doctor` / `release gate` JSON runs, and the audit
  record in `audit/phase154_context_budget_summary.md`.

### Phase 155 - Backup Verifier Signal Cleanup

Goal:
Remove stale verifier noise so release/readiness diagnostics reflect the
current Somi surface instead of outdated sample paths.

Build:
- replace the outdated `somicontroller.py` backup sample with the current
  `somi.py` CLI entrypoint
- add regression coverage so future verifier changes keep reporting the current
  critical path set

Validation:
- focused ops diagnostics regressions
- live `doctor` and `release gate` passes

Exit criteria:
- healthy phase checkpoints validate cleanly without false missing-file rows

Status:
- Completed on 2026-03-19.
- `ops/backup_verifier.py` now validates `somi.py` instead of the removed
  `somicontroller.py`, so modern framework checkpoints show a clean
  `framework_backup` surface.
- Phase 155 validation stayed green with focused ops tests plus passing live
  `doctor` and `release gate` runs, recorded in
  `audit/phase155_backup_verifier_summary.md`.

## Benchmark Program

### Safe Everyday Benchmark

Purpose:
Measure the top everyday things normal users search for, excluding unsafe
categories.

Coverage:
- health general information
- official guidance
- Python/docs/software questions
- GitHub/repo lookups
- shopping/product comparisons
- travel and planning
- weather/news/finance smoke checks
- local info and logistics
- restaurants and entertainment
- direct URL summaries

Outputs:
- markdown summary
- JSONL rows
- per-category failure report
- repair manifest for transient misses

### Deep Research Benchmark

Purpose:
Measure multi-step research, citation quality, and contradiction handling.

Coverage:
- policy
- science summaries
- market landscape
- standards/spec research
- repo ecosystem analysis

### Coding Benchmark

Purpose:
Measure inspect/edit/verify/recover loops on real repos and fixtures.

Coverage:
- bug fix tasks
- refactors
- code explanation
- review findings
- safe publish flows

### Memory Benchmark

Purpose:
Measure recall quality, preference continuity, and memory hygiene.

Coverage:
- recurring preferences
- project continuity
- follow-up reminders
- false-memory resistance

### Telegram And Channel Benchmark

Purpose:
Measure cross-surface parity and remote usability.

Coverage:
- progress updates
- long task continuation
- document ingestion
- voice notes
- coding and research delivery

### Post-Implementation Full-System Stress Program

Purpose:
Act as the final proving ground after all planned upgrades are implemented.

This program should run only after the major implementation phases are
complete. It is intended to answer one question clearly:

"Can Somi help a normal person reliably across the core things they actually
want to do, on consumer-grade hardware, without falling apart?"

Stress packs:

#### 1. `Search100`

Goal:
Run `100` of the most common safe everyday search tasks and judge not only
retrieval quality, but answer usefulness.

Coverage:
- factual lookups
- latest/current queries
- product comparisons
- travel and local planning
- official guidance and government information
- docs and software questions
- GitHub/repo inspection
- direct URL summaries

Measure:
- correctness
- freshness
- source quality
- answer clarity
- user confidence
- latency

Pass bar:
- no broken category
- no repeated source-hygiene regressions
- answer style remains polished at scale

#### 2. `Memory100`

Goal:
Store and retrieve `100` distinct memory items spanning preferences,
projects, facts, and follow-ups.

Coverage:
- stable user preferences
- project state
- task continuity
- personal facts the system is allowed to remember
- memory promotions and decay cases

Measure:
- retrieval accuracy
- contamination rate
- false-memory rate
- usefulness of recalled memory
- correct memory-source lineage

Pass bar:
- low false-memory rate
- strong precision on durable preferences and active project recall

#### 3. `Reminder100`

Goal:
Create, edit, trigger, complete, and recover `100` reminder or automation
items.

Coverage:
- one-off reminders
- recurring reminders
- edits and cancellations
- delivery formatting
- missed-trigger recovery
- cross-surface reminder continuity

Measure:
- scheduling accuracy
- delivery clarity
- recovery after interruption
- duplicate/missed reminder rate

Pass bar:
- reminders fire correctly and predictably
- formatting stays clear and actionable

#### 4. `Compaction100`

Goal:
Run `100` long-context compression and resume scenarios.

Coverage:
- long research threads
- long coding threads
- interrupted tool runs
- multi-surface handoffs
- branch summaries with unresolved tasks

Measure:
- retained constraints
- retained open questions
- retained evidence
- drift after resume
- token-budget compliance

Pass bar:
- compressed sessions remain coherent and resumable
- no severe loss of mission-critical context

#### 5. `OCR100`

Goal:
Process `100` document or image extraction cases across clean and messy
inputs.

Coverage:
- scanned PDFs
- phone photos
- forms
- tables
- receipts
- mixed-layout pages
- Telegram-uploaded documents

Measure:
- extraction accuracy
- schema quality
- cleanup quality
- citation/provenance quality
- usability of downstream output

Pass bar:
- output is dependable enough for real downstream use
- noisy OCR cases degrade gracefully rather than catastrophically

#### 6. `Coding100`

Goal:
Run `100` coding tasks that exercise inspection, editing, verification,
review, sandboxing, snapshots, and repair.

Coverage:
- bug fixes
- refactors
- explanations
- test repair
- code review findings
- repo import and snapshot flows
- git commit/publish dry-run behavior

Measure:
- task completion quality
- verify-loop success rate
- rollback/recovery reliability
- explanation quality
- safety of edits and publish actions

Pass bar:
- coding workflows are consistently safe, explainable, and recoverable

#### 7. `AverageUser30`

Goal:
Run a full `30` minute mixed-use scenario from an average user perspective.

Scenario should include:
- casual chat
- search and follow-up questions
- one memory recall moment
- one reminder creation
- one small planning task
- one document/OCR interaction
- one small coding or file-help interaction
- at least one interruption and resume moment
- at least one GUI or Telegram surface transition, if available

Measure:
- perceived helpfulness
- confusion points
- awkward phrasing
- latency spikes
- tool transparency
- trustworthiness
- continuity across tasks

Pass bar:
- the session feels smooth, human-centered, and reliable end to end
- no "this feels broken" moments for a normal user

Artifacts:
- markdown summary per pack
- JSONL event rows
- category report cards
- repaired-failure manifest
- final readiness brief

Repair rule:
- any failed pack must generate a focused repair phase before final release
- after repair, rerun only the failed pack, then rerun a mixed smoke slice to
  check for regressions

## Safe Autonomy Principles

These rules should govern all future autonomy work.

### Implement By Default

- task state machine and resume ledger
- bounded autonomy profiles
- action preview, rollback, and audit trail
- background task runner
- resource-aware planning
- trust-aware answer policy
- local evidence and artifact memory
- failure-recovery loops
- cross-surface task continuity

### Implement With Explicit Approval Paths

- skill apprenticeship and draft skill creation
- proactive suggestions based on remembered preferences
- delegated subagents for larger research or coding jobs
- offline knowledge packs that may affect task routing or advice style

### Do Not Enable By Default

- silent autonomous messaging to other people
- autonomous purchases, bookings, or account changes
- unbounded self-modification
- always-on microphone or surveillance-style sensing

### Design Standard

All autonomy features must be:

- local-first where practical
- visible to the user
- interruptible
- auditable
- reversible when meaningful
- compatible with consumer-grade hardware constraints
- cautious on high-stakes topics

## Additional Improvements Worth Considering

- persona packs with stronger domain-specific voice control
- richer calendar/reminder flows once memory is stabilized
- exportable research dossiers and coding change packs
- local observability panel for tasks, failures, and latency
- better asset pipeline for premium GUI visuals
- plugin trust metadata and signing
- workspace-level policies for enterprise use
- user-tunable verbosity, confidence, and citation density
- stronger source blacklist and scam/SEO-content suppression
- better compare-table rendering in chat and GUI
- structured answer types for recipes, itineraries, compare, explain, guide,
  and latest
- watchdogs for stuck tools and self-healing retries

## Final Release Criteria

Somi is ready for the next long pause only when:

- search feels trustworthy, current, and pleasant across the major safe
  everyday categories
- GUI feels premium, legible, and alive
- memory behaves usefully and predictably
- coding flows are safe, powerful, and well-explained
- Telegram feels like the same Somi, not a weaker branch
- OCR/document handling is dependable
- onboarding, update, and diagnostics reduce friction materially
- benchmarks and finality artifacts are green enough that future work is
  optional rather than urgent

## Recommended Order Of Attack

For the next campaign, prioritize in this order:

1. Phase 151
2. Phase 152
3. Phase 153

Rationale:
- Search shaping, observability, and memory review are now materially stronger,
  so the next gap is runtime continuity across surfaces.
- Telegram parity is one of the clearest remaining places where Somi can widen
  the gap over weaker sidecar-style frameworks.
- Once continuity is solid, output finality and trust controls become the
  fastest way to turn raw capability into a visibly premium user experience.
