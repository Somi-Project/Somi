from __future__ import annotations

import os
import select
import signal
import subprocess
import time

OUTPUT_CAP = 16000


def _truncate(text: str) -> str:
    if len(text) <= OUTPUT_CAP:
        return text
    return text[:OUTPUT_CAP] + "\n...[truncated]"


def _run_with_pty(cmd: list[str], cwd: str | None, env: dict[str, str], timeout_s: int) -> tuple[int, str, str]:
    master_fd, slave_fd = os.openpty()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        close_fds=True,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    chunks: list[bytes] = []
    deadline = time.monotonic() + max(1, timeout_s)

    try:
        while True:
            if proc.poll() is not None:
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=2)
                return 124, "", f"Timed out after {timeout_s}s"

            r, _, _ = select.select([master_fd], [], [], min(0.2, remaining))
            if not r:
                continue

            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)

        while True:
            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master_fd)

    out = b"".join(chunks).decode("utf-8", errors="replace")
    return int(proc.returncode or 0), out, ""


def run(args: dict, ctx) -> dict:
    bin_name = str(args.get("bin") or "").strip()
    argv = args.get("argv") or []
    cwd = args.get("cwd")
    timeout_s = int(args.get("timeout_s") or 20)
    env_in = args.get("env") or {}
    pty_enabled = bool(args.get("pty", False))
    allowed_bins = [str(x) for x in (args.get("allowed_bins") or []) if str(x).strip()]

    if not bin_name:
        return {"ok": False, "exit_code": 2, "stdout": "", "stderr": "Missing bin"}

    # Never allow path-based execution from this generic tool.
    if os.path.basename(bin_name) != bin_name:
        return {"ok": False, "exit_code": 126, "stdout": "", "stderr": "Bin must be basename only"}

    if not allowed_bins:
        return {"ok": False, "exit_code": 126, "stdout": "", "stderr": "Denied: empty allowlist"}
    if bin_name not in allowed_bins:
        return {"ok": False, "exit_code": 126, "stdout": "", "stderr": f"Denied by allowlist: {bin_name}"}

    cmd = [bin_name] + [str(x) for x in argv]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    env.update({str(k): str(v) for k, v in env_in.items()})

    try:
        if pty_enabled:
            exit_code, stdout, stderr = _run_with_pty(cmd, cwd, env, timeout_s)
        else:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=False,
            )
            exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stdout": "", "stderr": f"Timed out after {timeout_s}s"}
    except FileNotFoundError:
        return {"ok": False, "exit_code": 127, "stdout": "", "stderr": f"Binary not found: {bin_name}"}
    except Exception as exc:
        return {"ok": False, "exit_code": 1, "stdout": "", "stderr": str(exc)}

    return {
        "ok": exit_code == 0,
        "exit_code": int(exit_code),
        "stdout": _truncate(stdout or ""),
        "stderr": _truncate(stderr or ""),
    }
