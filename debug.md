# Phase 7 Debug Notes

## Completed checks
- Added optional remote read-only calendar providers (Google/MS Graph) in fail-closed token-consumer mode.
- Added artifact-store sharding + optional primary mirroring.
- Added goal-link confirmation queue.
- Added sparse-data bootstrap relaxation mode for clustering to avoid empty early UX.
- Reduced memory pressure in Phase 7 JSONL ingestion by bounded tail-byte reads (`PHASE7_JSONL_TAIL_READ_BYTES`).
- Hardened goal-link resolution to update the latest goal_model revision for the goal.
- Upgraded Executive GUI queue UX from ID-only flow to table-selection flow with row-select approve/reject support.
- Added queue table scaling ergonomics:
  - client-side text filter
  - structured status preset (`pending|approved|rejected|all`)
  - structured date-range filtering (`from` / `to` YYYY-MM-DD)
  - table sorting on columns
- Added queue action affordance:
  - Approve/Reject buttons disabled until a valid proposal id is selected/entered.
- Added lifecycle telemetry:
  - queue depth trend (`current_depth`, `max_depth_seen`, samples)
  - approval/rejection counts + approval latency stats
  - shard file growth (`current_files`, `max_files_seen`, samples)
- Added GUI-oriented test coverage for proposal-id validator and date parser helpers (skips when PyQt6 missing).

## Simulation + audit loops
1. Loop 1 (suite): full Phase 7 + heartbeat tests passed.
2. Loop 2 (runtime smoke): py_compile + queue/provider simulations passed.
3. Loop 3 (structured filter hardening): status/date filters + API list-by-status patched; regression tests passed.

## Remaining merge-risk items
1. Optional future enhancement: persisted filter presets and saved queue views.
2. OAuth refresh/exchange remains intentionally deferred to future modular auth/email layer work.
