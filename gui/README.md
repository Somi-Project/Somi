# gui

PyQt desktop interface for Somi.

## Contents
- chat panel/popout
- module control panels
- theme loading and UI assets integration
- premium cockpit shell and dashboard clusters
- research pulse, coding studio, and control room surfaces

## Start Here

- shell entry:
  - [`somicontroller.py`](/C:/somex/somicontroller.py)
- split controller helpers:
  - [`somicontroller_parts/README.md`](/C:/somex/somicontroller_parts/README.md)
- theme system:
  - [`themes/README.md`](/C:/somex/gui/themes/README.md)
- contributor map:
  - [`docs/architecture/CONTRIBUTOR_MAP.md`](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md)

## Main Surfaces

- `chatpanel.py`
  - primary conversation surface
- `aicoregui.py`
  - shell-level rendering helpers for browse traces, trust signals, and chat UX
- `codingstudio.py`
  - coding workstation
- `researchstudio.py`
  - research workstation
- `controlroom.py`
  - operator and observability surface
- `themes/`
  - light, shadowed, and dark premium themes plus shared cockpit styling

## Good First Debug Paths

- if the premium shell looks cramped or misaligned:
  - [`somicontroller_parts/layout_methods.py`](/C:/somex/somicontroller_parts/layout_methods.py)
- if browse traces or research pulse details look wrong:
  - [`aicoregui.py`](/C:/somex/gui/aicoregui.py)
  - [`researchstudio.py`](/C:/somex/gui/researchstudio.py)
- if coding-specific UI feels off:
  - [`codingstudio.py`](/C:/somex/gui/codingstudio.py)
  - [`codingstudio_data.py`](/C:/somex/gui/codingstudio_data.py)
