# Continuity Workflows

Continuity workflows are compact offline playbooks that turn bundled knowledge
packs into actionable checklists.

## Current Domains

- sanitation
- health
- food
- power

## Why They Exist

- keep recovery guidance structured when the web is unavailable
- make workflow execution resumable through Somi's existing workflow runtime
- give operators a safe checklist format that works on weak hardware

## CLI

```powershell
somi offline continuity --root C:\somex --runtime-mode survival --query "restore shelter power"
```

## Implementation Notes

- manifests live in `workflow_runtime/manifests/`
- bundled source packs live in `knowledge_packs/`
- the continuity snapshot ranks workflows against a query and the current
  hardware-aware pack catalog
