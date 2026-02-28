from __future__ import annotations

from datetime import datetime, timezone

import difflib
import json
import re
from pathlib import Path
from typing import Any

from handlers.contracts.base import build_base
from handlers.contracts.store import ArtifactStore
from executive.istari import AuditLog, CapabilityRegistry, ProposalStore, ScopedExecutor, TokenStore, build_proposal


class IstariProtocol:
    def __init__(self, registry_path: str | None = None) -> None:
        default_registry = Path(__file__).resolve().parents[1] / "config" / "capability_registry.json"
        self.registry = CapabilityRegistry(str(registry_path or default_registry))
        self.proposals = ProposalStore("executive")
        self.tokens = TokenStore("executive")
        self.audit = AuditLog("audit")
        self.executor = ScopedExecutor(self.registry)
        self.artifacts = ArtifactStore()

    def _append_artifact(self, user_id: str, artifact_type: str, content: dict[str, Any], route: str = "command") -> dict[str, Any]:
        # keep envelope consistent with universal contract helper.
        art = build_base(artifact_type=artifact_type, inputs={"route": route, "user_query": "istari"}, content=content)
        self.artifacts.append(user_id, art)
        return art

    def _find_pending(self, proposal_id: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        rows = self.proposals.list_pending()
        if proposal_id:
            return self.proposals.find(proposal_id), rows
        return (rows[-1] if len(rows) == 1 else None), rows

    def _render_proposal(self, p: dict[str, Any]) -> str:
        scope = p.get("scope") or {}
        return (
            f"# proposal_action\n"
            f"- proposal_id: `{p.get('proposal_id')}`\n"
            f"- capability: `{p.get('capability')}`\n"
            f"- risk_tier: `{p.get('risk_tier')}`\n"
            f"- requires_approval: `{p.get('requires_approval')}`\n"
            f"- scope: `{json.dumps(scope, ensure_ascii=False)}`"
        )

    def _render_token(self, t: dict[str, Any], plaintext_token: str) -> str:
        return (
            f"# approval_token\n"
            f"- proposal_id: `{t.get('proposal_id')}`\n"
            f"- token_id: `{t.get('token_id')}`\n"
            f"- token: `{plaintext_token}` (shown once; not stored in artifacts)\n"
            f"- expires_at: `{t.get('expires_at')}`"
        )

    def _diff_preview(self, proposal: dict[str, Any]) -> str:
        lines: list[str] = []
        for step in list(proposal.get("steps") or []):
            params = dict(step.get("parameters") or {})
            path = str(params.get("path") or "").strip()
            content = str(params.get("content") or "")
            if not path:
                continue
            p = Path(path)
            before = p.read_text(encoding="utf-8") if p.exists() else ""
            diff = "\n".join(
                difflib.unified_diff(
                    before.splitlines(),
                    content.splitlines(),
                    fromfile=f"{path}:before",
                    tofile=f"{path}:after",
                    lineterm="",
                )
            )
            lines.append(diff[:2000])
        return "\n\n".join(lines).strip()

    def _command_preview(self, proposal: dict[str, Any]) -> str:
        out = []
        for step in list(proposal.get("steps") or []):
            params = dict(step.get("parameters") or {})
            cmd = params.get("command") or []
            cwd = str(params.get("cwd") or ".")
            if isinstance(cmd, list):
                cmd_s = " ".join(str(x) for x in cmd)
            else:
                cmd_s = str(cmd)
            out.append(f"$ {cmd_s}\n(cwd={cwd})")
        return "\n\n".join(out).strip()

    def handle(self, prompt: str, user_id: str, toolbox_run_match: re.Match[str] | None = None) -> tuple[bool, str]:
        text = (prompt or "").strip()
        low = text.lower()

        if toolbox_run_match:
            tool_name = toolbox_run_match.group(1)
            arg_name = (toolbox_run_match.group(2) or "friend").strip()
            cmd = ["python", "-m", "toolbox.dispatch", tool_name, arg_name]
            proposal = build_proposal(
                capability="shell.exec_scoped",
                summary=f"Execute tool '{tool_name}' with scoped args",
                justification=["Explicit user request via run tool command"],
                scope={"commands": [" ".join(cmd)], "paths": [str(Path('.').resolve())]},
                steps=[
                    {
                        "step_id": "s1",
                        "action": "run_command",
                        "parameters": {"command": cmd, "cwd": str(Path('.').resolve())},
                    }
                ],
                risk_tier="tier3",
                ui_hints={"show_command_preview": True},
            )
            self.proposals.append(proposal)
            self.audit.append("proposal_created", proposal["proposal_id"], proposal["capability"], proposal["summary"], metadata={"risk_tier": proposal["risk_tier"]})
            self._append_artifact(user_id, "proposal_action", proposal)
            return True, self._render_proposal(proposal) + "\n\n## Command preview\n" + self._command_preview(proposal)

        if low.startswith("approve"):
            m = re.match(r"^approve(?:\s+([a-f0-9]{6,64}))?\s*$", low)
            proposal_id = m.group(1) if m else None
            proposal, rows = self._find_pending(proposal_id)
            if proposal is None:
                if not rows:
                    denied = {"type": "denied_action", "proposal_id": proposal_id or "none", "denied_at": datetime.now(timezone.utc).isoformat(), "reason": "No pending proposal to approve", "no_autonomy": True}
                    self._append_artifact(user_id, "denied_action", denied)
                    return True, "# denied_action\n- reason: no pending proposal"
                denied = {"type": "denied_action", "proposal_id": proposal_id or "none", "denied_at": datetime.now(timezone.utc).isoformat(), "reason": "Multiple pending proposals; specify proposal_id", "no_autonomy": True}
                self._append_artifact(user_id, "denied_action", denied)
                return True, "# denied_action\n- reason: multiple pending proposals; specify proposal_id"
            ttl = 300
            issued = self.tokens.issue(proposal, ttl_seconds=ttl, one_time=True)
            token_value = issued.pop("token")
            self.audit.append("token_issued", proposal["proposal_id"], proposal["capability"], "Approval token issued", token_digest=issued["token_digest"])
            self._append_artifact(user_id, "approval_token", issued)
            return True, self._render_token(issued, token_value)

        if low.startswith("deny") or low.startswith("reject"):
            m = re.match(r"^(?:deny|reject)(?:\s+([a-f0-9]{6,64}))?", low)
            proposal_id = m.group(1) if m else ""
            denied = {"type": "denied_action", "proposal_id": proposal_id or "none", "denied_at": datetime.now(timezone.utc).isoformat(), "reason": "Denied by user", "no_autonomy": True}
            self._append_artifact(user_id, "denied_action", denied)
            return True, "# denied_action\n- reason: denied by user"

        if low.startswith("revoke"):
            m = re.match(r"^revoke(?:\s+(all|[a-f0-9]{6,64}))?", low)
            arg = (m.group(1) if m else "") or ""
            rows = self.tokens.revoke(all_tokens=(arg == "all"), token_digest=(arg if arg and arg != "all" else None), proposal_id=(arg if arg and arg != "all" else None), reason="user_request")
            if not rows:
                return True, "# revoked_token\n- result: none"
            for row in rows:
                self._append_artifact(user_id, "revoked_token", row)
                self.audit.append("token_revoked", "none", "none", "Token revoked", token_digest=row.get("token_digest"))
            return True, f"# revoked_token\n- revoked: {len(rows)}"

        if low.startswith("execute"):
            m = re.match(r"^execute\s+([a-f0-9]{6,64})\s+([A-Za-z0-9_\-\.]+)\s*$", text)
            if not m:
                failed = {
                    "type": "executed_action",
                    "proposal_id": "none",
                    "token_digest": "invalid",
                    "capability": "none",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "success": False,
                    "effects": {},
                    "outputs": {},
                    "errors": [{"code": "invalid_execute_syntax", "message": "usage execute <proposal_id> <token>"}],
                    "audit_event_ids": [],
                    "no_autonomy": True,
                }
                self._append_artifact(user_id, "executed_action", failed)
                return True, "# executed_action\n- success: false\n- error: usage `execute <proposal_id> <token>`"
            proposal_id = m.group(1)
            token = m.group(2)
            proposal = self.proposals.find(proposal_id)
            if not proposal:
                failed = {
                    "type": "executed_action",
                    "proposal_id": proposal_id,
                    "token_digest": self.tokens.digest(token),
                    "capability": "none",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "success": False,
                    "effects": {},
                    "outputs": {},
                    "errors": [{"code": "proposal_not_found", "message": "proposal not found"}],
                    "audit_event_ids": [],
                    "no_autonomy": True,
                }
                self._append_artifact(user_id, "executed_action", failed)
                return True, "# executed_action\n- success: false\n- error: proposal not found"
            ok, reason, token_row = self.tokens.validate(token, proposal_id)
            if not ok or not token_row:
                failed = {
                    "type": "executed_action",
                    "proposal_id": proposal_id,
                    "token_digest": self.tokens.digest(token),
                    "capability": proposal.get("capability"),
                    "started_at": "",
                    "ended_at": "",
                    "success": False,
                    "effects": {},
                    "outputs": {},
                    "errors": [{"code": reason, "message": "token validation failed"}],
                    "audit_event_ids": [],
                    "no_autonomy": True,
                }
                self._append_artifact(user_id, "executed_action", failed)
                return True, "# executed_action\n- success: false\n- error: token invalid"
            preview = self._diff_preview(proposal) if proposal.get("capability") == "file.write_scoped" else self._command_preview(proposal)
            out = self.executor.execute(proposal, token_row, preview_ready=bool(preview))
            self.tokens.redeem(token_row["token_digest"])
            ev1 = self.audit.append("execution_started", proposal_id, proposal.get("capability"), "Execution started", token_digest=token_row.get("token_digest"))
            ev2 = self.audit.append("execution_finished", proposal_id, proposal.get("capability"), f"Execution success={out.get('success')}", token_digest=token_row.get("token_digest"))
            out["audit_event_ids"] = [ev1, ev2]
            self._append_artifact(user_id, "executed_action", out)
            return True, f"# executed_action\n- success: {str(bool(out.get('success'))).lower()}"

        return False, ""
