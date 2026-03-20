# Somi Deploy

This folder holds deployment profiles and rollout helpers for different Somi
environments.

Main files:
- `profiles.py`: named deployment or runtime profile definitions.
- `rollouts.py`: rollout helpers for packaging and environment transitions.

For basic users:
- Most local users can ignore this folder unless they are preparing a release or
  switching installation style.

For developers:
- Keep deployment concerns separated from core cognition and runtime logic.
- This is the right place for packaging profiles, distribution defaults, and
  rollout helpers that support Somi's direct-download and self-hosted identity.
