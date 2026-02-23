from __future__ import annotations

from jobs.engine import JobsEngine
from runtime.ctx import ToolContext
from runtime.policy import enforce_policy
from runtime.privilege import PrivilegeLevel
from toolbox.dispatch import ToolboxDispatch


def create_tool_job(name: str, description: str, active: bool = False, mode: str = "standard", trust: str = "TRUSTED") -> dict:
    enforce_policy({"trust": trust, "action": "install" if active else "plan"})
    return JobsEngine().run_create_tool(name=name, description=description, mode=mode, active=active)


def dispatch_or_run(tool_name: str, args: dict | None = None, trust: str = "TRUSTED") -> dict:
    enforce_policy({"trust": trust, "action": "run"})
    ctx = ToolContext(capabilities={"tool.run", "fs.read"}, privilege=PrivilegeLevel.SAFE)
    return ToolboxDispatch().run(tool_name, args or {}, ctx)
