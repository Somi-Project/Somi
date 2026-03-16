from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _latest_pass(job: dict[str, Any]) -> dict[str, Any]:
    passes = [dict(item) for item in list(dict(job or {}).get("passes") or []) if isinstance(item, dict)]
    return dict(passes[-1] if passes else {})


def _top_sources(job: dict[str, Any], *, limit: int = 6) -> list[dict[str, Any]]:
    latest = _latest_pass(job)
    return [dict(item) for item in list(latest.get("sources") or []) if isinstance(item, dict)][:limit]


def _top_claims(job: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    latest = _latest_pass(job)
    return [dict(item) for item in list(latest.get("claims") or []) if isinstance(item, dict)][:limit]


def _document_exhibits(job: dict[str, Any], *, limit: int = 4) -> list[dict[str, Any]]:
    packets = [dict(item) for item in list(dict(job or {}).get("document_packets") or []) if isinstance(item, dict)]
    return packets[:limit]


def _citation_rows(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(sources, start=1):
        rows.append(
            {
                "id": f"S{index}",
                "title": str(item.get("title") or item.get("url") or "Source"),
                "url": str(item.get("url") or ""),
                "source_type": str(item.get("source_type") or ""),
                "published_date": str(item.get("published_date") or ""),
            }
        )
    return rows


def _default_recommendation(export_kind: str) -> str:
    if export_kind == "slide_outline":
        return "Use this export in presentation or briefing workflows."
    if export_kind == "knowledge_page":
        return "Use this export for knowledge vault ingestion and long-term recall."
    if export_kind == "decision_memo":
        return "Use this export where an operator needs a recommendation plus caveats."
    return "Use this export as a reusable research brief for follow-up automations."


def build_export(job: dict[str, Any], *, export_type: str, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(job or {})
    latest = _latest_pass(payload)
    coverage = dict(latest.get("coverage") or {})
    conflicts = [dict(item) for item in list(latest.get("conflicts") or []) if isinstance(item, dict)]
    sources = _top_sources(payload)
    claims = _top_claims(payload)
    documents = _document_exhibits(payload)
    export_kind = str(export_type or "research_brief").strip().lower() or "research_brief"
    graph_payload = dict(graph or {})
    citations = _citation_rows(sources)

    common_header = [
        f"# {str(payload.get('title') or payload.get('query') or 'Research Job')}",
        "",
        f"Query: {payload.get('query') or ''}",
        f"Coverage: {coverage.get('summary') or 'n/a'}",
        f"Graph: {graph_payload.get('summary') or 'n/a'}",
        "",
    ]

    if export_kind == "slide_outline":
        body = [
            *common_header,
            "## Slide 1: Why this matters",
            f"- Research question: {payload.get('query') or ''}",
            "## Slide 2: Best-supported findings",
        ]
        body.extend(f"- {claim.get('text')}" for claim in claims[:4])
        body.append("## Slide 3: Source landscape")
        body.extend(f"- {row.get('title')} [{row.get('source_type')}]" for row in citations[:4])
        body.append("## Slide 4: Conflicts and caveats")
        body.extend(f"- {row.get('reason')}" for row in conflicts[:4] or [{"reason": "No major contradictions detected."}])
    elif export_kind == "knowledge_page":
        body = [
            *common_header,
            "## Summary",
            f"- Research memory: {dict(payload.get('memory') or {}).get('summary') or 'n/a'}",
            "## Claims",
        ]
        body.extend(f"- {claim.get('text')} [{claim.get('confidence')}]" for claim in claims[:8])
        if documents:
            body.append("## Document Exhibits")
            body.extend(
                f"- {row.get('label')} :: type={row.get('document_type')} records={row.get('record_count')} tables={row.get('table_count')}"
                for row in documents
            )
        body.append("## Sources")
        body.extend(f"- {row.get('title')} ({row.get('url')})" for row in citations[:8])
    elif export_kind == "decision_memo":
        body = [
            f"# Decision Memo: {payload.get('title') or payload.get('query') or 'Research Job'}",
            "",
            f"Query: {payload.get('query') or ''}",
            f"Coverage: {coverage.get('summary') or 'n/a'}",
            f"Graph: {graph_payload.get('summary') or 'n/a'}",
            "",
            "## Recommendation",
            f"- Proceed with caution; current coverage score is {coverage.get('coverage_score') or 0}.",
            "## Supporting evidence",
        ]
        body.extend(f"- {claim.get('text')}" for claim in claims[:5])
        if documents:
            body.append("## Attached exhibits")
            body.extend(
                f"- {row.get('label')} :: manual_review={row.get('manual_review_required')} score={row.get('confidence_score')}"
                for row in documents
            )
        body.append("## Risks")
        body.extend(f"- {row.get('reason')}" for row in conflicts[:5] or [{"reason": "Residual uncertainty remains because source coverage is incomplete."}])
    else:
        body = [
            f"# Research Brief: {payload.get('title') or payload.get('query') or 'Research Job'}",
            "",
            f"Coverage: {coverage.get('summary') or 'n/a'}",
            f"Research memory: {dict(payload.get('memory') or {}).get('summary') or 'n/a'}",
            f"Evidence graph: {graph_payload.get('summary') or 'n/a'}",
            "",
            "## Best-supported claims",
        ]
        body.extend(f"- {claim.get('text')} [{claim.get('confidence')}]" for claim in claims[:6])
        body.append("## Contradictions")
        body.extend(f"- {row.get('reason')}" for row in conflicts[:6] or [{"reason": "No major contradictions detected."}])
        if documents:
            body.append("## Document exhibits")
            body.extend(
                f"- {row.get('label')} :: tables={row.get('table_count')} charts={row.get('chart_count')} records={row.get('record_count')}"
                for row in documents
            )
        body.append("## Sources")
        body.extend(f"- {row.get('title')} ({row.get('url')})" for row in citations[:6])

    artifact_bundle = {
        "query": str(payload.get("query") or ""),
        "job_id": str(payload.get("job_id") or ""),
        "export_type": export_kind,
        "coverage": coverage,
        "claim_count": len(list(latest.get("claims") or [])),
        "source_count": len(list(latest.get("sources") or [])),
        "conflict_count": len(conflicts),
        "document_count": len(documents),
        "table_count": sum(int(item.get("table_count") or 0) for item in documents),
        "chart_count": sum(int(item.get("chart_count") or 0) for item in documents),
        "graph_summary": str(graph_payload.get("summary") or ""),
        "graph_stats": dict(graph_payload.get("stats") or {}),
        "documents": [
            {
                "document_id": str(item.get("document_id") or ""),
                "label": str(item.get("label") or ""),
                "document_type": str(item.get("document_type") or ""),
                "record_count": int(item.get("record_count") or 0),
                "table_count": int(item.get("table_count") or 0),
                "chart_count": int(item.get("chart_count") or 0),
                "manual_review_required": bool(item.get("manual_review_required")),
                "exports": dict(item.get("exports") or {}),
            }
            for item in documents
        ],
        "citations": citations,
        "recommendation": _default_recommendation(export_kind),
    }
    return {"export_type": export_kind, "markdown": "\n".join(body).strip() + "\n", "artifact_bundle": artifact_bundle}


def save_export(*, root_dir: str | Path, job_id: str, export_payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    export_type = str(export_payload.get("export_type") or "research_brief")
    stem = f"{str(job_id or '').strip()}_{export_type}"
    md_path = root / f"{stem}.md"
    json_path = root / f"{stem}.json"
    md_path.write_text(str(export_payload.get("markdown") or ""), encoding="utf-8")
    json_path.write_text(json.dumps(dict(export_payload.get("artifact_bundle") or {}), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"markdown_path": str(md_path), "json_path": str(json_path)}
