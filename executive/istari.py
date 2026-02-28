from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from handlers.contracts.store import ArtifactStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


RISK_TIERS = {"tier0", "tier1", "tier2", "tier3", "tier4"}


@dataclass(frozen=True)
class Capability:
    capability_id: str
    risk_tier: str
    enabled: bool
    requires_approval: bool
    allowed_roots: list[str]
    protected_paths: list[str]
    allow_commands: list[str]
    deny_patterns: list[str]
    preconditions: list[str]


class CapabilityRegistry:
    def __init__(self, path: str = "config/capability_registry.json") -> None:
        self.path = Path(path)
        self.capabilities: dict[str, Capability] = {}
        self.load()

    def load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        caps: dict[str, Capability] = {}
        for row in list(raw.get("capabilities") or []):
            cid = str(row.get("id") or "").strip()
            if not cid:
                raise ValueError("capability id required")
            tier = str(row.get("risk_tier") or "").strip()
            if tier not in RISK_TIERS:
                raise ValueError(f"invalid tier for {cid}")
            caps[cid] = Capability(
                capability_id=cid,
                risk_tier=tier,
                enabled=bool(row.get("enabled", True)),
                requires_approval=bool(row.get("requires_approval", False) or tier in {"tier2", "tier3", "tier4"}),
                allowed_roots=[str(x) for x in list(row.get("allowed_roots") or [])],
                protected_paths=[str(x) for x in list(row.get("protected_paths") or [])],
                allow_commands=[str(x) for x in list(row.get("command_allowlist") or [])],
                deny_patterns=[str(x) for x in list(row.get("command_denylist_patterns") or [])],
                preconditions=[str(x) for x in list(row.get("preconditions") or [])],
            )
        self.capabilities = caps

    def get(self, capability_id: str) -> Capability:
        cap = self.capabilities.get(str(capability_id or ""))
        if cap is None:
            raise ValueError(f"capability not found: {capability_id}")
        return cap


