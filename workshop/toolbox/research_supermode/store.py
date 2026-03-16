from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResearchSupermodeStore:
    def __init__(self, root_dir: str | Path = "sessions/research_supermode") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = self.root_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir = self.root_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.graphs_dir = self.root_dir / "graphs"
        self.graphs_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir = self.root_dir / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.bundles_dir = self.root_dir / "bundles"
        self.bundles_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{str(job_id or '').strip()}.json"

    def _active_path(self, user_id: str) -> Path:
        return self.users_dir / str(user_id or "default_user").strip() / "active_job.json"

    def write_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = dict(payload or {})
        path = self._job_path(str(job.get("job_id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        user_id = str(job.get("user_id") or "").strip()
        if user_id and str(job.get("status") or "").lower() == "active":
            active_path = self._active_path(user_id)
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(json.dumps({"job_id": str(job.get("job_id") or "")}, indent=2) + "\n", encoding="utf-8")
        return job

    def load_job(self, job_id: str) -> dict[str, Any] | None:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def get_active_job(self, user_id: str) -> dict[str, Any] | None:
        active_path = self._active_path(user_id)
        if not active_path.exists():
            return None
        try:
            payload = json.loads(active_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        job_id = str(dict(payload or {}).get("job_id") or "").strip()
        if not job_id:
            return None
        return self.load_job(job_id)

    def list_jobs(self, *, user_id: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.jobs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if user_id and str(payload.get("user_id") or "").strip() != str(user_id).strip():
                continue
            rows.append(payload)
        rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return rows[: max(1, int(limit or 12))]

    def write_graph(self, job_id: str, graph: dict[str, Any]) -> str:
        safe_job_id = str(job_id or "").strip()
        if not safe_job_id:
            raise ValueError("job_id is required")
        path = self.graphs_dir / f"{safe_job_id}_graph.json"
        path.write_text(json.dumps(dict(graph or {}), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return str(path)

    def load_graph(self, job_id: str) -> dict[str, Any] | None:
        path = self.graphs_dir / f"{str(job_id or '').strip()}_graph.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def write_bundle(self, job_id: str, export_type: str, payload: dict[str, Any]) -> str:
        safe_job_id = str(job_id or "").strip()
        safe_export_type = str(export_type or "research_brief").strip().lower() or "research_brief"
        if not safe_job_id:
            raise ValueError("job_id is required")
        path = self.bundles_dir / f"{safe_job_id}_{safe_export_type}_bundle.json"
        path.write_text(json.dumps(dict(payload or {}), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return str(path)
