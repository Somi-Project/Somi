from __future__ import annotations

import argparse
import json
import re
import sys

from executive.engine import ExecutiveEngine
from workshop.toolbox.stacks.contracts_core.store import ArtifactStore
from jobs.engine import JobsEngine
from runtime.ctx import ToolContext
from runtime.errors import PolicyError, VerifyError
from runtime.privilege import PrivilegeLevel
from runtime.stream import PrintStepSink
from workshop.toolbox.dispatch import ToolboxDispatch
from workshop.toolbox.installer import ToolInstaller
from workshop.toolbox.registry import ToolRegistry
from workshop.toolbox.runtime import InternalToolRuntime
from workshop.toolbox.sync_registry import sync_installed_tools
from workshop.toolbox.health import generate_tool_health_report


def run_nl(text: str):
    m = re.search(r"hello.*for\s+([A-Za-z0-9_-]+)", text.lower())
    name = m.group(1) if m else "friend"
    ctx = ToolContext(
        capabilities={"tool.run", "fs.read"}, privilege=PrivilegeLevel.SAFE
    )
    return ToolboxDispatch().run("hello_tool", {"name": name.title()}, ctx)


def _emit_result(result: dict) -> int:
    print(json.dumps(result, indent=2, default=str))
    return 1 if isinstance(result, dict) and "error" in result else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    h = sub.add_parser("mvp-hello")
    h.add_argument("--name", default="Somi")
    h.add_argument("--active", action="store_true")
    h.add_argument("--mode", default="standard")

    c = sub.add_parser("create-tool")
    c.add_argument("name")
    c.add_argument("--description", default="Tool created by Somi toolbox")
    c.add_argument("--active", action="store_true")
    c.add_argument("--mode", default="standard")

    sub.add_parser("list-tools")
    sub.add_parser("sync-tools")
    th = sub.add_parser("tool-health")
    th.add_argument("--strict", action="store_true")
    imp = sub.add_parser("import-tool")
    imp.add_argument("src_dir")
    imp.add_argument("name")
    imp.add_argument("version")
    imp.add_argument("--job-id", default="manual-import")
    r = sub.add_parser("run")
    r.add_argument("tool")
    r.add_argument("--args", default="{}")

    rd = sub.add_parser("run-direct")
    rd.add_argument("tool")
    rd.add_argument("--args", default="{}")

    nl = sub.add_parser("run-nl")
    nl.add_argument("text")

    sj = sub.add_parser("show-job")
    sj.add_argument("job_id")

    art = sub.add_parser("artifacts")
    art_sub = art.add_subparsers(dest="art_cmd")
    art_sub.add_parser("rebuild-index")
    compact = art_sub.add_parser("compact-index")
    compact.add_argument("--max-age-days", type=int, default=180)
    compact.add_argument("--no-adaptive", action="store_true")

    ex = sub.add_parser("exec")
    ex_sub = ex.add_subparsers(dest="exec_cmd")
    ex_sub.add_parser("status")
    ex_sub.add_parser("list")
    ex_sub.add_parser("tick")
    apv = ex_sub.add_parser("approve")
    apv.add_argument("intent_id")
    apv.add_argument("--token", default="")
    rej = ex_sub.add_parser("reject")
    rej.add_argument("intent_id")
    ex_sub.add_parser("pause")
    ex_sub.add_parser("resume")

    args = ap.parse_args()
    try:
        if args.cmd == "mvp-hello":
            out = JobsEngine().run_create_tool(
                "hello_tool",
                "Returns greeting + system time",
                args.mode,
                args.active,
                PrintStepSink(),
                run_args={"name": args.name},
            )
            return _emit_result(out)
        if args.cmd == "create-tool":
            out = JobsEngine().run_create_tool(
                args.name, args.description, args.mode, args.active, PrintStepSink()
            )
            return _emit_result(out)
        if args.cmd == "list-tools":
            print(json.dumps(ToolRegistry().list_tools(), indent=2))
            return 0
        if args.cmd == "sync-tools":
            return _emit_result(sync_installed_tools())
        if args.cmd == "tool-health":
            report = generate_tool_health_report()
            code = _emit_result(report)
            if bool(args.strict) and int(report.get("unhealthy") or 0) > 0:
                return 1
            return code
        if args.cmd == "import-tool":
            ctx = ToolContext(
                capabilities={"tool.install", "fs.read", "fs.write"},
                privilege=PrivilegeLevel.ACTIVE,
            )
            out = ToolInstaller().install(
                src_dir=args.src_dir,
                name=args.name,
                version=args.version,
                ctx=ctx,
                job_id=args.job_id,
            )
            return _emit_result({"ok": True, "installed": out})
        if args.cmd == "run":
            payload = json.loads(args.args)
            ctx = ToolContext(
                capabilities={"tool.run", "fs.read"}, privilege=PrivilegeLevel.SAFE
            )
            return _emit_result(ToolboxDispatch().run(args.tool, payload, ctx))
        if args.cmd == "run-direct":
            payload = json.loads(args.args)
            reg = ToolRegistry()
            entry = reg.find(args.tool)
            if not entry:
                return _emit_result({"error": f"tool not found: {args.tool}"})
            policy = dict(entry.get("policy") or {})
            if bool(policy.get("requires_approval", True)):
                return _emit_result({"error": "run-direct denied: tool requires approval"})
            out = InternalToolRuntime(registry=reg).run(args.tool, payload, {"source": "cli", "approved": True})
            if isinstance(out, dict):
                return _emit_result(out)
            return _emit_result({"ok": True, "result": out})
        if args.cmd == "run-nl":
            return _emit_result(run_nl(args.text))
        if args.cmd == "show-job":
            path = f"jobs/history/{args.job_id}.json"
            with open(path, "r", encoding="utf-8") as f:
                print(f.read())
            return 0
        if args.cmd == "artifacts":
            if args.art_cmd == "rebuild-index":
                ArtifactStore().rebuild_indexes()
                return _emit_result({"ok": True, "message": "artifact indexes rebuilt"})
            if args.art_cmd == "compact-index":
                stats = ArtifactStore().compact_global_indexes(max_age_days=int(args.max_age_days), adaptive=not bool(args.no_adaptive))
                return _emit_result({"ok": True, "message": "artifact indexes compacted", "stats": stats, "adaptive": not bool(args.no_adaptive)})
            return _emit_result({"error": "unknown artifacts subcommand"})

        if args.cmd == "exec":
            engine = ExecutiveEngine()
            if args.exec_cmd in ("status", "list"):
                print(
                    json.dumps(
                        {"paused": engine.paused, "items": engine.queue.list()},
                        indent=2,
                    )
                )
                return 0
            if args.exec_cmd == "tick":
                return _emit_result(engine.tick())
            if args.exec_cmd == "approve":
                return _emit_result(
                    engine.approve_and_run(
                        args.intent_id, approval_token=args.token or None
                    )
                )
            if args.exec_cmd == "reject":
                return _emit_result(engine.queue.set_state(args.intent_id, "REJECTED"))
            if args.exec_cmd == "pause":
                return _emit_result(engine.set_paused(True))
            if args.exec_cmd == "resume":
                return _emit_result(engine.set_paused(False))
            return _emit_result({"error": "unknown exec subcommand"})

        ap.print_help()
        return 2
    except (
        json.JSONDecodeError,
        VerifyError,
        PolicyError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

