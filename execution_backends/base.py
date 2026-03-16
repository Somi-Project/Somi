from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BackendExecutionRequest:
    commands: list[list[str]]
    cwd: str
    env: dict[str, str]
    timeout_seconds: int
    output_cap: int = 8000
    allow_network: bool = False
    allow_external_apps: bool = False
    allow_delete: bool = False
    read_write_paths: list[str] = field(default_factory=list)
    read_only_paths: list[str] = field(default_factory=list)
    sandbox_root: str = ""
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    backend: str
    elapsed_ms: int


class ExecutionBackendError(RuntimeError):
    pass
