from __future__ import annotations

from typing import Any

from gateway import GatewayService


class NodeManagerSnapshotBuilder:
    def __init__(self, gateway_service: GatewayService | None = None) -> None:
        self.gateway_service = gateway_service or GatewayService()

    def build(self) -> dict[str, Any]:
        snapshot = dict(self.gateway_service.snapshot(limit=24) or {})
        return {
            "nodes": [dict(row) for row in list(snapshot.get("nodes") or [])],
            "audit": [dict(row) for row in list(snapshot.get("remote_audit") or [])],
            "tokens": [dict(row) for row in list(snapshot.get("node_tokens") or [])],
            "pairings": [dict(row) for row in list(snapshot.get("pairings") or [])],
            "summary": {
                "node_count": len(list(snapshot.get("nodes") or [])),
                "audit_count": len(list(snapshot.get("remote_audit") or [])),
                "token_count": len(list(snapshot.get("node_tokens") or [])),
            },
        }
