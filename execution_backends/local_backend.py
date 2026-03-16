from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .base import BackendExecutionRequest, BackendExecutionResult, ExecutionBackendError
from runtime.sandbox import WorkspaceSandbox


class LocalExecutionBackend:
    name = "local"

    def execute(self, request: BackendExecutionRequest) -> BackendExecutionResult:
        if not request.commands or not request.commands[0]:
            raise ExecutionBackendError("No command provided for local backend")

        if str(request.sandbox_root or "").strip():
            sandbox = WorkspaceSandbox(request.sandbox_root)
            cwd_path = Path(str(request.cwd or ".")).expanduser().resolve()
            if not sandbox.contains(cwd_path):
                raise ExecutionBackendError(f"Working directory escapes sandbox: {request.cwd}")
            sandbox.validate_paths(list(request.read_write_paths or []))
            sandbox.validate_paths(list(request.read_only_paths or []))

        start = time.perf_counter()
        proc = subprocess.run(
            request.commands[0],
            cwd=request.cwd,
            env=dict(request.env or {}),
            capture_output=True,
            text=True,
            timeout=max(1, int(request.timeout_seconds or 1)),
        )
        stdout = str(proc.stdout or "")[: int(request.output_cap or 8000)]
        stderr = str(proc.stderr or "")[: int(request.output_cap or 8000)]
        return BackendExecutionResult(
            returncode=int(proc.returncode),
            stdout=stdout,
            stderr=stderr,
            backend=self.name,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
        )
