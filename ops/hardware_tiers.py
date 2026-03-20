from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HardwareSnapshot:
    cpu_count: int
    memory_gb: float
    gpu_available: bool
    storage_free_gb: float


@dataclass(frozen=True)
class HardwareTierProfile:
    tier: str
    runtime_mode: str
    context_profile: str
    max_parallel_tools: int
    background_mode: str
    preferred_pack_variant: str
    ocr_policy: str
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_memory_gb() -> float:
    try:
        import psutil  # type: ignore

        return round(float(psutil.virtual_memory().total) / (1024.0**3), 1)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(float(status.ullTotalPhys) / (1024.0**3), 1)
        except Exception:
            pass
    return 0.0


def detect_hardware_snapshot(root_dir: str = ".") -> HardwareSnapshot:
    cpu_count = max(1, int(os.cpu_count() or 1))
    memory_gb = _detect_memory_gb()
    gpu_available = bool(shutil.which("nvidia-smi") or os.environ.get("CUDA_VISIBLE_DEVICES"))
    try:
        usage = shutil.disk_usage(root_dir)
        storage_free_gb = round(float(usage.free) / (1024.0**3), 1)
    except Exception:
        storage_free_gb = 0.0
    return HardwareSnapshot(
        cpu_count=cpu_count,
        memory_gb=memory_gb,
        gpu_available=gpu_available,
        storage_free_gb=storage_free_gb,
    )


def classify_hardware_tier(snapshot: HardwareSnapshot) -> str:
    if snapshot.memory_gb and snapshot.memory_gb < 8:
        return "survival"
    if snapshot.cpu_count < 4:
        return "survival"
    if snapshot.memory_gb and snapshot.memory_gb < 16:
        return "low"
    if snapshot.gpu_available or (snapshot.memory_gb and snapshot.memory_gb >= 32):
        return "high"
    return "balanced"


def build_hardware_tier_profile(
    snapshot: HardwareSnapshot,
    *,
    runtime_mode: str = "normal",
) -> HardwareTierProfile:
    tier = classify_hardware_tier(snapshot)
    mode = str(runtime_mode or "normal").strip().lower() or "normal"
    notes: list[str] = []

    if tier == "survival" or mode == "survival":
        notes.append("Favor compact knowledge packs, text-first UX, and explicit on-demand OCR.")
        return HardwareTierProfile(
            tier="survival",
            runtime_mode="survival",
            context_profile="4k",
            max_parallel_tools=1,
            background_mode="minimal",
            preferred_pack_variant="compact",
            ocr_policy="on_demand",
            notes=tuple(notes),
        )
    if tier == "low" or mode == "low_power":
        notes.append("Keep background work bounded and prefer compact packs on weaker hardware.")
        return HardwareTierProfile(
            tier="low",
            runtime_mode="low_power",
            context_profile="8k",
            max_parallel_tools=2,
            background_mode="bounded",
            preferred_pack_variant="compact",
            ocr_policy="light",
            notes=tuple(notes),
        )
    if tier == "high":
        notes.append("Hardware can sustain richer OCR, broader indexing, and heavier parallel research.")
        return HardwareTierProfile(
            tier="high",
            runtime_mode="normal",
            context_profile="32k",
            max_parallel_tools=5,
            background_mode="full",
            preferred_pack_variant="expanded",
            ocr_policy="rich",
            notes=tuple(notes),
        )
    notes.append("Balanced profile keeps the current workstation behavior without lowering the framework ceiling.")
    return HardwareTierProfile(
        tier="balanced",
        runtime_mode="normal",
        context_profile="16k",
        max_parallel_tools=3,
        background_mode="standard",
        preferred_pack_variant="compact",
        ocr_policy="standard",
        notes=tuple(notes),
    )


def build_hardware_tier_snapshot(root_dir: str = ".", *, runtime_mode: str = "normal") -> dict[str, Any]:
    snapshot = detect_hardware_snapshot(root_dir)
    profile = build_hardware_tier_profile(snapshot, runtime_mode=runtime_mode)
    return {
        "snapshot": asdict(snapshot),
        "profile": profile.as_dict(),
        "power_aware": True,
        "capability_preserving": True,
    }
