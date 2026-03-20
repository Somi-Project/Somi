from __future__ import annotations

from typing import Any

from runtime.security_guard import domain_from_url, sanitize_untrusted_text, trust_label, trust_tier_for_domain
from workshop.toolbox.stacks._async import run_coro_sync


def _build_citation_map(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for idx, row in enumerate(results or [], start=1):
        item = dict(row or {})
        url = str(item.get("url") or item.get("link") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        domain = domain_from_url(url)
        tier = trust_tier_for_domain(domain)
        out.append(
            {
                "id": idx,
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "domain": domain,
                "source": str(item.get("source") or item.get("provider") or "web").strip(),
                "published_at": str(item.get("published_at") or item.get("date") or "").strip(),
                "trust_tier": int(tier),
                "trust_label": trust_label(tier),
            }
        )
    return out


def _min_sources_required(signals: dict[str, Any], route_hint: str) -> int:
    intent = str((signals or {}).get("intent") or "").strip().lower()
    hint = str(route_hint or "").strip().lower()
    if intent in {"science", "research"}:
        return 3
    if intent in {"news", "weather", "crypto", "forex", "stock/commodity"}:
        return 2
    if hint in {"websearch", "research"}:
        return 2
    return 1


def _min_trusted_sources_required(signals: dict[str, Any], route_hint: str) -> int:
    intent = str((signals or {}).get("intent") or "").strip().lower()
    hint = str(route_hint or "").strip().lower()
    if intent in {"science", "research"}:
        return 2
    if intent in {"news", "weather"}:
        return 1
    if hint in {"websearch", "research"}:
        return 1
    return 0


def _build_evidence_contract(
    *,
    query: str,
    signals: dict[str, Any],
    route_hint: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    required = _min_sources_required(signals, route_hint)
    found = len(citations)
    trusted_required = _min_trusted_sources_required(signals, route_hint)
    trusted_found = sum(1 for c in citations if int(c.get("trust_tier") or 0) >= 2)

    source_ok = found >= required
    trust_ok = trusted_found >= trusted_required
    satisfied = source_ok and trust_ok

    if satisfied:
        degrade_reason = ""
    elif found == 0:
        degrade_reason = "no_sources"
    elif not source_ok:
        degrade_reason = "insufficient_sources"
    else:
        degrade_reason = "insufficient_trusted_sources"

    return {
        "query": str(query or ""),
        "required_min_sources": int(required),
        "required_min_trusted_sources": int(trusted_required),
        "found_sources": int(found),
        "trusted_sources": int(trusted_found),
        "satisfied": bool(satisfied),
        "degrade_reason": degrade_reason,
        "must_cite": bool(found > 0),
    }


def _render_contract_block(
    *,
    evidence_contract: dict[str, Any],
    citation_map: list[dict[str, Any]],
) -> str:
    lines = [
        "## Evidence Contract",
        f"- required_min_sources: {int(evidence_contract.get('required_min_sources') or 0)}",
        f"- required_min_trusted_sources: {int(evidence_contract.get('required_min_trusted_sources') or 0)}",
        f"- found_sources: {int(evidence_contract.get('found_sources') or 0)}",
        f"- trusted_sources: {int(evidence_contract.get('trusted_sources') or 0)}",
        f"- satisfied: {bool(evidence_contract.get('satisfied'))}",
        "- rule: cite only from Citation Map when evidence exists",
        "- rule: if insufficient evidence, answer with explicit uncertainty",
        "## Citation Map",
    ]

    if not citation_map:
        lines.append("- (none)")
    else:
        for row in citation_map[:10]:
            title = str(row.get("title") or "(untitled)")
            url = str(row.get("url") or "")
            domain = str(row.get("domain") or "")
            cid = int(row.get("id") or 0)
            trust = str(row.get("trust_label") or "low")
            lines.append(f"- [{cid}] {title} ({domain}, trust={trust}) {url}")

    if not bool(evidence_contract.get("satisfied", False)):
        reason = str(evidence_contract.get("degrade_reason") or "insufficient_sources")
        lines.append(f"- degrade_notice: evidence threshold not met ({reason})")

    return "\n".join(lines)


def _render_execution_block(report: dict[str, Any]) -> str:
    steps = [sanitize_untrusted_text(str(item or ""), max_len=240) for item in list((report or {}).get("execution_steps") or []) if str(item or "").strip()]
    if not steps:
        return ""
    lines = ["## Execution Trace"]
    summary = sanitize_untrusted_text(str((report or {}).get("execution_summary") or ""), max_len=320)
    if summary:
        lines.append(f"- summary: {summary}")
    for step in steps[:6]:
        if step:
            lines.append(f"- {step}")
    return "\n".join(lines)


def run_web_intelligence(
    *,
    query: str,
    tool_veto: bool = False,
    reason: str = "",
    signals: dict[str, Any] | None = None,
    route_hint: str = "",
) -> dict[str, Any]:
    q_raw = str(query or "").strip()
    q = sanitize_untrusted_text(q_raw, max_len=420)
    if not q:
        return {"ok": False, "error": "query is required"}

    safe_signals = dict(signals or {})

    try:
        from workshop.toolbox.stacks.web_core.websearch import WebSearchHandler
    except Exception as exc:
        return {"ok": False, "error": f"web stack unavailable: {exc}"}

    try:
        handler = WebSearchHandler()
        results = run_coro_sync(
            handler.search(
                q,
                tool_veto=bool(tool_veto),
                reason=str(reason or ""),
                signals=safe_signals,
                route_hint=str(route_hint or ""),
            )
        )
        formatted = handler.format_results(results)
        browse_report = dict(handler.last_browse_report or {}) if isinstance(handler.last_browse_report, dict) else {}
    except Exception as exc:
        return {"ok": False, "error": f"web search failed: {exc}"}

    result_rows = list(results or [])
    citation_map = _build_citation_map(result_rows)
    evidence_contract = _build_evidence_contract(
        query=q,
        signals=safe_signals,
        route_hint=str(route_hint or ""),
        citations=citation_map,
    )

    contract_block = _render_contract_block(
        evidence_contract=evidence_contract,
        citation_map=citation_map,
    )
    execution_block = _render_execution_block(browse_report)
    parts = [str(formatted or "").strip()]
    if execution_block:
        parts.append(execution_block)
    parts.append(contract_block)
    formatted_with_contract = "\n\n".join([part for part in parts if part]).strip()

    return {
        "ok": True,
        "query": q,
        "sanitized_query": q,
        "count": len(result_rows),
        "results": result_rows,
        "formatted": formatted_with_contract,
        "citation_map": citation_map,
        "evidence_contract": evidence_contract,
        "browse_report": browse_report,
        "execution_trace": list(browse_report.get("execution_steps") or []),
        "execution_summary": str(browse_report.get("execution_summary") or ""),
        "degraded": not bool(evidence_contract.get("satisfied", False)),
    }
