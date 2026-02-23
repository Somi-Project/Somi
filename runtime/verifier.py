from __future__ import annotations

import ast
import json
from pathlib import Path

from runtime.errors import VerifyError
from runtime.shell import ShellRunner


def _has_run_contract(source: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            args = [a.arg for a in node.args.args]
            return len(args) >= 2 and args[0] == "args" and args[1] == "ctx"
    return False


def verify_project(tool_dir: str, ctx) -> None:
    base = Path(tool_dir)
    manifest_path = base / "manifest.json"
    tool_path = base / "tool.py"
    if not manifest_path.exists() or not tool_path.exists():
        raise VerifyError("manifest.json and tool.py are required")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "name" not in manifest or "version" not in manifest:
        raise VerifyError("Manifest must include name and version")

    text = tool_path.read_text(encoding="utf-8")
    if not _has_run_contract(text):
        raise VerifyError("tool.py must define run(args, ctx)")

    runner = ShellRunner(cwd=str(base), allowlist={"pytest", "python"})
    code, out = runner.run(["pytest", "-q"], ctx)
    if code != 0:
        raise VerifyError(f"pytest failed: {out}")