class ProposalStore:
    def __init__(self, root: str = "executive") -> None:
        self.path = Path(root) / "pending_proposals.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, proposal: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(_json_dumps(proposal) + "\n")

    def list_pending(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    def find(self, proposal_id: str) -> dict[str, Any] | None:
        for p in reversed(self.list_pending()):
            if str(p.get("proposal_id")) == str(proposal_id):
                return p
        return None


class TokenStore:
    def __init__(self, root: str = "executive") -> None:
        self.path = Path(root) / "tokens.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def issue(self, proposal: dict[str, Any], ttl_seconds: int = 300, one_time: bool = True) -> dict[str, Any]:
        token = secrets.token_urlsafe(24)
        digest = self.digest(token)
        now = _utc_now()
        payload = {
            "type": "approval_token",
            "token_id": secrets.token_hex(8),
            "token_digest": digest,
            "proposal_id": proposal["proposal_id"],
            "capability": proposal["capability"],
            "scope": dict(proposal.get("scope") or {}),
            "issued_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=max(1, int(ttl_seconds)))),
            "one_time": bool(one_time),
            "revoked": False,
            "redeemed_at": None,
            "no_autonomy": True,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(_json_dumps(payload) + "\n")
        shown = dict(payload)
        shown["token"] = token
        return shown

    def _all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def _append(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(_json_dumps(row) + "\n")

    def validate(self, token: str, proposal_id: str) -> tuple[bool, str, dict[str, Any] | None]:
        digest = self.digest(token)
        rows = [r for r in self._all() if str(r.get("token_digest")) == digest]
        if not rows:
            return False, "token_missing", None

        base = next((r for r in rows if r.get("type") == "approval_token" and r.get("proposal_id")), None)
        if not base:
            return False, "token_missing", None
        if str(base.get("proposal_id")) != str(proposal_id):
            return False, "proposal_mismatch", base

        revoked = any(r.get("type") == "revoked_token" for r in rows) or bool(base.get("revoked"))
        redeemed_at = base.get("redeemed_at") or next((r.get("redeemed_at") for r in reversed(rows) if r.get("redeemed_at")), None)

        if revoked:
            return False, "token_revoked", base
        if _utc_now() >= datetime.fromisoformat(str(base.get("expires_at"))):
            return False, "token_expired", base
        if bool(base.get("one_time")) and redeemed_at:
            return False, "token_already_used", base
        return True, "ok", base

    def redeem(self, token_digest: str) -> None:
        self._append({"type": "approval_token_redeem", "token_digest": token_digest, "redeemed_at": _iso(_utc_now())})

    def revoke(self, *, token_digest: str | None = None, proposal_id: str | None = None, all_tokens: bool = False, reason: str = "user_request") -> list[dict[str, Any]]:
        revoked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._all():
            if str(row.get("type") or "") != "approval_token":
                continue
            dig = str(row.get("token_digest") or "")
            if not dig or dig in seen:
                continue
            hit = bool(all_tokens or (token_digest and dig == token_digest) or (proposal_id and row.get("proposal_id") == proposal_id))
            if not hit:
                continue
            event = {
                "type": "revoked_token",
                "token_digest": dig,
                "revoked_at": _iso(_utc_now()),
                "reason": reason,
                "no_autonomy": True,
            }
            self._append(event)
            revoked.append(event)
            seen.add(dig)
        return revoked


class AuditLog:
    def __init__(self, root: str = "audit") -> None:
        self.events_path = Path(root) / "events.jsonl"
        self.index_path = Path(root) / "index.json"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._redactor = ArtifactStore()

    def append(self, event_type: str, proposal_id: str, capability: str, summary: str, token_digest: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        eid = f"evt_{secrets.token_hex(6)}"
        evt = {
            "event_id": eid,
            "timestamp": _iso(_utc_now()),
            "event_type": event_type,
            "proposal_id": proposal_id,
            "token_digest": token_digest,
            "capability": capability,
            "summary": summary[:240],
            "metadata": dict(metadata or {}),
        }
        evt, _ = self._redactor._redact_value(evt)
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(_json_dumps(evt) + "\n")
        idx = {}
        if self.index_path.exists():
            idx = json.loads(self.index_path.read_text(encoding="utf-8"))
        idx.setdefault("proposal_id", {}).setdefault(proposal_id, []).append(eid)
        if token_digest:
            idx.setdefault("token_digest", {}).setdefault(token_digest, []).append(eid)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)
        return eid


def build_proposal(*, capability: str, summary: str, justification: list[str], scope: dict[str, Any], steps: list[dict[str, Any]], related_artifact_ids: list[str] | None = None, expires_in_s: int = 300, ui_hints: dict[str, Any] | None = None, risk_tier: str = "tier2") -> dict[str, Any]:
    stable = {
        "capability": capability,
        "summary": summary,
        "scope": scope,
        "steps": steps,
    }
    proposal_id = hashlib.sha256(_json_dumps(stable).encode("utf-8")).hexdigest()[:20]
    return {
        "type": "proposal_action",
        "proposal_id": proposal_id,
        "capability": capability,
        "risk_tier": risk_tier,
        "summary": summary,
        "justification": [str(x)[:240] for x in list(justification or [])][:8],
        "scope": dict(scope or {}),
        "steps": list(steps or []),
        "preconditions": ["diff preview will be shown"] if capability == "file.write_scoped" else (["command preview shown"] if capability == "shell.exec_scoped" else []),
        "requires_approval": True,
        "expires_in_s": max(1, int(expires_in_s)),
        "no_autonomy": True,
        "related_artifact_ids": [str(x) for x in list(related_artifact_ids or [])][:20],
        "ui_hints": dict(ui_hints or {}),
    }


class PolicyEnforcer:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def _normalize_command(self, command: Any) -> str:
        if isinstance(command, list):
            return " ".join(str(x).strip() for x in command if str(x).strip())
        return str(command or "").strip()

    def _path_ok(self, path: str, roots: list[str], protected: list[str]) -> tuple[bool, str]:
        p = Path(path)
        if ".." in p.parts:
            return False, "path_traversal"
        full = p.resolve()
        if roots:
            allowed = False
            for r in roots:
                rr = Path(r).resolve()
                if str(full).startswith(str(rr)):
                    allowed = True
                    break
            if not allowed:
                return False, "outside_allowed_roots"
        for pp in protected:
            rp = Path(pp).resolve()
            if str(full).startswith(str(rp)):
                return False, "protected_path"
        return True, "ok"

    def enforce(self, proposal: dict[str, Any], token_row: dict[str, Any], preview_ready: bool = False) -> tuple[bool, list[dict[str, str]]]:
        errs: list[dict[str, str]] = []
        cap = self.registry.get(str(proposal.get("capability") or ""))
        if not cap.enabled:
            errs.append({"code": "capability_disabled", "message": cap.capability_id})
        if cap.requires_approval and not token_row:
            errs.append({"code": "approval_required", "message": "missing token"})
        if str((token_row or {}).get("proposal_id")) != str(proposal.get("proposal_id")):
            errs.append({"code": "proposal_mismatch", "message": "token mismatch"})

        scope = dict(proposal.get("scope") or {})
        scope_paths = [str(p) for p in list(scope.get("paths") or [])]
        scope_commands = [self._normalize_command(c) for c in list(scope.get("commands") or []) if self._normalize_command(c)]
        for p in scope_paths:
            ok, reason = self._path_ok(str(p), cap.allowed_roots, cap.protected_paths)
            if not ok:
                errs.append({"code": reason, "message": str(p)})
        for cmd in scope_commands:
            head = cmd.strip().split(" ")[0] if cmd.strip() else ""
            if cap.allow_commands and head not in set(cap.allow_commands):
                errs.append({"code": "command_not_allowlisted", "message": cmd})
            for pat in cap.deny_patterns:
                if re.search(pat, cmd, flags=re.IGNORECASE):
                    errs.append({"code": "command_denylisted", "message": cmd})

        steps = [s for s in list(proposal.get("steps") or []) if isinstance(s, dict)]
        if cap.capability_id == "file.write_scoped":
            if not preview_ready:
                errs.append({"code": "diff_preview_missing", "message": "preview required"})
            for step in steps:
                params = dict(step.get("parameters") or {})
                step_path = str(params.get("path") or "").strip()
                if not step_path:
                    errs.append({"code": "step_path_missing", "message": str(step.get("step_id") or "")})
                    continue
                if scope_paths and step_path not in scope_paths:
                    errs.append({"code": "scope_step_path_mismatch", "message": step_path})
                ok, reason = self._path_ok(step_path, cap.allowed_roots, cap.protected_paths)
                if not ok:
                    errs.append({"code": reason, "message": step_path})

        if cap.capability_id == "shell.exec_scoped":
            if not preview_ready:
                errs.append({"code": "command_preview_missing", "message": "preview required"})
            for step in steps:
                params = dict(step.get("parameters") or {})
                cmd_norm = self._normalize_command(params.get("command"))
                if not cmd_norm:
                    errs.append({"code": "step_command_missing", "message": str(step.get("step_id") or "")})
                    continue
                if scope_commands and cmd_norm not in scope_commands:
                    errs.append({"code": "scope_step_command_mismatch", "message": cmd_norm})
                head = cmd_norm.split(" ")[0]
                if cap.allow_commands and head not in set(cap.allow_commands):
                    errs.append({"code": "command_not_allowlisted", "message": cmd_norm})
                for pat in cap.deny_patterns:
                    if re.search(pat, cmd_norm, flags=re.IGNORECASE):
                        errs.append({"code": "command_denylisted", "message": cmd_norm})
                cwd = str(params.get("cwd") or ".").strip()
                ok, reason = self._path_ok(cwd, cap.allowed_roots, cap.protected_paths)
                if not ok:
                    errs.append({"code": f"cwd_{reason}", "message": cwd})

        return (len(errs) == 0), errs


class ScopedExecutor:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self.enforcer = PolicyEnforcer(registry)

    def execute(self, proposal: dict[str, Any], token: dict[str, Any], *, preview_ready: bool) -> dict[str, Any]:
        started = _iso(_utc_now())
        ok, errors = self.enforcer.enforce(proposal, token, preview_ready=preview_ready)
        if not ok:
            return {
                "type": "executed_action",
                "proposal_id": proposal.get("proposal_id"),
                "token_digest": token.get("token_digest"),
                "capability": proposal.get("capability"),
                "started_at": started,
                "ended_at": _iso(_utc_now()),
                "success": False,
                "effects": {},
                "outputs": {},
                "errors": errors,
                "audit_event_ids": [],
                "no_autonomy": True,
            }

        effects: dict[str, Any] = {}
        outputs: dict[str, Any] = {}
        capability = str(proposal.get("capability") or "")
        if capability == "file.write_scoped":
            files_written = []
            for step in list(proposal.get("steps") or []):
                params = dict(step.get("parameters") or {})
                path = Path(str(params.get("path") or ""))
                content = str(params.get("content") or "")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                files_written.append(str(path))
            effects["files_written"] = files_written
            outputs["paths"] = files_written
        elif capability == "shell.exec_scoped":
            cmds = []
            for step in list(proposal.get("steps") or []):
                params = dict(step.get("parameters") or {})
                cmd = [str(x) for x in list(params.get("command") or []) if str(x)]
                cwd = str(params.get("cwd") or ".")
                proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=False, timeout=30)
                cmds.append({"command": cmd, "exit_code": proc.returncode, "stdout": (proc.stdout or "")[:2000], "stderr": (proc.stderr or "")[:2000]})
            effects["commands_run"] = [x["command"] for x in cmds]
            outputs["artifact_ids"] = []
            outputs["command_results"] = cmds
        elif capability == "message.send_scoped":
            return {
                "type": "executed_action",
                "proposal_id": proposal.get("proposal_id"),
                "token_digest": token.get("token_digest"),
                "capability": capability,
                "started_at": started,
                "ended_at": _iso(_utc_now()),
                "success": False,
                "effects": {},
                "outputs": {},
                "errors": [{"code": "not_configured", "message": "message sending integration is not configured"}],
                "audit_event_ids": [],
                "no_autonomy": True,
            }

        return {
            "type": "executed_action",
            "proposal_id": proposal.get("proposal_id"),
            "token_digest": token.get("token_digest"),
            "capability": capability,
            "started_at": started,
            "ended_at": _iso(_utc_now()),
            "success": True,
            "effects": effects,
            "outputs": outputs,
            "errors": [],
            "audit_event_ids": [],
            "no_autonomy": True,
        }
