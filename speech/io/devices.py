from __future__ import annotations

from typing import Any

import sounddevice as sd


def list_devices() -> list[dict[str, Any]]:
    devices = sd.query_devices()
    # sounddevice can return DeviceList-like object; normalize to list[dict]
    return [dict(d) for d in devices]


def list_hostapis() -> list[dict[str, Any]]:
    apis = sd.query_hostapis()
    return [dict(a) for a in apis]


def _as_index(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _hostapi_priority(os_profile: str | None) -> tuple[str, ...]:
    profile = (os_profile or "auto").lower()
    if profile == "windows":
        return ("wasapi", "wdm-ks", "mme", "directsound")
    if profile == "mac":
        return ("core audio",)
    if profile == "linux":
        return ("pipewire", "pulse", "alsa", "jack")
    # auto: attempt all common profiles in a practical order
    return ("wasapi", "core audio", "pipewire", "pulse", "alsa", "jack", "mme", "directsound")


def resolve_device(
    device: int | str | None,
    *,
    kind: str,
    os_profile: str | None = "auto",
) -> int | None:
    """Resolve an input/output device index from index or name-substring.

    kind: 'input' or 'output'.
    """
    if device is None or (isinstance(device, str) and not device.strip()):
        return None

    if isinstance(device, int):
        return device

    raw = str(device).strip()
    idx = _as_index(raw)
    if idx is not None:
        return idx

    devices = list_devices()
    hostapis = list_hostapis()
    raw_lower = raw.lower()
    key = "max_input_channels" if kind == "input" else "max_output_channels"

    candidates = []
    for i, dev in enumerate(devices):
        if int(dev.get(key, 0) or 0) <= 0:
            continue
        name = str(dev.get("name", ""))
        if raw_lower in name.lower():
            hostapi_idx = int(dev.get("hostapi", -1) or -1)
            hostapi_name = ""
            if 0 <= hostapi_idx < len(hostapis):
                hostapi_name = str(hostapis[hostapi_idx].get("name", "")).lower()
            candidates.append((i, hostapi_name, name))

    if not candidates:
        return None

    priorities = _hostapi_priority(os_profile)
    for pref in priorities:
        for i, host_name, _dev_name in candidates:
            if pref in host_name:
                return i

    return candidates[0][0]
