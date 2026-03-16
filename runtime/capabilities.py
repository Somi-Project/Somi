from __future__ import annotations

from runtime.errors import CapabilityError

CAP_FS_READ = "fs.read"
CAP_FS_WRITE = "fs.write"
CAP_SHELL_EXEC = "shell.exec"
CAP_TOOL_INSTALL = "tool.install"
CAP_TOOL_RUN = "tool.run"


def require_cap(ctx, cap: str) -> None:
    caps = set(getattr(ctx, "capabilities", set()) or set())
    if cap not in caps:
        raise CapabilityError(f"Missing capability: {cap}")
