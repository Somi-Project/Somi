from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_scorecard(payload: dict[str, Any]) -> dict[str, Any]:
    steps = [dict(item) for item in list(payload.get("steps") or []) if isinstance(item, dict)]
    total_steps = len(steps)
    successful_steps = sum(1 for step in steps if str(step.get("status") or "").lower() in {"ok", "passed", "completed", "green"})
    failed_steps = sum(1 for step in steps if str(step.get("status") or "").lower() in {"failed", "error", "red", "blocked"})
    verify_failures = sum(1 for step in steps if str(step.get("step_type") or "").lower() in {"verify", "test", "repair"} and str(step.get("status") or "").lower() in {"failed", "error", "red"})
    touched_files = list(dict.fromkeys(str(item) for item in list(payload.get("touched_files") or []) if str(item).strip()))
    multi_file = len(touched_files) >= 2
    repair_recovery = 1 if failed_steps and successful_steps else 0
    finality_score = round(
        min(
            100.0,
            25.0
            + (successful_steps * 12.0)
            + (8.0 if multi_file else 0.0)
            + (10.0 if repair_recovery else 0.0)
            - (verify_failures * 6.0),
        ),
        2,
    )
    next_actions: list[str] = []
    if failed_steps:
        next_actions.append("Inspect the latest failed verify or test step before applying another patch.")
    elif not total_steps:
        next_actions.append("Capture the first patch or inspection step so the job loop has ground truth.")
    elif not multi_file:
        next_actions.append("Touch the minimum set of related files, not just one file, when the task spans code and tests.")
    else:
        next_actions.append("Run the lightest useful verification command again before marking the task done.")

    return {
        "total_steps": total_steps,
        "successful_steps": successful_steps,
        "failed_steps": failed_steps,
        "repair_failures": verify_failures,
        "multi_file": multi_file,
        "touched_file_count": len(touched_files),
        "finality_score": finality_score,
        "summary": f"score={finality_score} | steps={successful_steps}/{max(1, total_steps)} | files={len(touched_files)}",
        "next_actions": next_actions,
    }


class CodingJobStore:
    def __init__(self, root_dir: str | Path = "sessions/coding/jobs") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = self.root_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.root_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{str(job_id or '').strip()}.json"

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{str(session_id or '').strip()}.json"

    def load_job(self, job_id: str) -> dict[str, Any] | None:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        payload["scorecard"] = _job_scorecard(payload)
        return payload

    def _write_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        data["scorecard"] = _job_scorecard(data)
        path = self._job_path(str(data.get("job_id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        session_id = str(data.get("session_id") or "").strip()
        if session_id:
            session_path = self._session_path(session_id)
            session_path.write_text(
                json.dumps({"job_id": str(data.get("job_id") or ""), "updated_at": str(data.get("updated_at") or _now_iso())}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        return data

    def get_active_job(self, session_id: str) -> dict[str, Any] | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        job_id = str(dict(payload or {}).get("job_id") or "").strip()
        if not job_id:
            return None
        job = self.load_job(job_id)
        if not isinstance(job, dict):
            return None
        if str(job.get("status") or "").lower() in {"completed", "cancelled"}:
            return None
        return job

    def start_or_resume_job(
        self,
        *,
        session_id: str,
        objective: str,
        workspace_root: str,
        profile_key: str,
        repo_focus_files: list[str] | None = None,
    ) -> dict[str, Any]:
        active = self.get_active_job(session_id)
        if isinstance(active, dict):
            objective_text = str(objective or "").strip()
            if objective_text:
                active["objective"] = objective_text
            active["updated_at"] = _now_iso()
            return self._write_job(active)

        payload = {
            "job_id": f"cjob_{uuid.uuid4().hex[:12]}",
            "session_id": str(session_id or "").strip(),
            "objective": str(objective or "").strip(),
            "workspace_root": str(workspace_root or "").strip(),
            "profile_key": str(profile_key or "python").strip().lower() or "python",
            "status": "active",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "repo_focus_files": [str(item) for item in list(repo_focus_files or []) if str(item).strip()],
            "steps": [],
            "touched_files": [],
            "commands": [],
            "notes": [],
        }
        return self._write_job(payload)

    def record_step(
        self,
        *,
        job_id: str,
        step_type: str,
        status: str,
        command: str = "",
        files: list[str] | None = None,
        notes: str = "",
        score: float | int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.load_job(job_id)
        if not isinstance(payload, dict):
            raise ValueError(f"Unknown coding job: {job_id}")
        step = {
            "step_id": f"step_{uuid.uuid4().hex[:10]}",
            "step_type": str(step_type or "step").strip().lower() or "step",
            "status": str(status or "completed").strip().lower() or "completed",
            "command": str(command or "").strip(),
            "files": [str(item) for item in list(files or []) if str(item).strip()],
            "notes": str(notes or "").strip(),
            "score": float(score or 0.0) if score is not None else 0.0,
            "meta": dict(meta or {}),
            "created_at": _now_iso(),
        }
        payload.setdefault("steps", []).append(step)
        touched_files = list(payload.get("touched_files") or [])
        payload["touched_files"] = list(dict.fromkeys([*touched_files, *step["files"]]))
        if step["command"]:
            payload["commands"] = list(dict.fromkeys([*list(payload.get("commands") or []), step["command"]]))[:12]
        if step["notes"]:
            payload["notes"] = list(dict.fromkeys([*list(payload.get("notes") or []), step["notes"]]))[:12]
        payload["updated_at"] = _now_iso()
        return self._write_job(payload)

    def complete_job(self, job_id: str, *, status: str = "completed", notes: str = "") -> dict[str, Any]:
        payload = self.load_job(job_id)
        if not isinstance(payload, dict):
            raise ValueError(f"Unknown coding job: {job_id}")
        payload["status"] = str(status or "completed").strip().lower() or "completed"
        payload["updated_at"] = _now_iso()
        if notes:
            payload["notes"] = list(dict.fromkeys([*list(payload.get("notes") or []), str(notes)]))[:12]
        return self._write_job(payload)
