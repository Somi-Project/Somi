from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .auth import authorize_action as decide_action
from .auth import build_auth_context, normalize_scopes
from .protocol import (
    GatewayEventRecord,
    GatewayHealthRecord,
    GatewayNodeRecord,
    GatewayPairingRecord,
    GatewayPresenceRecord,
    GatewaySessionRecord,
    utcnow_iso,
)
from .store import GatewayStore

_NODE_CAPABILITIES = {
    "browser_node": ["browser.snapshot", "browser.read", "browser.action"],
    "speech_node": ["speech.tts", "speech.stt"],
    "mobile_relay_node": ["mobile.relay", "deliver.mobile", "prompt.mobile"],
    "gpu_runner_node": ["gpu.inference", "model.run", "coding.execute"],
    "file_relay_node": ["files.read", "files.write", "artifacts.sync"],
}
_APPROVAL_ORDER = {
    "observe_only": 1,
    "operator_confirm": 2,
    "trusted_automation": 3,
    "full_remote": 4,
}
_ACTION_TIER = {
    "observe": "observe_only",
    "prompt": "observe_only",
    "deliver": "observe_only",
    "execute": "operator_confirm",
    "install": "trusted_automation",
    "system": "full_remote",
}


def _clip(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_node_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "browser": "browser_node",
        "speech": "speech_node",
        "mobile": "mobile_relay_node",
        "mobile_relay": "mobile_relay_node",
        "gpu": "gpu_runner_node",
        "file": "file_relay_node",
    }
    return aliases.get(raw, raw or "browser_node")


