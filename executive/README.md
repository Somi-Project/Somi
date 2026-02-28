# Executive subsystem (Istari + governance)

This folder contains Somi's **execution governance layer**: proposal/approval controls, deterministic policy checks, and bounded execution helpers.

## What lives here

- `istari.py`
  - Core primitives:
    - `CapabilityRegistry`
    - `ProposalStore`
    - `TokenStore`
    - `PolicyEnforcer`
    - `ScopedExecutor`
    - `AuditLog`
  - Purpose: deterministic enforcement of high-impact actions (no LLM in enforcement path).

- `istari_runtime.py`
  - Turn protocol adapter (`IstariProtocol`) for explicit commands:
    - propose (`run tool ...`)
    - `approve <proposal_id>`
    - `deny|reject [proposal_id]`
    - `revoke <token|proposal|all>`
    - `execute <proposal_id> <token>`
  - Persists one artifact per protocol turn.

- legacy/adjacent executive components (`engine.py`, `queue.py`, `approvals.py`, etc.)
  - earlier queue/budget flow still used by existing executive features.

## Interoperability map

- **Routing** (`handlers/routing.py`)
  - Emits route signals (`read_only`, `requires_execution`).

- **Agent orchestration** (`agents.py`)
  - Invokes `IstariProtocol` first for execution-governance commands.
  - Keeps read-only paths low-latency by avoiding unnecessary controller work.

- **Artifacts** (`handlers/contracts/*`)
  - Istari protocol writes governance artifacts through universal envelope helpers.
  - Strict validators include:
    - `proposal_action`
    - `approval_token`
    - `executed_action`
    - `denied_action`
    - `revoked_token`

- **Audit + redaction**
  - `AuditLog` writes append-only events in `audit/events.jsonl`.
  - Events are redacted using the shared artifact redaction helper before write.

## Safety model (high-level)

1. Build proposal with explicit scope.
2. Require approval token for scoped execution capabilities.
3. Enforce token validity + scope/path/command/cwd constraints deterministically.
4. Execute synchronously (no background jobs).
5. Write audit event trail and governance artifact.

## Config and defaults

- Registry config: `config/capability_registry.json`
- Conservative defaults:
  - read-only capabilities open
  - high-risk capabilities approval-gated or disabled
  - command allowlist + denylist patterns
  - protected paths and allowed roots

## Notes for co-devs

- Prefer extending `PolicyEnforcer` checks before broadening command coverage.
- Keep one-artifact-per-turn behavior in protocol handlers.
- Avoid introducing LLM-dependent checks in enforcement or token validation paths.
- Add tests for each new capability/command pattern (`tests/test_istari_guardrails.py`, `tests/test_istari_protocol.py`).
