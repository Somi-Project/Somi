# System Map

This is the frozen backbone map for Somi at the end of the framework-upgrade chapter, just before packaging and installer work.

## Pillars

1. User experience
2. Security
3. Flawless functions on consumer grade hardware
4. Fast
5. Modular

## Top-Level Domains

### UI Shell

Purpose:

- desktop operator experience
- cockpit, chat, panels, controls, status views
- agent studio and control-room inspection surfaces

Owner paths:

- [somicontroller.py](/C:/somex/somicontroller.py)
- [somicontroller_parts](/C:/somex/somicontroller_parts)
- [gui](/C:/somex/gui)

Notes:

- UI should orchestrate, not own core business logic.
- UI may display runtime state and trigger actions, but execution policy belongs elsewhere.
- Phase 10 adds the first unified control-room surface for sessions, tasks, subagents, workflows, automations, channels, memory, and failure inspection.

### Agent Runtime

Purpose:

- turn handling
- routing
- model selection
- history shaping
- response generation
- follow-up resolution

Owner paths:

- [agents.py](/C:/somex/agents.py)
- [agent_methods](/C:/somex/agent_methods)
- [runtime](/C:/somex/runtime)
- [workshop/toolbox/agent_core](/C:/somex/workshop/toolbox/agent_core)

Notes:

- This is the runtime brain, not the durable system of record.

### State Plane

Purpose:

- canonical session and turn storage
- event timelines
- searchable operational history
- reconstruction of what happened without replaying scattered files

Owner paths:

- [state](/C:/somex/state)
- [sessions/state](/C:/somex/sessions/state)

Notes:

- This is the new source of truth for runtime timelines.
- File snapshots still exist, but they now sit beneath a canonical event layer.

### Executive Layer

Purpose:

- memory
- strategic planning
- prompt assembly
- proactivity
- life-modeling
- synthesis

Owner paths:

- [executive](/C:/somex/executive)

Notes:

- This is Somi's higher-order cognition and long-horizon logic.

### Tool and Capability Plane

Purpose:

- tool registration
- toolbox loading
- stack composition
- OCR, research, image, contracts, web intelligence

Owner paths:

- [workshop/toolbox](/C:/somex/workshop/toolbox)
- [workshop/skills](/C:/somex/workshop/skills)

Notes:

- Phase 3 introduced the stronger registry/control plane for tool metadata, toolsets, and runtime governance.
- Phase 4 introduced broader execution backends and safety envelopes around local execution.

### Execution Backends

Purpose:

- backend abstraction for execution
- sandboxed local execution routing
- future Docker, SSH, and worker execution
- stable execution contracts above raw subprocess calls

Owner paths:

- [execution_backends](/C:/somex/execution_backends)
- [runtime/sandbox.py](/C:/somex/runtime/sandbox.py)
- [runtime/shell.py](/C:/somex/runtime/shell.py)
- [runtime/tool_execution.py](/C:/somex/runtime/tool_execution.py)

Notes:

- Phase 4 routes current local execution through explicit backend objects.
- New backends can now be added without rewriting loaders or ticket handling.

### Subagent Plane

Purpose:

- isolated child-agent execution
- delegation profiles and heuristics
- background status snapshots
- parent/child trace continuity

Owner paths:

- [subagents](/C:/somex/subagents)
- [runtime/task_graph.py](/C:/somex/runtime/task_graph.py)
- [executive/strategic](/C:/somex/executive/strategic)
- [workshop/toolbox/agent_core](/C:/somex/workshop/toolbox/agent_core)

Notes:

- Phase 5 adds the first true child-agent runtime instead of overloading the parent turn.
- Status snapshots are durable in `sessions/subagents`, and parent threads track child runs in the task graph.
- Delegation is explicit through `/delegate ...` so normal chat stays predictable and fast.

### Workflow Plane

Purpose:

- restricted workflow execution
- manifest-backed repeatable scripts
- tool RPC without parent-turn tool chatter
- durable workflow run snapshots

Owner paths:

- [workflow_runtime](/C:/somex/workflow_runtime)
- [runtime/tool_orchestrator.py](/C:/somex/runtime/tool_orchestrator.py)
- [workshop/toolbox/runtime.py](/C:/somex/workshop/toolbox/runtime.py)

Notes:

- Phase 6 adds a bounded Python workflow runner instead of generic free-form code execution.
- Workflows call tools through explicit allowlists and the existing registry/policy runtime.
- Runs persist under `sessions/workflows`, giving later phases a stable place to inspect or replay automations.

### Memory Search Plane

Purpose:

- session search across prior turns, artifacts, and jobs
- curated memory blocks for stable prompt injection
- frozen prompt snapshots resilient to compaction
- memory hygiene and operational recall

Owner paths:

- [search](/C:/somex/search)
- [executive/memory](/C:/somex/executive/memory)
- [runtime/history_compaction.py](/C:/somex/runtime/history_compaction.py)
- [heartbeat/tasks](/C:/somex/heartbeat/tasks)

Notes:

- Phase 7 adds a Hermes-style local session search layer above the canonical state plane.
- Prompt memory is now separated into curated, working, and operational blocks before injection.
- Frozen memory snapshots live under `sessions/state/memory_blocks` so compaction and recovery can reuse a stable prompt view.

