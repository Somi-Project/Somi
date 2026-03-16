# SOMI Neo Upgrade Roadmap

Date: 2026-03-15

Purpose: define the final capability chapter that pushes Somi from "strong local framework" to "open-source market leader" before packaging, installer, and post-release setup-wizard work.

This roadmap is the new canonical upgrade plan.

Supersedes:

- `upgrade.md`
- `upgradeplan.md`
- `pyside6_upgradeplan.md`
- `speech_upgradeplan.md`
- `toolbox_coding_upgradeplan.md`

## Pillars

Every phase must preserve or improve these:

1. best user experience for ordinary humans
2. flawless operations
3. security centric by default
4. modular architecture
5. consumer-hardware friendly
6. captivating product feel
7. cross-platform capable

## Scope

Included in this chapter:

- finality benchmarking
- secure coding superiority
- research superiority
- skill ecosystem superiority
- gateway and node superiority
- ontology action/governance maturity
- cross-surface continuity
- high-prestige UI surfaces
- final publish-grade framework validation

Explicitly not included in this chapter:

- setup and repair wizard
- packaging and installer implementation

Those come immediately after this roadmap is complete.

## Champion Standard

Somi should be better than the competition in overall lived experience, not necessarily every single niche benchmark.

Target outcome:

- better integrated local AI operating system than DeerFlow, Hermes, OpenClaw, OpenHands, and Goose
- near-best-in-class coding, research, memory, automation, and control-plane behavior on consumer hardware
- strong enough architecture, security, and polish to be a credible "default choice" for self-hosted agent users

## Phase Discipline

These rules apply to every phase without exception:

- before each phase, create a full repo backup
- backup naming pattern:
  - `backups/neoupgrade_phaseXX_start_YYYYMMDD_HHMMSS`
  - `backups/neoupgrade_phaseXX_complete_YYYYMMDD_HHMMSS`
- all tests run through `.venv`
- after each phase, patch until the phase is green
- do not start the next phase with any known failing regression
- keep wrappers under architecture limits and split again if needed
- if context compaction occurs, resume from the latest phase backup and canonical docs

## Mandatory Verification After Every Phase

Minimum required checks:

- `.venv\Scripts\python -m pytest tests -q`
- `.venv\Scripts\python audit\simulate_chat_flow_regression.py`
- `.venv\Scripts\python runtime\live_chat_stress.py`
- phase-specific smoke tests
- offscreen GUI checks for new desktop surfaces
- any new benchmark or harness introduced by the phase

If a phase changes security, remote execution, coding, browser, OCR, speech, or memory behavior, add focused regression tests before moving on.

## Scoring Model

Each phase should improve at least one of these hard metrics:

- task finality
- time to finality
- successful autonomous completion rate
- grounded-answer reliability
- security posture or audit clarity
- user-facing setup simplicity
- recovery and rollback safety
- perceived polish and operator confidence

## Phase Plan

### Phase 1: Finality Lab Backbone

Goal:

- make Somi measurable instead of merely impressive

Deliverables:

- unified benchmark lab for coding, research, OCR, speech, automation, browser, and memory
- hardware-profile capture so results are normalized for consumer machines
- task packs for "easy", "normal", and "hard" workflows
- time-to-finality capture for every benchmark branch
- benchmark result persistence and leaderboard summaries

Win condition:

- Somi can prove where it is fast, where it is accurate, and where it still needs polish

Phase-specific verification:

- benchmark lab smoke tests
- persisted benchmark snapshots
- benchmark diff between two runs

### Phase 2: Secure Coding Sandbox Matrix

Goal:

- give Somi a coding runtime serious enough to compete with OpenHands and Claude Code style workflows

Deliverables:

- selectable coding backends:
  - local managed venv
  - repo snapshot sandbox
  - optional Docker backend
  - optional remote sandbox backend
- workspace quotas, path boundaries, and rollback snapshots
- safe write-preview model before large file changes
- stronger repo-task isolation and branch/task scoping

Win condition:

- coding mode can safely perform real repo work without turning the local machine into chaos

Phase-specific verification:

- repo patch/test loops
- rollback snapshot restore
- sandbox boundary tests

### Phase 3: Champion Coding Agent

Goal:

- make Somi feel like a top-tier local coding copilot, not just a tool wrapper

Deliverables:

- repo map and dependency awareness
- better multi-file planning and execution
- patch -> test -> diagnose -> repatch loop scoring
- long-running coding jobs with resumable state
- stronger code review and fix verification
- coding memory tuned for project context
- explicit coding task scorecards in coding studio

Win condition:

- Somi closes far more coding tasks autonomously and cleanly than it does now

Phase-specific verification:

- benchmark coding tasks
- multi-file edits
- failing test repair loops
- regression for workspace safety and diffs

### Phase 4: Research Supermode

Goal:

- beat DeerFlow on operator usefulness while staying local-first

Deliverables:

- long-running research jobs
- research subagent orchestration
- deeper browse/read/extract/compare loops
- source trust scoring and contradiction detection
- research memory tuned for long investigations
- explicit research progress and coverage tracking

Win condition:

- Somi can run deeper, longer, more structured research than a normal chat loop

Phase-specific verification:

- long research task pack
- citation integrity tests
- contradiction and source-merging checks

### Phase 5: Evidence Graph and Research Exports

Goal:

- make research outputs look and feel premium and decision-ready

Deliverables:

