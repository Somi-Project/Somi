"""List audio devices and suggested Somi input/output device indexes."""

from __future__ import annotations

import argparse

from speech.io.devices import default_device_for_kind, list_devices, list_hostapis


def main() -> None:
    p = argparse.ArgumentParser(description="List audio devices and host APIs")
    p.add_argument("--os-profile", choices=["auto", "windows", "mac", "linux"], default="auto")
    args = p.parse_args()

    hostapis = list_hostapis()
    devices = list_devices()
    in_idx = default_device_for_kind("input", os_profile=args.os_profile)
    out_idx = default_device_for_kind("output", os_profile=args.os_profile)

    print(f"Suggested input index ({args.os_profile}): {in_idx}")
    print(f"Suggested output index ({args.os_profile}): {out_idx}")
    print()
    for i, dev in enumerate(devices):
        host_idx = int(dev.get("hostapi", -1) or -1)
        host_name = hostapis[host_idx].get("name", "?") if 0 <= host_idx < len(hostapis) else "?"
        print(
            f"[{i}] {dev.get('name')} | hostapi={host_name} "
            f"| in={dev.get('max_input_channels', 0)} out={dev.get('max_output_channels', 0)}"
        )


if __name__ == "__main__":
    main()
