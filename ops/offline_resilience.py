from __future__ import annotations

from pathlib import Path
from typing import Any

from ops.hardware_tiers import build_hardware_tier_snapshot
from workshop.toolbox.stacks.research_core.evidence_cache import EvidenceCacheStore
from workshop.toolbox.stacks.research_core.local_packs import DEFAULT_REQUIRED_CATEGORIES, scan_local_packs


def run_offline_resilience(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir)
    pack_report = scan_local_packs(root)
    agentpedia_pages = root / "database" / "agentpedia" / "pages"
    agentpedia_page_count = len(list(agentpedia_pages.glob("*.md"))) if agentpedia_pages.exists() else 0
    evidence_root = root / "state" / "research_cache"
    evidence_cache = EvidenceCacheStore(root=evidence_root)
    evidence_records = len(list(evidence_cache.root.glob("*.json"))) if evidence_cache.root.exists() else 0
    hardware = build_hardware_tier_snapshot(str(root))

    fallback_order = []
    if int(pack_report.get("pack_count") or 0) > 0:
        fallback_order.append("bundled_local_packs")
    if agentpedia_page_count > 0:
        fallback_order.append("agentpedia_pages")
    if evidence_records > 0:
        fallback_order.append("evidence_cache")

    readiness = "ready"
    recommendations = list(pack_report.get("recommendations") or [])
    if list(pack_report.get("missing_categories") or []):
        readiness = "partial"
    if not fallback_order:
        readiness = "blocked"
        recommendations.append("Seed at least one local pack, Agentpedia page, or evidence cache artifact for degraded-network resilience.")
    if readiness == "ready" and not evidence_records:
        recommendations.append("Capture more evidence-cache snapshots so repeat research stays useful during weak connectivity.")

    summary = (
        f"packs={pack_report.get('pack_count', 0)} "
        f"docs={pack_report.get('document_count', 0)} "
        f"agentpedia_pages={agentpedia_page_count} "
        f"evidence_cache={evidence_records}"
    )
    return {
        "ok": readiness != "blocked",
        "readiness": readiness,
        "summary": summary,
        "knowledge_packs": pack_report,
        "pack_root": str(Path(str(pack_report.get("pack_root") or root / 'knowledge_packs'))),
        "required_categories": list(DEFAULT_REQUIRED_CATEGORIES),
        "missing_categories": list(pack_report.get("missing_categories") or []),
        "agentpedia_pages_root": str(agentpedia_pages),
        "agentpedia_pages_count": agentpedia_page_count,
        "evidence_cache_root": str(evidence_root),
        "evidence_cache_records": evidence_records,
        "hardware_profile": hardware,
        "fallback_order": fallback_order,
        "recommendations": recommendations,
    }


def format_offline_resilience(report: dict[str, Any]) -> str:
    pack_report = dict(report.get("knowledge_packs") or {})
    lines = [
        "[Somi Offline Resilience]",
        f"- ok: {bool(report.get('ok', False))}",
        f"- readiness: {report.get('readiness', 'blocked')}",
        f"- summary: {report.get('summary', '')}",
        f"- pack_root: {report.get('pack_root', '')}",
        f"- packs: {pack_report.get('pack_count', 0)}",
        f"- documents: {pack_report.get('document_count', 0)}",
        f"- agentpedia_pages: {report.get('agentpedia_pages_count', 0)}",
        f"- evidence_cache_records: {report.get('evidence_cache_records', 0)}",
        f"- hardware_tier: {dict(report.get('hardware_profile') or {}).get('profile', {}).get('tier', 'unknown')}",
        f"- preferred_pack_variant: {dict(report.get('hardware_profile') or {}).get('profile', {}).get('preferred_pack_variant', 'compact')}",
        f"- fallback_order: {', '.join(list(report.get('fallback_order') or [])) or '--'}",
        f"- missing_categories: {', '.join(list(report.get('missing_categories') or [])) or '--'}",
    ]
    recommendations = list(report.get("recommendations") or [])
    lines.append("")
    lines.append("Recommendations:")
    if not recommendations:
        lines.append("- none")
    else:
        for item in recommendations:
            lines.append(f"- {item}")
    return "\n".join(lines)
