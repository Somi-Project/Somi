# Somi Ontology

This package is the typed relationship layer that ties Somi's actions, jobs,
approvals, automations, and node activity into a queryable system model.

Main files:
- `schema.py`: ontology types and edge definitions.
- `store.py`: persistence and lookup helpers.
- `service.py`: higher-level ontology operations used by the runtime and ops
  surfaces.

For basic users:
- You usually see this indirectly through audit trails, task continuity, and
  control-room visibility.

For developers:
- Use this package when a new feature needs durable typed relationships instead
  of ad hoc JSON blobs.
- Keep ontology writes descriptive and reversible so operator tooling can trace
  what happened and why.
