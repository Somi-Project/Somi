from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


def _run_git(root_path: Path, args: list[str], *, timeout_s: int = 30) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        ["git", *list(args or [])],
        cwd=str(root_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, int(timeout_s or 30)),
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": int(proc.returncode),
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
        "command": "git " + " ".join(str(x) for x in list(args or [])),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _git_installed(root_path: Path) -> bool:
    try:
        result = _run_git(root_path, ["--version"], timeout_s=10)
    except Exception:
        return False
    return bool(result.get("ok"))


def _is_git_repo(root_path: Path) -> bool:
    try:
        result = _run_git(root_path, ["rev-parse", "--is-inside-work-tree"], timeout_s=10)
    except Exception:
        return False
    return bool(result.get("ok")) and "true" in str(result.get("stdout") or "").lower()


def _parse_branch_header(header: str) -> dict[str, Any]:
    text = str(header or "").strip()
    if text.startswith("## "):
        text = text[3:]
    branch = text
    upstream = ""
    ahead = 0
    behind = 0
    detached = False

    if "..." in text:
        branch, remainder = text.split("...", 1)
        if " [" in remainder:
            upstream, detail = remainder.split(" [", 1)
            detail = detail.rstrip("] ")
            ahead_match = re.search(r"ahead (\d+)", detail)
            behind_match = re.search(r"behind (\d+)", detail)
            ahead = int(ahead_match.group(1)) if ahead_match else 0
            behind = int(behind_match.group(1)) if behind_match else 0
        else:
            upstream = remainder.strip()
    elif " " in text:
        branch = text.split(" ", 1)[0].strip()

    detached = branch in {"HEAD", "(detached)"} or branch.startswith("HEAD")
    return {
        "branch": branch.strip(),
        "upstream": upstream.strip(),
        "ahead": ahead,
        "behind": behind,
        "detached": detached,
    }


def _parse_changed_path(line: str) -> str:
    text = str(line or "").rstrip()
    if not text or text.startswith("## "):
        return ""
    payload = text[3:] if len(text) > 3 else text
    if " -> " in payload:
        payload = payload.split(" -> ", 1)[1]
    return payload.strip().strip('"')


def workspace_git_status(root_path: str | Path) -> dict[str, Any]:
    root = Path(root_path).resolve()
    git_installed = _git_installed(root)
    if not git_installed:
        return {
            "ok": False,
            "available": False,
            "git_installed": False,
            "clean": True,
            "summary": "git is not installed",
            "changed_files": [],
            "status_lines": [],
            "remotes": [],
        }
    if not _is_git_repo(root):
        return {
            "ok": True,
            "available": False,
            "git_installed": True,
            "clean": True,
            "branch": "",
            "upstream": "",
            "ahead": 0,
            "behind": 0,
            "detached": False,
            "summary": "not a git repo",
            "changed_files": [],
            "status_lines": [],
            "remotes": [],
            "last_commit": "",
        }

    status_result = _run_git(root, ["status", "--short", "--branch"], timeout_s=15)
    lines = [line.rstrip() for line in str(status_result.get("stdout") or "").splitlines() if line.strip()]
    branch_meta = _parse_branch_header(lines[0] if lines else "")
    changed_lines = [line for line in lines[1:] if line.strip()]
    changed_files = [path for path in (_parse_changed_path(line) for line in changed_lines) if path]

    remotes_result = _run_git(root, ["remote", "-v"], timeout_s=10)
    remotes: list[dict[str, str]] = []
    for line in str(remotes_result.get("stdout") or "").splitlines():
        parts = line.split()
        if len(parts) >= 3:
            remotes.append({"name": parts[0].strip(), "url": parts[1].strip(), "kind": parts[2].strip("()")})
    unique_remotes: list[dict[str, str]] = []
    seen_remote_keys: set[tuple[str, str, str]] = set()
    for row in remotes:
        key = (row["name"], row["url"], row["kind"])
        if key in seen_remote_keys:
            continue
        seen_remote_keys.add(key)
        unique_remotes.append(row)

    last_commit_result = _run_git(root, ["--no-pager", "log", "-1", "--pretty=format:%h %s"], timeout_s=10)
    last_commit = str(last_commit_result.get("stdout") or "").strip()
    clean = not changed_lines
    summary_parts = [branch_meta.get("branch") or "detached", "clean" if clean else f"{len(changed_files)} changed"]
    if branch_meta.get("upstream"):
        ahead = int(branch_meta.get("ahead") or 0)
        behind = int(branch_meta.get("behind") or 0)
        if ahead or behind:
            summary_parts.append(f"+{ahead}/-{behind}")
        else:
            summary_parts.append("synced")
    elif unique_remotes:
        summary_parts.append("no upstream")

    return {
        "ok": bool(status_result.get("ok")),
        "available": True,
        "git_installed": True,
        "branch": str(branch_meta.get("branch") or ""),
        "upstream": str(branch_meta.get("upstream") or ""),
        "ahead": int(branch_meta.get("ahead") or 0),
        "behind": int(branch_meta.get("behind") or 0),
        "detached": bool(branch_meta.get("detached")),
        "clean": clean,
        "summary": " | ".join(summary_parts),
        "changed_files": changed_files,
        "status_lines": changed_lines,
        "remotes": unique_remotes,
        "last_commit": last_commit,
    }