def _normalize_capabilities(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values or []:
        item = str(value or "").strip().lower()
        if item and item not in seen:
            seen.add(item)
            rows.append(item)
    return rows


def _tier_at_least(current: str, required: str) -> bool:
    return _APPROVAL_ORDER.get(str(current or "").strip().lower(), 0) >= _APPROVAL_ORDER.get(str(required or "").strip().lower(), 0)


def _path_within_roots(requested_path: str, roots: list[str]) -> bool:
    raw_path = str(requested_path or "").strip()
    if not raw_path or not roots:
        return True
    try:
        target = Path(raw_path).expanduser().resolve()
    except Exception:
        return False
    for root in roots:
        try:
            base = Path(str(root or "")).expanduser().resolve()
        except Exception:
            continue
        if target == base or base in target.parents:
            return True
    return False


class GatewayService:
    def __init__(self, root_dir: str | Path = "sessions/gateway", delivery_gateway=None) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.store = GatewayStore(root_dir=self.root_dir)
        self.delivery_gateway = delivery_gateway

    def _is_pairing_expired(self, pairing: dict[str, Any] | None) -> bool:
        if not pairing:
            return False
        expires_at = _parse_iso(pairing.get("expires_at"))
        if expires_at is None:
            return False
        return expires_at <= datetime.now(timezone.utc)

    def register_session(
        self,
        *,
        user_id: str,
        surface: str,
        client_id: str,
        client_label: str = "",
        platform: str = "",
        auth_mode: str = "local",
        session_id: str = "",
        status: str = "online",
        scopes: list[str] | None = None,
        pairing_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pairing = self.store.get_pairing(str(pairing_id or "")) if str(pairing_id or "").strip() else None
        auth = build_auth_context(
            surface=surface,
            auth_mode=auth_mode,
            pairing_record=pairing,
            granted_scopes=scopes,
            metadata=metadata,
        )
        meta = dict(metadata or {})
        meta.update(
            {
                "allowed_actions": list(auth.get("allowed_actions") or []),
                "remote_safe": bool(auth.get("remote_safe", True)),
                "pairing_id": str(pairing_id or ""),
            }
        )
        record = GatewaySessionRecord(
            session_id=str(session_id or f"gw-{uuid.uuid4().hex[:12]}"),
            user_id=str(user_id or "default_user"),
            surface=str(surface or "").strip().lower(),
            client_id=str(client_id or surface or "client").strip().lower(),
            client_label=str(client_label or client_id or surface or "client"),
            platform=str(platform or ""),
            auth_mode=str(auth.get("auth_mode") or auth_mode or "local"),
            trust_level=str(auth.get("trust_level") or "trusted_local"),
            status=str(status or "online").strip().lower(),
            created_at=utcnow_iso(),
            last_seen_at=utcnow_iso(),
            metadata=meta,
        )
        row = self.store.upsert_session(record.to_record())
        self.update_presence(
            session_id=str(row.get("session_id") or ""),
            status=str(row.get("status") or "online"),
            activity="registered",
            detail=str(row.get("client_label") or row.get("client_id") or ""),
            metadata={"trust_level": row.get("trust_level", "")},
        )
        return row

    def touch_session(self, session_id: str, *, status: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        row = self.store.get_session(session_id)
        if not row:
            raise ValueError(f"Unknown gateway session: {session_id}")
        merged_metadata = dict(row.get("metadata") or {})
        merged_metadata.update(dict(metadata or {}))
        row["last_seen_at"] = utcnow_iso()
        if str(status or "").strip():
            row["status"] = str(status).strip().lower()
        row["metadata"] = merged_metadata
        return self.store.upsert_session(row)

    def update_presence(
        self,
        *,
        session_id: str,
        status: str = "online",
        activity: str = "",
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.touch_session(session_id, status=status)
        record = GatewayPresenceRecord(
            session_id=str(session.get("session_id") or ""),
            client_id=str(session.get("client_id") or ""),
            user_id=str(session.get("user_id") or ""),
            surface=str(session.get("surface") or ""),
            status=str(status or session.get("status") or "online").strip().lower(),
            activity=_clip(activity, limit=140),
            detail=_clip(detail, limit=220),
            updated_at=utcnow_iso(),
            metadata=dict(metadata or {}),
        )
        return self.store.upsert_presence(record.to_record())

    def record_health(
        self,
        *,
        service_id: str,
        surface: str,
        status: str,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = GatewayHealthRecord(
            service_id=str(service_id or "").strip().lower(),
            surface=str(surface or "").strip().lower(),
            status=str(status or "unknown").strip().lower(),
            summary=_clip(summary, limit=220),
            updated_at=utcnow_iso(),
            metadata=dict(metadata or {}),
        )
        return self.store.record_health(record.to_record())

    def publish_event(
        self,
        *,
        event_type: str,
        surface: str,
        title: str,
        body: str = "",
        level: str = "info",
        user_id: str = "",
        session_id: str = "",
        client_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = GatewayEventRecord(
            event_id=f"gwe-{uuid.uuid4().hex[:16]}",
            event_type=str(event_type or "event").strip().lower(),
            surface=str(surface or "").strip().lower(),
            title=_clip(title, limit=160),
            body=_clip(body, limit=600),
            level=str(level or "info").strip().lower(),
            user_id=str(user_id or ""),
            session_id=str(session_id or ""),
            client_id=str(client_id or ""),
            created_at=utcnow_iso(),
            metadata=dict(metadata or {}),
        )
        return self.store.append_event(record.to_record())

    def record_prompt_ingress(
        self,
        *,
        surface: str,
        user_id: str,
        text: str,
        session_id: str = "",
        client_id: str = "",
        thread_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = dict(metadata or {})
        if thread_id:
            meta["thread_id"] = str(thread_id)
        return self.publish_event(
            event_type="prompt_ingress",
            surface=surface,
            title=f"Ingress from {surface}",
            body=text,
            level="info",
            user_id=user_id,
            session_id=session_id,
            client_id=client_id,
            metadata=meta,
        )

    def issue_pairing(
        self,
        *,
        requested_surface: str,
        client_label: str,
        platform: str = "",
        owner_user_id: str = "default_user",
        scopes: list[str] | None = None,
        expires_minutes: int = 20,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = GatewayPairingRecord(
            pairing_id=f"pair-{uuid.uuid4().hex[:12]}",
            code=self.store.random_code(),
            requested_surface=str(requested_surface or "").strip().lower(),
            client_label=str(client_label or requested_surface or "remote-client"),
            platform=str(platform or ""),
            owner_user_id=str(owner_user_id or "default_user"),
            status="pending",
            scopes=normalize_scopes(scopes),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=max(1, int(expires_minutes or 20)))).isoformat(),
            metadata=dict(metadata or {}),
        )
        item = self.store.issue_pairing(record.to_record())
        self.publish_event(
            event_type="pairing_requested",
            surface=str(requested_surface or "remote"),
            title=f"Pairing requested for {client_label}",
            body=f"code={item.get('code', '')}",
            metadata={"pairing_id": item.get("pairing_id", ""), "platform": platform},
        )
        return item

    def register_remote_session(
        self,
        *,
        user_id: str,
        surface: str,
        client_id: str,
        client_label: str,
        platform: str = "",
        pairing_code: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pairing = self.store.get_pairing_by_code(str(pairing_code or "").strip()) if str(pairing_code or "").strip() else None
        if pairing:
            if self._is_pairing_expired(pairing):
                self.store.confirm_pairing(
                    code=str(pairing_code or "").strip(),
                    status="expired",
                    metadata={"expired_at": utcnow_iso()},
                    updated_at=utcnow_iso(),
                )
                raise ValueError("Pairing code expired")
            session = self.register_session(
                user_id=user_id,
                surface=surface,
                client_id=client_id,
                client_label=client_label,
                platform=platform,
                auth_mode="paired",
                pairing_id=str(pairing.get("pairing_id") or ""),
                metadata={"remote_client": True, **dict(metadata or {})},
            )
            self.confirm_pairing(
                code=str(pairing_code or "").strip(),
                session_id=str(session.get("session_id") or ""),
                actor="gateway_service",
            )
            self.publish_event(
                event_type="pairing_confirmed",
                surface=surface,
                title=f"Paired {client_label}",
                body=f"{surface}:{client_id}",
                user_id=user_id,
                session_id=str(session.get("session_id") or ""),
                client_id=str(session.get("client_id") or ""),
                metadata={"pairing_id": pairing.get("pairing_id", "")},
            )
            return self.store.get_session(str(session.get("session_id") or "")) or session

        session = self.register_session(
            user_id=user_id,
            surface=surface,
            client_id=client_id,
            client_label=client_label,
            platform=platform,
            auth_mode="remote",
            metadata={"remote_client": True, **dict(metadata or {})},
        )
        self.publish_event(
            event_type="remote_session_registered",
            surface=surface,
            title=f"Unpaired remote session {client_label}",
            body=f"{surface}:{client_id}",
            level="warn",
            user_id=user_id,
            session_id=str(session.get("session_id") or ""),
            client_id=str(session.get("client_id") or ""),
        )
        return session

    def register_node(
        self,
        *,
        user_id: str,
        node_type: str,
        node_id: str,
        client_label: str = "",
        platform: str = "",
        pairing_code: str = "",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_type = _normalize_node_type(node_type)
        merged_metadata = dict(metadata or {})
        merged_metadata["node_type"] = normalized_type
        merged_metadata["requested_capabilities"] = _normalize_capabilities(capabilities or _NODE_CAPABILITIES.get(normalized_type, []))
        merged_metadata.setdefault("approval_tier", "operator_confirm")
        merged_metadata.setdefault("path_roots", [])
        merged_metadata.setdefault("secret_slots", [])
        session = self.register_remote_session(
            user_id=user_id,
            surface="node",
            client_id=str(node_id or normalized_type or "node").strip().lower(),
            client_label=str(client_label or node_id or normalized_type),
            platform=platform,
            pairing_code=pairing_code,
            metadata=merged_metadata,
        )
        trust_level = str(session.get("trust_level") or "untrusted_remote")
        status = "online" if trust_level == "paired_remote" else "pending_pair"
        record = GatewayNodeRecord(
            node_id=str(node_id or normalized_type or f"node-{uuid.uuid4().hex[:8]}").strip().lower(),
            session_id=str(session.get("session_id") or ""),
            user_id=str(user_id or "default_user"),
            node_type=normalized_type,
            client_label=str(client_label or session.get("client_label") or node_id or normalized_type),
            platform=str(platform or ""),
            trust_level=trust_level,
            status=status,
            capabilities=_normalize_capabilities(capabilities or _NODE_CAPABILITIES.get(normalized_type, [])),
            created_at=utcnow_iso(),
            updated_at=utcnow_iso(),
            metadata=merged_metadata,
        )
        item = self.store.upsert_node(record.to_record())
        self.publish_event(
            event_type="node_registered",
            surface="node",
            title=f"Node registered: {item.get('client_label') or item.get('node_id')}",
            body=f"{item.get('node_type')} [{item.get('status')}]",
            level="info" if item.get("status") == "online" else "warn",
            user_id=str(user_id or "default_user"),
            session_id=str(session.get("session_id") or ""),
            client_id=str(session.get("client_id") or ""),
            metadata={"node_id": item.get("node_id", ""), "capabilities": item.get("capabilities", [])},
        )
        return item

    def heartbeat_node(
        self,
        node_id: str,
        *,
        status: str = "online",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.store.get_node(str(node_id or ""))
        if not row:
            raise ValueError(f"Unknown gateway node: {node_id}")
        merged_metadata = dict(row.get("metadata") or {})
        merged_metadata.update(dict(metadata or {}))
        merged_capabilities = _normalize_capabilities(capabilities or list(row.get("capabilities") or []))
        row["status"] = str(status or row.get("status") or "online").strip().lower()
        row["updated_at"] = utcnow_iso()
        row["capabilities"] = merged_capabilities
        row["metadata"] = merged_metadata
        item = self.store.upsert_node(row)
        session_id = str(item.get("session_id") or "")
        if session_id:
            try:
                self.update_presence(
                    session_id=session_id,
                    status="online" if item.get("status") not in {"offline", "revoked"} else str(item.get("status") or "offline"),
                    activity="node_heartbeat",
                    detail=f"{item.get('node_type')} :: {', '.join(merged_capabilities[:3])}",
                    metadata={"node_id": item.get("node_id", "")},
                )
            except Exception:
                pass
        return item

    def list_nodes(self, *, limit: int = 20, capability: str = "", node_type: str = "", status: str = "") -> list[dict[str, Any]]:
        rows = self.store.list_nodes(limit=max(20, int(limit or 20)), status=status, node_type=node_type)
        if not str(capability or "").strip():
            return rows[: max(1, int(limit or 20))]
        needle = str(capability or "").strip().lower()
        filtered = [row for row in rows if needle in {str(item).lower() for item in list(row.get("capabilities") or [])}]
        return filtered[: max(1, int(limit or 20))]

    def capability_registry(self, *, limit: int = 60) -> dict[str, list[str]]:
        registry: dict[str, list[str]] = {}
        for row in self.store.list_nodes(limit=limit):
            label = str(row.get("client_label") or row.get("node_id") or "")
            for capability in list(row.get("capabilities") or []):
                key = str(capability or "").strip().lower()
                if not key:
                    continue
                registry.setdefault(key, [])
                if label and label not in registry[key]:
                    registry[key].append(label)
        return dict(sorted(registry.items()))

    def record_remote_action(
        self,
        *,
        node_id: str,
        action: str,
        outcome: str,
        reason: str,
        capability: str = "",
        requested_path: str = "",
        actor: str = "gateway_service",
        requires_approval: bool = False,
        operator_confirmed: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = self.store.get_node(str(node_id or "")) or {}
        record = {
            "audit_id": f"gwa-{uuid.uuid4().hex[:16]}",
            "node_id": str(node.get("node_id") or node_id or "").strip().lower(),
            "session_id": str(node.get("session_id") or ""),
            "user_id": str(node.get("user_id") or ""),
            "action": str(action or "").strip().lower(),
            "capability": str(capability or "").strip().lower(),
            "requested_path": str(requested_path or "").strip(),
            "outcome": str(outcome or "").strip().lower(),
            "reason": str(reason or "").strip().lower(),
            "actor": str(actor or "gateway_service"),
            "requires_approval": bool(requires_approval),
            "operator_confirmed": bool(operator_confirmed),
            "created_at": utcnow_iso(),
            "metadata": dict(metadata or {}),
        }
        audit = self.store.append_remote_audit(record)
        self.publish_event(
            event_type="remote_action_audit",
            surface="node",
            title=f"{record['action']}::{record['outcome']}",
            body=f"{record['node_id']} :: {record['reason']}",
            level="warn" if record["outcome"] != "allowed" else "info",
            user_id=str(node.get("user_id") or ""),
            session_id=str(node.get("session_id") or ""),
            client_id=str(node.get("node_id") or ""),
            metadata={"audit_id": audit.get("audit_id", ""), "capability": record["capability"]},
        )
        return audit

    def authorize_node_action(
        self,
        node_id: str,
        *,
        action: str,
        capability: str = "",
        requested_path: str = "",
        actor: str = "gateway_service",
        operator_confirmed: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = self.store.get_node(str(node_id or ""))
        if not node:
            decision = {"allowed": False, "reason": "unknown_node", "action": str(action or "").strip().lower(), "node_id": str(node_id or "")}
            self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason="unknown_node", capability=capability, requested_path=requested_path, actor=actor, metadata=metadata)
            return decision
        if str(node.get("status") or "").strip().lower() in {"revoked", "offline"}:
            decision = {"allowed": False, "reason": "node_revoked", "action": str(action or "").strip().lower(), "node_id": str(node_id or "")}
            self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason="node_revoked", capability=capability, requested_path=requested_path, actor=actor, metadata=metadata)
            return decision
        base = self.authorize_action(str(node.get("session_id") or ""), str(action or ""))
        if not bool(base.get("allowed")):
            self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason=str(base.get("reason") or "scope_missing"), capability=capability, requested_path=requested_path, actor=actor, metadata=metadata)
            return {**base, "node_id": str(node_id or "")}
        if str(capability or "").strip():
            capabilities = {str(item).lower() for item in list(node.get("capabilities") or [])}
            if str(capability).strip().lower() not in capabilities:
                self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason="capability_missing", capability=capability, requested_path=requested_path, actor=actor, metadata=metadata)
                return {**base, "allowed": False, "reason": "capability_missing", "node_id": str(node_id or "")}
        node_meta = dict(node.get("metadata") or {})
        approval_tier = str(node_meta.get("approval_tier") or "operator_confirm").strip().lower()
        action_tiers = {str(k).strip().lower(): str(v).strip().lower() for k, v in dict(node_meta.get("action_tiers") or {}).items()}
        required_tier = action_tiers.get(str(action or "").strip().lower(), _ACTION_TIER.get(str(action or "").strip().lower(), "observe_only"))
        requires_approval = _APPROVAL_ORDER.get(required_tier, 0) >= _APPROVAL_ORDER["operator_confirm"]
        if not _tier_at_least(approval_tier, required_tier):
            self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason="approval_tier_too_low", capability=capability, requested_path=requested_path, actor=actor, requires_approval=requires_approval, operator_confirmed=operator_confirmed, metadata=metadata)
            return {**base, "allowed": False, "reason": "approval_tier_too_low", "node_id": str(node_id or ""), "required_tier": required_tier, "approval_tier": approval_tier}
        if requires_approval and not bool(operator_confirmed):
            self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason="operator_confirmation_required", capability=capability, requested_path=requested_path, actor=actor, requires_approval=True, operator_confirmed=operator_confirmed, metadata=metadata)
            return {**base, "allowed": False, "reason": "operator_confirmation_required", "node_id": str(node_id or ""), "required_tier": required_tier}
        roots = [str(item) for item in list(node_meta.get("path_roots") or []) if str(item).strip()]
        if not _path_within_roots(requested_path, roots):
            self.record_remote_action(node_id=node_id, action=action, outcome="denied", reason="path_boundary_violation", capability=capability, requested_path=requested_path, actor=actor, requires_approval=requires_approval, operator_confirmed=operator_confirmed, metadata=metadata)
            return {**base, "allowed": False, "reason": "path_boundary_violation", "node_id": str(node_id or ""), "path_roots": roots}
        audit = self.record_remote_action(
            node_id=node_id,
            action=action,
            outcome="allowed",
            reason="allowed",
            capability=capability,
            requested_path=requested_path,
            actor=actor,
            requires_approval=requires_approval,
            operator_confirmed=operator_confirmed,
            metadata=metadata,
        )
        return {**base, "allowed": True, "reason": "allowed", "node_id": str(node_id or ""), "audit_id": str(audit.get("audit_id") or "")}

    def revoke_node(self, node_id: str, *, actor: str = "local_operator", reason: str = "") -> dict[str, Any]:
        node = self.store.get_node(str(node_id or ""))
        if not node:
            raise ValueError(f"Unknown gateway node: {node_id}")
        node_meta = dict(node.get("metadata") or {})
        node_meta.update({"revoked_by": str(actor or "local_operator"), "revoked_reason": str(reason or ""), "revoked_at": utcnow_iso()})
        node["status"] = "revoked"
        node["updated_at"] = utcnow_iso()
        node["metadata"] = node_meta
        item = self.store.upsert_node(node)
        session_id = str(item.get("session_id") or "")
        if session_id:
            try:
                self.touch_session(session_id, status="revoked", metadata={"revoked": True, "revoked_reason": reason})
                self.update_presence(session_id=session_id, status="revoked", activity="node_revoked", detail=str(reason or "revoked"))
            except Exception:
                pass
        self.publish_event(
            event_type="node_revoked",
            surface="node",
            title=f"Node revoked: {item.get('client_label') or item.get('node_id')}",
            body=str(reason or "revoked by operator"),
            level="warn",
            user_id=str(item.get("user_id") or ""),
            session_id=session_id,
            client_id=str(item.get("node_id") or ""),
        )
        return item

    def rotate_node_token(self, node_id: str, *, actor: str = "local_operator", label: str = "") -> dict[str, Any]:
        node = self.store.get_node(str(node_id or ""))
        if not node:
            raise ValueError(f"Unknown gateway node: {node_id}")
        raw_token = secrets.token_urlsafe(24)
        preview = f"{raw_token[:4]}...{raw_token[-4:]}"
        now = utcnow_iso()
        token = self.store.rotate_node_token(
            {
                "token_id": f"gwt-{uuid.uuid4().hex[:12]}",
                "node_id": str(node.get("node_id") or "").strip().lower(),
                "label": str(label or "node-access"),
                "token_hash": hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                "preview": preview,
                "status": "active",
                "created_at": now,
                "rotated_at": now,
                "metadata": {"actor": str(actor or "local_operator")},
            }
        )
        node_meta = dict(node.get("metadata") or {})
        node_meta["token_preview"] = preview
        node_meta["token_rotated_at"] = now
        node["metadata"] = node_meta
        node["updated_at"] = now
        self.store.upsert_node(node)
        return {"token": raw_token, "token_preview": preview, "record": token}

    def confirm_pairing(
        self,
        *,
        code: str,
        session_id: str = "",
        actor: str = "local_operator",
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        item = self.store.confirm_pairing(
            code=str(code or "").strip(),
            session_id=str(session_id or ""),
            status="paired",
            scopes=normalize_scopes(scopes),
            metadata={"paired_by": actor, **dict(metadata or {})},
            updated_at=utcnow_iso(),
        )
        if not item:
            return None
        if str(session_id or "").strip():
            session = self.store.get_session(session_id)
            if session:
                auth = build_auth_context(
                    surface=str(session.get("surface") or item.get("requested_surface") or "remote"),
                    auth_mode="paired",
                    pairing_record=item,
                    metadata=session.get("metadata") or {},
                )
                session["trust_level"] = str(auth.get("trust_level") or "paired_remote")
                session["auth_mode"] = str(auth.get("auth_mode") or "paired")
                meta = dict(session.get("metadata") or {})
                meta["allowed_actions"] = list(auth.get("allowed_actions") or [])
                meta["remote_safe"] = bool(auth.get("remote_safe", True))
                meta["pairing_id"] = str(item.get("pairing_id") or "")
                session["metadata"] = meta
                session["last_seen_at"] = utcnow_iso()
                self.store.upsert_session(session)
                self.update_presence(
                    session_id=session_id,
                    status="online",
                    activity="paired",
                    detail=str(item.get("client_label") or item.get("requested_surface") or "remote client"),
                    metadata={"pairing_id": item.get("pairing_id", "")},
                )
                node = self.store.get_node_by_session(session_id)
                if node:
                    node["trust_level"] = str(auth.get("trust_level") or node.get("trust_level") or "paired_remote")
                    node["status"] = "online"
                    node["updated_at"] = utcnow_iso()
                    self.store.upsert_node(node)
        return item

    def authorize_action(self, session_id: str, action: str) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if not session:
            return {
                "allowed": False,
                "action": str(action or "").strip().lower(),
                "trust_level": "missing",
                "reason": "unknown_session",
            }
        pairing_id = str((session.get("metadata") or {}).get("pairing_id") or "")
        pairing = self.store.get_pairing(pairing_id) if pairing_id else None
        if str(session.get("auth_mode") or "").strip().lower() == "paired" and not pairing:
            return {
                "allowed": False,
                "action": str(action or "").strip().lower(),
                "trust_level": "missing_pairing",
                "reason": "missing_pairing_record",
                "session_id": str(session.get("session_id") or ""),
                "surface": str(session.get("surface") or ""),
            }
        if pairing and self._is_pairing_expired(pairing):
            return {
                "allowed": False,
                "action": str(action or "").strip().lower(),
                "trust_level": str(session.get("trust_level") or "paired_remote"),
                "reason": "expired_pairing",
                "session_id": str(session.get("session_id") or ""),
                "surface": str(session.get("surface") or ""),
            }
        ctx = build_auth_context(
            surface=str(session.get("surface") or ""),
            auth_mode=str(session.get("auth_mode") or "local"),
            pairing_record=pairing,
            granted_scopes=(session.get("metadata") or {}).get("allowed_actions") or [],
            metadata=session.get("metadata") or {},
        )
        decision = decide_action(ctx, action)
        decision["session_id"] = str(session.get("session_id") or "")
        decision["surface"] = str(session.get("surface") or "")
        return decision

    def status_feed(self, *, limit: int = 24) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in self.store.list_presence(limit=limit):
            rows.append(
                {
                    "kind": "presence",
                    "timestamp": str(item.get("updated_at") or ""),
                    "surface": str(item.get("surface") or ""),
                    "status": str(item.get("status") or ""),
                    "title": str(item.get("client_id") or item.get("session_id") or "presence"),
                    "detail": _clip(item.get("activity") or item.get("detail") or "", limit=180),
                }
            )
        for item in self.store.list_health(limit=limit):
            rows.append(
                {
                    "kind": "health",
                    "timestamp": str(item.get("updated_at") or ""),
                    "surface": str(item.get("surface") or ""),
                    "status": str(item.get("status") or ""),
                    "title": str(item.get("service_id") or "health"),
                    "detail": _clip(item.get("summary") or "", limit=180),
                }
            )
        for item in self.store.list_pairings(limit=limit):
            rows.append(
                {
                    "kind": "pairing",
                    "timestamp": str(item.get("updated_at") or item.get("created_at") or ""),
                    "surface": str(item.get("requested_surface") or ""),
                    "status": str(item.get("status") or ""),
                    "title": str(item.get("client_label") or item.get("pairing_id") or "pairing"),
                    "detail": f"code={item.get('code', '')}",
                }
            )
        for item in self.store.list_nodes(limit=limit):
            rows.append(
                {
                    "kind": "node",
                    "timestamp": str(item.get("updated_at") or item.get("created_at") or ""),
                    "surface": "node",
                    "status": str(item.get("status") or ""),
                    "title": str(item.get("client_label") or item.get("node_id") or "node"),
                    "detail": f"{item.get('node_type', '')} :: {', '.join(list(item.get('capabilities') or [])[:3])}",
                }
            )
        for item in self.store.list_events(limit=limit):
            rows.append(
                {
                    "kind": "event",
                    "timestamp": str(item.get("created_at") or ""),
                    "surface": str(item.get("surface") or ""),
                    "status": str(item.get("level") or "info"),
                    "title": str(item.get("title") or item.get("event_type") or "event"),
                    "detail": _clip(item.get("body") or "", limit=180),
                }
            )
        rows.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        return rows[: max(1, int(limit or 24))]

    def snapshot(self, *, limit: int = 12) -> dict[str, Any]:
        sessions = self.store.list_sessions(limit=limit)
        presence = self.store.list_presence(limit=limit)
        health = self.store.list_health(limit=limit)
        events = self.store.list_events(limit=limit)
        pairings = self.store.list_pairings(limit=limit)
        nodes = self.store.list_nodes(limit=limit)
        remote_audit = self.store.list_remote_audit(limit=limit)
        node_tokens = self.store.list_node_tokens(limit=limit)
        status_feed = self.status_feed(limit=limit)

        trust_counts: dict[str, int] = {}
        for row in sessions:
            key = str(row.get("trust_level") or "unknown")
            trust_counts[key] = trust_counts.get(key, 0) + 1

        pairing_counts: dict[str, int] = {}
        for row in pairings:
            key = str(row.get("status") or "unknown")
            pairing_counts[key] = pairing_counts.get(key, 0) + 1

        node_type_counts: dict[str, int] = {}
        node_status_counts: dict[str, int] = {}
        for row in nodes:
            node_type = str(row.get("node_type") or "unknown")
            node_status = str(row.get("status") or "unknown")
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1
            node_status_counts[node_status] = node_status_counts.get(node_status, 0) + 1

        delivery_channels: list[dict[str, Any]] = []
        if self.delivery_gateway is not None:
            try:
                for channel_name in self.delivery_gateway.list_channels():
                    delivery_channels.append(
                        {
                            "channel": channel_name,
                            "inbox": len(self.delivery_gateway.list_messages(channel_name, box="inbox", limit=6)),
                            "outbox": len(self.delivery_gateway.list_messages(channel_name, box="outbox", limit=6)),
                            "queue": len(self.delivery_gateway.list_messages(channel_name, box="queue", limit=6)),
                        }
                    )
            except Exception:
                delivery_channels = []

        return {
            "root_dir": str(self.root_dir),
            "sessions": sessions,
            "presence": presence,
            "health": health,
            "events": events,
            "pairings": pairings,
            "nodes": nodes,
            "remote_audit": remote_audit,
            "node_tokens": node_tokens,
            "status_feed": status_feed,
            "trust_level_counts": trust_counts,
            "pairing_status_counts": pairing_counts,
            "node_type_counts": node_type_counts,
            "node_status_counts": node_status_counts,
            "capability_registry": self.capability_registry(limit=max(limit, 40)),
            "delivery_channels": delivery_channels,
        }
