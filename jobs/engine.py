from __future__ import annotations

import uuid
from pathlib import Path

from jobs.models import Job, JobState
from jobs.summarizer import write_job_summary
from runtime.audit import append_event
from runtime.cancel import CancelToken
from runtime.ctx import JobContext
from runtime.errors import CancelledError
from runtime.fs_ops import FSOps
from runtime.job_state import JobPhase, validate_transition
from runtime.journal import Journal
from runtime.plan_lint import lint_plan
from runtime.privilege import PrivilegeLevel
from runtime.sandbox import WorkspaceSandbox
from runtime.stream import StepEvent, StepSink
from runtime.verifier import verify_static
from toolbox.builder import ToolBuilder


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
        del run_args, active
        job_id = str(uuid.uuid4())[:8]
        job = Job(job_id=job_id, objective=f"create {name}", state=JobState.RUNNING)
        phase = JobPhase.NEW
        if sink:
            sink.emit(StepEvent("job", f"Job {job_id} started"))

        journal = Journal(Path("jobs/journal") / f"{job_id}.jsonl")
        ctx = JobContext(
            capabilities={"fs.read", "fs.write", "tool.run"},
            privilege=PrivilegeLevel.SAFE,
            cancel_token=cancel_token or CancelToken(),
            journal=journal,
            job_id=job_id,
            mode=mode,
        )
        fs = FSOps(WorkspaceSandbox("tools/workspace"), journal, ctx)

        try:
            validate_transition(phase, JobPhase.PURSUIT)
            phase = JobPhase.PURSUIT
            append_event(job_id, "plan created", {"objective": job.objective})
            plan = {
                "steps": [
                    "generate patch-only tool skeleton",
                    "static verify",
                    "await approval for any execution",
                ],
                "risk": "LOW",
            }
            errs = lint_plan(plan, mode="safe", autonomy=True)
            if errs:
                raise ValueError("Plan lint failed: " + "; ".join(errs))

            validate_transition(phase, JobPhase.PLAN_READY)
            phase = JobPhase.PLAN_READY
            built_rel = ToolBuilder(fs).build(name, description, workspace=".")
            tool_dir = str(Path("tools/workspace") / built_rel)
            append_event(job_id, "patch generated", {"tool_dir": tool_dir})
            if sink:
                sink.emit(StepEvent("build", f"Built {tool_dir}"))

            validate_transition(phase, JobPhase.SIM_DONE)
            phase = JobPhase.SIM_DONE
            verify_static(tool_dir)
            validate_transition(phase, JobPhase.PATCH_READY)
            phase = JobPhase.PATCH_READY
            append_event(
                job_id,
                "approval requested",
                {"reason": "execution disabled in safe mode"},
            )
            validate_transition(phase, JobPhase.AWAITING_APPROVAL)
            phase = JobPhase.AWAITING_APPROVAL
            result = {
                "state": phase.value,
                "message": "Patch ready; execution requires approval ticket",
            }
            job.state = JobState.VERIFIED
        except CancelledError as exc:
            job.state = JobState.CANCELLED
            phase = JobPhase.FAILED
            result = {"error": str(exc)}
            append_event(job_id, "failure", {"error": str(exc)})
        except Exception as exc:
            job.state = JobState.FAILED
            phase = JobPhase.FAILED
            result = {"error": str(exc)}
            append_event(job_id, "failure", {"error": str(exc)})

        summary = {
            "job_id": job_id,
            "state": job.state.value,
            "objective": job.objective,
            "result": result,
            "phase": phase.value,
        }
        write_job_summary(job_id, summary)
        if sink:
            sink.emit(StepEvent("job", f"Job {job_id} finished: {job.state.value}"))
        return summary
