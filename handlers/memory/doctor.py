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
    lines.extend(["", "DB stats:"])
    for k, v in stats.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
