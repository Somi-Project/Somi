from __future__ import annotations

from dataclasses import asdict
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from workshop.toolbox.stacks._async import run_coro_sync
from workshop.toolbox.stacks.research_core.evidence_claims import extract_claim_candidates
from workshop.toolbox.stacks.research_core.evidence_reconcile import reconcile_claims
from workshop.toolbox.stacks.research_core.evidence_schema import EvidenceItem
from workshop.toolbox.stacks.research_core.evidence_scoring import classify_source_type, score_items
from workshop.toolbox.stacks.research_core.reader import deep_read_items
from workshop.toolbox.stacks.web_intelligence import run_web_intelligence
from workshop.toolbox.research_supermode.evidence_graph import build_evidence_graph
from workshop.toolbox.research_supermode.exports import build_export, save_export
from workshop.toolbox.research_supermode.store import ResearchSupermodeStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_id() -> str:
    return f"rjob_{uuid.uuid4().hex[:12]}"


def _pass_id() -> str:
    return f"rpass_{uuid.uuid4().hex[:10]}"


def _title(query: str) -> str:
    text = " ".join(str(query or "").strip().split())
    return text[:84] if len(text) <= 84 else f"{text[:81].rstrip()}..."


def _tokens(text: str) -> set[str]:
    return {token for token in str(text or "").lower().replace("%", " percent ").split() if len(token) > 2}


def _polarity(text: str) -> int:
    lowered = str(text or "").lower()
    negative = any(token in lowered for token in ("no benefit", "not effective", "worse", "decrease", "harm"))
    positive = any(token in lowered for token in ("improved", "improves", "benefit", "effective", "increase", "reduces"))
    if negative and "benefit" in lowered and "no benefit" in lowered:
        positive = positive and False
    if positive and not negative:
        return 1
    if negative and not positive:
        return -1
    return 0


def _needs_recency(query: str, signals: dict[str, Any]) -> bool:
    query_l = str(query or "").lower()
    intent = str(dict(signals or {}).get("intent") or "").lower()
    if intent in {"news", "research"}:
        return True
    return any(token in query_l for token in ("latest", "recent", "today", "current", "newest"))


def _normalise_results(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(payload, dict):
        return [dict(item) for item in list(payload.get("results") or []) if isinstance(item, dict)], dict(payload)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)], {}
    return [], {}


def _build_items(results: list[dict[str, Any]], *, query: str, needs_recency: bool) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for index, row in enumerate(results, start=1):
        url = str(row.get("url") or row.get("link") or "").strip()
        title = str(row.get("title") or "").strip() or f"Source {index}"
        snippet = str(row.get("description") or row.get("snippet") or "").strip()
        item = EvidenceItem(
            id=f"src_{index}",
            title=title,
            url=url,
            source_type=classify_source_type(url, provider_hint=str(row.get("source") or row.get("provider") or "")),
            published_date=str(row.get("published_at") or row.get("date") or "").strip() or None,
            retrieved_at=_now_iso(),
            snippet=snippet,
            content_excerpt=str(row.get("content_excerpt") or "").strip() or None,
            identifiers={"provider": str(row.get("source") or row.get("provider") or "")},
            domain=(urlparse(url).netloc or "").lower() or None,
        )
        items.append(item)
    return score_items(items, question=query, needs_recency=needs_recency)


