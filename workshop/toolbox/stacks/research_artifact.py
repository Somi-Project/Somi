from __future__ import annotations

from typing import Any

from workshop.toolbox.stacks._async import run_coro_sync


def _build_artifact(args: dict[str, Any]) -> dict[str, Any]:
    from workshop.toolbox.stacks.contracts_core.orchestrator import build_artifact_for_intent, validate_and_render

    artifact = build_artifact_for_intent(
        artifact_intent=str(args.get("artifact_intent") or ""),
        query=str(args.get("query") or ""),
        route=str(args.get("route") or "llm_only"),
        answer_text=str(args.get("answer_text") or ""),
        raw_search_results=list(args.get("raw_search_results") or []),
        rag_block=str(args.get("rag_block") or ""),
        min_sources=int(args.get("min_sources") or 3),
        previous_plan=dict(args.get("previous_plan") or {}) or None,
        new_constraints=list(args.get("new_constraints") or []),
        trigger_reason=dict(args.get("trigger_reason") or {}) or None,
    )
    markdown = validate_and_render(artifact)
    return {"ok": True, "artifact": artifact, "markdown": markdown}


def run_research_artifact(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    if not action:
        return {"ok": False, "error": "action is required"}

    try:
        from workshop.toolbox.stacks.research_core.agentpedia import Agentpedia

        agentpedia = Agentpedia(write_back=False)
    except Exception as exc:
        return {"ok": False, "error": f"research stack unavailable: {exc}"}

    try:
        if action == "generate_artifact":
            return _build_artifact(args)

        if action == "agentpedia_search":
            query = str(args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "query is required"}
            results = run_coro_sync(agentpedia.search(query, allow_router=True))
            return {"ok": True, "count": len(results or []), "results": results or []}

        if action == "agentpedia_topic_page":
            topic = str(args.get("topic") or "").strip()
            if not topic:
                return {"ok": False, "error": "topic is required"}
            return {"ok": True, "topic": topic, "markdown": agentpedia.get_topic_page(topic)}

        if action == "agentpedia_list_topics":
            rows = agentpedia.list_topics(limit=int(args.get("k") or 200))
            return {"ok": True, "count": len(rows or []), "topics": rows or []}

        if action == "agentpedia_add_facts":
            facts = list(args.get("facts") or [])
            return {"ok": True, "result": agentpedia.add_facts(facts)}

        if action == "agentpedia_grow":
            return {
                "ok": True,
                "result": agentpedia.grow(
                    role=str(args.get("role") or "") or None,
                    interests=list(args.get("interests") or []) or None,
                    max_facts=int(args.get("max_facts") or 2),
                    mode=str(args.get("mode") or "safe"),
                ),
            }

        if action == "agentpedia_stats":
            return {"ok": True, "result": agentpedia.get_agentpedia_stats()}

        return {"ok": False, "error": f"unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"research action failed: {exc}"}


