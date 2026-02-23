from __future__ import annotations

from pathlib import Path

from runtime.capabilities import CAP_FS_READ, CAP_FS_WRITE, require_cap
from runtime.journal import Journal
from runtime.sandbox import WorkspaceSandbox


class FSOps:
    def __init__(self, sandbox: WorkspaceSandbox, journal: Journal, ctx) -> None:
        self.sandbox = sandbox
        self.journal = journal
        self.ctx = ctx

    def read_text(self, path: str) -> str:
        require_cap(self.ctx, CAP_FS_READ)
        p = self.sandbox.resolve(path)
        text = p.read_text(encoding="utf-8")
        self.journal.append("fs.read", "Read file", {"path": str(p)})
        return text

    def write_text(self, path: str, content: str) -> None:
        require_cap(self.ctx, CAP_FS_WRITE)
        data = content.encode("utf-8")
        self.sandbox.check_size(data)
        p = self.sandbox.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.journal.append("fs.write", "Write file", {"path": str(p), "bytes": len(data)})

    def mkdir(self, path: str) -> None:
        require_cap(self.ctx, CAP_FS_WRITE)
        p = self.sandbox.resolve(path)
        p.mkdir(parents=True, exist_ok=True)
        self.journal.append("fs.mkdir", "Create directory", {"path": str(p)})

    def list_dir(self, path: str) -> list[str]:
        require_cap(self.ctx, CAP_FS_READ)
        p = self.sandbox.resolve(path)
        out = sorted([x.name for x in p.iterdir()]) if p.exists() else []
        self.journal.append("fs.list", "List directory", {"path": str(p), "count": len(out)})
        return out
