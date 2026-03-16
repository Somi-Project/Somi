# Tool Migration Kit (Backlog)

Planned future capability:
- Import an external tool folder.
- Validate `manifest.json` + `tool.py` contract (`run(args, ctx)`).
- Auto-fix common path/import issues to Somi workspace layout.
- Stage in `workshop/tools/.staging/<job_id>/...`.
- Re-hash and register into `workshop/tools/registry.json`.

Related spec:
- `workshop/toolbox/SKILLS_TOOL_SCAFFOLD_SPEC.md` (defines conversion from `SKILL.md` into a tool scaffold).

Not implemented yet:
- Code auto-heal/refactor for incompatible tools.
- Automatic dependency remapping.
- Automatic behavior regression tests.