def workspace_git_diff(
    root_path: str | Path,
    *,
    relative_path: str = "",
    staged: bool = False,
    max_chars: int = 16000,
) -> dict[str, Any]:
    root = Path(root_path).resolve()
    status = workspace_git_status(root)
    if not bool(status.get("available")):
        return {"ok": False, "error": "Workspace is not a git repository.", "diff": "", "truncated": False}

    args = ["--no-pager", "diff"]
    if staged:
        args.append("--cached")
    args.append("--no-ext-diff")
    if str(relative_path or "").strip():
        args.extend(["--", str(relative_path).strip()])
    result = _run_git(root, args, timeout_s=20)
    diff_text = str(result.get("stdout") or "")
    cap = max(500, min(int(max_chars or 16000), 40000))
    return {
        "ok": bool(result.get("ok")),
        "diff": diff_text[:cap],
        "chars": len(diff_text),
        "truncated": len(diff_text) > cap,
        "relative_path": str(relative_path or "").strip(),
        "staged": bool(staged),
        "stderr": str(result.get("stderr") or "").strip(),
    }


def workspace_git_commit(
    root_path: str | Path,
    *,
    message: str,
    add_paths: list[str] | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    root = Path(root_path).resolve()
    status = workspace_git_status(root)
    if not bool(status.get("available")):
        return {"ok": False, "status": "not_git_repo", "error": "Workspace is not a git repository."}

    commit_message = " ".join(str(message or "").split()).strip()
    if not commit_message:
        return {"ok": False, "status": "missing_message", "error": "Commit message is required."}

    pathspecs = [str(item).strip() for item in list(add_paths or []) if str(item).strip()]
    add_args = ["add", "-A"]
    if pathspecs:
        add_args.extend(["--", *pathspecs])
    else:
        add_args.append(".")
    add_result = _run_git(root, add_args, timeout_s=20)
    if not bool(add_result.get("ok")):
        return {
            "ok": False,
            "status": "add_failed",
            "error": str(add_result.get("stderr") or add_result.get("stdout") or "").strip(),
        }

    staged_check = _run_git(root, ["diff", "--cached", "--quiet", "--exit-code"], timeout_s=10)
    if int(staged_check.get("returncode") or 0) == 0 and not allow_empty:
        return {
            "ok": False,
            "status": "no_changes",
            "error": "No staged changes to commit.",
            "git": workspace_git_status(root),
        }

    commit_args = ["commit", "-m", commit_message]
    if allow_empty:
        commit_args.append("--allow-empty")
    commit_result = _run_git(root, commit_args, timeout_s=30)
    ok = bool(commit_result.get("ok"))
    head_result = _run_git(root, ["rev-parse", "HEAD"], timeout_s=10) if ok else {"stdout": ""}
    last_commit_result = _run_git(root, ["--no-pager", "log", "-1", "--pretty=format:%h %s"], timeout_s=10) if ok else {"stdout": ""}
    return {
        "ok": ok,
        "status": "committed" if ok else "commit_failed",
        "message": commit_message,
        "commit": str(head_result.get("stdout") or "").strip(),
        "last_commit": str(last_commit_result.get("stdout") or "").strip(),
        "stdout": str(commit_result.get("stdout") or "").strip(),
        "stderr": str(commit_result.get("stderr") or "").strip(),
        "git": workspace_git_status(root),
    }


def workspace_git_publish_status(
    root_path: str | Path,
    *,
    remote: str = "origin",
    branch: str = "",
) -> dict[str, Any]:
    root = Path(root_path).resolve()
    status = workspace_git_status(root)
    if not bool(status.get("available")):
        return {
            "ok": False,
            "remote_configured": False,
            "branch": "",
            "summary": "Workspace is not a git repository.",
            "git": status,
        }

    current_branch = str(branch or status.get("branch") or "").strip()
    remote_name = str(remote or "origin").strip() or "origin"
    remote_url_result = _run_git(root, ["remote", "get-url", remote_name], timeout_s=10)
    remote_configured = bool(remote_url_result.get("ok"))
    remote_url = str(remote_url_result.get("stdout") or "").strip()
    upstream = str(status.get("upstream") or "").strip()
    ahead = int(status.get("ahead") or 0)
    behind = int(status.get("behind") or 0)
    remote_branch_exists = False

    if remote_configured and current_branch:
        ls_remote = _run_git(root, ["ls-remote", "--heads", remote_name, current_branch], timeout_s=20)
        remote_branch_exists = bool(str(ls_remote.get("stdout") or "").strip())

    summary = "not publish-ready"
    if not remote_configured:
        summary = f"Remote '{remote_name}' is not configured"
    elif not current_branch:
        summary = "No current branch is available"
    elif not upstream:
        summary = f"{current_branch} has no upstream"
    elif ahead or behind:
        summary = f"{current_branch} is +{ahead}/-{behind} against {upstream}"
    else:
        summary = f"{current_branch} is synced with {upstream}"

    return {
        "ok": remote_configured and bool(current_branch),
        "remote": remote_name,
        "remote_url": remote_url,
        "remote_configured": remote_configured,
        "branch": current_branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "remote_branch_exists": remote_branch_exists,
        "summary": summary,
        "git": status,
    }


def workspace_git_push(
    root_path: str | Path,
    *,
    remote: str = "origin",
    branch: str = "",
    set_upstream: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(root_path).resolve()
    publish_status = workspace_git_publish_status(root, remote=remote, branch=branch)
    if not bool(publish_status.get("remote_configured")):
        return {
            "ok": False,
            "status": "remote_missing",
            "error": str(publish_status.get("summary") or "Remote is not configured."),
            "publish_status": publish_status,
        }
    current_branch = str(publish_status.get("branch") or "").strip()
    if not current_branch:
        return {
            "ok": False,
            "status": "missing_branch",
            "error": "No current branch is available for push.",
            "publish_status": publish_status,
        }

    args = ["push"]
    if dry_run:
        args.append("--dry-run")
    if set_upstream or not str(publish_status.get("upstream") or "").strip():
        args.append("--set-upstream")
    args.extend([str(remote or "origin"), current_branch])
    result = _run_git(root, args, timeout_s=45)
    return {
        "ok": bool(result.get("ok")),
        "status": "pushed" if bool(result.get("ok")) and not dry_run else ("dry_run" if bool(result.get("ok")) else "push_failed"),
        "remote": str(remote or "origin"),
        "branch": current_branch,
        "dry_run": bool(dry_run),
        "stdout": str(result.get("stdout") or "").strip(),
        "stderr": str(result.get("stderr") or "").strip(),
        "publish_status": workspace_git_publish_status(root, remote=remote, branch=current_branch),
    }
