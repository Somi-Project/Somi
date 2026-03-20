# Somi Competitive Advantage Upgrade Plan

This document is the dedicated roadmap for the next concentrated Somi upgrade
wave. It extends the broader direction in [update.md](C:/somex/update.md) and
turns the remaining competitive gaps into an execution plan.

The goal is not cosmetic progress. The goal is to make Somi the strongest
local-first AI operating framework on consumer hardware, with clear advantages
over Hermes, OpenClaw, and similar agent systems in search, coding, autonomy,
clarity, safety, and long-run resilience.

## Mission

Somi should become:

- the best local-first research and coding assistant on consumer hardware
- the safest high-autonomy assistant for normal users
- the clearest AI workstation for operators, builders, and researchers
- the most adaptable open system for importing outside skills and plugins
- the strongest foundation for future offline and crisis-resilient operation

## Current Position

Somi is already strong in:

- no-key search and research quality
- local coding and repair workflows
- desktop operator experience
- diagnostics, release gates, and regression discipline
- evidence-first answer shaping

Somi still has headroom in:

- deeper adaptive memory
- Telegram and cross-channel runtime parity
- warning-free runtime and cleaner async shutdown
- visible autonomy and action transparency
- coding autonomy and guarded multi-step execution
- plugin and skill interoperability
- newcomer readability across the repo

## Competitive Target

Somi should aim to:

- surpass Hermes in visible task continuity, memory usefulness, and coding depth
- surpass OpenClaw in local-first power, research quality, and guardrailed
  autonomy
- match or exceed both in product polish, plugin adaptability, and user trust

## Non-Negotiable Guardrails

These rules apply to every autonomy, coding, plugin, and channel phase.

- no spending money without explicit human approval
- no purchases, bookings, or subscription changes without explicit human
  approval
- no deleting user files, emails, reminders, or accounts without explicit human
  approval
- no sending external messages or uploads without explicit human approval, unless
  the user has deliberately configured a narrow trusted automation
- no unbounded self-modification
- no silent plugin execution from imported ecosystems
- no high-risk system changes without preview, audit, and rollback
- every important action must be visible, interruptible, and logged

## Design Rules

- build local-first where practical
- optimize for consumer-grade hardware
- preserve capability and adapt resources instead of weakening the framework
- keep long-running tasks resumable
- prefer evidence, provenance, and explicit confidence over smooth bluffing
- keep the user in control for destructive, costly, or socially risky actions
- make advanced power visible without overwhelming new users
- keep docs and architecture discoverable for basic and dev users

## Capability Preservation And Resource Adaptation

Somi should not be artificially weakened at the framework level.

The right model is:

- preserve current and future capability
- scale down gracefully on weak hardware
- scale up aggressively on strong hardware
- gate dangerous side effects at execution time, not cognition time

Practical implications:

- low-end systems should get lighter models, lower background concurrency,
  smaller indexes, and text-first UX
- high-end systems should get larger contexts, richer OCR, stronger coding and
  research loops, and more parallel execution
- the same runtime should support both "survival mode" and "full power mode"
- image analysis, OCR depth, and heavy background work should be user-tunable,
  not framework-disabled by default

This keeps Somi useful now and prevents the architecture from capping its future
role in recovery, education, science support, and civilization rebuilding.

## Distribution Sovereignty

Somi should be architected so that platform or app-store policy pressure does
not define the core system.

Strategic stance:

- keep `Somi Core` self-hosted, direct-download, and app-store-independent
- treat platform compliance as a thin client-edge concern when unavoidable
- avoid central identity or age-verification storage by default
- do not weaken model cognition to satisfy distribution rules
- preserve the same local-first, user-owned core across desktop, LAN, and
  self-hosted deployments

Practical policy:

- direct install, GitHub release, package manager, and container paths should
  remain first-class
- if a store or OS client requires age or policy signals, isolate that logic to
  the affected surface adapter only
