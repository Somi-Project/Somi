# tests

Focused regression packs for Somi subsystems and upgrade phases.

## What Lives Here

- phased runtime tests
- coding/coding-studio tests
- docs and ops regression checks
- Telegram, OCR, autonomy, and release-readiness tests

## Reading Order

1. find the subsystem you are touching
2. read the nearest `test_*` file here
3. read any matching root-level `test_*.py` integration test next

## Good Contributor Habit

When adding a new subsystem capability, add:

- one focused regression in `tests/`
- one broader integration check if the change crosses GUI/runtime boundaries
