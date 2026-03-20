from __future__ import annotations

from typing import Dict, List


def memory_doctor_report(
    *,
    user_id: str,
    query: str,
    vec_enabled: bool,
    scopes: List[str],
    fts_hits: List[tuple[str, float]],
    vec_hits: List[str],
    fused_ids: List[str],
    injected_preview: str,
    events: List[Dict],
    stats: Dict[str, int],
    retrieval_trace: Dict | None = None,
    source_summary: Dict | None = None,
    latest_sources: List[Dict] | None = None,
    review_summary: Dict | None = None,
) -> str:
    lines = [
        "[Memory Doctor]",
        f"- user_id: {user_id}",
        f"- vectors_enabled: {vec_enabled}",
        f"- scopes: {', '.join(scopes)}",
        f"- query: {query}",
        f"- fts_hits: {len(fts_hits)}",
        f"- vec_hits: {len(vec_hits)}",
        f"- fused_ids: {', '.join(fused_ids[:8]) if fused_ids else '(none)'}",
        "",
        "Top candidates:",
    ]
    for iid, score in fts_hits[:5]:
        lines.append(f"- FTS {iid} score={score:.4f}")
    for iid in vec_hits[:5]:
        lines.append(f"- VEC {iid}")
    lines.extend(["", "Injected preview:", injected_preview[:700], "", "Recent events:"])
    for e in events[:10]:
        lines.append(f"- {e.get('created_at')} | {e.get('event_type')} | {e.get('memory_id')}")
    if source_summary:
        lines.extend(["", "Knowledge vault:"])
        lines.append(f"- total_sources: {dict(source_summary).get('total_sources', 0)}")
        lines.append(f"- total_items: {dict(source_summary).get('total_items', 0)}")
        lines.append(f"- by_type: {dict(source_summary).get('by_type', {})}")
    if latest_sources:
        lines.append("- latest_sources:")
        for row in list(latest_sources or [])[:5]:
            lines.append(f"  - {row.get('source_type')} | {row.get('title')} | {row.get('location')}")
    if retrieval_trace:
        trace = dict(retrieval_trace.get("trace") or retrieval_trace)
        lines.extend(["", "Retrieval explainability:"])
        lines.append(f"- trace_id: {retrieval_trace.get('trace_id', trace.get('trace_id', ''))}")
        lines.append(f"- selected_count: {len(list(trace.get('selected_items') or []))}")
        lines.append(f"- session_hits: {trace.get('session_hit_count', 0)}")
        for item in list(trace.get("selected_items") or [])[:6]:
            lines.append(
                f"  - {item.get('scope', '')} | {item.get('retrieved_via', [])} | {item.get('preview', '')}"
            )
    if review_summary:
        lines.extend(["", "Memory review:"])
        lines.append(f"- status: {dict(review_summary).get('status', 'idle')}")
        lines.append(f"- summary: {dict(review_summary).get('summary', '')}")
        lines.append(
            f"- promote={dict(review_summary).get('promotion_count', 0)} | "
            f"conflicts={dict(review_summary).get('conflict_count', 0)} | "
            f"stale={dict(review_summary).get('stale_count', 0)}"
        )
    lines.extend(["", "DB stats:"])
    for k, v in stats.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