- do not let store-facing policy mutate the behavior of the self-hosted core
- do not build Somi around centralized compliance dependencies
- prefer optional compatibility layers over mandatory framework-wide identity
  systems

This is not a plan to evade laws or platform rules. It is a plan to keep Somi's
core architecture independent, resilient, and user-owned.

## Borrow And Adapt Strategy

We should steal good ideas aggressively, but adapt them to Somi's values.

### From Hermes

- highly visible action traces
- strong session continuity and runtime feel
- task execution that feels alive and inspectable
- memory and skill usage as obvious first-class behaviors

### From OpenClaw

- plugin and provider abstraction
- channel and runtime unification
- product polish around control, setup, and operational surfaces
- reusable integration standards

### From DeerFlow, GPT Researcher, and Open Deep Research

- explicit planning and reflection loops
- better decomposition of large tasks
- stronger evidence aggregation and contradiction handling
- clearer long-form research briefs and finality structure

## Workstreams

### A. Memory 2.0

Make memory deeper, more adaptive, and more useful without becoming noisy or
creepy.

Target outcomes:

- better retrieval precision by task type
- stronger preference and workflow memory
- conflict detection and stale-memory demotion
- better compaction survival
- clearer user-facing memory review and trust signals

### B. Unified Runtime And Channel Parity

Make GUI, Telegram, and future channels feel like the same Somi.

Target outcomes:

- shared task IDs, state, approvals, artifacts, and resumability
- Telegram parity for documents, OCR, research, and coding artifacts
- consistent approvals and trust messaging across surfaces
- groundwork for future channel adapters without code sprawl

### C. Coding Superiority

Push Somi's coding layer toward a true Codex-class local workstation.

Target outcomes:

- stronger inspect-edit-verify loops
- better symbol and repo understanding
- safer patching and rollback
- richer code review, change explanation, and risk scoring
- strong GitHub prep and publish workflows with human approval gates

### D. Safe Autonomy

Increase autonomous usefulness without relaxing safety.

Target outcomes:

- bounded autonomy profiles
- resumable task state machine
- background execution with clear stop and escalation rules
- approval policies by action class
- resource-aware planning on weaker machines

### E. Plugin And Skill Federation

Make Somi compatible with outside skill ecosystems instead of isolating itself.

Target outcomes:

- import and adapt markdown skill bundles such as `SKILL.md`
- normalize external plugin metadata into a Somi registry
- support trust tiers, provenance, approval policies, and sandboxing
- reduce duplicated ecosystem work by reusing outside skill investments

### F. UX And Visible Execution

Make Somi feel premium, transparent, and calm.

Target outcomes:

- better action timelines and live task cards
- improved answer presentation for search, coding, and planning
- clearer trust chips, citations, and status signals
- smoother GUI states and fewer confusing transitions

### G. Runtime Stability And Warning Cleanup

Eliminate harmless-but-ugly warnings and long-run rough edges.

Target outcomes:

- quieter async shutdown
- fewer socket and subprocess cleanup warnings
- more deterministic test teardown
- stable stress runs and cleaner logs

### H. Repo Clarity And Newcomer Experience

Make Somi easier to understand, extend, and debug.

Target outcomes:

- subfolder readmes for basic and dev audiences
- refreshed architecture maps
- clearer system boundaries and entrypoints
- easier plugin, coding, memory, and runtime discovery

### I. Distribution Sovereignty And Surface Independence

Keep Somi free from unnecessary platform lock-in and centralized compliance
dependencies.

Target outcomes:

- strong direct-download and self-hosted identity
- thin surface compliance adapters where unavoidable
- no central age or identity store by default
- clearer separation between core cognition and distribution constraints

### J. Civilization Continuity And Recovery

Make Somi a practical continuity framework that remains useful through severe
infrastructure failure, social fragmentation, and long recovery periods.

Target outcomes:

- offline-first survival of core functions
- local knowledge packs for recovery-critical domains
- hardware-aware execution from very low-end to high-end systems
- resumable operation across power and network instability
- safe node-to-node knowledge and task sharing when connectivity returns

