from __future__ import annotations

import argparse
import json
import re
import sys

from executive.engine import ExecutiveEngine
from jobs.engine import JobsEngine
from runtime.ctx import ToolContext
from runtime.errors import PolicyError, VerifyError
from runtime.privilege import PrivilegeLevel
from runtime.stream import PrintStepSink
from toolbox.dispatch import ToolboxDispatch
from toolbox.registry import ToolRegistry


def run_nl(text: str):
    m = re.search(r"hello.*for\s+([A-Za-z0-9_-]+)", text.lower())
    name = m.group(1) if m else "friend"
    ctx = ToolContext(capabilities={"tool.run", "fs.read"}, privilege=PrivilegeLevel.SAFE)
    return ToolboxDispatch().run("hello_tool", {"name": name.title()}, ctx)


def _emit_result(result: dict) -> int:
    print(json.dumps(result, indent=2))
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
    r = sub.add_parser("run")
    r.add_argument("tool")
    r.add_argument("--args", default="{}")

    nl = sub.add_parser("run-nl")
    nl.add_argument("text")

    sj = sub.add_parser("show-job")
    sj.add_argument("job_id")

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
            out = JobsEngine().run_create_tool(args.name, args.description, args.mode, args.active, PrintStepSink())
            return _emit_result(out)
        if args.cmd == "list-tools":
            print(json.dumps(ToolRegistry().list_tools(), indent=2))
            return 0
        if args.cmd == "run":
            payload = json.loads(args.args)
            ctx = ToolContext(capabilities={"tool.run", "fs.read"}, privilege=PrivilegeLevel.SAFE)
            return _emit_result(ToolboxDispatch().run(args.tool, payload, ctx))
        if args.cmd == "run-nl":
            return _emit_result(run_nl(args.text))
        if args.cmd == "show-job":
            path = f"jobs/history/{args.job_id}.json"
            with open(path, "r", encoding="utf-8") as f:
                print(f.read())
            return 0
        if args.cmd == "exec":
            engine = ExecutiveEngine()
            if args.exec_cmd in ("status", "list"):
                print(json.dumps({"paused": engine.paused, "items": engine.queue.list()}, indent=2))
                return 0
            if args.exec_cmd == "tick":
                return _emit_result(engine.tick())
            if args.exec_cmd == "approve":
                return _emit_result(engine.approve_and_run(args.intent_id, approval_token=args.token or None))
            if args.exec_cmd == "reject":
                return _emit_result(engine.queue.set_state(args.intent_id, "REJECTED"))
            if args.exec_cmd == "pause":
                return _emit_result(engine.set_paused(True))
            if args.exec_cmd == "resume":
                return _emit_result(engine.set_paused(False))
            return _emit_result({"error": "unknown exec subcommand"})

        ap.print_help()
        return 2
    except (json.JSONDecodeError, VerifyError, PolicyError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
