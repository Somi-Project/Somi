from __future__ import annotations

import unittest

from ops.hardware_tiers import HardwareSnapshot, build_hardware_tier_profile, build_hardware_tier_snapshot, classify_hardware_tier
from ops.offline_resilience import run_offline_resilience


class HardwareTiersPhase172Tests(unittest.TestCase):
    def test_classify_survival_low_and_high_tiers(self) -> None:
        self.assertEqual(classify_hardware_tier(HardwareSnapshot(cpu_count=2, memory_gb=4.0, gpu_available=False, storage_free_gb=20.0)), "survival")
        self.assertEqual(classify_hardware_tier(HardwareSnapshot(cpu_count=4, memory_gb=12.0, gpu_available=False, storage_free_gb=50.0)), "low")
        self.assertEqual(classify_hardware_tier(HardwareSnapshot(cpu_count=16, memory_gb=64.0, gpu_available=True, storage_free_gb=200.0)), "high")

    def test_build_hardware_profile_preserves_capability_with_mode_overrides(self) -> None:
        snapshot = HardwareSnapshot(cpu_count=8, memory_gb=24.0, gpu_available=False, storage_free_gb=100.0)
        normal = build_hardware_tier_profile(snapshot, runtime_mode="normal")
        low_power = build_hardware_tier_profile(snapshot, runtime_mode="low_power")
        self.assertEqual(normal.tier, "balanced")
        self.assertEqual(normal.context_profile, "16k")
        self.assertEqual(low_power.runtime_mode, "low_power")
        self.assertEqual(low_power.preferred_pack_variant, "compact")

    def test_offline_resilience_reports_hardware_profile(self) -> None:
        report = run_offline_resilience("C:\\somex")
        hardware = dict(report.get("hardware_profile") or {})
        profile = dict(hardware.get("profile") or {})
        self.assertTrue(hardware)
        self.assertIn(str(profile.get("tier") or ""), {"survival", "low", "balanced", "high"})
        self.assertTrue(str(profile.get("preferred_pack_variant") or ""))

    def test_hardware_tier_snapshot_marks_power_aware_and_capability_preserving(self) -> None:
        snapshot = build_hardware_tier_snapshot("C:\\somex")
        self.assertTrue(bool(snapshot.get("power_aware")))
        self.assertTrue(bool(snapshot.get("capability_preserving")))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
