# somicontroller_parts

Split helpers for the main desktop shell in
[`somicontroller.py`](/C:/somex/somicontroller.py).

This package exists to keep the GUI controller understandable without pushing
all runtime wiring into one giant file.

## Start Here

- `bootstrap_methods.py`
  - startup wiring for services, stores, themes, and studio snapshots
- `layout_methods.py`
  - premium shell layout, panel composition, and Research Pulse widgets
- `runtime_methods.py`
  - runtime-bound actions that bridge UI events to agent/control services
- `status_methods.py`
  - shell status text, heartbeat/pulse summaries, and compact progress helpers
- `settings_methods.py`
  - persisted UI settings, theme state, and startup preference recovery
- `studio_methods.py`
  - helpers that refresh and synchronize Research Studio, Coding Studio, and
    Control Room data
- `fetch_methods.py`
  - background fetch helpers used by shell panels

## How To Read This Layer

1. Read [`somicontroller.py`](/C:/somex/somicontroller.py) to see the shell
   entry point and imports.
2. Follow into `bootstrap_methods.py` to see how services are attached.
3. Use `layout_methods.py` and `status_methods.py` for the visible shell state.
4. Use `runtime_methods.py` when tracing a user action into the runtime.

## Common Contributor Tasks

- Add a new shell card or panel:
  - start in `layout_methods.py`
- Surface new runtime status:
  - start in `status_methods.py`
- Add a persisted GUI preference:
  - start in `settings_methods.py`
- Wire a new studio refresh path:
  - start in `studio_methods.py`
