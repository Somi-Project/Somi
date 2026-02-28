# Phase 5 / Istari Debug Log

Requested workflow followed:
1) simulate
2) audit what is wrong
3) plan patch
4) execute patches
5) document grey-zone risks

Focus rubric used:
1. User experience
2. Security
3. Latency
4. No unnecessary complexity
5. Actually works

---

## A) Simulation Pass

### Simulated scenarios
- **Read-only query path** (`weather/news/finance/llm_only`) should bypass execution control path.
- **Proposal scope tampering** where `scope.paths` is safe but `steps[].parameters.path` points somewhere else.
- **Command tampering** where `scope.commands` is benign but `steps[].parameters.command` differs.
- **Unsafe command cwd** where command executes outside allowed roots.
- **Token revocation edge case** with append-only token events in JSONL store.

### Why these were selected
They directly impact UX latency, security boundary integrity, and deterministic policy behavior.

---

## B) Audit Findings (before patch)

### 1) Scope/step mismatch gap (security)
`PolicyEnforcer` validated declared `scope`, but execution consumed `steps[].parameters` without enforcing equality/containment. This permits intent drift between what user approved and what runs.

### 2) Shell cwd boundary not enforced at step-level (security)
`cwd` in execution step was not validated against allowed roots.

### 3) Token revoke event inflation (integrity/noise)
`revoke()` iterated all token rows (including non-issuance events), which could create unnecessary/duplicate revoke events.

### 4) Schema invariant looseness (contract clarity)
`proposal_action.requires_approval` / `proposal_action.no_autonomy` accepted `false` after coercion, which weakens the explicit contract.

### 5) Minor hygiene
Unused imports in `executive/istari.py`.

---

## C) Patch Plan

1. Harden deterministic enforcer to validate step payloads against approved scope.
2. Enforce shell step cwd root constraints.
3. Tighten token revoke targeting to issuance rows only + dedupe digests.
4. Tighten proposal schema invariants for `requires_approval` and `no_autonomy`.
5. Add regression tests for each discovered gap.
6. Keep latency neutral for read-only routes (no added overhead to read-only fast path).

---

## D) Executed Patches

### Code patches
- `executive/istari.py`
  - Added command normalization helper in `PolicyEnforcer`.
  - Enforced **step-path must match scoped paths** for `file.write_scoped`.
  - Enforced **step-command must match scoped commands** for `shell.exec_scoped`.
  - Enforced **step cwd inside allowed roots/protected-path rules**.
  - Improved `TokenStore.revoke()` to only target `approval_token` rows and deduplicate revokes.
  - Removed unused imports.
  - Kept execution synchronous and deterministic.

- `handlers/contracts/schemas.py`
  - `proposal_action.requires_approval` is now enforced as true.
  - `proposal_action.no_autonomy` is now enforced as true.

- `tests/test_istari_guardrails.py`
  - Added tests for:
    - scope vs step path mismatch rejection
    - scope vs step command mismatch rejection
    - cwd outside allowed roots rejection
    - revoke targeting only issuance tokens

---

## E) Validation / Results

Executed:
- `pytest -q tests/test_istari_guardrails.py tests/test_governance.py tests/test_skill_command_governance.py tests/test_executive_engine.py`
- `pytest -q tests/test_artifacts_phase4.py`

Result: all passed.

---

## F) Grey-zone issues (for your decision)

These are not broken now, but are strategic choices:

1. **Istari module exists but is still mostly library-level, not fully orchestrated into one end-to-end runtime command protocol.**
   - Current code has strong primitives; if you want strict Phase-5 UX (proposal turn -> explicit approve/deny/revoke turn -> executed artifact turn), we should wire a dedicated turn router path that emits exactly one artifact each turn.

2. **Audit log redaction path parity**
   - `ArtifactStore` has redaction, while Istari `AuditLog` currently writes directly. If you want hard consistency, we should route Istari event writes through the same redaction helper pipeline.

3. **Command allowlist policy breadth**
   - Current allowlist defaults are conservative. If real workflows need broader command coverage, we should expand incrementally with explicit tests and per-command policy notes.

4. **Latency instrumentation**
   - Fast-path bypass logic exists, but we do not yet publish explicit p50/p95 metrics for “read-only turn with pending approvals present” vs baseline. If you want confidence at scale, add lightweight timers and a perf regression check.

---

## Recommendation

Given your priorities (UX + security + low latency + no drama), the next safest route is:
- keep current hardening,
- add end-to-end Istari orchestration behind a feature flag,
- instrument latency before enabling by default.

That gives you reversible rollout while preserving current user experience.


## G) Follow-up fixes now implemented

Based on your approval to apply all suggestions, these additional changes were completed:

1. **Istari runtime command protocol wired**
   - Added `executive/istari_runtime.py` with a deterministic turn protocol for:
     - proposal creation (from `run tool ...`)
     - `approve <proposal_id>`
     - `deny|reject`
     - `revoke <token|proposal|all>`
     - `execute <proposal_id> <token>`
   - Enforces one-artifact-per-turn by persisting only the relevant artifact type per protocol command.

2. **Audit redaction parity**
   - `AuditLog` in `executive/istari.py` now routes events through the same redaction helper used by `ArtifactStore` before writing `audit/events.jsonl`.

3. **Allowlist policy practicality**
   - Preserved conservative defaults in config, while hardening step-level normalization/validation in enforcement path to support controlled incremental broadening later without policy drift.

4. **Latency instrumentation + fast-path hardening**
   - `Agent` now records lightweight turn performance samples (`controller_ms`, `istari_ms`, route, read-only fast-path flag).
   - Controller invocation no longer triggers solely because a pending ticket exists, preventing unnecessary latency on read-only turns.
   - Added periodic read-only fast-path perf logging (average controller ms).

5. **Additional regression tests**
   - Added protocol + redaction tests (`tests/test_istari_protocol.py`).
   - Added async agent test proving read-only turns bypass controller even with pending ticket (`tests/test_artifacts_phase4_agent_async.py`).


## H) Extra audit loop (post-protocol integration)

### Simulate
- Approve with no pending proposal.
- Execute with invalid token format/value.
- Revoke flow producing audit rows with missing identifiers.

### Audit
- Some negative-path artifacts used empty placeholder fields (`proposal_id`, `token_digest`) that can weaken strict contract compatibility downstream.
- Minor test hygiene issue (dead local variable) in protocol test.
- Missing Executive folder README for onboarding/interoperability context.

### Patch
- Strengthened negative-path payloads in `IstariProtocol` to always include stable non-empty placeholders where needed.
- Ensured invalid-token execution failure emits deterministic digest-based `token_digest` value.
- Added `executive/README.md` documenting architecture, interoperability, safety model, and extension guidance.
- Added tests for approve-without-pending and execute-invalid-token paths.

### Result
- No known failing cases in targeted governance/protocol/async regression suite after patch.
