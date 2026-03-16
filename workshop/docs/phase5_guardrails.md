# Phase 5 Guardrailed Capability Layer

## Step 0 discovery notes (hook points)

- Universal artifact envelope normalization is in `handlers/contracts/base.py` (`normalize_envelope`).
- Artifact strict validators/registry are in `handlers/contracts/schemas.py` (`STRICT_VALIDATORS`, `validate_artifact`).
- Artifact append-only store and indexes are in `handlers/contracts/store.py` (`append`, global indexes).
- Router signal structure is in `handlers/routing.py` (`RouteDecision.signals`, `decide_route`).
- Existing approval/controller path is in `runtime/controller.py` and is invoked from `agents.py`.
- Redaction prior to artifact write is handled in `ArtifactStore._redact_value` inside `handlers/contracts/store.py`.
- Existing executive queue infra is in `executive/queue.py` and `executive/engine.py`.
- Test layout for governance/artifacts is under `tests/` (e.g. `tests/test_governance.py`, `tests/test_artifacts_phase4.py`).

## What was added in Phase 5

- New deterministic capability layer module: `executive/istari.py`.
- New safe-by-default registry config: `config/capability_registry.json`.
- New Phase 5 contract validators:
  - `proposal_action`
  - `approval_token`
  - `executed_action`
  - `denied_action`
  - `revoked_token`

## Latency guardrails (important)

To avoid latency regressions for safe requests:

- `handlers/routing.py` now sets `signals.requires_execution = false` and `signals.read_only = true` for read-only routes (websearch/weather/news/finance/story/llm_only style flows).
- `agents.py` now bypasses the controller/approval path unless execution semantics are present (tool run, approval/revoke style command, pending ticket, or a route explicitly marking `requires_execution=true`).

This preserves fast path behavior for normal retrieval and LLM-only turns.
