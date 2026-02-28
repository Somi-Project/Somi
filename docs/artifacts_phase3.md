# Artifacts Phase 3

## Universal envelope
All persisted artifact JSONL entries now use a normalized envelope with these required top-level fields:

- `artifact_id`
- `session_id`
- `timestamp`
- `contract_name`
- `contract_version`
- `schema_version`
- `route`
- `trigger_reason` (`explicit_request`, `matched_phrases`, `structural_signals`, `tie_break`)
- `confidence`
- `input_fingerprint`
- `data`
- `extra_sections`
- `warnings`
- `revises_artifact_id`
- `diff_summary`

Backward aliases (`artifact_type`, `content`, `created_at`) remain populated for compatibility.

## Precedence and evidence thresholds
Contract selection is deterministic with precedence:

1. `meeting_summary`
2. `action_items`
3. `decision_matrix`
4. `status_update`
5. `research_brief`
6. `doc_extract`
7. `plan`

Selection rules:
- Explicit request wins if its contract is eligible.
- Otherwise, first eligible contract in precedence order is selected.
- Tie-break decision is stored in `trigger_reason.tie_break`.
- Conservative gates prevent over-triggering (e.g., `decision_matrix` needs >=2 options, `plan` blocked for educational “steps of ...” prompts).

## Validation caps and invariants
`validate_artifact(contract_name, payload)` is the single strict entrypoint.

Enforced in strict validation:
- Unknown fields rejected at contract payload level.
- Contract-specific caps on list sizes and string lengths.
- `decision_matrix` invariants:
  - options in range 2–8
  - criteria weights sum to 1.0 within 0.999–1.001
  - scores cover full option×criterion matrix
  - score bounds 1–5
- `action_items` invariants:
  - each item requires `task`
  - `owner` defaults to `Unassigned`
  - `due` nullable

If validation fails, artifact orchestration fails safe and the assistant returns normal response content without persisting JSONL.

## Revision metadata and diff summaries
Revisions include:
- `revises_artifact_id`
- `diff_summary`

Plan revision artifacts now emit stable summary text documenting retained steps and added constraints.

## Secret redaction policy
Before persistence, artifact payloads are scanned for obvious secrets/tokens and replaced with `[REDACTED]`:

- `sk-...` style API keys
- `ghp_...` GitHub tokens
- `Bearer ...` tokens
- private key blocks (`BEGIN PRIVATE KEY`)
- long token-like blobs

When redaction occurs, a warning is appended:
- `Potential secret redacted`

## Index and retrieval API
Per-session read index file:
- `sessions/artifacts/<session_id>.index.json`

Store APIs:
- `get_last(session_id, contract_name)`
- `get_by_id(session_id, artifact_id)`

Index is read-only optimization; JSONL remains source-of-truth. Missing/corrupt index rebuilds from JSONL.

## Stress/golden tests
Run:

```bash
pytest tests/test_artifacts_phase1.py tests/test_artifacts_phase2.py tests/test_artifacts_phase3.py
```

The phase 3 tests cover:
- precedence determinism
- validation fallback behavior
- no-write on failed validation path
- secret redaction
- action_items + status_update triggers and schemas
- plan revision metadata and retrieval/index behavior
