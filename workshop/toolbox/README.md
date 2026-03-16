# Workshop Toolbox

Toolchain for building, registering, dispatching, and running internal tools.

## Core Modules
- `builder`, `installer`, `loader`, `dispatch`, `registry`, `runtime`
- `bridge` for internal create/dispatch helpers used by executive and skills paths
- `sync_registry` for hash/manifest reconciliation
- scaffolding templates in `templates/`

## Stack Entry Points
Tool wrappers in `workshop/tools/installed/*/tool.py` route to toolbox stacks:
- `workshop.toolbox.stacks.web_intelligence`
- `workshop.toolbox.stacks.research_artifact`
- `workshop.toolbox.stacks.ocr_stack`
- `workshop.toolbox.stacks.image_tooling`

## Migrated Internal Packages
- `workshop.toolbox.stacks.ocr_core`
- `workshop.toolbox.stacks.contracts_core`
- `workshop.toolbox.stacks.image_core`
- `workshop.toolbox.stacks.research_core`
- `workshop.toolbox.stacks.web_core`
- `workshop.toolbox.agent_core`

## Integrations
- `workshop.integrations.telegram`
- `workshop.integrations.twitter`
- `workshop.integrations.audio`

## Specs and Backlog
- `SKILLS_TOOL_SCAFFOLD_SPEC.md`: future conversion contract for `SKILL.md -> tool scaffold`
- `MIGRATION_KIT.md`: future external tool import and adaptation flow

## CLI Health
- `python -m workshop.cli.cli_toolbox tool-health`
