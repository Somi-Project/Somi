# Debug + Audit Report (GUI Personality Selector pass)

## Goal
Implement a personality dropdown in the main GUI (`somicontroller.py`) so switching personality updates:
1. chat personality selection, and
2. `config/assistant_profile.json` `active_persona_key`.

---

## Simulation → Debug → Plan → Patch (Cycle 1)

### Simulate
- Audited GUI flow:
  - main window quick actions (`build_quick_action_bar`),
  - chat launcher (`open_chat`),
  - chat subwindow selector (`gui/aicoregui.py`).
- Found no main-window personality selector bound to assistant profile state.

### Debug
- Existing behavior only used chat dialog agent combo and defaulted to first persona.
- `assistant_profile.json` could drift from GUI-selected persona unless changed by heartbeat runtime fallback.

### Plan
- Add a dedicated personality dropdown in main quick-action bar.
- Load initial selection from `assistant_profile.json`.
- Persist changes back to `assistant_profile.json` immediately on selection.
- Keep chat window default in sync with selected personality.

### Patch
- `somicontroller.py`:
  - imported `QComboBox`, `load_assistant_profile`, `save_assistant_profile`.
  - added assistant profile path constant.
  - added helpers:
    - `_selected_agent_name()`
    - `_load_selected_agent_key()`
    - `_persist_selected_agent_key()`
    - `on_persona_changed()`
  - added **Personality dropdown** to `build_quick_action_bar()`.
  - updated `open_chat()` and preload path to honor selected persona.
- `gui/aicoregui.py`:
  - chat selector now defaults to `app.selected_agent_key`.
  - start/apply paths persist selected persona via app hooks.

---

## Repeat Simulation → Patch if needed (Cycle 2)

### Simulate
- Reviewed interaction between main dropdown and active chat worker.
- Noticed potential UX regression: switching persona in main GUI forced `use_studies=True` in worker update.

### Debug
- This could unexpectedly change the user’s current RAG preference when only persona should change.

### Plan
- Preserve existing worker `use_studies` state during personality switch.

### Patch
- `somicontroller.py` `on_persona_changed()` now reads current worker `use_studies` and reuses it when calling `update_agent(...)`.

---

## Validation
- `python -m py_compile somicontroller.py gui/aicoregui.py agents.py handlers/heartbeat.py tests/test_phase6_heartbeat.py tests/test_artifacts_phase4_agent_async.py`
- `pytest -q tests/test_phase6_heartbeat.py tests/test_artifacts_phase4.py tests/test_artifacts_phase4_agent_async.py`
- Result: all targeted tests pass.

---

## Answer to design question
- `personalC.json` should remain the **persona catalog** (definitions/content).
- `assistant_profile.json` should remain the **runtime overlay** (active pointer + knobs + timestamps).
- They are intentionally different responsibilities; the dropdown writes only the pointer (`active_persona_key`) to profile, not duplicate persona content.

---

## Simulation → Audit → Plan → Patch (Merge-readiness pass)

### Simulate
- Re-ran targeted tests and re-audited GUI persona wiring paths (`refresh_agent_names`, preload warmup path, chat open/apply sync).

### Audit findings
1. Warmup path still instantiated chat worker with `_default_agent_key()` instead of currently selected persona.
2. Persona dropdown options were not refreshed when persona catalog list changed at runtime (possible stale UI list).

### Plan
- Route warmup worker creation through `selected_agent_key` with fallback safety.
- Make `refresh_agent_names()` keep the dropdown model synchronized and preserve selection where possible.

### Patch
- Updated `_on_agent_warmed(...)` to use selected persona key (with validity fallback).
- Updated `refresh_agent_names()` to repopulate `persona_combo` safely while preserving a valid selected item and avoiding recursive signal emissions.

### Merge-readiness
- No failing targeted tests.
- No schema/runtime regressions detected in heartbeat-related suites.
- GUI personality selection now consistently drives preload + chat defaults + persisted profile pointer.

---

## Final audit mini-patch

### Audit finding
- If persona catalog changes removed/renamed the currently selected key, `refresh_agent_names()` corrected in-memory selection but did not persist the corrected key to `assistant_profile.json`.

### Patch
- `refresh_agent_names()` now persists corrected fallback key via `_persist_selected_agent_key(...)` when drift is detected.

### Result
- GUI selection, runtime selection, and persisted profile pointer remain convergent after catalog churn.
