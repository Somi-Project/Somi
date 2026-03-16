from __future__ import annotations

import ast
import json
from pathlib import Path

from config import toolboxsettings as tbs
from runtime.approval import ApprovalReceipt, validate_receipt
from runtime.audit import append_event
from runtime.errors import PolicyError, VerifyError
from runtime.staging import run_commands_in_staging
from runtime.ticketing import ExecutionTicket, ticket_hash


def _has_run_contract(source: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            args = [a.arg for a in node.args.args]
            return len(args) >= 2 and args[0] == "args" and args[1] == "ctx"
    return False


def verify_static(tool_dir: str) -> None:
    base = Path(tool_dir)
    manifest_path = base / "manifest.json"
    tool_path = base / "tool.py"
    if not manifest_path.exists() or not tool_path.exists():
        raise VerifyError("manifest.json and tool.py are required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "name" not in manifest or "version" not in manifest:
        raise VerifyError("Manifest must include name and version")
    if not _has_run_contract(tool_path.read_text(encoding="utf-8")):
        raise VerifyError("tool.py must define run(args, ctx)")


def verify_exec(
    tool_dir: str, ticket: ExecutionTicket, receipt: ApprovalReceipt | None
) -> list[dict]:
    if tbs.normalized_mode() == tbs.MODE_SAFE:
        raise PolicyError("verify_exec is disabled in SAFE mode")
    if not Path(tool_dir).exists():
        raise VerifyError("verify_exec tool_dir does not exist")
    th = ticket_hash(ticket)
    validate_receipt(th, receipt, "MEDIUM")
    append_event(
        ticket.job_id, "execution started", {"ticket_hash": th, "action": "verify_exec"}
    )
    results = run_commands_in_staging(ticket, max_output_kb=tbs.MAX_OUTPUT_KB)
    append_event(
        ticket.job_id, "execution ended", {"ticket_hash": th, "results": results}
    )
    return results


def verify_project(tool_dir: str) -> None:
    verify_static(tool_dir)
