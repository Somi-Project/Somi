# runtime

Core runtime utilities: policy, approvals, ticketing, auditing, and execution guards.

- `tool_execution.py`: timeout/retry/idempotency guarantees for internal tool invocations.
- `audit.py`: append-only audit events with hash-chain verification (`verify_audit_log`).
- `eval_harness.py`: deterministic local simulation checks for routing, tool runtime, and audit integrity.
