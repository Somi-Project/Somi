from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from skills_local.federation import (
    PluginRegistry,
    build_plugin_descriptor,
    dry_run_import_skill,
    import_skill_bundle,
    plugin_execution_policy,
)


_SAMPLE_SKILL = """---
name: Browser Repair Skill
description: Assist with browser automation and telegram delivery.
user-invocable: true
---

# Purpose
- Help inspect a site and send a status update.

# Workflow
- Use browser tools to open the repair console.
- If the task succeeds, send message back to Telegram.
"""


class PluginFederationPhase163Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_plugin_federation_"))
        self.registry = PluginRegistry(root_dir=self.temp_dir / "registry")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_plugin_descriptor_infers_tools_and_approval(self) -> None:
        descriptor = build_plugin_descriptor(
            skill_text=_SAMPLE_SKILL,
            source_path=str(self.temp_dir / "browser_skill" / "SKILL.md"),
            trust_tier="adapted_experimental",
        )
        payload = descriptor.to_dict()
        self.assertEqual(payload["trust_tier"], "adapted_experimental")
        self.assertIn("browser", payload["required_tools"])
        self.assertIn("telegram", payload["required_tools"])
        self.assertIn("confirm_external_message", payload["approval_expectations"])
        self.assertIn("experimental_import", payload["warnings"])

    def test_import_skill_bundle_registers_descriptor(self) -> None:
        bundle_dir = self.temp_dir / "bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "SKILL.md").write_text(_SAMPLE_SKILL, encoding="utf-8")

        imported = import_skill_bundle(bundle_dir, registry=self.registry, trust_tier="adapted_reviewed")
        self.assertTrue(imported["ok"])
        descriptor = dict(imported.get("descriptor") or {})
        loaded = self.registry.load(str(descriptor.get("plugin_id") or ""))
        self.assertIsNotNone(loaded)
        self.assertEqual(str(loaded.get("trust_tier") or ""), "adapted_reviewed")

    def test_dry_run_import_and_policy_enforce_trust_tier(self) -> None:
        bundle_dir = self.temp_dir / "disabled_bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "SKILL.md").write_text(_SAMPLE_SKILL, encoding="utf-8")

        preview = dry_run_import_skill(bundle_dir, trust_tier="disabled")
        self.assertTrue(preview["ok"])
        policy = plugin_execution_policy(dict(preview.get("descriptor") or {}))
        self.assertFalse(policy["allowed"])
        self.assertTrue(policy["requires_review"])
        self.assertTrue(policy["requires_approval"])


if __name__ == "__main__":
    unittest.main()
