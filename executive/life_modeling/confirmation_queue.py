from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from executive.life_modeling.telemetry import Phase7Telemetry


class GoalLinkConfirmationQueue:
    """File-backed queue for UI approval of goal_link_proposal artifacts."""

    def __init__(self, path: str = "executive/index/goal_link_queue.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.telemetry = Phase7Telemetry(path=str(getattr(settings, "PHASE7_TELEMETRY_PATH", "executive/index/phase7_telemetry.json")))

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"items": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"items": []}

    def _write(self, payload: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def enqueue(self, proposals: list[dict[str, Any]]) -> int:
        state = self._read()
        rows = list(state.get("items") or [])
        existing = {str(r.get("proposal_id") or "") for r in rows}
        added = 0
        for p in list(proposals or []):
            pid = str(p.get("proposal_id") or "")
            if not pid or pid in existing:
                continue
            rows.append(
                {
                    "proposal_id": pid,
                    "goal_id": str(p.get("goal_id") or ""),
                    "project_id": str(p.get("project_id") or ""),
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "payload": p,
                }
            )
            existing.add(pid)
            added += 1
        self._write({"items": rows})
        self.telemetry.record_queue_depth(len([r for r in rows if str(r.get("status") or "") == "pending"]))
        return added

    def list_all(self) -> list[dict[str, Any]]:
        state = self._read()
        return [dict(r) for r in list(state.get("items") or []) if isinstance(r, dict)]

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        st = str(status or "pending").strip().lower()
        if st in {"all", "*"}:
            return self.list_all()
        return [r for r in self.list_all() if str(r.get("status") or "").strip().lower() == st]

    def list_pending(self) -> list[dict[str, Any]]:
        return self.list_by_status("pending")

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        state = self._read()
        for row in list(state.get("items") or []):
            if str(row.get("proposal_id") or "") == str(proposal_id or ""):
                return dict(row)
        return None

    def resolve(self, proposal_id: str, *, approved: bool) -> bool:
        state = self._read()
        rows = list(state.get("items") or [])
        hit = False
        for row in rows:
            if str(row.get("proposal_id") or "") == str(proposal_id or ""):
                row["status"] = "approved" if approved else "rejected"
                row["resolved_at"] = datetime.now(timezone.utc).isoformat()
                hit = True
                break
        if hit:
            self._write({"items": rows})
            current = [r for r in rows if str(r.get("status") or "") == "pending"]
            self.telemetry.record_queue_depth(len(current))
            row = next((r for r in rows if str(r.get("proposal_id") or "") == str(proposal_id or "")), None)
            latency = None
            if row is not None:
                try:
                    created = datetime.fromisoformat(str(row.get("created_at") or "").replace("Z", "+00:00"))
                    resolved = datetime.fromisoformat(str(row.get("resolved_at") or "").replace("Z", "+00:00"))
                    latency = max(0.0, (resolved - created).total_seconds())
                except Exception:
                    latency = None
            self.telemetry.record_queue_resolution(approved=approved, latency_seconds=latency)
        return hit
