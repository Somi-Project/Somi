# state

Persistent runtime state stores shared across higher-level services.

## Key Files

- `store.py`
  - event and session-state persistence helpers

## Read This Package When

- a feature needs durable state outside of a single request
- you are tracing how runtime history or session events are persisted
- you need a simple place to start before following state usage upward into
  GUI, gateway, or executive layers