## Phase Plan

### Phase 156 - Risk Policy And Autonomy Contract

Goal:
- define one shared policy engine for safe actions across GUI, Telegram, coding,
  plugins, and future channels

Build:
- create a central action-risk taxonomy
- classify actions into read, write, destructive, financial, external-message,
  system-change, and plugin-exec groups
- add approval requirements, preview requirements, and rollback requirements per
  group
- make the policy visible in runtime traces and operator UX

Likely areas:
- `ops/`
- `workflow_runtime/`
- `workshop/toolbox/coding/`
- `workshop/integrations/`
- `gui/`

Validation:
- unit tests for action classification and approval behavior
- CLI and GUI policy smoke tests
- Telegram parity smoke for approval prompts

Exit:
- no destructive or costly action path bypasses the policy layer

### Phase 157 - Adaptive Memory Lanes

Goal:
- split memory into clearer lanes and improve retrieval relevance

Build:
- define lanes for profile, preferences, workflows, project context, evidence,
  reminders, and session summaries
- add freshness, confidence, source lineage, and contradiction markers
- bias retrieval differently for search, coding, reminders, and social chat

Likely areas:
- `executive/memory/`
- `state/`
- `ops/context_budget.py`

Validation:
- targeted memory store and retrieval tests
- stale-memory demotion tests
- contradiction-resolution tests
- compaction survival checks

Exit:
- memory retrieval improves precision without over-injecting stale facts

### Phase 158 - Memory Review, Promotion, And User Control

Goal:
- make memory feel smarter and more trustworthy to users

Build:
- strengthen promotion rules for repeated useful patterns
- add memory review cards and explain why a memory exists
- add hide, downgrade, promote, and forget controls
- add workflow memory for repeated user habits and coding patterns

Likely areas:
- `executive/memory/`
- `gui/controlroom_data.py`
- `somicontroller_parts/`

Validation:
- memory review tests
- GUI control room smoke tests
- repeated-pattern promotion tests

Exit:
- users can inspect and manage memory without confusion

### Phase 159 - Unified Task Envelope Across Surfaces

Goal:
- make one task model power GUI, Telegram, and future channels

Build:
- unify task IDs, artifact references, approval state, progress state, and final
  outputs
- make surface transitions preserve task context cleanly
- keep coding, research, OCR, and reminder flows resumable across surfaces

Likely areas:
- `workflow_runtime/`
- `gateway/`
- `workshop/integrations/`
- `gui/`

Validation:
- desktop to Telegram handoff tests
- interrupted-task resume tests
- multi-surface artifact access tests

Exit:
- Somi feels like one runtime, not separate apps pretending to be one agent

### Phase 160 - Telegram Parity And Artifact Delivery

Goal:
- close the Telegram gap with the desktop shell

Build:
- better artifact cards for research, OCR, and coding results
- parity for approvals, task progress, file summaries, and document extraction
- clearer fallback behavior when UI-rich elements are unavailable
- improve OCR and doc summaries specifically for mobile-originated input

Likely areas:
- `workshop/integrations/`
- `gateway/`
- `ocr/`
- `gui/`

Validation:
- Telegram interaction pack
- OCR and document pack
- coding result delivery pack

Exit:
- Telegram feels like a strong Somi surface, not a weaker satellite

### Phase 161 - Coding Control Plane II

Goal:
- make Somi stronger at multi-step coding tasks and safer under pressure

Build:
- stronger repo map refresh and symbol extraction
- better change planning, change explanation, and patch bundling
- richer verification loops with targeted tests and rollback logic
- risk scoring for edits and dependency changes
- safer GitHub prep, commit, and push guidance with explicit approval gates

Likely areas:
- `workshop/toolbox/coding/`
- `tests/`
- `gui/codingstudio.py`

Validation:
- coding task corpus
- repo inspection tests
- rollback and snapshot tests
- guarded publish tests

Exit:
- Somi can inspect, change, verify, explain, and recover code work with higher
  confidence than before

