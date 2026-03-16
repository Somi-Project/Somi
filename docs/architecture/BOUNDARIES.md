# Boundaries

These are the active package boundaries frozen in Phase 1.

## Ownership Rules

### UI Shell

Paths:

- [somicontroller.py](/C:/somex/somicontroller.py)
- [somicontroller_parts](/C:/somex/somicontroller_parts)
- [gui](/C:/somex/gui)

Owns:

- widgets
- operator workflows
- visual state presentation
- user-triggered actions
- control-room inspection and replay surfaces

Should not own:

- tool execution logic
- memory persistence logic
- agent loop policy
- security policy

### Agent Runtime

Paths:

- [agents.py](/C:/somex/agents.py)
- [agent_methods](/C:/somex/agent_methods)
- [runtime](/C:/somex/runtime)
- [workshop/toolbox/agent_core](/C:/somex/workshop/toolbox/agent_core)

Owns:

- routing
- model failover
- history compaction
- response assembly
- loop detection
- turn orchestration

Should not own:

- GUI rendering
- persistent analytics dashboards
- long-term deployment control

### State Plane

Paths:

- [state](/C:/somex/state)
- [sessions/state](/C:/somex/sessions/state)

Owns:

- session records
- turn records
- event timelines
- searchable operational state

Should not own:

- model prompting policy
- GUI rendering
- tool implementation details

### Executive Layer

Paths:

- [executive](/C:/somex/executive)

Owns:

- memory
- strategic planning
- prompting policy
- proactivity
- life-modeling

Should not own:

- direct UI widget code
- raw transport/channel adapters

### Tool Plane

Paths:

- [workshop/toolbox](/C:/somex/workshop/toolbox)
- [workshop/skills](/C:/somex/workshop/skills)

Owns:

- tool definitions
- tool registry
- toolsets
- capability metadata
- stack composition
- tool runtime adapters
- skill loading

Should not own:

- top-level session history policy
- UI orchestration

### Execution Backends

Paths:

- [execution_backends](/C:/somex/execution_backends)
- [runtime/sandbox.py](/C:/somex/runtime/sandbox.py)
- [runtime/shell.py](/C:/somex/runtime/shell.py)
- [runtime/tool_execution.py](/C:/somex/runtime/tool_execution.py)

Owns:

- backend selection
- execution routing
- sandbox path boundaries
- local execution implementation

Should not own:

- tool discovery metadata
- prompt routing logic
- UI widget behavior

### Subagent Plane

Paths:

- [subagents](/C:/somex/subagents)
- [runtime/task_graph.py](/C:/somex/runtime/task_graph.py)
- [executive/strategic](/C:/somex/executive/strategic)
- [workshop/toolbox/agent_core](/C:/somex/workshop/toolbox/agent_core)

Owns:

- child-agent profiles
- delegation selection and command parsing
- isolated child traces
- background status snapshots
- task-graph links between parent and child runs

Should not own:

- direct GUI widget rendering
- arbitrary unapproved shell execution
- parent-turn prompt assembly

### Workflow Plane

Paths:

- [workflow_runtime](/C:/somex/workflow_runtime)
- [runtime/tool_orchestrator.py](/C:/somex/runtime/tool_orchestrator.py)
- [workshop/toolbox/runtime.py](/C:/somex/workshop/toolbox/runtime.py)

Owns:

- manifest-backed workflow definitions
- restricted script validation
- tool RPC execution for repeatable chains
- workflow run snapshots and child traces

Should not own:

- unconstrained Python execution
- direct UI rendering
- approval bypasses around non-read-only tools

### Memory Search Plane

Paths:

- [search](/C:/somex/search)
- [executive/memory](/C:/somex/executive/memory)
- [runtime/history_compaction.py](/C:/somex/runtime/history_compaction.py)
- [heartbeat/tasks](/C:/somex/heartbeat/tasks)

Owns:

- session search over canonical runtime state
- frozen memory snapshots
- memory injection hygiene
- compact recall summaries for follow-up continuity

Should not own:

- direct GUI widgets
- external delivery transport implementations
- unrestricted model prompting policy beyond memory blocks

### Ontology Plane

Paths:

- [ontology](/C:/somex/ontology)
- [runtime/task_graph.py](/C:/somex/runtime/task_graph.py)
- [executive/life_modeling](/C:/somex/executive/life_modeling)
- [state](/C:/somex/state)

Owns:

- typed operational objects
- object relationships and lifecycle projection
- shared graph search across operational entities
- object contracts used by later automations and operator surfaces

Should not own:

- raw GUI presentation logic
- tool execution implementations
- direct transport/channel delivery

### Gateway Plane

Paths:

- [gateway](/C:/somex/gateway)
- [workshop/integrations](/C:/somex/workshop/integrations)
- [sessions/delivery](/C:/somex/sessions/delivery)

Owns:

- channel registry and adapter contracts
- durable inbox and outbox logging
- surface-specific delivery semantics
- typed session, presence, health, and event stream contracts
- pairing records and remote client trust rules

Should not own:

- automation schedule policy
- prompt routing logic
- GUI-only presentation rules

### Delivery and Automation

Paths:

- [heartbeat](/C:/somex/heartbeat)
- [jobs](/C:/somex/jobs)
- [workshop/integrations](/C:/somex/workshop/integrations)

Owns:

- notifications
- reminders
- automatable tasks
- channel delivery

Should not own:

- core model selection logic
- GUI rendering

### Ops Control Plane

Paths:

- [ops](/C:/somex/ops)
- [deploy](/C:/somex/deploy)
- [runtime/policy.py](/C:/somex/runtime/policy.py)
- [executive/approvals.py](/C:/somex/executive/approvals.py)

Owns:

- runtime environment profiles
- rollout gate evaluation
- policy decision ledgers
- model and tool metrics
- release-readiness scorecards
- replay harnesses and benchmark diffs
- framework-freeze and packaging handoff artifacts

Should not own:

- direct tool execution implementations
- GUI rendering details
- prompt assembly

### Learning Plane

Paths:

- [learning](/C:/somex/learning)
- [audit](/C:/somex/audit)
- [tests](/C:/somex/tests)
- [runtime/eval_harness.py](/C:/somex/runtime/eval_harness.py)

Owns:

- turn trajectory capture
- replay and scorecard helpers
- workflow-derived skill suggestions
- regression pack inventory
- benchmark baseline evidence for major framework branches

Should not own:

- live tool execution policy
- transport adapters
- direct GUI widget behavior

## No-Monolith Rules

- Do not add new feature clusters to `agents.py`.
- Do not add new feature clusters to `somicontroller.py`.
- New major features should land in a package with at least one focused module.
- If a wrapper crosses its contract threshold, split again before adding more features.

## Wrapper Thresholds

The following thresholds are enforced by tests:

- `agents.py`: max 900 lines, max 50 KB
- `somicontroller.py`: max 900 lines, max 50 KB

These are intentionally strict because both files are compatibility surfaces now.

## Dependency Direction

Preferred direction:

1. `config`
2. `state` and storage abstractions
3. `runtime` and `executive`
4. `toolbox`
5. `delivery`
6. `ui`

Until later phases land, this is guidance rather than a full import firewall.

## Future Packages Reserved By Plan

These names are reserved by the upgrade roadmap and should not be used casually for unrelated work:

- `state`
- `platform_registry`
- `execution_backends`
- `ontology`
- `gateway`
- `automations`
