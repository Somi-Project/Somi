from __future__ import annotations

from pathlib import Path

from runtime.errors import SandboxError


class WorkspaceSandbox:
    def __init__(self, workspace: str | Path, max_bytes: int = 5 * 1024 * 1024) -> None:
        self.root = Path(workspace).resolve()
        self.max_bytes = max_bytes

    def contains(self, path: str | Path) -> bool:
        candidate = Path(path).expanduser().resolve()
        try:
            candidate.relative_to(self.root)
            return True
        except ValueError:
            return False

    def resolve(self, rel_path: str | Path) -> Path:
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise SandboxError(f"Path traversal blocked: {rel_path}") from exc
        return candidate

    def validate_paths(self, paths: list[str | Path]) -> list[Path]:
        resolved: list[Path] = []
        for raw_path in list(paths or []):
            path = Path(raw_path).expanduser()
            if path.is_absolute():
                candidate = path.resolve()
                if not self.contains(candidate):
                    raise SandboxError(f"Sandbox path blocked: {raw_path}")
                resolved.append(candidate)
                continue
            resolved.append(self.resolve(path))
        return resolved

    def check_size(self, data: bytes) -> None:
        if len(data) > self.max_bytes:
            raise SandboxError("File too large for sandbox policy")
