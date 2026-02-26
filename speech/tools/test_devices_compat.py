"""Compatibility tests for cross-platform device resolution."""

from __future__ import annotations

import pytest

# Avoid hard-exit during pytest collection when optional dependency is absent.
devices = pytest.importorskip(
    "speech.io.devices", reason="sounddevice unavailable in environment"
)


def test_devices_compat_resolution() -> None:
    orig_list_devices = devices.list_devices
    orig_list_hostapis = devices.list_hostapis
    try:
        devices.list_devices = lambda: [
            {
                "name": "Mic A",
                "hostapi": 0,
                "max_input_channels": 2,
                "max_output_channels": 0,
            },
            {
                "name": "Speakers WASAPI",
                "hostapi": 1,
                "max_input_channels": 0,
                "max_output_channels": 2,
            },
            {
                "name": "USB Headset",
                "hostapi": 2,
                "max_input_channels": 1,
                "max_output_channels": 2,
            },
        ]
        devices.list_hostapis = lambda: [
            {"name": "Core Audio"},
            {"name": "Windows WASAPI"},
            {"name": "ALSA"},
        ]

        assert devices.resolve_device("Mic", kind="input", os_profile="mac") == 0
        assert devices.resolve_device("Speakers", kind="output", os_profile="windows") == 1
        assert devices.resolve_device("Headset", kind="output", os_profile="linux") == 2
        assert devices.resolve_device("2", kind="output", os_profile="auto") == 2
        assert devices.resolve_device(None, kind="input", os_profile="auto") is None
    finally:
        devices.list_devices = orig_list_devices
        devices.list_hostapis = orig_list_hostapis
