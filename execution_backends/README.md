# execution_backends

Execution backend contracts and implementations.

This layer lets Somi run work through different execution environments without
rewriting higher-level coding or runtime logic each time.

## Key Files

- `base.py`
  - backend interface and shared behavior
- `factory.py`
  - backend selection
- `local_backend.py`
  - local execution backend

## Read This Package When

- you are changing how Somi chooses an execution environment
- you want to add another backend
- you are debugging local execution behavior below the coding/runtime layers