### Phase 162 - Guarded Autonomy Profiles

Goal:
- make autonomy more helpful without becoming reckless

Build:
- define `ask-first`, `balanced`, and `hands-off-safe` profiles
- add step budgets, time budgets, retry budgets, and escalation triggers
- improve background task runner and failure recovery
- make resource-aware planning stronger on weaker hardware

Likely areas:
- `workflow_runtime/`
- `ops/`
- `gui/`
- `workshop/toolbox/coding/`

Validation:
- autonomy profile tests
- long-task resume tests
- failure-recovery stress tests

Exit:
- users can pick autonomy strength without losing trust or control

### Phase 163 - Plugin Federation Core

Goal:
- create one plugin network that can absorb outside skill ecosystems safely

Build:
- define a Somi plugin descriptor with capability metadata, trust tier, tool
  requirements, provenance, and approval expectations
- build importer primitives for markdown skill bundles and plugin manifests
- define trust tiers: native, adapted-reviewed, adapted-experimental, disabled
- route imported capabilities through Somi's policy and sandbox layers

Likely areas:
- `skills_local/`
- `workshop/`
- `ops/`
- `docs/architecture/`

Validation:
- plugin registry tests
- trust-tier enforcement tests
- skill import parse tests

Exit:
- Somi can ingest outside skill patterns without bypassing safety

### Phase 164 - Hermes And OpenClaw Skill Adapters

Goal:
- make interoperability real, not theoretical

Build:
- add adapters for common `SKILL.md` style bundles
- map outside skill metadata into Somi plugin descriptors
- support dry-run import, review, and approve flows
- add compatibility docs and import examples

Likely areas:
- `skills_local/`
- `docs/architecture/`
- `tests/`

Validation:
- import tests using sample external skill bundles
- safety tests ensuring imported prompts do not bypass approval rules
- docs integrity checks for plugin docs

Exit:
- a contributor can adapt outside skills into Somi without inventing a new
  parallel ecosystem

### Phase 165 - Visible Execution And Premium UX Pass

Goal:
- make Somi feel more alive, more premium, and easier to trust

Build:
- expand task and action timeline UX
- improve research, coding, and reminder result cards
- refine microcopy, empty states, loading states, and fallback states
- improve answer rendering for compare, explain, guide, latest, and planning

Likely areas:
- `gui/`
- `somicontroller_parts/`
- `executive/synthesis/`

Validation:
- offscreen GUI smoke
- user-journey simulation pack
- answer-shaping tests

Exit:
- Somi feels more polished than utilitarian, but still clear and calm

### Phase 166 - Runtime Cleanup And Warning Elimination

Goal:
- remove the "harmless warning" class of rough edge

Build:
- trace socket, subprocess, and async teardown warnings to the actual shutdown
  paths
- harden event loop cleanup
- tighten resource closure for OCR, browser, and benchmark tooling
- turn known-cleanup warnings into explicit regressions

Likely areas:
- `ops/`
- `tests/`
- `workshop/`
- `ocr/`

Validation:
- warning-sensitive test runs
- subprocess-heavy stress runs
- release gate and doctor reruns

Exit:
- common regression and stress runs are quiet, not just functionally green

### Phase 167 - Repo Clarity And Newcomer Docs Pass

Goal:
- make the project legible to new users and new developers

Build:
- add or refine subfolder readmes in all major user-facing and dev-facing areas
- refresh `SYSTEM_MAP.md`, contributor maps, and newcomer checklists
- create "basic user" and "dev user" navigational docs where needed
- explain plugin federation, autonomy guardrails, and coding control surfaces

Likely areas:
- `docs/architecture/`
- top-level subfolders lacking readmes
- `README.md`

Validation:
- docs integrity
- newcomer walkthrough spot checks
- release gate docs pass

Exit:
- a new contributor can understand the major moving parts without reverse
  engineering the repo

### Phase 168 - Benchmark Repair Loop

Goal:
- prove the new upgrades under real load before calling them complete

