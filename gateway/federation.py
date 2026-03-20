from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: Any, *, fallback: str = "node") -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value or "").strip())[:100]
    return text or fallback


def _listify(values: list[Any] | tuple[Any, ...] | set[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


@dataclass(frozen=True)
class FederatedEnvelope:
    node_id: str
    lane: str
    subject: str
    body: str
    direction: str = "outbox"
    envelope_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"
    created_at: str = ""
    available_at: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        envelope_id = str(self.envelope_id or f"{_safe_id(self.node_id, fallback='node')}_{uuid.uuid4().hex[:12]}")
        created_at = str(self.created_at or _now_iso())
        return {
            "envelope_id": envelope_id,
            "node_id": _safe_id(self.node_id),
            "lane": str(self.lane or "knowledge").strip().lower() or "knowledge",
            "subject": str(self.subject or "").strip(),
            "body": str(self.body or "").strip(),
            "direction": str(self.direction or "outbox").strip().lower() or "outbox",
            "capabilities": _listify(self.capabilities),
            "artifacts": list(self.artifacts or []),
            "status": str(self.status or "pending").strip().lower() or "pending",
            "created_at": created_at,
            "available_at": str(self.available_at or created_at),
            "expires_at": str(self.expires_at or ""),
            "metadata": dict(self.metadata or {}),
        }


class FederatedEnvelopeStore:
    def __init__(self, root_dir: str | Path = "state/node_exchange") -> None:
        self.root_dir = Path(root_dir)
        self.inbox_root = self.root_dir / "inbox"
        self.outbox_root = self.root_dir / "outbox"
        self.archive_root = self.root_dir / "archive"
        for path in (self.inbox_root, self.outbox_root, self.archive_root):
            path.mkdir(parents=True, exist_ok=True)

    def _lane_root(self, direction: str, node_id: str) -> Path:
        stem = {"inbox": self.inbox_root, "archive": self.archive_root}.get(str(direction or "outbox").strip().lower(), self.outbox_root)
        path = stem / _safe_id(node_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path_for(self, direction: str, node_id: str, envelope_id: str) -> Path:
        return self._lane_root(direction, node_id) / f"{_safe_id(envelope_id, fallback='envelope')}.json"

    def write(self, envelope: FederatedEnvelope | dict[str, Any]) -> dict[str, Any]:
        payload = envelope.to_record() if isinstance(envelope, FederatedEnvelope) else FederatedEnvelope(**dict(envelope or {})).to_record()
        path = self._path_for(str(payload.get("direction") or "outbox"), str(payload.get("node_id") or ""), str(payload.get("envelope_id") or ""))
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return payload

    def ingest(self, *, node_id: str, lane: str, subject: str, body: str, capabilities: list[str] | None = None, artifacts: list[dict[str, Any]] | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.write(
            FederatedEnvelope(
                node_id=node_id,
                lane=lane,
                subject=subject,
                body=body,
                direction="inbox",
                capabilities=list(capabilities or []),
                artifacts=list(artifacts or []),
                metadata=dict(metadata or {}),
            )
        )

    def publish(self, *, node_id: str, lane: str, subject: str, body: str, capabilities: list[str] | None = None, artifacts: list[dict[str, Any]] | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.write(
            FederatedEnvelope(
                node_id=node_id,
                lane=lane,
                subject=subject,
                body=body,
                direction="outbox",
                capabilities=list(capabilities or []),
                artifacts=list(artifacts or []),
                metadata=dict(metadata or {}),
            )
        )

    def list_envelopes(self, *, direction: str = "inbox", node_id: str | None = None, lane: str | None = None, status: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        direction_name = str(direction or "inbox").strip().lower() or "inbox"
        base_root = {"outbox": self.outbox_root, "archive": self.archive_root}.get(direction_name, self.inbox_root)
        roots = [base_root / _safe_id(node_id)] if str(node_id or "").strip() else [path for path in sorted(base_root.iterdir()) if path.is_dir()]
        rows: list[dict[str, Any]] = []
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("*.json")):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(raw, dict):
                    continue
                if lane and str(raw.get("lane") or "") != str(lane):
                    continue
                if status and str(raw.get("status") or "") != str(status):
                    continue
                rows.append(raw)
        rows.sort(key=lambda item: str(item.get("available_at") or item.get("created_at") or ""), reverse=True)
        return rows[: max(1, int(limit or 40))]

    def acknowledge(self, *, direction: str = "inbox", node_id: str, envelope_id: str, status: str = "acknowledged") -> dict[str, Any] | None:
        current_path = self._path_for(direction, node_id, envelope_id)
        if not current_path.exists():
            return None
        try:
            raw = json.loads(current_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        raw["status"] = str(status or "acknowledged").strip().lower() or "acknowledged"
        raw["acknowledged_at"] = _now_iso()
        archived = self._path_for("archive", node_id, envelope_id)
        archived.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        current_path.unlink(missing_ok=True)
        return raw


def build_federation_snapshot(root_dir: str | Path = ".") -> dict[str, Any]:
    store = FederatedEnvelopeStore(Path(root_dir) / "state" / "node_exchange")
    inbox = store.list_envelopes(direction="inbox", limit=200)
    outbox = store.list_envelopes(direction="outbox", limit=200)
    archive = store.list_envelopes(direction="archive", limit=200)
    node_ids = sorted(
        {
            str(item.get("node_id") or "").strip()
            for item in (inbox + outbox + archive)
            if str(item.get("node_id") or "").strip()
        }
    )
    lane_counts: dict[str, int] = {}
    for row in inbox + outbox:
        lane = str(row.get("lane") or "general").strip().lower() or "general"
        lane_counts[lane] = int(lane_counts.get(lane) or 0) + 1
    return {
        "ok": True,
        "root": str(store.root_dir),
        "nodes": node_ids,
        "node_count": len(node_ids),
        "pending_inbox": len(inbox),
        "pending_outbox": len(outbox),
        "archived": len(archive),
        "lane_counts": lane_counts,
        "recent_inbox": inbox[:5],
        "recent_outbox": outbox[:5],
    }


def format_federation_snapshot(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Federated Node Exchange]",
        f"- root: {report.get('root', '')}",
        f"- node_count: {report.get('node_count', 0)}",
        f"- pending_inbox: {report.get('pending_inbox', 0)}",
        f"- pending_outbox: {report.get('pending_outbox', 0)}",
        f"- archived: {report.get('archived', 0)}",
        f"- nodes: {', '.join(list(report.get('nodes') or [])) or '--'}",
    ]
    lane_counts = dict(report.get("lane_counts") or {})
    lines.append(f"- lane_counts: {', '.join(f'{k}={v}' for k, v in sorted(lane_counts.items())) or '--'}")
    return "\n".join(lines)
