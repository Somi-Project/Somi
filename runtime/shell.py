from __future__ import annotations

import os
import subprocess

from runtime.capabilities import CAP_SHELL_EXEC, require_cap
from runtime.errors import ShellError


class ShellRunner:
    def __init__(self, allowlist: set[str] | None = None, cwd: str = ".", timeout_s: int = 30, output_cap: int = 8000) -> None:
        self.allowlist = allowlist or {"python", "pytest"}
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.output_cap = output_cap

    def run(self, cmd: list[str], ctx) -> tuple[int, str]:
        require_cap(ctx, CAP_SHELL_EXEC)
        if not cmd:
            raise ShellError("Empty command")
        if cmd[0] not in self.allowlist:
            raise ShellError(f"Command not allowlisted: {cmd[0]}")

        env = {"PATH": os.environ.get("PATH", "")}
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise ShellError(f"Command timed out after {self.timeout_s}s: {' '.join(cmd)}") from exc

        out = (proc.stdout + proc.stderr)[: self.output_cap]
        return proc.returncode, out
