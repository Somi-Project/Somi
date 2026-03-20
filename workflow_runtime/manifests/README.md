Workflow manifests live here.

Each manifest is a JSON document that declares:

- `manifest_id`
- `name`
- `description`
- `script`
- `allowed_tools`
- `backend`
- `timeout_seconds`
- `max_tool_calls`
- `metadata`

The Phase 6 runner executes these scripts through a restricted Python subset.
Scripts do not get raw imports, file access, or arbitrary builtins.
They call approved tools through `tool(...)`, can add notes with `emit(...)`,
and should write their final output to `result`.

Current bundled examples include:

- `research_digest`
- `continuity_sanitation`
- `continuity_power_recovery`
- `continuity_food_startup`
- `continuity_field_health`
