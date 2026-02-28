from __future__ import annotations

import json

from handlers.contracts.store import ArtifactStore


def test_store_recovers_from_corrupt_index(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    store.append("u1", {"artifact_id": "art_ok", "artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}})

    idx = tmp_path / "artifacts" / "u1.index.json"
    idx.write_text("{not json", encoding="utf-8")

    got = store.get_last("u1", "plan")
    assert got is not None
    assert got.get("artifact_id") == "art_ok"



def test_store_index_ignores_empty_contract_and_artifact_id(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    store.append("u1", {"artifact_id": "", "artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}})

    idx = tmp_path / "artifacts" / "u1.index.json"
    payload = json.loads(idx.read_text(encoding="utf-8"))

    assert "" not in (payload.get("by_id") or {})
