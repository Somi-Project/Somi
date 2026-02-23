from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from runtime.errors import VerifyError
from runtime.hashing import sha256_file
from toolbox.registry import ToolRegistry


class ToolLoader:
    def __init__(self, registry: ToolRegistry | None = None, timeout_s: int = 20, output_cap: int = 8000) -> None:
        self.registry = registry or ToolRegistry()
        self.timeout_s = timeout_s
        self.output_cap = output_cap

    def _verify(self, entry: dict) -> None:
        for rel, expected in entry.get("hashes", {}).items():
            target = Path(entry["path"]) / rel
            if not target.exists() or not target.is_file():
                raise VerifyError(f"Missing hashed file: {rel}")
            actual = sha256_file(target)
            if actual != expected:
                raise VerifyError(f"Hash mismatch for {rel}")

    def _validate_contract(self, tool_path: Path) -> None:
        source = tool_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise VerifyError(f"tool.py syntax error: {exc}") from exc

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                args = [a.arg for a in node.args.args]
                if len(args) >= 2 and args[0] == "args" and args[1] == "ctx":
                    return
                raise VerifyError("tool.py run signature must be run(args, ctx)")
        raise VerifyError("tool.py missing callable run(args, ctx)")

    def _build_preexec_fn(self):
        def _preexec() -> None:
            import resource

            # CPU seconds hard-limit and address space cap (best effort).
            resource.setrlimit(resource.RLIMIT_CPU, (self.timeout_s, self.timeout_s))
            mem = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            # NOTE: UID/GID drop is environment-dependent and omitted here to avoid
            # interpreter permission failures in managed runtimes.


        return _preexec if os.name == "posix" else None

    def load(self, name: str):
        entry = self.registry.find(name)
        if not entry:
            raise VerifyError(f"Tool not found: {name}")
        self._verify(entry)
        tool_path = Path(entry["path"]) / "tool.py"
        if not tool_path.exists():
            raise VerifyError("tool.py missing from installed tool path")
        self._validate_contract(tool_path)

        def run_in_subprocess(args: dict, _ctx):
            code = (
                "import json\n"
                "import importlib.util\n"
                "import socket\n"
                "def _blocked(*a, **k):\n"
                "    raise RuntimeError('Network disabled by toolbox sandbox')\n"
                "socket.socket = _blocked\n"
                "socket.create_connection = _blocked\n"
                "args=json.loads(__import__('sys').argv[1])\n"
                "spec=importlib.util.spec_from_file_location('tool_runtime', 'tool.py')\n"
                "mod=importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(mod)\n"
                "result=mod.run(args,None)\n"
                "print(json.dumps(result))\n"
            )
            sandbox_home = str(Path(entry["path"]) / ".sandbox_home")
            Path(sandbox_home).mkdir(parents=True, exist_ok=True)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": sandbox_home,
                "PYTHONNOUSERSITE": "1",
            }
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-c", code, json.dumps(args)],
                    cwd=str(Path(entry["path"])),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    preexec_fn=self._build_preexec_fn(),
                )
            except subprocess.TimeoutExpired as exc:
                raise VerifyError(f"Tool timed out after {self.timeout_s}s") from exc
            out = (proc.stdout + proc.stderr)[: self.output_cap].strip()
            if proc.returncode != 0:
                raise VerifyError(f"Tool execution failed: {out}")
            try:
                return json.loads(proc.stdout.strip() or "{}")
            except json.JSONDecodeError as exc:
                raise VerifyError(f"Tool returned non-JSON output: {out}") from exc

        return run_in_subprocess
