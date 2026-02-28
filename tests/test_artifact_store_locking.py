from __future__ import annotations

from handlers.contracts.store import ArtifactStore


def test_store_creates_session_lock_file(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    store.append("u1", {"artifact_id": "art1", "artifact_type": "plan", "content": {"objective": "x", "steps": ["a"]}})

    lock = tmp_path / "artifacts" / "u1.lock"
    assert lock.exists()