def _coverage(items: list[EvidenceItem], claims: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    trusted = [item for item in items if item.source_type in {"official", "academic", "reputable_news", "reference"}]
    deep_read = [item for item in items if str(item.content_excerpt or "").strip()]
    domains = sorted({str(item.domain or "") for item in items if str(item.domain or "").strip()})
    coverage_score = round(
        min(
            100.0,
            (len(items) * 8.0) + (len(trusted) * 12.0) + (len(deep_read) * 8.0) + (len(claims) * 4.0) - (len(conflicts) * 3.0),
        ),
        2,
    )
    return {
        "source_count": len(items),
        "trusted_source_count": len(trusted),
        "deep_read_count": len(deep_read),
        "claim_count": len(claims),
        "conflict_count": len(conflicts),
        "domains": domains,
        "coverage_score": coverage_score,
        "summary": f"sources={len(items)} trusted={len(trusted)} claims={len(claims)} conflicts={len(conflicts)} coverage={coverage_score}",
    }


def _guess_document_label(packet: dict[str, Any], *, index: int) -> str:
    for key in ("label", "title", "document_title"):
        value = str(packet.get(key) or "").strip()
        if value:
            return value
    for key in ("source_path", "image_path"):
        value = str(packet.get(key) or "").strip()
        if value:
            return Path(value).stem.replace("_", " ").strip() or f"Document {index}"
    return f"Document {index}"


def _guess_chart_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
    charts = [dict(item) for item in list(packet.get("charts") or []) if isinstance(item, dict)]
    if charts:
        return charts
    for export_name, export_value in dict(packet.get("exports") or {}).items():
        if "chart" in str(export_name).lower() or "plot" in str(export_name).lower():
            charts.append(
                {
                    "label": str(export_name).replace("_", " "),
                    "chart_type": "export",
                    "series_count": 1,
                    "path": str(export_value or ""),
                }
            )
    return charts


def _normalize_document_inputs(document_inputs: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for index, raw in enumerate(list(document_inputs or []), start=1):
        if not isinstance(raw, dict):
            continue
        quality = dict(raw.get("quality") or {})
        structured_records = [dict(item) for item in list(raw.get("structured_records") or []) if isinstance(item, dict)]
        table_rows = [dict(item) for item in list(raw.get("tables") or []) if isinstance(item, dict)]
        if not table_rows:
            for table_index, shape in enumerate(list(quality.get("table_shapes") or []), start=1):
                if not isinstance(shape, dict):
                    continue
                table_rows.append(
                    {
                        "table_id": f"doc_{index}:table:{table_index}",
                        "label": str(shape.get("label") or f"Table {table_index}"),
                        "row_count": int(shape.get("rows") or shape.get("row_count") or len(structured_records)),
                        "columns": list(shape.get("columns") or []),
                    }
                )
        linked_source_ids = [str(item) for item in list(raw.get("linked_source_ids") or []) if str(item).strip()]
        label = _guess_document_label(raw, index=index)
        charts = _guess_chart_rows(raw)
        packet = {
            "document_id": str(raw.get("document_id") or f"doc_{index}").strip() or f"doc_{index}",
            "label": label,
            "document_type": str(raw.get("document_type") or raw.get("schema_id") or raw.get("mode") or "document"),
            "summary": str(raw.get("structured_text") or raw.get("raw_text") or "")[:1200],
            "record_count": len(structured_records),
            "confidence_score": float(quality.get("score") or raw.get("confidence_score") or 0.0),
            "manual_review_required": bool(quality.get("manual_review_required") or raw.get("manual_review_required")),
            "manual_review_message": str(quality.get("manual_review_message") or raw.get("manual_review_message") or ""),
            "tables": table_rows,
            "table_count": len(table_rows),
            "charts": charts,
            "chart_count": len(charts),
            "exports": dict(raw.get("exports") or {}),
            "provenance": dict(raw.get("provenance") or {}),
            "linked_source_ids": linked_source_ids,
        }
        packets.append(packet)

    summary = {
        "document_count": len(packets),
        "table_count": sum(int(item.get("table_count") or 0) for item in packets),
        "chart_count": sum(int(item.get("chart_count") or 0) for item in packets),
        "manual_review_count": sum(1 for item in packets if bool(item.get("manual_review_required"))),
    }
    summary["summary"] = (
        f"documents={summary['document_count']} tables={summary['table_count']} "
        f"charts={summary['chart_count']} manual_review={summary['manual_review_count']}"
    )
    return packets, summary


def _merge_document_packets(existing: list[dict[str, Any]] | None, incoming: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for packet in [*(list(existing or [])), *(list(incoming or []))]:
        if not isinstance(packet, dict):
            continue
        key = str(packet.get("document_id") or "").strip() or f"doc_{len(merged) + 1}"
        merged[key] = dict(packet)
    return list(merged.values())


def _subagent_rows(items: list[EvidenceItem], claims: list[dict[str, Any]], conflicts: list[dict[str, Any]], coverage: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": "discovery_scout", "status": "completed" if items else "idle", "summary": f"Ranked {len(items)} sources."},
        {"id": "source_reader", "status": "completed" if coverage.get("deep_read_count") else "idle", "summary": f"Deep-read {coverage.get('deep_read_count') or 0} sources."},
        {"id": "contradiction_guard", "status": "completed", "summary": f"Found {len(conflicts)} contradictions across {len(claims)} claims."},
        {"id": "coverage_analyst", "status": "completed", "summary": str(coverage.get("summary") or "")},
    ]


def _memory_summary(job: dict[str, Any]) -> dict[str, Any]:
    passes = [dict(item) for item in list(job.get("passes") or []) if isinstance(item, dict)]
    domains: list[str] = []
    for item in passes:
        domains.extend(str(domain) for domain in list(dict(item.get("coverage") or {}).get("domains") or []) if str(domain).strip())
    recent_queries = [str(item.get("query") or "") for item in passes[-3:] if str(item.get("query") or "").strip()]
    unique_domains = sorted(dict.fromkeys(domains))
    contradictions = sum(int(dict(item.get("coverage") or {}).get("conflict_count") or 0) for item in passes)
    document_summary = dict(job.get("document_summary") or {})
    lines = []
    if recent_queries:
        lines.append("Recent passes: " + " | ".join(recent_queries))
    if unique_domains:
        lines.append("Observed domains: " + ", ".join(unique_domains[:6]))
    if document_summary.get("document_count"):
        lines.append(
            "Document exhibits: "
            f"{document_summary.get('document_count')} docs / "
            f"{document_summary.get('table_count') or 0} tables / "
            f"{document_summary.get('chart_count') or 0} charts"
        )
    lines.append(f"Contradictions seen so far: {contradictions}")
    return {"summary": " | ".join(lines[:3]), "lines": lines[:5]}


def _detect_source_conflicts(items: list[EvidenceItem]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(items):
        left_text = " ".join(part for part in [left.title, left.snippet or "", left.content_excerpt or ""] if part)
        left_tokens = _tokens(left_text)
        left_pol = _polarity(left_text)
        if not left_tokens or left_pol == 0:
            continue
        for right in items[index + 1 :]:
            right_text = " ".join(part for part in [right.title, right.snippet or "", right.content_excerpt or ""] if part)
            right_tokens = _tokens(right_text)
            right_pol = _polarity(right_text)
            if right_pol == 0 or right_pol == left_pol:
                continue
            if len(left_tokens & right_tokens) < 3:
                continue
            conflicts.append(
                {
                    "type": "source_directional",
                    "claim_a": left.id,
                    "claim_b": right.id,
                    "reason": "Opposing source language detected during comparison.",
                }
            )
    return conflicts


class ResearchSupermodeService:
    def __init__(self, store: ResearchSupermodeStore | None = None) -> None:
        self.store = store or ResearchSupermodeStore()

    def _write(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = dict(job or {})
        passes = [dict(item) for item in list(payload.get("passes") or []) if isinstance(item, dict)]
        latest = dict(passes[-1] if passes else {})
        coverage = dict(latest.get("coverage") or {})
        payload["progress"] = {
            "pass_count": len(passes),
            "coverage_score": float(coverage.get("coverage_score") or 0.0),
            "summary": str(coverage.get("summary") or "No research progress yet."),
        }
        payload["memory"] = _memory_summary(payload)
        graph = build_evidence_graph(payload) if passes else {}
        payload["evidence_graph_summary"] = str(dict(graph or {}).get("summary") or "")
        payload["updated_at"] = _now_iso()
        return self.store.write_job(payload)

    def _run_pass(
        self,
        *,
        query: str,
        signals: dict[str, Any],
        route_hint: str,
        results: list[dict[str, Any]],
        document_packets: list[dict[str, Any]] | None,
        deep_read: bool,
        max_reads: int,
    ) -> dict[str, Any]:
        needs_recency = _needs_recency(query, signals)
        items = _build_items(results, query=query, needs_recency=needs_recency)
        if deep_read and items:
            try:
                items = run_coro_sync(deep_read_items(items, max_reads=max_reads))
                items = score_items(items, question=query, needs_recency=needs_recency)
            except Exception:
                pass

        candidates = extract_claim_candidates(items, max_claims_per_item=4)
        claims, conflicts = reconcile_claims(candidates, items_by_id={item.id: item for item in items}, risk_mode="normal")
        if not conflicts:
            conflicts = _detect_source_conflicts(items)
        claim_rows = [asdict(claim) for claim in claims]
        coverage = _coverage(items, claim_rows, conflicts)
        doc_packets = [dict(item) for item in list(document_packets or []) if isinstance(item, dict)]
        document_summary = {
            "document_count": len(doc_packets),
            "table_count": sum(int(item.get("table_count") or 0) for item in doc_packets),
            "chart_count": sum(int(item.get("chart_count") or 0) for item in doc_packets),
            "manual_review_count": sum(1 for item in doc_packets if bool(item.get("manual_review_required"))),
        }
        if document_summary["document_count"]:
            coverage["document_count"] = document_summary["document_count"]
            coverage["table_count"] = document_summary["table_count"]
            coverage["chart_count"] = document_summary["chart_count"]
            coverage["manual_review_count"] = document_summary["manual_review_count"]
            coverage["summary"] = (
                f"{coverage.get('summary') or ''} "
                f"docs={document_summary['document_count']} tables={document_summary['table_count']} charts={document_summary['chart_count']}"
            ).strip()
        return {
            "pass_id": _pass_id(),
            "query": str(query or ""),
            "route_hint": str(route_hint or "research"),
            "created_at": _now_iso(),
            "results": results,
            "sources": [asdict(item) for item in items],
            "claims": claim_rows,
            "conflicts": list(conflicts),
            "coverage": coverage,
            "document_summary": document_summary,
            "subagents": _subagent_rows(items, claim_rows, conflicts, coverage),
        }

    def start_job(
        self,
        *,
        user_id: str,
        query: str,
        signals: dict[str, Any] | None = None,
        route_hint: str = "research",
        result_provider: Callable[[str, dict[str, Any], str], Any] | None = None,
        document_inputs: list[dict[str, Any]] | None = None,
        deep_read: bool = True,
        max_reads: int = 4,
        resume_active: bool = True,
    ) -> dict[str, Any]:
        safe_user = str(user_id or "default_user").strip() or "default_user"
        signal_payload = dict(signals or {})
        document_packets, document_summary = _normalize_document_inputs(document_inputs)
        active = self.store.get_active_job(safe_user) if resume_active else None
        if isinstance(active, dict) and str(active.get("query") or "").strip().lower() == str(query or "").strip().lower():
            job = active
        else:
            job = {
                "job_id": _job_id(),
                "user_id": safe_user,
                "title": _title(query),
                "query": str(query or "").strip(),
                "status": "active",
                "signals": signal_payload,
                "route_hint": str(route_hint or "research"),
                "passes": [],
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        merged_documents = _merge_document_packets(list(job.get("document_packets") or []), document_packets)
        merged_summary = {
            "document_count": len(merged_documents),
            "table_count": sum(int(item.get("table_count") or 0) for item in merged_documents),
            "chart_count": sum(int(item.get("chart_count") or 0) for item in merged_documents),
            "manual_review_count": sum(1 for item in merged_documents if bool(item.get("manual_review_required"))),
        }
        merged_summary["summary"] = (
            f"documents={merged_summary['document_count']} tables={merged_summary['table_count']} "
            f"charts={merged_summary['chart_count']} manual_review={merged_summary['manual_review_count']}"
        )
        job["document_packets"] = merged_documents
        job["document_summary"] = merged_summary if merged_documents else document_summary

        raw = result_provider(query, signal_payload, route_hint) if callable(result_provider) else run_web_intelligence(query=query, signals=signal_payload, route_hint=route_hint)
        results, raw_payload = _normalise_results(raw)
        pass_payload = self._run_pass(
            query=query,
            signals=signal_payload,
            route_hint=route_hint,
            results=results,
            document_packets=list(job.get("document_packets") or []),
            deep_read=deep_read,
            max_reads=max_reads,
        )
        if raw_payload:
            pass_payload["raw"] = raw_payload
        job.setdefault("passes", []).append(pass_payload)
        job["latest_pass_id"] = str(pass_payload.get("pass_id") or "")
        job["subagents"] = list(pass_payload.get("subagents") or [])
        return self._write(job)

    def resume_job(
        self,
        *,
        job_id: str,
        query: str = "",
        signals: dict[str, Any] | None = None,
        route_hint: str = "",
        result_provider: Callable[[str, dict[str, Any], str], Any] | None = None,
        document_inputs: list[dict[str, Any]] | None = None,
        deep_read: bool = True,
        max_reads: int = 4,
    ) -> dict[str, Any]:
        job = self.store.load_job(job_id)
        if not isinstance(job, dict):
            raise ValueError(f"Unknown research job: {job_id}")
        effective_query = str(query or job.get("query") or "").strip()
        signal_payload = dict(job.get("signals") or {})
        signal_payload.update(dict(signals or {}))
        hint = str(route_hint or job.get("route_hint") or "research")
        document_packets, document_summary = _normalize_document_inputs(document_inputs)
        merged_documents = _merge_document_packets(list(job.get("document_packets") or []), document_packets)
        if merged_documents:
            job["document_packets"] = merged_documents
            job["document_summary"] = {
                "document_count": len(merged_documents),
                "table_count": sum(int(item.get("table_count") or 0) for item in merged_documents),
                "chart_count": sum(int(item.get("chart_count") or 0) for item in merged_documents),
                "manual_review_count": sum(1 for item in merged_documents if bool(item.get("manual_review_required"))),
                "summary": (
                    f"documents={len(merged_documents)} "
                    f"tables={sum(int(item.get('table_count') or 0) for item in merged_documents)} "
                    f"charts={sum(int(item.get('chart_count') or 0) for item in merged_documents)} "
                    f"manual_review={sum(1 for item in merged_documents if bool(item.get('manual_review_required')))}"
                ),
            }
        elif document_summary:
            job["document_summary"] = document_summary
        raw = result_provider(effective_query, signal_payload, hint) if callable(result_provider) else run_web_intelligence(query=effective_query, signals=signal_payload, route_hint=hint)
        results, raw_payload = _normalise_results(raw)
        pass_payload = self._run_pass(
            query=effective_query,
            signals=signal_payload,
            route_hint=hint,
            results=results,
            document_packets=list(job.get("document_packets") or []),
            deep_read=deep_read,
            max_reads=max_reads,
        )
        if raw_payload:
            pass_payload["raw"] = raw_payload
        job.setdefault("passes", []).append(pass_payload)
        job["latest_pass_id"] = str(pass_payload.get("pass_id") or "")
        job["subagents"] = list(pass_payload.get("subagents") or [])
        job["signals"] = signal_payload
        job["route_hint"] = hint
        return self._write(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.store.load_job(job_id)
        if not isinstance(job, dict):
            return None
        return self._write(job)

    def list_jobs(self, *, user_id: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        return [self._write(dict(item)) for item in self.store.list_jobs(user_id=user_id, limit=limit)]

    def build_graph(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not isinstance(job, dict):
            raise ValueError(f"Unknown research job: {job_id}")
        graph = build_evidence_graph(job)
        graph_path = self.store.write_graph(job_id, graph)
        graph["graph_path"] = graph_path
        job["evidence_graph"] = graph
        self._write(job)
        return graph

    def export_job(self, job_id: str, *, export_type: str = "research_brief") -> dict[str, Any]:
        job = self.get_job(job_id)
        if not isinstance(job, dict):
            raise ValueError(f"Unknown research job: {job_id}")
        graph = self.build_graph(job_id)
        export_payload = build_export(job, export_type=export_type, graph=graph)
        paths = save_export(root_dir=self.store.exports_dir, job_id=job_id, export_payload=export_payload)
        bundle_payload = {
            "job_id": str(job_id or ""),
            "created_at": _now_iso(),
            "graph_path": str(graph.get("graph_path") or ""),
            "artifact_bundle": dict(export_payload.get("artifact_bundle") or {}),
            **paths,
        }
        bundle_path = self.store.write_bundle(job_id, str(export_payload.get("export_type") or export_type), bundle_payload)
        artifact = {**export_payload, **paths, "bundle_path": bundle_path, "graph_path": str(graph.get("graph_path") or "")}
        artifacts = [dict(item) for item in list(job.get("artifacts") or []) if isinstance(item, dict)]
        artifacts.append(
            {
                "export_type": export_payload["export_type"],
                "bundle_path": bundle_path,
                "graph_path": str(graph.get("graph_path") or ""),
                **paths,
                "created_at": _now_iso(),
            }
        )
        job["artifacts"] = artifacts[-12:]
        self._write(job)
        return artifact
