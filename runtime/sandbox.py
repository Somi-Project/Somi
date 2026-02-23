from __future__ import annotations

from pathlib import Path

from runtime.errors import SandboxError


class WorkspaceSandbox:
    def __init__(self, workspace: str | Path, max_bytes: int = 5 * 1024 * 1024) -> None:
        self.root = Path(workspace).resolve()
        self.max_bytes = max_bytes

    def resolve(self, rel_path: str | Path) -> Path:
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise SandboxError(f"Path traversal blocked: {rel_path}") from exc
        return candidate

    def check_size(self, data: bytes) -> None:
        if len(data) > self.max_bytes:
            raise SandboxError("File too large for sandbox policy")
