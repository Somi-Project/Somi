from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from workshop.toolbox.research_supermode import ResearchSupermodeService


def run(args: dict[str, object], ctx) -> dict[str, object]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()
    service = ResearchSupermodeService()
    document_inputs = args.get("document_inputs") or []
    if isinstance(document_inputs, dict):
        document_inputs = [document_inputs]
    elif not isinstance(document_inputs, list):
        document_inputs = []

    try:
        if action == "start_job":
            query = str(args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "query is required"}
            job = service.start_job(
                user_id=str(args.get("user_id") or "default_user"),
                query=query,
                signals=dict(args.get("signals") or {}),
                route_hint=str(args.get("route_hint") or "research"),
                document_inputs=[dict(item) for item in document_inputs if isinstance(item, dict)],
                deep_read=bool(args.get("deep_read", True)),
                max_reads=int(args.get("max_reads") or 4),
                resume_active=True,
            )
            return {"ok": True, "job": job}

        if action == "resume_job":
            job = service.resume_job(
                job_id=str(args.get("job_id") or ""),
                query=str(args.get("query") or ""),
                signals=dict(args.get("signals") or {}),
                route_hint=str(args.get("route_hint") or ""),
                document_inputs=[dict(item) for item in document_inputs if isinstance(item, dict)],
                deep_read=bool(args.get("deep_read", True)),
                max_reads=int(args.get("max_reads") or 4),
            )
            return {"ok": True, "job": job}

        if action == "status":
            job_id = str(args.get("job_id") or "").strip()
            if job_id:
                job = service.get_job(job_id)
            else:
                job = service.store.get_active_job(str(args.get("user_id") or "default_user"))
                job = service.get_job(str(dict(job or {}).get("job_id") or "")) if isinstance(job, dict) else None
            return {"ok": True, "job": job or {}}

        if action == "list_jobs":
            return {
                "ok": True,
                "jobs": service.list_jobs(user_id=str(args.get("user_id") or "").strip() or None, limit=int(args.get("limit") or 8)),
            }

        if action == "build_graph":
            graph = service.build_graph(str(args.get("job_id") or ""))
            return {"ok": True, "graph": graph}

        if action == "export_job":
            artifact = service.export_job(str(args.get("job_id") or ""), export_type=str(args.get("export_type") or "research_brief"))
            return {"ok": True, "artifact": artifact}

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
