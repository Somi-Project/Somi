# workflow_runtime

Bounded workflow execution for scripted multi-step operations.

## Key Files

- `manifests.py`
  - workflow manifest definitions and storage
- `runner.py`
  - restricted workflow execution engine
- `guard.py`
  - safety checks and execution guardrails
- `store.py`
  - persisted workflow run state

## Read This Package When

- a task uses a workflow manifest instead of direct chat/runtime control
- you want to understand safe multi-step execution under tighter constraints
- you are debugging manifest validation or workflow replay behavior
