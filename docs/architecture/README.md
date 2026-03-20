# Somi Architecture

This directory is the architecture reference pack for Somi.

It exists for three reasons:

1. preserve a compact map of the system during context compaction,
2. define package ownership and boundaries before later upgrades,
3. stop the codebase from quietly drifting back into large monoliths.

Read these in order:

- [SYSTEM_MAP.md](/C:/somex/docs/architecture/SYSTEM_MAP.md)
- [BOUNDARIES.md](/C:/somex/docs/architecture/BOUNDARIES.md)
- [RECOVERY_PLAYBOOK.md](/C:/somex/docs/architecture/RECOVERY_PLAYBOOK.md)
- [CONTRIBUTOR_MAP.md](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md)
- [NEWCOMER_CHECKLIST.md](/C:/somex/docs/architecture/NEWCOMER_CHECKLIST.md)
- [system_manifest.json](/C:/somex/docs/architecture/system_manifest.json)

Phase status:

- `Phase 1`: architecture freeze
- `Phase 2`: canonical state plane
- `Phase 3`: strong tool registry and policy metadata
- `Phase 4`: execution backend abstraction and safety envelopes
- `Phase 5`: isolated subagent runtime, delegation profiles, and child status snapshots
- `Phase 6`: restricted workflow runtime with manifest-backed tool RPC
- `Phase 7`: session search, curated memory blocks, and memory hygiene
- `Phase 8`: typed ontology projection for conversations, tasks, reminders, artifacts, jobs, systems, and channels
- `Phase 9`: delivery gateway, schedulable automations, and automation run state
- `Phase 10`: agent studio / control room views for sessions, tasks, subagents, workflows, automations, channels, memory, and failures
- `Phase 11`: runtime profiles, rollout gates, policy decision logging, and local model/tool observability
- `Phase 12`: trajectory capture, replay scorecards, workflow-derived skill suggestions, and regression-pack inventory
- `Release reference`: [FRAMEWORK_RELEASE_NOTES.md](/C:/somex/docs/release/FRAMEWORK_RELEASE_NOTES.md)
