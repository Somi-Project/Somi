from __future__ import annotations

from dataclasses import dataclass, field

from runtime.cancel import CancelToken
from runtime.privilege import PrivilegeLevel


@dataclass
class ToolContext:
    capabilities: set[str]
    privilege: PrivilegeLevel = PrivilegeLevel.SAFE
    cancel_token: CancelToken = field(default_factory=CancelToken)
    journal: object | None = None


@dataclass
class JobContext(ToolContext):
    job_id: str = ""
    mode: str = "standard"
