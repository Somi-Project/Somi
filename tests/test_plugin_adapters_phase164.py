from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from skills_local import PluginRegistry, approve_imported_plugin, import_skill_bundle, review_skill_bundle


_CODEX_STYLE_SKILL = """---
name: Git Publish Review
description: Prepare git publish work with approval.
user-invocable: true
metadata: {"runtime":{"skillKey":"git_publish_review"}}
---

# Purpose
- Inspect git status and prepare a publish review.

# Workflow
- Check git diff.
- Draft a commit.
- Push only after approval.
"""


class PluginAdaptersPhase164Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_plugin_adapters_"))
        self.registry = PluginRegistry(root_dir=self.temp_dir / "registry")
        self.bundle_dir = self.temp_dir / "openclaw_publish_skill"
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        (self.bundle_dir / "SKILL.md").write_text(_CODEX_STYLE_SKILL, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_review_skill_bundle_reports_origin_and_policy(self) -> None:
        review = review_skill_bundle(self.bundle_dir, trust_tier="adapted_experimental")
        self.assertTrue(review["ok"])
        self.assertEqual(str(dict(review.get("origin") or {}).get("origin") or ""), "openclaw_skill_bundle")
        self.assertEqual(str(review.get("recommendation") or ""), "review_required")
        self.assertTrue(bool(dict(review.get("policy") or {}).get("requires_approval")))

    def test_approve_imported_plugin_promotes_to_reviewed(self) -> None:
        imported = import_skill_bundle(self.bundle_dir, registry=self.registry, trust_tier="adapted_experimental")
        self.assertTrue(imported["ok"])
        plugin_id = str(dict(imported.get("descriptor") or {}).get("plugin_id") or "")
        approved = approve_imported_plugin(plugin_id, registry=self.registry)
        self.assertTrue(approved["ok"])
        descriptor = dict(approved.get("descriptor") or {})
        self.assertEqual(str(descriptor.get("trust_tier") or ""), "adapted_reviewed")
        self.assertNotIn("experimental_import", list(descriptor.get("warnings") or []))


if __name__ == "__main__":
    unittest.main()
