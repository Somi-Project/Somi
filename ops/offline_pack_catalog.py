from __future__ import annotations

from pathlib import Path
from typing import Any

from ops.hardware_tiers import build_hardware_tier_snapshot
from workshop.toolbox.stacks.research_core.local_packs import (
    resolve_local_pack_url,
    scan_local_packs,
    search_local_pack_rows,
)


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def build_offline_pack_catalog(
    root_dir: str | Path = ".",
    *,
    runtime_mode: str = "normal",
    query: str = "",
    limit: int = 6,
) -> dict[str, Any]:
    root = Path(root_dir)
    hardware = build_hardware_tier_snapshot(str(root), runtime_mode=runtime_mode)
    preferred_variant = str(dict(hardware.get("profile") or {}).get("preferred_pack_variant") or "compact")
    pack_report = scan_local_packs(root)
    packs = [dict(item) for item in list(pack_report.get("packs") or [])]
    packs.sort(
        key=lambda item: (
            0 if str(item.get("variant") or "") == preferred_variant else 1,
            str(item.get("category") or ""),
            str(item.get("name") or ""),
        )
    )

    query_text = " ".join(str(query or "").split()).strip()
    recommended_rows = [dict(item) for item in search_local_pack_rows(root, query_text, limit=max(1, _safe_int(limit, 6)))] if query_text else []
    preferred_hits = []
    fallback_hits = []
    for row in recommended_rows:
        target = preferred_hits if str(row.get("pack_variant") or "") == preferred_variant else fallback_hits
        target.append(row)

    doc_previews: list[dict[str, Any]] = []
    for row in recommended_rows[: max(1, _safe_int(limit, 6))]:
        resolved = resolve_local_pack_url(root, str(row.get("url") or ""))
        if not resolved:
            continue
        doc_previews.append(
            {
                "title": str(resolved.get("title") or row.get("title") or ""),
                "pack_id": str(resolved.get("pack_id") or row.get("pack_id") or ""),
                "variant": str(resolved.get("variant") or row.get("pack_variant") or ""),
                "trust": str(resolved.get("trust") or "bundled_local"),
                "sha256": str(resolved.get("sha256") or ""),
                "path": str(resolved.get("path") or row.get("local_path") or ""),
            }
        )

    coverage = {
        "categories_present": list(pack_report.get("categories_present") or []),
        "missing_categories": list(pack_report.get("missing_categories") or []),
        "schema_versions": list(pack_report.get("schema_versions") or []),
        "variants_present": list(pack_report.get("variants_present") or []),
    }
    recommendations = list(pack_report.get("recommendations") or [])
    if query_text and not preferred_hits and fallback_hits:
        recommendations.append(
            f"No local '{preferred_variant}' hit matched '{query_text}'. Somi can fall back to other bundled variants until a preferred variant is installed."
        )
    if preferred_variant not in list(pack_report.get("variants_present") or []):
        recommendations.append(
            f"Install or generate a '{preferred_variant}' pack variant so this hardware tier gets its preferred offline footprint."
        )

    return {
        "ok": bool(pack_report.get("ok", False)),
        "pack_root": str(Path(str(pack_report.get("pack_root") or root / "knowledge_packs"))),
        "runtime_mode": str(runtime_mode or "normal"),
        "hardware_profile": hardware,
        "preferred_variant": preferred_variant,
        "pack_count": int(pack_report.get("pack_count") or 0),
        "document_count": int(pack_report.get("document_count") or 0),
        "coverage": coverage,
        "packs": [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "category": str(item.get("category") or ""),
                "variant": str(item.get("variant") or ""),
                "trust": str(item.get("trust") or ""),
                "updated_at": str(item.get("updated_at") or ""),
                "doc_count": int(item.get("doc_count") or 0),
                "integrity": str(item.get("integrity") or ""),
            }
            for item in packs
        ],
        "query": query_text,
        "recommended_rows": recommended_rows,
        "preferred_hits": preferred_hits,
        "fallback_hits": fallback_hits,
        "doc_previews": doc_previews,
        "recommendations": recommendations,
    }


def format_offline_pack_catalog(report: dict[str, Any]) -> str:
    coverage = dict(report.get("coverage") or {})
    lines = [
        "[Somi Offline Pack Catalog]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- pack_root: {report.get('pack_root', '')}",
        f"- runtime_mode: {report.get('runtime_mode', 'normal')}",
        f"- preferred_variant: {report.get('preferred_variant', 'compact')}",
        f"- pack_count: {report.get('pack_count', 0)}",
        f"- document_count: {report.get('document_count', 0)}",
        f"- categories_present: {', '.join(list(coverage.get('categories_present') or [])) or '--'}",
        f"- variants_present: {', '.join(list(coverage.get('variants_present') or [])) or '--'}",
        f"- missing_categories: {', '.join(list(coverage.get('missing_categories') or [])) or '--'}",
    ]

    query = str(report.get("query") or "").strip()
    if query:
        lines.append(f"- query: {query}")
        lines.append(f"- preferred_hits: {len(list(report.get('preferred_hits') or []))}")
        lines.append(f"- fallback_hits: {len(list(report.get('fallback_hits') or []))}")

    lines.append("")
    lines.append("Recommendations:")
    recommendations = list(report.get("recommendations") or [])
    if not recommendations:
        lines.append("- none")
    else:
        for item in recommendations:
            lines.append(f"- {item}")

    previews = list(report.get("doc_previews") or [])[:3]
    if previews:
        lines.append("")
        lines.append("Preview Docs:")
        for item in previews:
            lines.append(
                f"- {item.get('title', '')} [{item.get('pack_id', '')}/{item.get('variant', '')}] ({item.get('trust', '')})"
            )
    return "\n".join(lines)
