# Recovery Playbook

Use this file when context compaction, bad refactors, or partial edits create uncertainty.

## First Checks

1. Read [upgradeplan.md](/C:/somex/upgradeplan.md).
2. Read [SYSTEM_MAP.md](/C:/somex/docs/architecture/SYSTEM_MAP.md).
3. Read [BOUNDARIES.md](/C:/somex/docs/architecture/BOUNDARIES.md).
4. Open the latest matching backup folder under [backups](/C:/somex/backups).

## Current Split Anchors

- [agents_split_reference.md](/C:/somex/agents_split_reference.md)
- [somicontroller_split_reference.md](/C:/somex/somicontroller_split_reference.md)

## Recovery Principle

Do not rebuild blind.

Always prefer:

1. reading the latest phase backup,
2. comparing against the split reference files,
3. restoring or reapplying focused changes from the backup,
4. re-running the test suite before continuing.

## Phase Backups

Phase backups are stored under [backups](/C:/somex/backups) using a phase-oriented folder pattern.

Example:

- `backups/phase01_YYYYMMDD_HHMMSS/`

Minimum backup contents before a phase begins:

- active wrapper files
- extracted method packages
- current roadmap documents
- any package directly touched by the upcoming phase

## If A File Gets Re-Monolithed

1. Restore the last good wrapper and extracted package from backup.
2. Use the split reference file as the source of truth for where logic belongs.
3. Re-run:

```powershell
.\.venv\Scripts\python -m pytest tests
```

## If State Goes Out Of Sync

Check these directories first:

- [sessions/state_ledger](/C:/somex/sessions/state_ledger)
- [sessions/task_graph](/C:/somex/sessions/task_graph)
- [sessions/plan_executor](/C:/somex/sessions/plan_executor)
- [sessions/logs](/C:/somex/sessions/logs)

## If The Plan Is Lost

The minimum restoration order is:

1. [upgradeplan.md](/C:/somex/upgradeplan.md)
2. [docs/architecture/system_manifest.json](/C:/somex/docs/architecture/system_manifest.json)
3. latest relevant backup folder
