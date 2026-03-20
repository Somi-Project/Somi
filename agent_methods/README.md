# agent_methods

Split agent behavior helpers used by the compatibility agent/runtime layer.

These modules keep major behavior categories separated so the agent surface does
not collapse back into one giant monolith.

## Key Files

- `response_methods.py`
  - response shaping and reply helpers
- `search_memory_methods.py`
  - search and memory-oriented agent helpers
- `coding_methods.py`
  - coding-mode agent behavior
- `text_methods.py`
  - text cleanup and formatting helpers
- `history_methods.py`
  - session/history-aware behavior
- `model_methods.py`
  - model/runtime binding helpers
- `subagent_methods.py`
  - subagent-facing helpers

## Read This Package When

- you are tracing the agent compatibility layer rather than the lower stacks
- you want to understand how the agent assembles behaviors from split helpers
- you are trying to move behavior out of `agents.py` without losing structure
