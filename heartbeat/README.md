# Heartbeat subsystem

This folder contains periodic assistant pulse tasks and user-facing heartbeat artifacts.

## Romeo & Juliet naming

The old numbered lifecycle names were removed in favor of themed names:

- `montague_context` = context graph / life-modeling enrichment lane.
- `capulet_strategy` = strategic analysis routing lane.
- `duel_approval_required` = execution guardrail flag (approval required before any execution).

## Debugging checklist

1. Verify heartbeat routing input in `handlers/heartbeat.py` and `handlers/routing.py`.
2. Confirm automatic brief policy with global proactivity flags in `config/settings.py`.
3. Validate emitted artifacts include `no_autonomy: true` and guardrails.
4. Confirm calls into `executive.life_modeling.run_montague_context_if_enabled` succeed and are debounced.
5. Run focused tests:
   - `pytest -q tests/test_phase6_heartbeat.py` (legacy filename for heartbeat regression tests)
   - `pytest -q tests/test_proactivity_layer.py`

## Common failure signatures

- Missing context updates: inspect Montague debounce/telemetry files under `executive/index/`.
- Unexpected immediate pings: inspect proactivity caps in `config/settings.py` and `executive/proactivity/router.py`.
- Strategy route mismatch: inspect `capulet_artifact_type` signal production in `handlers/routing.py`.