- evidence graph for claims, sources, entities, and contradictions
- export targets:
  - research brief
  - slide outline
  - knowledge page
  - decision memo
- better PDF/table/chart extraction integration
- artifact bundling for downstream automations

Win condition:

- Somi research output is not only accurate, but obviously reusable

Phase-specific verification:

- export correctness tests
- evidence graph persistence tests
- document extraction regression pack

### Phase 6: Skill Forge and Self-Expansion

Goal:

- make Somi capable of expanding itself in a controlled, auditable way

Deliverables:

- agent-authored skill drafts
- install-review-approve flow for new skills
- local skill templates with dependency manifests
- skill regression hooks
- skill provenance and change history
- ability for Somi to propose a new skill when blocked by a repeated task gap

Win condition:

- Somi can responsibly grow its own toolbox instead of hard-stopping on capability gaps

Phase-specific verification:

- draft-skill generation
- approval-gated install path
- bad-skill rejection tests

### Phase 7: Skill Marketplace and Trust Layer

Goal:

- overtake Hermes and Goose in practical skill usability

Deliverables:

- signed or trust-labeled skill packages
- skill compatibility checks
- update channels and rollback
- marketplace-style browser in GUI
- recommended bundles by persona or workflow
- trust badges:
  - first-party
  - community reviewed
  - local experimental

Win condition:

- users can discover, trust, install, disable, update, and recover skills cleanly

Phase-specific verification:

- install/update/rollback tests
- trust-policy tests
- GUI marketplace smoke tests

### Phase 8: Node Mesh and Pairing

Goal:

- move Somi toward OpenClaw-level multi-surface power without losing safety

Deliverables:

- node host for remote capabilities
- pairing flow for trusted nodes
- capability discovery and heartbeat
- first node types:
  - browser node
  - speech node
  - mobile relay node
  - gpu runner node
  - file relay node

Win condition:

- Somi can extend beyond one machine cleanly while keeping trust explicit

Phase-specific verification:

- pairing flow tests
- node heartbeat tests
- capability registry tests

### Phase 9: Security-Centric Remote Execution

Goal:

- make remote and distributed power feel safe enough to ship publicly

Deliverables:

- capability scopes per node
- approval tiers per node and per action
- session recording and audit for remote actions
- remote kill switch and revoke flow
- stronger secret handling and token rotation surfaces
- remote file and execution boundaries

Win condition:

- remote execution is powerful but clearly governed

Phase-specific verification:

- security audit additions
- scope and revoke tests
- remote-action denial-path tests

### Phase 10: Ontology Actions and Human Oversight

Goal:

- turn Somi's ontology into a true action/governance backbone

Deliverables:

- typed actions attached to ontology objects
- durable approval chains for high-risk operations
- lifecycle states for tasks, artifacts, jobs, automations, and nodes
- runbooks/playbooks bound to object types
- clearer control-room operational action surfaces

Win condition:

- Somi's internal graph is no longer passive state; it becomes operational control

Phase-specific verification:

- object-action linkage tests
- approval persistence tests
- ontology projection regression checks

### Phase 11: Prestige UX and Cross-Surface Continuity

Goal:

- make people instantly understand that Somi is special

Deliverables:

- research studio
- node manager
- skill marketplace UI
- better ambient continuity between GUI, Telegram, coding studio, and future mobile relay
- richer session handoff views
- more cinematic, futuristic, high-confidence desktop surfaces

Win condition:

- Somi looks and feels like a flagship AI workstation, not a utility app

Phase-specific verification:

- offscreen GUI surface checks
- navigation continuity tests
- chat-to-studio and studio-to-chat handoff tests

### Phase 12: Champion Freeze and Publish Gate

Goal:

- prove Somi is ready to compete publicly

Deliverables:

- full system gauntlet across all major branches
- comparison scorecard against target competitor strengths
- final capability and regression freeze
- publish-grade release notes for framework features
- explicit blocker ledger for anything that still should be solved before installer work

Win condition:

- Somi is functionally stable, benchmarked, secure, and compelling enough to publish as a serious market-leading open-source agent framework

Phase-specific verification:

- full framework verification
- benchmark suite across all major branches
- release gate
- framework freeze
- manual UI smoke across flagship surfaces

## Final Completion Criteria

This chapter is complete only when all of the following are true:

- every phase has both a start backup and a completion backup
- all core test suites are green
- benchmark/finality evidence exists for all major branches
- no critical or high-severity security findings remain
- no known broken flagship surface remains in GUI, chat, coding, research, speech, automation, gateway, memory, or ontology control
- Somi can credibly claim top-tier status in integrated local AI framework capability

## Final End-of-Chapter Validation

At the end of Phase 12, run and patch until green:

- `.venv\Scripts\python -m pytest tests -q`
- `.venv\Scripts\python audit\simulate_chat_flow_regression.py`
- `.venv\Scripts\python runtime\live_chat_stress.py`
- full benchmark lab
- release gate
- framework freeze
- coding studio smoke
- control room smoke
- speech smoke
- research studio smoke
- node and pairing smoke

## Publishing Intent

This roadmap is explicitly aimed at making Somi publishable as the best all-around open-source self-hosted AI agent framework on the market, within the reality of consumer hardware and non-enterprise local deployments.

Somi does not need to beat Palantir on enterprise server operations.

Somi does need to be the best overall choice for people who want:

- one coherent local AI operating system
- coding, research, memory, voice, automation, and control in one framework
- serious capability without enterprise infrastructure
- a product they actually enjoy using
