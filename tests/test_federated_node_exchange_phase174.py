from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gateway.federation import FederatedEnvelopeStore, build_federation_snapshot


ROOT = Path(__file__).resolve().parents[1]


class FederatedNodeExchangePhase174Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="somi_federation_phase174_"))
        self.store = FederatedEnvelopeStore(self.temp_dir / "state" / "node_exchange")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_publish_ingest_and_acknowledge_round_trip(self) -> None:
        outbound = self.store.publish(
            node_id="shelter_b",
            lane="knowledge",
            subject="water update",
            body="Use clean treated storage containers only.",
            capabilities=["knowledge_sync"],
        )
        inbound = self.store.ingest(
            node_id="shelter_b",
            lane="task",
            subject="check inverter",
            body="Need confirmation on inverter fuse state.",
            capabilities=["task_sync"],
        )
        self.assertEqual(len(self.store.list_envelopes(direction="outbox")), 1)
        self.assertEqual(len(self.store.list_envelopes(direction="inbox")), 1)
        archived = self.store.acknowledge(direction="inbox", node_id="shelter_b", envelope_id=str(inbound.get("envelope_id") or ""))
        self.assertEqual(str(archived.get("status") or ""), "acknowledged")
        snapshot = build_federation_snapshot(self.temp_dir)
        self.assertEqual(int(snapshot.get("pending_outbox") or 0), 1)
        self.assertEqual(int(snapshot.get("archived") or 0), 1)
        self.assertIn("shelter_b", list(snapshot.get("nodes") or []))
        self.assertEqual(str(outbound.get("lane") or ""), "knowledge")

    def test_cli_snapshot_returns_json(self) -> None:
        self.store.publish(
            node_id="relay_alpha",
            lane="knowledge",
            subject="seed inventory",
            body="Compact update",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "somi.py"),
                "offline",
                "federation",
                "--json",
                "--root",
                str(self.temp_dir),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.fail(f"offline federation CLI failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        payload = json.loads(result.stdout)
        self.assertEqual(int(payload.get("pending_outbox") or 0), 1)
        self.assertIn("relay_alpha", list(payload.get("nodes") or []))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