Build:
- rerun focused safe search packs
- run memory, reminders, compaction, OCR, and coding stress packs
- run Telegram parity and autonomy stress slices
- repair failures in tight loops before the final gauntlet

Validation:
- phase-specific reports per pack
- repaired-failure manifest
- mixed smoke reruns after each repair

Exit:
- no red pack remains unaddressed before final acceptance

### Phase 169 - Competitive Finality Run

Goal:
- confirm Somi's practical advantage with one clean acceptance cycle

Build:
- run the full safe system gauntlet
- run an operator-style session simulation
- produce a final readiness brief that calls out remaining optional polish only

Validation:
- `Search100`
- `Memory100`
- `Reminder100`
- `Compaction100`
- `OCR100`
- `Coding100`
- `AverageUser30`

Exit:
- Somi feels coherent, powerful, and trustworthy across its core surfaces

### Phase 170 - Offline Resilience Foundations

Goal:
- lay groundwork for future crisis-resilient operation without derailing the
  current product wave

Build:
- define local knowledge-pack interfaces
- identify priority offline domains: repair, communications, power, water,
  medical reference, agriculture, fabrication, and documentation
- keep this read-heavy and defensive

Validation:
- design review
- loader tests
- offline-mode smoke

Exit:
- the later shelter and resilience mode has a real technical foundation

### Phase 171 - Distribution Sovereignty Layer

Goal:
- keep Somi's core independent from app-store and OS policy shifts

Build:
- define a surface-compliance adapter contract for optional client-edge policy
  handling
- document direct-download, local, and self-hosted-first distribution paths
- ensure any future age or account-signal handling remains coarse, optional, and
  isolated to affected clients
- keep the self-hosted core free of mandatory centralized identity services
- document the difference between core policy, surface policy, and user policy

Likely areas:
- `docs/architecture/`
- `workshop/integrations/`
- `gateway/`
- `README.md`

Validation:
- architecture doc review
- docs integrity
- surface-policy smoke tests for any affected client adapters

Exit:
- Somi can adapt at the edges without compromising the freedom of the core

### Phase 172 - Hardware Tiers And Survival Mode

Goal:
- make Somi practical on weak, unstable, or power-constrained systems without
  degrading the framework's ceiling

Build:
- define hardware tiers from low-end CPU-only systems to higher-end GPU systems
- add runtime profiles for normal mode, low-power mode, and survival mode
- tune concurrency, model choice, indexing strategy, and UI behavior per tier
- persist unfinished work so tasks survive power loss and resume cleanly

Likely areas:
- `workflow_runtime/`
- `ops/`
- `gui/`
- `state/`

Validation:
- low-resource smoke runs
- resume-after-interruption tests
- power-aware scheduling tests

Exit:
- Somi remains usable on weak hardware and becomes stronger automatically on
  better hardware

### Phase 173 - Offline Knowledge Pack Architecture

Goal:
- give Somi durable, locally searchable recovery knowledge that does not depend
  on the open web

Build:
- define a signed, versioned knowledge-pack format
- build ingestion, indexing, update, and provenance tracking for local packs
- prioritize packs for water, sanitation, food production, power, repair,
  communications, emergency care references, education, and basic sciences
- support compact and expanded variants for different storage budgets

Likely areas:
- `search/`
- `executive/`
- `docs/architecture/`
- `ops/`

Validation:
- offline retrieval tests
- provenance and integrity tests
- compact-pack and full-pack indexing tests

Exit:
- Somi can answer core continuity questions from local packs when the internet
  is unavailable

### Phase 174 - Federated Node Communication Layer

Goal:
- let Somi nodes exchange tasks, knowledge, and updates when links become
  available again

Build:
- define a node-to-node messaging and artifact-sharing layer
- align local tool interoperability with MCP where useful
- evaluate A2A-style agent exchange for task and capability negotiation
- prepare optional store-and-forward sync for intermittent connectivity
- keep all of this optional and self-hosted first

