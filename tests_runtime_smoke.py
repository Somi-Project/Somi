from __future__ import annotations

from pathlib import Path

from executive.engine import ExecutiveEngine
from executive.queue import ExecutiveQueue
from runtime.cancel import CancelToken
from runtime.ctx import ToolContext
from runtime.errors import CancelledError, SandboxError, ShellError
from runtime.fs_ops import FSOps
from runtime.journal import Journal
from runtime.privilege import PrivilegeLevel
from runtime.sandbox import WorkspaceSandbox
from runtime.shell import ShellRunner
from runtime.hashing import sha256_file
from toolbox.loader import ToolLoader
from toolbox.registry import ToolRegistry


def main():
    journal_path = Path("tmp/test_runtime.journal.jsonl")
    ctx = ToolContext(capabilities={"fs.read", "fs.write", "shell.exec"}, privilege=PrivilegeLevel.SAFE)
    fs = FSOps(WorkspaceSandbox("tmp/workspace"), Journal(journal_path), ctx)

    fs.mkdir(".")
    fs.write_text("ok.txt", "hello")
    assert Path("tmp/workspace/ok.txt").exists(), "FSOps write failed"

    try:
        fs.write_text("../bad.txt", "no")
        raise AssertionError("Traversal should fail")
    except SandboxError:
        pass

    try:
        fs.sandbox.resolve("../workspace_evil/hack.txt")
        raise AssertionError("Prefix traversal should fail")
    except SandboxError:
        pass

    try:
        ShellRunner(allowlist={"python"}, cwd=".").run(["bash", "-lc", "echo hi"], ctx)
        raise AssertionError("Non-allowlisted command should fail")
    except ShellError:
        pass

    tok = CancelToken()
    tok.cancel()
    assert tok.is_cancelled(), "CancelToken failed"
    try:
        tok.raise_if_cancelled()
        raise AssertionError("raise_if_cancelled should raise")
    except CancelledError:
        pass

    engine = ExecutiveEngine()
    engine.set_paused(False)
    created = engine.tick()
    assert created.get("intent_id"), "Executive did not create intent"
    assert created.get("approval_token"), "Approval token missing in response"

    # Ensure plaintext token is NOT persisted in queue.
    stored = next((it for it in engine.queue.list() if it.get("intent_id") == created["intent_id"]), {})
    assert "approval_token" not in stored, "Plain approval token must not be persisted"
    assert stored.get("approval_token_hash"), "Token hash should be persisted"

    engine_fresh = ExecutiveEngine()
    bad = engine_fresh.approve_and_run(created["intent_id"], "wrong-token")
    assert "error" in bad, "Wrong token should fail"

    approved = engine_fresh.approve_and_run(created["intent_id"], created.get("approval_token"))
    assert "error" not in approved, f"Approval flow failed across sessions: {approved}"


    # Loader contract check should not execute import-time side effects.
    side = Path("tmp/side_effect.txt")
    tool_dir = Path("tmp/noexec_tool")
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "tool.py").write_text("from pathlib import Path\nPath('tmp/side_effect.txt').write_text('bad')\ndef run(args, ctx):\n    return {'ok': True}\n", encoding="utf-8")
    (tool_dir / "manifest.json").write_text('{"name":"noexec","version":"0.1.0"}', encoding="utf-8")
    hashes = {"tool.py": sha256_file(tool_dir / "tool.py"), "manifest.json": sha256_file(tool_dir / "manifest.json")}
    reg = ToolRegistry("tmp/registry.json")
    reg.register({"name": "noexec", "version": "0.1.0", "path": str(tool_dir), "hashes": hashes, "enabled": True})
    ToolLoader(registry=reg).load("noexec")
    assert not side.exists(), "Loader contract validation executed import side effects"


    # Loader subprocess should block network calls from tool runtime.
    net_dir = Path("tmp/net_tool")
    net_dir.mkdir(parents=True, exist_ok=True)
    (net_dir / "tool.py").write_text("import socket\ndef run(args, ctx):\n    socket.create_connection(('example.com', 80), timeout=1)\n    return {'ok': True}\n", encoding="utf-8")
    (net_dir / "manifest.json").write_text('{"name":"nettool","version":"0.1.0"}', encoding="utf-8")
    net_hashes = {"tool.py": sha256_file(net_dir / "tool.py"), "manifest.json": sha256_file(net_dir / "manifest.json")}
    reg.register({"name": "nettool", "version": "0.1.0", "path": str(net_dir), "hashes": net_hashes, "enabled": True})
    net_runner = ToolLoader(registry=reg).load("nettool")
    try:
        net_runner({}, None)
        raise AssertionError("Networked tool should be blocked")
    except Exception:
        pass

    q = ExecutiveQueue(queue_path="tmp/q.json", history_path="tmp/q.hist.jsonl")
    Path("tmp/q.json").write_text("{ bad json", encoding="utf-8")
    assert q.list() == [], "Corrupt queue should self-heal to empty list"

    assert journal_path.exists(), "Journal file not written"
    print("runtime smoke passed")


if __name__ == "__main__":
    main()
