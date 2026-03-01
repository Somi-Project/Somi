# Strategic Layer Debug Review (latest pass)

## Implemented from your requested next patch

1. Expanded execution-bypass vocabulary **just enough** via config:
   - Added configurable `STRATEGIC_EXECUTION_BYPASS_PHRASES` (default: `do it`, `apply`, `run`, `execute`, `proceed now`).
   - Routing bypass now consumes this setting through policy helpers.

2. Added optional human-readable adapter (display-only):
   - New `executive/strategic/human_summary.py` with minimal renderer.
   - Agent can append a short summary to returned text when `STRATEGIC_HUMAN_SUMMARY_ENABLED=True`.
   - Stored artifact payload remains strict JSON and unchanged.

3. Added explicit fallback template for missing original plan ID:
   - New fallback artifact type: `plan_revision_missing_original`.
   - Returned when user requests plan revision but no `original_plan_id` is available.
   - Explicitly requests `original_plan_id` with examples.

4. Lookup overhead middle-ground (kept lightweight):
   - No index-backed resolver added.
   - Existing bounded allowlist set-membership resolver retained (O(1), low overhead).

## Additional hardening retained
- Short-lived context pack cache in Agent to reduce repeated disk reads.
- Non-autonomy and forbidden-key protections remain in place.

## Current known non-blocking greyzone
1. Human summary text style could be tuned per persona/UX surface.
2. Fallback artifact type `plan_revision_missing_original` remains UX-focused and now has explicit validator coverage plus markdown rendering support.

## Latest cycle fixes
- Added explicit validator coverage for `plan_revision_missing_original`.
- Ensured planner validates fallback artifact before returning it.
- Fixed agent envelope typing to use actual emitted artifact type (prevents mislabeling fallback as `plan_revision`).

- Strategic optional human summary is display-only and not persisted into chat history context; history stores strict JSON payload to reduce clutter.

- Strategic requests now bypass continuity/heartbeat early-return paths to avoid being shadowed by non-strategic artifacts.
