from __future__ import annotations

import unittest

from gateway.surface_policy import (
    build_distribution_sovereignty_snapshot,
    build_surface_policy_signal,
    evaluate_surface_policy,
)


class DistributionSovereigntyPhase171Tests(unittest.TestCase):
    def test_direct_download_surface_keeps_core_sovereign(self) -> None:
        decision = evaluate_surface_policy(
            build_surface_policy_signal("desktop", distribution="direct_download")
        )
        self.assertFalse(decision.adapter_active)
        self.assertEqual(decision.enforcement_scope, "none")
        self.assertFalse(decision.requires_age_signal)

    def test_managed_mobile_surface_uses_edge_adapter_only(self) -> None:
        decision = evaluate_surface_policy(
            build_surface_policy_signal(
                "mobile_app",
                distribution="app_store",
                requested_capabilities=["payments", "chat"],
            )
        )
        self.assertTrue(decision.adapter_active)
        self.assertEqual(decision.enforcement_scope, "surface_only")
        self.assertTrue(decision.requires_age_signal)
        self.assertIn("payments", decision.blocked_capabilities)

    def test_snapshot_reports_principles_and_surface_rows(self) -> None:
        snapshot = build_distribution_sovereignty_snapshot(
            signals=[
                build_surface_policy_signal("desktop", distribution="direct_download"),
                build_surface_policy_signal("mobile_app", distribution="app_store"),
            ]
        )
        self.assertEqual(int(snapshot.get("surface_count") or 0), 2)
        self.assertFalse(bool(snapshot.get("central_identity_required")))
        self.assertTrue(list(snapshot.get("principles") or []))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
