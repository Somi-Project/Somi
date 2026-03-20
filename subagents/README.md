# Somi Subagents

This package contains the small delegated workers Somi can use for bounded
specialized tasks.

Main files:
- `specs.py`: subagent contracts and metadata.
- `registry.py`: local registry of available subagent types.
- `store.py`: persistence helpers for subagent state.
- `executor.py`: bounded execution layer for delegated runs.

For basic users:
- Subagents are not separate personalities. They are scoped helpers used by the
  main Somi runtime when a task benefits from specialization.

For developers:
- Keep subagents narrow, inspectable, and interruptible.
- Route all risky actions back through Somi's shared policy layer.
- Prefer subagents for decomposition and verification, not for bypassing audit
  or approval flows.
