# ops

Operational health, release readiness, and repair helpers for Somi.

## Start Here

- `doctor.py`
  - high-level framework health report
- `release_gate.py`
  - readiness scoring, subsystem dashboards, and release summaries
- `backup_creator.py`
  - phase-safe backup creation
- `backup_verifier.py`
  - backup validation and recovery confidence checks
- `docs_integrity.py`
  - contributor-doc coverage checks
- `security_audit.py`
  - security and policy findings
- `support_bundle.py`
  - support/export snapshot generation
- `replay_harness.py`
  - replay-based runtime validation
- `hardware_tiers.py`
  - consumer-hardware tier detection and survival-mode recommendations

## Use This Package When

- you are preparing a release or investigating readiness gaps
- you need a reliable pre-phase backup or rollback checkpoint
- you want operational diagnostics instead of product behavior
