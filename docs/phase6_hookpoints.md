# Phase 6 Discovery Notes (Heartbeat + Personalization)

Discovered modules and hook points used for this implementation:

- Universal artifact envelope: `handlers/contracts/base.py`
  - `build_base(...)` and `normalize_envelope(...)` are the canonical envelope creators/normalizers.
- Schema registry + validators: `handlers/contracts/schemas.py`
  - `STRICT_VALIDATORS` and `MARKDOWN_RENDERERS` are the artifact schema registry entrypoints.
- Artifact store + JSONL + index snapshot: `handlers/contracts/store.py`
  - `ArtifactStore.append(...)` writes JSONL artifacts.
  - `ArtifactStore.get_index_snapshot(...)` provides CPU-first indexed snapshot (no full scan).
- Phase 4 continuity fields: `handlers/contracts/base.py`, `handlers/continuity.py`
  - `thread_id`, `tags`, `status`, and `task_state` generation already wired in Phase 4.
- Phase 5 approval/capability pipeline: `runtime/controller.py`, `executive/istari.py`, `executive/istari_runtime.py`
  - `proposal_action` artifacts and approval token issuance are gated there.
  - Phase 6 heartbeat artifacts deliberately avoid `proposal_action` creation.
- Router/dispatcher intent entrypoint: `handlers/routing.py` + `agents.py`
  - `decide_route(...)` decides route, and `Agent.generate_response(...)` is the safe single-turn insertion point.
- Redaction/secret scrubbing: `handlers/contracts/store.py`
  - `ArtifactStore._redact_value(...)` is reused via normal artifact persistence path.

Phase 6 hook inserted in `agents.py` before normal response generation path and after continuity shortcut. This preserves one-artifact-per-turn while keeping read-only websearch/weather/news/finance/story routes unchanged unless explicit heartbeat triggers/proactivity conditions match.
