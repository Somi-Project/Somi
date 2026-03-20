# Newcomer Checklist

Use this when you are new to Somi and want the shortest safe path to a useful
change.

## First Debugging Steps

1. Read [`CONTRIBUTOR_MAP.md`](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md).
2. Create a focused checkpoint with `somi backup create`.
3. Read the nearest folder `README.md` for the area you plan to touch.
4. Find the existing regression test for that area before editing code.
5. Make the smallest coherent change you can explain in one paragraph.

## Where To Add Tests

- `tests/`
  - phased runtime, ops, Telegram, coding, and release tests
- root `test_*.py`
  - GUI and shell integration coverage
- `executive/memory/tests/`
  - memory-specific coverage

## Safe Edit Checklist

- confirm the user-visible behavior you are changing
- check whether the area already has a phase log entry
- avoid touching weather/news/finance unless there is a direct bug
- keep new docs and tests close to the changed subsystem
- rerun focused tests before broader validation

## Before You Open A Big Refactor

- trace the current entry point
- identify the nearest owner package
- write down the invariants that must stay true
- create a pre-refactor backup
- prefer adding a map or guardrail before moving major code