### Ontology Plane

Purpose:

- typed operational graph for real system objects
- projection of conversations, tasks, goals, reminders, artifacts, jobs, systems, and channels
- one searchable state model for later automations and control-room work

Owner paths:

- [ontology](/C:/somex/ontology)
- [runtime/task_graph.py](/C:/somex/runtime/task_graph.py)
- [executive/life_modeling](/C:/somex/executive/life_modeling)
- [state](/C:/somex/state)

Notes:

- Phase 8 promotes Somi's internal state into a typed graph instead of leaving it spread across unrelated files and stores.
- The ontology is currently projection-first: it reads durable state, memory, task graphs, artifacts, and jobs into one shared object model.
- Later phases can bind UI views, automations, and deployment controls directly to these objects and links.

### Gateway Plane

Purpose:

- delivery channel registry
- desktop and queued channel adapters
- shared inbox/outbox logs for surfaced messages
- stable cross-surface delivery contracts

Owner paths:

- [gateway](/C:/somex/gateway)
- [workshop/integrations](/C:/somex/workshop/integrations)
- [sessions/delivery](/C:/somex/sessions/delivery)

Notes:

- Phase 9 adds a real delivery abstraction instead of treating every surface as a one-off integration.
- Desktop delivery is immediate and durable; queued channels like Telegram can receive the same payload later without changing automation code.
- The upgrade roadmap Phase 2 adds a typed local gateway surface for session identity, presence, health, and event streams above raw delivery.
- GUI activity and Telegram ingress now publish into the same gateway snapshot, which gives the control room one shared operator surface instead of separate ad hoc status paths.
- The upgrade roadmap Phase 3 adds pairing records, remote-session trust states, and a merged status feed so future nodes can be introduced without weakening the execution boundary.

### Delivery and Automation

Purpose:

- heartbeat
- reminders
- jobs
- future gateway / automations / cross-channel delivery

Owner paths:

- [heartbeat](/C:/somex/heartbeat)
- [jobs](/C:/somex/jobs)
- [workshop/integrations](/C:/somex/workshop/integrations)

Notes:

- Today this is fragmented; later phases will unify it.
- Phase 9 now owns automation scheduling, delivery dispatch, and automation run history through [automations](/C:/somex/automations).

### Config and Policy

Purpose:

- model profiles
- memory budgets
- settings
- policy defaults

Owner paths:

- [config](/C:/somex/config)

### Ops Control Plane

Purpose:

- runtime profiles and rollout gates
- policy decision logging
- tool and model metrics
- local observability for upgrades and troubleshooting

Owner paths:

- [ops](/C:/somex/ops)
- [deploy](/C:/somex/deploy)
- [runtime/policy.py](/C:/somex/runtime/policy.py)
- [executive/approvals.py](/C:/somex/executive/approvals.py)

Notes:

- Phase 11 introduces a Palantir-style local control plane without giving up Somi's local-first posture.
- Runtime profiles are versioned, rollout gates are explicit, and policy/tool/model observations now persist under `sessions/ops`.
- Phase 11 also adds replay harnesses, persisted release-gate snapshots, benchmark diffs, and a control-room observability surface.
- Phase 12 turns those observations into durable freeze artifacts and a packaging handoff under `docs/release` and `sessions/release_gate`.

### Learning Plane

Purpose:

- trajectory capture and replay
- scorecards for latency, tool success, correction rate, and grounding
- workflow-derived skill suggestions
- regression pack inventory for future audits

Owner paths:

- [learning](/C:/somex/learning)
- [audit](/C:/somex/audit)
- [tests](/C:/somex/tests)
- [runtime/eval_harness.py](/C:/somex/runtime/eval_harness.py)

Notes:

- Phase 12 closes the loop by capturing real turn trajectories and turning them into replayable diagnostics.
- Eval output now carries a scorecard, regression-pack inventory, and skill suggestions derived from successful workflows.
- Benchmark baselines and release-gate evidence now feed the final framework freeze before packaging.

### Session and Artifact Storage

Purpose:

- logs
- media
- ledgers
- task graphs
- plan state
- cached outputs

Owner paths:

- [sessions](/C:/somex/sessions)

Notes:

- Today this is file-heavy.
- Phase 2 introduced a canonical event/session store above this.
- These files remain useful as snapshots and caches.

## Current Architectural Direction

Somi is moving from:

- file-heavy local runtime with strong features

toward:

- explicit control plane
- canonical state plane
- stronger tool registry
- execution backends
- isolated subagents
- restricted workflows
- workflow runtime
- memory search and curated prompt memory
- ontology-backed operations
- ontology-driven operations
- delivery gateway and schedulable automations
- operator studio and control-room inspection
- runtime profiles, rollout gates, and observability
- trajectory capture, replay scorecards, and skill synthesis

## Immediate Rules

- `agents.py` remains a compatibility wrapper and runtime entry surface.
- `somicontroller.py` remains a compatibility wrapper and desktop entry surface.
- new work should prefer owner packages instead of expanding wrappers.
- major new subsystems should be added as packages, not as catch-all files.
