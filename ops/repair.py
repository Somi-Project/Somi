from __future__ import annotations

from pathlib import Path
from typing import Any

from executive.memory.store import SQLiteMemoryStore
from gateway import GatewayService
from workshop.toolbox.registry import ToolRegistry

from .control_plane import OpsControlPlane


def apply_safe_repairs(root_dir: str | Path = ".") -> list[dict[str, Any]]:
    root = Path(root_dir)
    actions: list[dict[str, Any]] = []

    for relative in ("backups", "sessions", "database", "docs/architecture"):
        path = root / relative
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            actions.append({"action": "create_dir", "path": str(path)})

    ops = OpsControlPlane(root_dir=root / "sessions" / "ops")
    actions.append({"action": "ensure_ops_control", "active_profile": ops.get_active_profile().get("profile_id", "")})

    gateway = GatewayService(root_dir=root / "sessions" / "gateway")
    actions.append({"action": "ensure_gateway_store", "path": str(gateway.root_dir)})

    registry = ToolRegistry(path=str(root / "workshop" / "tools" / "registry.json"))
    actions.append({"action": "ensure_tool_registry", "tool_count": len(registry.load().get("tools", []))})

    memory_store = SQLiteMemoryStore(str(root / "database" / "memory_store" / "memory.db"))
    actions.append({"action": "ensure_memory_store", "vec_enabled": bool(memory_store.vec_enabled)})

    return actions
