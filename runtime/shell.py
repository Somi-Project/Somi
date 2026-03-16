from __future__ import annotations

import os

from config import toolboxsettings as tbs
from execution_backends import (
    DEFAULT_BACKEND_REGISTRY,
    BackendExecutionRequest,
    ExecutionBackendError,
)
from runtime.approval import ApprovalReceipt, validate_receipt
from runtime.capabilities import CAP_SHELL_EXEC, require_cap
from runtime.errors import PolicyError, ShellError
from runtime.ticketing import ExecutionTicket, ticket_hash


class ShellRunner:
    def __init__(
        self,
        allowlist: set[str] | None = None,
        cwd: str = ".",
        timeout_s: int = 30,
        output_cap: int = 8000,
        backend: str = "local",
    ) -> None:
        self.allowlist = allowlist or set(tbs.SAFE_ALLOWED_COMMANDS)
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.output_cap = output_cap
        self.backend = backend

    def propose_exec(self, cmd: list[str], job_id: str = "shell") -> ExecutionTicket:
        return ExecutionTicket(
            job_id=job_id,
            action="execute",
            commands=[cmd],
            cwd=self.cwd,
            backend=self.backend,
            timeout_seconds=self.timeout_s,
        )

    def execute_with_approval(
        self, ticket: ExecutionTicket, receipt: ApprovalReceipt | None, ctx
    ) -> tuple[int, str]:
        require_cap(ctx, CAP_SHELL_EXEC)
        if tbs.normalized_mode() == tbs.MODE_SAFE:
            raise PolicyError("SAFE mode denies command execution")
        if not ticket.commands or not ticket.commands[0]:
            raise ShellError("Empty command")
        cmd = ticket.commands[0]
        if self.allowlist and cmd[0] not in self.allowlist:
            raise ShellError(f"Command not allowlisted: {cmd[0]}")
        validate_receipt(ticket_hash(ticket), receipt, "MEDIUM")
        env = {"PATH": os.environ.get("PATH", "")}
        request = BackendExecutionRequest(
            commands=[list(cmd)],
            cwd=ticket.cwd,
            env=env,
            timeout_seconds=ticket.timeout_seconds,
            output_cap=self.output_cap,
            sandbox_root=ticket.cwd,
        )
        try:
            result = DEFAULT_BACKEND_REGISTRY.get(ticket.backend).execute(request)
        except ExecutionBackendError as exc:
            raise ShellError(str(exc)) from exc
        out = (result.stdout + result.stderr)[: self.output_cap]
        return result.returncode, out
