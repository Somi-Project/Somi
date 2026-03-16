from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any


_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_DEFAULT_BACKENDS = ("local",)
_DEFAULT_CHANNELS = ("chat", "gui")
_DEFAULT_TOOLSETS: dict[str, str] = {
    "research": "Information gathering, evidence gathering, OCR, and artifact synthesis.",
    "ops": "Operational checks, status workflows, and controlled execution surfaces.",
    "creator": "Image, chart, artifact, and presentation-oriented tools.",
    "safe-chat": "Low-risk read-only tools suitable for normal chat turns.",
    "automation": "Tools safe to schedule or run in background automations.",
    "developer": "Code, shell, and engineering-oriented tools.",
    "field": "On-the-ground capture tools such as OCR, image, and web intelligence.",
}


def _parse_semver(v: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(str(v).strip())
    if not m:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in list(items or []):
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _normalize_risk_tier(value: Any) -> str:
    tier = str(value or "LOW").strip().upper()
    if tier == "MED":
        tier = "MEDIUM"
    if tier not in _RISK_ORDER:
        return "LOW"
    return tier


def _normalize_backend(value: Any) -> str:
    raw = str(value or "local").strip().lower()
    aliases = {
        "shell": "local",
        "subprocess": "local",
        "process": "local",
        "desktop": "local",
        "cli": "local",
        "container": "docker",
        "k8s": "remote",
    }
    return aliases.get(raw, raw or "local")


def _normalize_channel(value: Any) -> str:
    raw = str(value or "chat").strip().lower()
    aliases = {
        "desktop": "gui",
        "ui": "gui",
        "telegram_bot": "telegram",
        "voice_chat": "voice",
        "scheduled": "automation",
    }
    return aliases.get(raw, raw or "chat")


def _tool_trust_label(entry: dict[str, Any]) -> str:
    path = Path(str(entry.get("path") or ""))
    normalized = path.as_posix().lower()
    if "workshop/tools/installed/" in normalized:
        return "installed_local"
    if normalized.startswith("workshop/"):
        return "bundled_local"
    if normalized:
        return "workspace_local"
    return "unknown"


class ToolRegistry:
    def __init__(self, path: str = "workshop/tools/registry.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save({"tools": []})

    def _normalize_policy(self, entry: dict[str, Any]) -> dict[str, Any]:
        raw = dict(entry.get("policy") or {})
        read_only = bool(raw.get("read_only", False))
        policy = {
            "read_only": read_only,
            "risk_tier": _normalize_risk_tier(raw.get("risk_tier", "LOW")),
            "requires_approval": bool(raw.get("requires_approval", not read_only)),
            "mutates_state": bool(raw.get("mutates_state", not read_only)),
        }
        return policy

    def _normalize_exposure(self, entry: dict[str, Any], *, read_only: bool) -> dict[str, bool]:
        raw = dict(entry.get("exposure") or {})
        return {
            "ui": bool(raw.get("ui", True)),
            "agent": bool(raw.get("agent", True)),
            "automation": bool(raw.get("automation", read_only)),
        }

    def _normalize_healthcheck(self, entry: dict[str, Any]) -> dict[str, list[str]]:
        raw = dict(((entry.get("runtime") or {}).get("healthcheck") or {}))
        return {
            "python_modules": _dedupe(list(raw.get("python_modules") or [])),
            "executables": _dedupe(list(raw.get("executables") or [])),
            "paths_exist": _dedupe(list(raw.get("paths_exist") or [])),
        }

    def _derive_capabilities(self, entry: dict[str, Any], policy: dict[str, Any]) -> list[str]:
        raw_caps = _dedupe(list(entry.get("capabilities") or []))
        if raw_caps:
            return raw_caps

        derived: list[str] = []
        for item in list(entry.get("tags") or []):
            derived.append(str(item))
        name = str(entry.get("name") or "")
        aliases = [name] + list(entry.get("aliases") or [])
        for item in aliases:
            token = str(item).split(".", 1)[0].strip().lower()
            if token:
                derived.append(token)

        if bool(policy.get("read_only", False)):
            derived.append("read")
        else:
            derived.extend(["write", "execute"])

        return _dedupe(derived)

    def _normalize_toolsets(self, entry: dict[str, Any], *, capabilities: list[str], policy: dict[str, Any], exposure: dict[str, bool]) -> list[str]:
        explicit = _dedupe(list(entry.get("toolsets") or []))
        if explicit:
            return explicit

        tags = {str(x).lower() for x in list(entry.get("tags") or [])}
        caps = {str(x).lower() for x in list(capabilities or [])}
        names = {str(entry.get("name") or "").lower()}
        names.update(str(x).lower() for x in list(entry.get("aliases") or []))
        toolsets: list[str] = []

        if caps & {"research", "web", "ocr", "artifact", "finance", "news", "weather", "vision"} or tags & {"research", "web", "ocr", "artifact"}:
            toolsets.append("research")
        if caps & {"image", "chart", "vision", "artifact"} or tags & {"image", "chart", "vision", "artifact"}:
            toolsets.append("creator")
        if caps & {"ocr", "image", "vision", "web"} or tags & {"ocr", "image", "vision", "web"}:
            toolsets.append("field")
        if not bool(policy.get("requires_approval", False)) and bool(policy.get("read_only", False)):
            toolsets.append("safe-chat")
        if bool(exposure.get("automation", False)) and _RISK_ORDER[str(policy.get("risk_tier") or "LOW")] <= _RISK_ORDER["MEDIUM"]:
            toolsets.append("automation")
        if caps & {"cli", "code", "execute", "developer"} or tags & {"developer", "cli", "code"} or any("cli" in name for name in names):
            toolsets.extend(["developer", "ops"])
        if caps & {"ops", "status", "execute"} or tags & {"ops", "status"}:
            toolsets.append("ops")

        return _dedupe(toolsets)

    def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        out = dict(entry or {})
        out.setdefault("enabled", True)
        out["name"] = str(out.get("name") or "").strip()
        out["version"] = str(out.get("version") or "0.0.0").strip()
        out["path"] = str(out.get("path") or "").strip()
        out["description"] = str(out.get("description") or "").strip()
        out["display_name"] = str(out.get("display_name") or out["name"]).strip()
        out["aliases"] = _dedupe(list(out.get("aliases") or []))
        out["examples"] = _dedupe(list(out.get("examples") or []))
        out["tags"] = _dedupe(list(out.get("tags") or []))
        out["input_schema"] = dict(out.get("input_schema") or {})
        out["hashes"] = dict(out.get("hashes") or {})

        policy = self._normalize_policy(out)
        exposure = self._normalize_exposure(out, read_only=bool(policy.get("read_only", False)))
        healthcheck = self._normalize_healthcheck(out)

        backends = _dedupe(
            [_normalize_backend(x) for x in list(((out.get("runtime") or {}).get("backends") or out.get("backends") or _DEFAULT_BACKENDS))]
        ) or list(_DEFAULT_BACKENDS)
        channels = _dedupe(
            [_normalize_channel(x) for x in list(out.get("channels") or _DEFAULT_CHANNELS)]
        ) or list(_DEFAULT_CHANNELS)
        capabilities = self._derive_capabilities(out, policy)
        toolsets = self._normalize_toolsets(out, capabilities=capabilities, policy=policy, exposure=exposure)

        out["policy"] = policy
        out["exposure"] = exposure
        out["capabilities"] = capabilities
        out["toolsets"] = toolsets
        out["backends"] = backends
        out["channels"] = channels
        out["runtime"] = {
            "backends": backends,
            "default_backend": str(((out.get("runtime") or {}).get("default_backend") or backends[0])),
            "healthcheck": healthcheck,
        }
        return out

    def _matches_filters(
        self,
        entry: dict[str, Any],
        *,
        toolset: str | None = None,
        channel: str | None = None,
        backend: str | None = None,
        include_disabled: bool = False,
    ) -> bool:
        if not include_disabled and not bool(entry.get("enabled", True)):
            return False
        if toolset and str(toolset).strip().lower() not in {x.lower() for x in list(entry.get("toolsets") or [])}:
            return False
        if channel and _normalize_channel(channel) not in {_normalize_channel(x) for x in list(entry.get("channels") or [])}:
            return False
        if backend and _normalize_backend(backend) not in {_normalize_backend(x) for x in list(entry.get("backends") or [])}:
            return False
        return True

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def register(self, entry: dict[str, Any]) -> None:
        normalized = self._normalize_entry(entry)
        data = self.load()
        data.setdefault("tools", [])
        data["tools"] = [
            tool
            for tool in data["tools"]
            if not (tool["name"] == normalized["name"] and tool["version"] == normalized["version"])
        ]
        data["tools"].append(normalized)
        self.save(data)

    def find(
        self,
        name: str,
        version: str | None = None,
        *,
        channel: str | None = None,
        backend: str | None = None,
        include_disabled: bool = False,
    ) -> dict[str, Any] | None:
        raw = (name or "").strip()
        parsed_name, parsed_version = (
            (raw.split("@", 1) + [None])[:2] if "@" in raw else (raw, None)
        )
        target_version = version or parsed_version
        needle = parsed_name.lower()
        candidates: list[dict[str, Any]] = []
        for raw_tool in self.load().get("tools", []):
            tool = self._normalize_entry(raw_tool)
            names = [tool.get("name", "")] + list(tool.get("aliases", []))
            if not any(needle == str(item).lower() for item in names):
                continue
            if target_version and tool.get("version") != target_version:
                continue
            if not self._matches_filters(tool, channel=channel, backend=backend, include_disabled=include_disabled):
                continue
            candidates.append(tool)
        if not candidates:
            return None
        if target_version:
            return candidates[0]
        return sorted(
            candidates,
            key=lambda tool: _parse_semver(str(tool.get("version", "0.0.0"))),
            reverse=True,
        )[0]

    def describe(self, name: str, version: str | None = None) -> dict[str, Any] | None:
        return self.find(name, version=version)

    def list_tools(
        self,
        *,
        toolset: str | None = None,
        channel: str | None = None,
        backend: str | None = None,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        tools = [self._normalize_entry(tool) for tool in self.load().get("tools", [])]
        tools = [
            tool
            for tool in tools
            if self._matches_filters(
                tool,
                toolset=toolset,
                channel=channel,
                backend=backend,
                include_disabled=include_disabled,
            )
        ]
        return sorted(
            tools,
            key=lambda tool: (tool.get("display_name") or tool.get("name") or "").lower(),
        )

    def list_toolsets(self, *, include_empty: bool = False) -> list[dict[str, Any]]:
        tool_counts: dict[str, int] = {key: 0 for key in _DEFAULT_TOOLSETS}
        for tool in self.list_tools():
            for toolset in list(tool.get("toolsets") or []):
                tool_counts[toolset] = tool_counts.get(toolset, 0) + 1

        out: list[dict[str, Any]] = []
        for key, description in _DEFAULT_TOOLSETS.items():
            count = int(tool_counts.get(key, 0))
            if count == 0 and not include_empty:
                continue
            out.append({"id": key, "description": description, "tool_count": count})
        return out

    def resolve_toolset(self, name: str) -> dict[str, Any]:
        toolset_id = str(name or "").strip().lower()
        description = _DEFAULT_TOOLSETS.get(toolset_id, "")
        tools = self.list_tools(toolset=toolset_id)
        return {
            "id": toolset_id,
            "description": description,
            "tool_count": len(tools),
            "tools": tools,
        }

    def availability(self, entry_or_name: dict[str, Any] | str) -> dict[str, Any]:
        entry = (
            self._normalize_entry(entry_or_name)
            if isinstance(entry_or_name, dict)
            else self.find(str(entry_or_name))
        )
        if not entry:
            return {"ok": False, "issues": ["tool_not_found"]}

        issues: list[str] = []
        path = Path(str(entry.get("path") or ""))
        if str(entry.get("path") or "").strip() and not path.exists():
            issues.append(f"missing_path:{path.as_posix()}")

        healthcheck = dict(((entry.get("runtime") or {}).get("healthcheck") or {}))
        for module_name in list(healthcheck.get("python_modules") or []):
            if importlib.util.find_spec(str(module_name)) is None:
                issues.append(f"missing_module:{module_name}")
        for executable in list(healthcheck.get("executables") or []):
            if shutil.which(str(executable)) is None:
                issues.append(f"missing_executable:{executable}")
        for raw_path in list(healthcheck.get("paths_exist") or []):
            if not Path(str(raw_path)).exists():
                issues.append(f"missing_required_path:{raw_path}")

        return {"ok": not issues, "issues": issues}

    def build_snapshot(
        self,
        *,
        toolset: str | None = None,
        channel: str | None = None,
        backend: str | None = None,
        include_disabled: bool = False,
    ) -> dict[str, Any]:
        tools = self.list_tools(
            toolset=toolset,
            channel=channel,
            backend=backend,
            include_disabled=include_disabled,
        )
        snapshot_tools: list[dict[str, Any]] = []
        for tool in tools:
            availability = self.availability(tool)
            snapshot_tools.append(
                {
                    "name": str(tool.get("name") or ""),
                    "display_name": str(tool.get("display_name") or tool.get("name") or ""),
                    "version": str(tool.get("version") or ""),
                    "description": str(tool.get("description") or ""),
                    "aliases": list(tool.get("aliases") or []),
                    "capabilities": list(tool.get("capabilities") or []),
                    "toolsets": list(tool.get("toolsets") or []),
                    "backends": list(tool.get("backends") or []),
                    "channels": list(tool.get("channels") or []),
                    "policy": dict(tool.get("policy") or {}),
                    "exposure": dict(tool.get("exposure") or {}),
                    "trust_label": _tool_trust_label(tool),
                    "available": bool(availability.get("ok", False)),
                    "availability_issues": list(availability.get("issues") or []),
                }
            )

        return {
            "count": len(snapshot_tools),
            "filters": {
                "toolset": str(toolset or ""),
                "channel": str(channel or ""),
                "backend": str(backend or ""),
            },
            "toolsets": self.list_toolsets(include_empty=False),
            "tools": snapshot_tools,
        }
