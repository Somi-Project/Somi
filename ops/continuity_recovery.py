from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ops.offline_pack_catalog import build_offline_pack_catalog
from workflow_runtime.manifests import WorkflowManifestStore


def _query_tokens(query: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"[a-z0-9]+", str(query or "").lower()):
        if len(token) < 3 or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _workflow_rows(root_dir: str | Path) -> list[dict[str, Any]]:
    store = WorkflowManifestStore(Path(root_dir) / "workflow_runtime" / "manifests")
    rows: list[dict[str, Any]] = []
    for manifest in store.list_manifests():
        if not str(manifest.manifest_id or "").startswith("continuity_"):
            continue
        metadata = dict(manifest.metadata or {})
        rows.append(
            {
                "manifest_id": str(manifest.manifest_id),
                "name": str(manifest.name),
                "description": str(manifest.description or ""),
                "allowed_tools": list(manifest.allowed_tools),
                "metadata": metadata,
                "keywords": [
                    item
                    for item in (
                        str(metadata.get("domain") or ""),
                        " ".join(list(metadata.get("tags") or [])),
                        str(manifest.name or ""),
                        str(manifest.description or ""),
                    )
                    if str(item).strip()
                ],
            }
        )
    return rows


def build_continuity_recovery_snapshot(
    root_dir: str | Path = ".",
    *,
    runtime_mode: str = "normal",
    query: str = "",
    limit: int = 4,
) -> dict[str, Any]:
    root = Path(root_dir)
    catalog = build_offline_pack_catalog(root, runtime_mode=runtime_mode, query=query, limit=limit)
    workflows = _workflow_rows(root)
    tokens = _query_tokens(query)
    ranked: list[dict[str, Any]] = []
    for row in workflows:
        blob = " ".join(list(row.get("keywords") or [])).lower()
        score = 0
        for token in tokens:
            if token in blob:
                score += 1
        if not tokens:
            score = 1
        ranked.append({**row, "score": score})
    ranked.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("manifest_id") or "")))
    recommended = [item for item in ranked if int(item.get("score") or 0) > 0][: max(1, int(limit or 4))]
    domains = sorted(
        {
            str(dict(item.get("metadata") or {}).get("domain") or "").strip()
            for item in workflows
            if str(dict(item.get("metadata") or {}).get("domain") or "").strip()
        }
    )
    return {
        "ok": bool(catalog.get("ok", False)) and bool(workflows),
        "runtime_mode": str(runtime_mode or "normal"),
        "query": str(query or "").strip(),
        "pack_catalog": catalog,
        "workflow_count": len(workflows),
        "domains": domains,
        "recommended_workflows": recommended,
        "continuity_ready": bool(catalog.get("ok", False)) and len(domains) >= 4,
    }


def format_continuity_recovery_snapshot(report: dict[str, Any]) -> str:
    lines = [
        "[Somi Continuity Recovery]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- runtime_mode: {report.get('runtime_mode', 'normal')}",
        f"- workflow_count: {report.get('workflow_count', 0)}",
        f"- domains: {', '.join(list(report.get('domains') or [])) or '--'}",
        f"- preferred_variant: {dict(dict(report.get('pack_catalog') or {}).get('hardware_profile') or {}).get('profile', {}).get('preferred_pack_variant', 'compact')}",
        f"- recommended_workflows: {len(list(report.get('recommended_workflows') or []))}",
    ]
    query = str(report.get("query") or "").strip()
    if query:
        lines.append(f"- query: {query}")
    recommended = list(report.get("recommended_workflows") or [])[:3]
    if recommended:
        lines.append("")
        lines.append("Top Workflows:")
        for item in recommended:
            lines.append(
                f"- {item.get('name', '')} [{item.get('manifest_id', '')}]"
            )
    return "\n".join(lines)
