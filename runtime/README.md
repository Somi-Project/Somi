# runtime

Core runtime utilities for policy, approvals, continuity, auditability, and
guarded execution.

## Contents

- `action_policy.py`
  - shared action taxonomy and approval/preview/rollback contract
- `autonomy_profiles.py`
  - bounded autonomy profiles with step, time, retry, and load budgets
- `background_tasks.py`
  - background-task store, retry posture, and local resource budget snapshots
- `task_resume.py`
  - continuity ledger for active threads, background work, and cross-surface
    handoffs
- `ollama_compat.py`
  - Ollama client compatibility and cleanup helpers
- `tool_execution.py`
  - timeout/retry/idempotency guarantees for internal tool invocations
- `audit.py`
  - append-only audit events with hash-chain verification
- `eval_harness.py`
  - deterministic local simulation checks for routing, tool runtime, and audit
    integrity

## Start Here

- overall contributor map:
  - [`docs/architecture/CONTRIBUTOR_MAP.md`](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md)
- desktop/runtime bridge:
  - [`somicontroller_parts/runtime_methods.py`](/C:/somex/somicontroller_parts/runtime_methods.py)
- main CLI surface:
  - [`somi.py`](/C:/somex/somi.py)

## Read This Package When

- you are debugging approvals, background-task safety, or runtime audit trails
- you need to understand execution policy and failure handling
- you are tracing a tool call that looks correct in the GUI but behaves oddly
  at runtime
- you are investigating autonomy limits, resume hints, or local warning cleanup
