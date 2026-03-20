# coding

Somi's local coding control plane.

This package is the backbone for Coding Studio, bounded repo edits, verify
loops, sandbox workspaces, git actions, and coding-session memory.

## Start Here

- `control_plane.py`
  - the main Codex-style entry point used by the GUI and runtime integrations
- `service.py`
  - session lifecycle, job state, and coding-mode orchestration
- `workspace.py`
  - managed workspaces and session-root handling
- `sandbox.py`
  - snapshot prep, sandbox inventory, and workspace isolation helpers
- `tooling.py`
  - file reads/writes, rollbacks, verify loops, and workspace inspection
- `git_ops.py`
  - git status, diff, commit, and publish helpers
- `repo_map.py`
  - project context maps and repo understanding summaries
- `scratchpad.py`
  - compaction-friendly coding summaries and working memory
- `scorecards.py`
  - environment and task-health summaries
- `jobs.py`, `store.py`, `models.py`
  - persisted coding job/session state

## Typical Contributor Paths

- Add a new coding action:
  - start in `control_plane.py`, then `tooling.py` or `git_ops.py`
- Improve workspace/session behavior:
  - start in `service.py`, `workspace.py`, and `jobs.py`
- Improve code understanding or session compaction:
  - start in `repo_map.py` and `scratchpad.py`

## Related Surfaces

- [`gui/codingstudio.py`](/C:/somex/gui/codingstudio.py)
- [`gui/codingstudio_data.py`](/C:/somex/gui/codingstudio_data.py)
- [`docs/architecture/CONTRIBUTOR_MAP.md`](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md)
