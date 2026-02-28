from __future__ import annotations

import json

from handlers.contracts.store import ArtifactStore


def test_rebuild_index_ignores_empty_artifact_id(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    p = tmp_path / "artifacts" / "u1.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)

    # historical malformed line with empty artifact_id
    p.write_text(
        json.dumps({"artifact_type": "plan", "artifact_id": "", "content": {"objective": "x", "steps": ["a"]}}) + "\n",
        encoding="utf-8",
    )

    store._rebuild_index("u1")
    idx = tmp_path / "artifacts" / "u1.index.json"
    payload = json.loads(idx.read_text(encoding="utf-8"))
    assert "" not in (payload.get("by_id") or {})
