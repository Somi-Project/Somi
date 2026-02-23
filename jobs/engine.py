from __future__ import annotations

import json
import uuid
from pathlib import Path

from jobs.models import Job, JobState
from jobs.summarizer import write_job_summary
from runtime.cancel import CancelToken
from runtime.ctx import JobContext
from runtime.errors import CancelledError
from runtime.fs_ops import FSOps
from runtime.journal import Journal
from runtime.privilege import PrivilegeLevel
from runtime.sandbox import WorkspaceSandbox
from runtime.stream import StepEvent, StepSink
from runtime.verifier import verify_project
from toolbox.builder import ToolBuilder
from toolbox.installer import ToolInstaller
from toolbox.loader import ToolLoader


class JobsEngine:
    def run_create_tool(
        self,
        name: str,
        description: str,
        mode: str,
        active: bool,
        sink: StepSink | None = None,
        run_args: dict | None = None,
        cancel_token: CancelToken | None = None,
    ):
        job_id = str(uuid.uuid4())[:8]
        job = Job(job_id=job_id, objective=f"create {name}", state=JobState.RUNNING)
        if sink:
            sink.emit(StepEvent("job", f"Job {job_id} started"))

        journal = Journal(Path("jobs/journal") / f"{job_id}.jsonl")
        capabilities = {"fs.read", "fs.write", "shell.exec", "tool.run"}
        if active:
            capabilities.add("tool.install")

        ctx = JobContext(
            capabilities=capabilities,
            privilege=PrivilegeLevel.ACTIVE if active else PrivilegeLevel.SAFE,
            cancel_token=cancel_token or CancelToken(),
            journal=journal,
            job_id=job_id,
            mode=mode,
        )
        fs = FSOps(WorkspaceSandbox("tools/workspace"), journal, ctx)

        try:
            ctx.cancel_token.raise_if_cancelled()
            built_rel = ToolBuilder(fs).build(name, description, workspace=".")
            tool_dir = str(Path("tools/workspace") / built_rel)
            if sink:
                sink.emit(StepEvent("build", f"Built {tool_dir}"))

            ctx.cancel_token.raise_if_cancelled()
            verify_project(tool_dir, ctx)
            job.state = JobState.VERIFIED
            if sink:
                sink.emit(StepEvent("verify", "Verification passed"))

            if active:
                ctx.cancel_token.raise_if_cancelled()
                manifest = json.loads(Path(tool_dir, "manifest.json").read_text(encoding="utf-8"))
                ToolInstaller(journal=journal).install(tool_dir, manifest["name"], manifest["version"], ctx, job_id)
                job.state = JobState.INSTALLED
                run_fn = ToolLoader().load(name)
                result = run_fn(run_args or {"name": "Somi"}, ctx)
                if sink:
                    sink.emit(StepEvent("run", "Tool executed"))
            else:
                result = {"safe_boundary": True, "message": "SAFE mode blocks installation"}
                if sink:
                    sink.emit(StepEvent("boundary", result["message"]))

            job.state = JobState.COMPLETED
        except CancelledError as exc:
            job.state = JobState.CANCELLED
            result = {"error": str(exc)}
            if sink:
                sink.emit(StepEvent("cancel", str(exc)))
        except Exception as exc:
            job.state = JobState.FAILED
            result = {"error": str(exc)}
            if sink:
                sink.emit(StepEvent("error", str(exc)))

        summary = {"job_id": job_id, "state": job.state.value, "objective": job.objective, "result": result}
        write_job_summary(job_id, summary)
        if sink:
            sink.emit(StepEvent("job", f"Job {job_id} finished: {job.state.value}"))
        return summary
