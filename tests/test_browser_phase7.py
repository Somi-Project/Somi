from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from workshop.toolbox.browser.runtime import browser_health, capture_page_state
from workshop.toolbox.browser.store import BrowserAutomationStore


class BrowserPhase7Tests(unittest.TestCase):
    def test_capture_page_state_reads_local_fixture(self) -> None:
        health = browser_health()
        if not bool(health.get("ok")):
            self.skipTest(str(health.get("install_hint") or "Browser runtime unavailable"))
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        html_path = Path(root) / "fixture.html"
        html_path.write_text(
            "<html><body><h1>Tokyo Plan</h1><a href='https://example.com/guide'>Guide</a>"
            "<form><input name='email'/><button>Go</button></form></body></html>",
            encoding="utf-8",
        )
        store = BrowserAutomationStore(root_dir=Path(root) / "browser_runtime")
        payload = capture_page_state(str(html_path), options={"max_links": 6, "text_cap": 800})
        snapshot = dict(payload.get("snapshot") or {})
        self.assertEqual(snapshot.get("form_count"), 1)
        self.assertGreaterEqual(int(snapshot.get("input_count") or 0), 1)
        self.assertEqual(len(list(snapshot.get("links") or [])), 1)
        self.assertTrue(store.captures_dir.exists())


if __name__ == "__main__":
    unittest.main()
