# Phase 4: Stateful Continuity

Phase 4 adds deterministic, suggestion-only cross-session continuity.

## What changed

- Universal artifact envelope now supports optional continuity metadata:
  - `tags`, `status`, `related_artifact_ids`, `parent_artifact_id`, `thread_id`, `continuity`.
- New artifact contracts:
  - `artifact_continuity`
  - `task_state`
- Global compact indexes (append/update on write):
  - `sessions/artifacts/index/thread_index.json`
  - `sessions/artifacts/index/tag_index.json`
  - `sessions/artifacts/index/status_index.json`
- Continuity engine hook runs after routing and before normal responder.
  - If confidence passes threshold, returns exactly one `artifact_continuity` artifact and exits turn.

## Determinism and safety

- Continuity emits suggestions only.
- `continuity.no_autonomy` is always true.
- No execution, no Agentpedia writes, no background jobs are triggered by continuity.
- Tags are normalized and capped.
- Link edges are capped (`related_artifact_ids` max 20).

## Rebuilding indexes

Manual developer CLI:

```bash
python cli_toolbox.py artifacts rebuild-index
python cli_toolbox.py artifacts compact-index --max-age-days 180
python cli_toolbox.py artifacts compact-index --max-age-days 180 --no-adaptive
```

## Disable continuity

Set `ENABLE_NL_ARTIFACTS=false` to disable artifact orchestration (including continuity hook).


## Adaptive compaction

- Default compaction is adaptive (`compact-index` without `--no-adaptive`).
- Adaptive mode keeps active/open thread/status rows longer while still trimming stale historical rows by age.
- Use `--no-adaptive` for strict age-cutoff behavior.
