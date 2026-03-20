from __future__ import annotations

from pathlib import Path
from typing import Any

from workshop.toolbox.research_supermode import ResearchSupermodeStore


class ResearchStudioSnapshotBuilder:
    def __init__(self, store: ResearchSupermodeStore | None = None) -> None:
        self.store = store or ResearchSupermodeStore()

    def build(self, *, user_id: str = "default_user") -> dict[str, Any]:
        active = dict(self.store.get_active_job(user_id) or {})
        jobs = [dict(row) for row in list(self.store.list_jobs(user_id=user_id, limit=16) or [])]
        export_rows: list[dict[str, Any]] = []
        for path in sorted(self.store.exports_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
            export_rows.append({"path": str(path), "name": path.name, "kind": "markdown"})
        for path in sorted(self.store.bundles_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
            export_rows.append({"path": str(path), "name": path.name, "kind": "bundle"})
        export_rows.sort(key=lambda item: Path(str(item.get("path") or "")).stat().st_mtime if Path(str(item.get("path") or "")).exists() else 0, reverse=True)
        graph_rows: list[dict[str, Any]] = []
        for path in sorted(self.store.graphs_dir.glob("*_graph.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
            graph_rows.append({"path": str(path), "name": path.name})
        active_progress = dict(active.get("progress") or {})
        active_memory = dict(active.get("memory") or {})
        active_subagents = [dict(row) for row in list(active.get("subagents") or []) if isinstance(row, dict)]
        return {
            "active_job": active,
            "jobs": jobs,
            "exports": export_rows[:20],
            "graphs": graph_rows,
            "summary": {
                "job_count": len(jobs),
                "export_count": len(export_rows),
                "graph_count": len(graph_rows),
                "active_job_id": str(active.get("job_id") or ""),
                "active_query": str(active.get("query") or ""),
                "active_status": str(active.get("status") or ""),
                "active_progress_summary": str(active_progress.get("summary") or ""),
                "active_memory_summary": str(active_memory.get("summary") or ""),
                "active_subagent_summary": ", ".join(
                    f"{str(row.get('id') or '--')}: {str(row.get('status') or '--')}" for row in active_subagents[:4]
                ),
            },
        }
