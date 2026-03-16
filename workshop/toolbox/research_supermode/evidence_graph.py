from __future__ import annotations

import re
from typing import Any


_STOPWORDS = {
    "about",
    "after",
    "against",
    "among",
    "been",
    "comparison",
    "document",
    "documents",
    "evidence",
    "framework",
    "frameworks",
    "from",
    "have",
    "into",
    "latest",
    "local",
    "more",
    "same",
    "source",
    "sources",
    "table",
    "tables",
    "that",
    "their",
    "there",
    "these",
    "this",
    "tool",
    "tools",
    "with",
}


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(token) > 3 and token not in _STOPWORDS]


def _text_summary(payload: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            str(payload.get("label") or ""),
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("text") or ""),
        )
        if part
    ).strip()


def _document_nodes(document_packets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    document_nodes: list[dict[str, Any]] = []
    table_nodes: list[dict[str, Any]] = []
    chart_nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for index, packet in enumerate(document_packets, start=1):
        doc_id = str(packet.get("document_id") or f"doc_{index}").strip()
        label = str(packet.get("label") or packet.get("title") or f"Document {index}")
        document_nodes.append(
            {
                "id": doc_id,
                "type": "document",
                "label": label,
                "meta": {
                    "document_type": str(packet.get("document_type") or ""),
                    "record_count": int(packet.get("record_count") or 0),
                    "confidence_score": float(packet.get("confidence_score") or 0.0),
                    "manual_review_required": bool(packet.get("manual_review_required")),
                },
            }
        )
        for table_index, table in enumerate(list(packet.get("tables") or []), start=1):
            table_id = str(table.get("table_id") or f"{doc_id}:table:{table_index}")
            table_nodes.append(
                {
                    "id": table_id,
                    "type": "table",
                    "label": str(table.get("label") or f"{label} table {table_index}"),
                    "meta": {
                        "row_count": int(table.get("row_count") or 0),
                        "columns": list(table.get("columns") or []),
                    },
                }
            )
            edges.append({"type": "contains_table", "from": doc_id, "to": table_id})
        for chart_index, chart in enumerate(list(packet.get("charts") or []), start=1):
            chart_id = str(chart.get("chart_id") or f"{doc_id}:chart:{chart_index}")
            chart_nodes.append(
                {
                    "id": chart_id,
                    "type": "chart",
                    "label": str(chart.get("label") or f"{label} chart {chart_index}"),
                    "meta": {
                        "chart_type": str(chart.get("chart_type") or ""),
                        "series_count": int(chart.get("series_count") or 0),
                    },
                }
            )
            edges.append({"type": "contains_chart", "from": doc_id, "to": chart_id})

    return document_nodes, table_nodes, chart_nodes, edges


def build_evidence_graph(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job or {})
    passes = [dict(item) for item in list(payload.get("passes") or []) if isinstance(item, dict)]
    latest = dict(passes[-1] if passes else {})
    sources = [dict(item) for item in list(latest.get("sources") or []) if isinstance(item, dict)]
    claims = [dict(item) for item in list(latest.get("claims") or []) if isinstance(item, dict)]
    conflicts = [dict(item) for item in list(latest.get("conflicts") or []) if isinstance(item, dict)]
    document_packets = [dict(item) for item in list(payload.get("document_packets") or []) if isinstance(item, dict)]

    source_nodes = [
        {
            "id": str(item.get("id") or ""),
            "type": "source",
            "label": str(item.get("title") or item.get("url") or "Source"),
            "meta": {
                "source_type": str(item.get("source_type") or ""),
                "url": str(item.get("url") or ""),
                "domain": str(item.get("domain") or ""),
                "score": float(item.get("score") or 0.0),
            },
        }
        for item in sources
        if str(item.get("id") or "").strip()
    ]
    claim_nodes = [
        {
            "id": str(item.get("id") or ""),
            "type": "claim",
            "label": str(item.get("text") or "Claim"),
            "meta": {
                "confidence": str(item.get("confidence") or ""),
                "confidence_score": float(item.get("confidence_score") or 0.0),
            },
        }
        for item in claims
        if str(item.get("id") or "").strip()
    ]

    document_nodes, table_nodes, chart_nodes, document_edges = _document_nodes(document_packets)

    entity_counts: dict[str, int] = {}
    corpus = [
        str(payload.get("query") or ""),
        *[str(item.get("title") or "") for item in sources],
        *[str(item.get("text") or "") for item in claims],
        *[_text_summary(item) for item in document_packets],
    ]
    for row in corpus:
        for token in _tokenize(row):
            entity_counts[token] = int(entity_counts.get(token, 0) or 0) + 1
    entity_nodes = [
        {"id": f"entity:{token}", "type": "entity", "label": token, "meta": {"mentions": count}}
        for token, count in sorted(entity_counts.items(), key=lambda item: (-item[1], item[0]))[:14]
    ]

    domain_nodes = [
        {"id": f"domain:{domain}", "type": "domain", "label": domain, "meta": {}}
        for domain in list(dict(latest.get("coverage") or {}).get("domains") or [])
        if str(domain).strip()
    ]

    edges: list[dict[str, Any]] = list(document_edges)
    for claim in claims:
        claim_id = str(claim.get("id") or "").strip()
        for source_id in list(claim.get("supporting_item_ids") or []):
            if claim_id and str(source_id).strip():
                edges.append({"type": "supports", "from": str(source_id), "to": claim_id})
        for source_id in list(claim.get("contradicting_item_ids") or []):
            if claim_id and str(source_id).strip():
                edges.append({"type": "contradicted_by", "from": str(source_id), "to": claim_id})

    for conflict in conflicts:
        left = str(conflict.get("claim_a") or "").strip()
        right = str(conflict.get("claim_b") or "").strip()
        if left and right:
            edges.append({"type": "conflicts", "from": left, "to": right, "reason": str(conflict.get("reason") or "")})

    entity_ids = {str(node.get("label") or ""): str(node.get("id") or "") for node in entity_nodes}
    mentionable_nodes = [*source_nodes, *claim_nodes, *document_nodes, *table_nodes, *chart_nodes]
    for node in mentionable_nodes:
        text = str(node.get("label") or "").lower()
        for token, entity_id in entity_ids.items():
            if token in text:
                edges.append({"type": "mentions", "from": str(node.get("id") or ""), "to": entity_id})

    source_by_id = {str(item.get("id") or ""): item for item in sources}
    for domain_node in domain_nodes:
        domain = str(domain_node.get("label") or "")
        for source_id, source in source_by_id.items():
            if str(source.get("domain") or "") == domain:
                edges.append({"type": "belongs_to", "from": source_id, "to": str(domain_node.get("id") or "")})

    source_ids = {str(node.get("id") or "") for node in source_nodes}
    for packet in document_packets:
        doc_id = str(packet.get("document_id") or "").strip()
        for source_id in list(packet.get("linked_source_ids") or []):
            if doc_id and str(source_id).strip() in source_ids:
                edges.append({"type": "derived_from", "from": doc_id, "to": str(source_id)})

    nodes = [*source_nodes, *claim_nodes, *document_nodes, *table_nodes, *chart_nodes, *entity_nodes, *domain_nodes]
    return {
        "summary": (
            f"nodes={len(nodes)} edges={len(edges)} claims={len(claim_nodes)} "
            f"sources={len(source_nodes)} documents={len(document_nodes)} "
            f"tables={len(table_nodes)} charts={len(chart_nodes)} conflicts={len(conflicts)}"
        ),
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "source_count": len(source_nodes),
            "claim_count": len(claim_nodes),
            "document_count": len(document_nodes),
            "table_count": len(table_nodes),
            "chart_count": len(chart_nodes),
            "entity_count": len(entity_nodes),
            "conflict_count": len(conflicts),
        },
    }
