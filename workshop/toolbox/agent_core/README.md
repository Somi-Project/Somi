# agent_core

Core agent-facing helpers that sit between the outer runtime and the internal
tool/search/coding stacks.

## Key Files

- `routing.py`
  - high-level routing helpers for deciding where a request should go
- `tool_context.py`
  - execution context helpers passed into tool/runtime calls
- `continuity.py`
  - session continuity and follow-on behavior support
- `delegation.py`
  - child/subagent delegation helpers
- `followup_resolver.py`
  - follow-up interpretation and request carry-forward logic
- `heartbeat.py`
  - assistant profile load/save helpers used by the shell/runtime
- `time_handler.py`
  - date/time normalization helpers

## When To Start Here

- you are tracing how a request gets routed before it becomes a tool call
- you need to understand agent continuity between turns
- you are debugging delegation or follow-up handling

## Related Layers

- [`workshop/toolbox/stacks/README.md`](/C:/somex/workshop/toolbox/stacks/README.md)
- [`runtime/README.md`](/C:/somex/runtime/README.md)
- [`docs/architecture/CONTRIBUTOR_MAP.md`](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md)
