from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path

from runtime.errors import VerifyError
from runtime.ticketing import ExecutionTicket


def staging_repo_dir(job_id: str) -> Path:
    return Path("sessions/jobs") / job_id / "staging_repo"


def _rollback_archive(job_id: str) -> Path:
    return Path("sessions/jobs") / job_id / "rollback_snapshot.tar.gz"


def create_staging_copy(job_id: str, source_repo: str = ".") -> Path:
    src = Path(source_repo).resolve()
    dest = staging_repo_dir(job_id)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    return dest


def apply_patch_to_staging(job_id: str, patch: str) -> None:
    patch_file = staging_repo_dir(job_id) / "proposed.patch"
    patch_file.write_text(patch, encoding="utf-8")


def create_snapshot_before_apply(job_id: str, repo: str = ".") -> dict:
    repo_path = Path(repo).resolve()
    archive = _rollback_archive(job_id)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(repo_path, arcname="repo", filter=lambda x: None if ".git/" in x.name else x)
    if (repo_path / ".git").exists():
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_path), text=True).strip()
        return {"kind": "git", "head": head, "archive": str(archive)}
    return {"kind": "files", "archive": str(archive)}


def _resolve_staging_cwd(ticket: ExecutionTicket) -> Path:
    root = staging_repo_dir(ticket.job_id).resolve()
    raw = Path(ticket.cwd)
    cwd = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not str(cwd).startswith(str(root)):
        raise VerifyError("staging cwd escapes staging root")
    return cwd


def run_commands_in_staging(ticket: ExecutionTicket, max_output_kb: int = 512) -> list[dict]:
    out: list[dict] = []
    cwd = _resolve_staging_cwd(ticket)
    for cmd in ticket.commands:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=ticket.timeout_seconds)
        output = (proc.stdout + proc.stderr)[: max_output_kb * 1024]
        out.append({"cmd": cmd, "code": proc.returncode, "output": output})
    return out


def _safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in tar.getmembers():
        target = (destination / member.name).resolve()
        if not str(target).startswith(str(root)):
            raise VerifyError("rollback archive contains unsafe path")
    tar.extractall(destination)


def rollback_staging(job_id: str) -> None:
    dest = staging_repo_dir(job_id)
    archive = _rollback_archive(job_id)
    if dest.exists():
        shutil.rmtree(dest)
    if archive.exists():
        with tarfile.open(archive, "r:gz") as tar:
            _safe_extract(tar, dest.parent)
        restored = dest.parent / "repo"
        if restored.exists():
            restored.rename(dest)