Likely areas:
- `gateway/`
- `workflow_runtime/`
- `workshop/integrations/`
- `docs/architecture/`

Validation:
- local multi-node simulation
- delayed-sync tests
- artifact transfer and trust tests

Exit:
- Somi can operate alone, then federate safely when communication returns

### Phase 175 - Continuity Domain Packs And Recovery Workflows

Goal:
- move from generic offline knowledge to practical recovery workflows

Build:
- create structured workflow packs for sanitation, repair, power recovery, food
  production, seed handling, water purification, local communications, and basic
  medical support references
- add answer templates and checklists for continuity scenarios
- keep sensitive biology and clinical content high-level, defensive, and
  provenance-rich
- add explicit uncertainty and escalate-to-expert messaging where appropriate

Likely areas:
- `executive/synthesis/`
- `search/`
- `docs/architecture/`
- `workflow_runtime/`

Validation:
- offline workflow retrieval tests
- checklist rendering tests
- high-stakes trust and citation tests

Exit:
- Somi can support communities with practical, defensive recovery guidance

### Phase 176 - Recovery Drill And Blackout Gauntlet

Goal:
- prove that Somi remains useful under degraded real-world conditions

Build:
- run no-internet, low-power, and interruption-heavy drills
- test offline search, memory, OCR, coding, reminders, and task resume behavior
- test multi-node sync after isolation periods
- document weak points and repair loops before declaring the layer stable

Likely areas:
- `audit/`
- `ops/`
- `tests/`
- `workflow_runtime/`

Validation:
- blackout drill report
- low-resource benchmark report
- intermittent-network recovery report

Exit:
- Somi demonstrates continuity under conditions far worse than normal desktop
  use

## Immediate 4-Hour Execution Order

The next concentrated upgrade wave should prioritize these phases first:

1. Phase 156
2. Phase 157
3. Phase 159
4. Phase 161
5. Phase 163
6. Phase 166

Rationale:

- the shared guardrail contract must exist before autonomy and plugin growth
- adaptive memory and unified runtime close the most important quality gaps
- coding power is one of Somi's clearest routes to long-term advantage
- plugin federation prevents ecosystem isolation
- warning cleanup keeps the framework from looking brittle under load

If time remains in the same 4-hour wave, continue with:

7. Phase 160
8. Phase 162
9. Phase 165

This sovereignty work should be planned alongside the next architecture and
docs passes, especially when touching channel adapters or distribution docs.

The civilization-continuity phases should begin after the near-term competitive
gaps are closed, then continue as a parallel strategic track in later upgrade
iterations.

## Validation Discipline

Before every implementation phase:

- create a checkpoint backup
- note target files and expected behaviors

After every implementation phase:

- run the smallest relevant targeted tests first
- run broader regression packs second
- rerun `doctor` and `release gate` for any ops-affecting change
- save a short markdown audit artifact for each phase

If a phase introduces regressions:

- create a patchwave backup before repair
- repair only the failing surface first
- rerun the failed focused pack
- rerun a mixed smoke slice to catch collateral regressions

## Success Criteria

This upgrade wave is successful when:

- memory is more useful, adaptive, and reviewable
- Telegram feels much closer to the desktop runtime
- coding flows are visibly stronger and safer
- autonomy is more capable without becoming reckless
- imported skills and plugins can be adapted into Somi safely
- UX is clearer, more premium, and more transparent
- runtime warnings are materially reduced or eliminated
- the repo is easier for newcomers to understand
- Somi has a clear path toward offline continuity and long-term recovery use

## What "Perfect" Means In Practice

Perfect does not mean no future ideas remain.

Perfect means:

- Somi feels more trustworthy than flashy
- Somi is more capable than its competitors where it matters most
- Somi makes fewer avoidable mistakes
- Somi explains itself clearly
- Somi recovers cleanly when things go wrong
- Somi stays safe under autonomy pressure
- Somi remains practical on consumer hardware
- Somi can keep helping when power, networks, and institutions become unreliable

That is the standard for the next wave.
