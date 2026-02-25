from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

from config import toolboxsettings as tbs
from runtime.approval import ApprovalReceipt, validate_receipt
from runtime.audit import append_event
from runtime.errors import PolicyError, VerifyError
from runtime.hashing import sha256_file
from runtime.risk import assess
from runtime.ticketing import ExecutionTicket, ticket_hash, validate_ticket_integrity
from toolbox.registry import ToolRegistry


class ToolLoader:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        timeout_s: int | None = None,
        output_cap: int = 8000,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.timeout_s = timeout_s or tbs.EXEC_TIMEOUT_SECONDS
        self.output_cap = output_cap

    def _verify(self, entry: dict) -> None:
        hashes = entry.get("hashes", {})
        expected_files = sorted(hashes.keys())
        actual_files: list[str] = []
        for file_path in Path(entry["path"]).rglob("*"):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(entry["path"]))
            if rel.startswith(".sandbox_home/"):
                continue
            actual_files.append(rel)
        if sorted(actual_files) != expected_files:
            raise VerifyError("Installed file set mismatch")
        for rel, expected in hashes.items():
            target = Path(entry["path"]) / rel
            if not target.exists() or not target.is_file():
                raise VerifyError(f"Missing hashed file: {rel}")
            actual = sha256_file(target)
            if actual != expected:
                raise VerifyError(f"Hash mismatch for {rel}")

    def _validate_contract(self, tool_path: Path) -> None:
        source = tool_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                args = [a.arg for a in node.args.args]
                if len(args) >= 2 and args[0] == "args" and args[1] == "ctx":
                    return
                raise VerifyError("tool.py run signature must be run(args, ctx)")
        raise VerifyError("tool.py missing callable run(args, ctx)")

    def _validate_runtime_guards(self, ticket: ExecutionTicket) -> None:
        cmd_text = "\n".join(" ".join(c).lower() for c in ticket.commands)
        if tbs.normalized_mode() != tbs.MODE_SYSTEM_AGENT:
            for pat in tbs.NEVER_DO_PATTERNS:
                if pat.lower() in cmd_text:
                    raise PolicyError(
                        f"Command pattern blocked by NEVER_DO policy: {pat}"
                    )
            if ticket.allow_system_wide:
                raise PolicyError("System-wide execution requires system_agent mode")
            protected = [Path(p).expanduser().resolve() for p in tbs.PROTECTED_PATHS]
            for rw in ticket.paths_rw:
                path = Path(rw).expanduser().resolve()
                if any(str(path).startswith(str(prot)) for prot in protected):
                    raise PolicyError(f"Protected path blocked: {rw}")
        if tbs.normalized_mode() == tbs.MODE_GUIDED:
            staging_root = (
                Path("sessions/jobs") / ticket.job_id / "staging_repo"
            ).resolve()
            cwd = Path(ticket.cwd).expanduser().resolve()
            if not str(cwd).startswith(str(staging_root)):
                raise PolicyError(
                    "GUIDED mode allows execution only in staging workspace"
                )

    def propose_exec(
        self, name: str, args: dict, job_id: str = "manual"
    ) -> ExecutionTicket:
        entry = self.registry.find(name)
        if not entry:
            raise VerifyError(f"Tool not found: {name}")
        self._verify(entry)
        tool_path = Path(entry["path"]) / "tool.py"
        self._validate_contract(tool_path)
        code = (
            "import json,importlib.util\n"
            "args=json.loads(__import__('sys').argv[1])\n"
            "spec=importlib.util.spec_from_file_location('tool_runtime', 'tool.py')\n"
            "mod=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "print(json.dumps(mod.run(args, {'approved': True})))\n"
        )
        return ExecutionTicket(
            job_id=job_id,
            action="execute",
            commands=[["python", "-I", "-c", code, json.dumps(args)]],
            cwd=entry["path"],
            allow_network=tbs.ALLOW_NETWORK,
            allow_external_apps=tbs.ALLOW_EXTERNAL_APPS,
            allow_delete=tbs.ALLOW_DELETE_ACTIONS,
            allow_system_wide=tbs.ALLOW_SYSTEM_WIDE_ACTIONS,
            paths_rw=[entry["path"]],
            timeout_seconds=self.timeout_s,
        )

    def execute_with_approval(
        self, ticket: ExecutionTicket, receipt: ApprovalReceipt | None
    ) -> dict:
        th = ticket_hash(ticket)
        report = assess(ticket, settings=tbs)
        validate_receipt(th, receipt, report.tier)
        validate_ticket_integrity(ticket, receipt.ticket_hash if receipt else th)
        append_event(
            ticket.job_id, "approval granted", {"ticket_hash": th, "risk": report.tier}
        )
        if tbs.normalized_mode() == tbs.MODE_SAFE:
            raise PolicyError("SAFE mode cannot execute")
        self._validate_runtime_guards(ticket)

        cmd = ticket.commands[0]
        env = {"PATH": os.environ.get("PATH", ""), **ticket.env_overrides}
        proc = subprocess.run(
            cmd,
            cwd=ticket.cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=ticket.timeout_seconds,
        )
        out = (proc.stdout + proc.stderr)[: self.output_cap]
        append_event(
            ticket.job_id,
            "execution ended",
            {"ticket_hash": th, "code": proc.returncode},
        )
        if proc.returncode != 0:
            raise VerifyError(f"Tool execution failed: {out}")
        return json.loads(proc.stdout.strip() or "{}")

    def load(self, name: str):
        def run_tool(args: dict, ctx):
            raise PolicyError(
                "Direct tool execution disabled; use propose_exec + execute_with_approval"
            )

        return run_tool
