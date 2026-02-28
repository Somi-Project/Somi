from __future__ import annotations

from typing import Any, Dict

from handlers.contracts.envelopes import to_doc_envelope, to_llm_envelope, to_search_envelope
from handlers.contracts.pipelines import (
    build_decision_matrix,
    build_doc_extract,
    build_meeting_summary,
    build_plan,
    build_plan_revision,
    build_research_brief,
)
from handlers.contracts.schemas import MARKDOWN_RENDERERS, STRICT_VALIDATORS


class ArtifactBuildError(ValueError):
    pass


def build_artifact_for_intent(
    *,
    artifact_intent: str,
    query: str,
    route: str,
    answer_text: str,
    raw_search_results: list[dict] | None = None,
    rag_block: str | None = None,
    min_sources: int = 3,
    previous_plan: Dict[str, Any] | None = None,
    new_constraints: list[str] | None = None,
) -> Dict[str, Any]:
    if artifact_intent == "research_brief":
        env = to_search_envelope(answer_text, raw_search_results)
        if len(env.sources) < int(min_sources):
            raise ArtifactBuildError(f"insufficient_sources:{len(env.sources)}<{int(min_sources)}")
        return build_research_brief(query=query, route=route, envelope=env, min_sources=min_sources)
    if artifact_intent == "doc_extract":
        env = to_doc_envelope(answer_text, rag_block)
        if not env.chunks and not env.page_refs:
            raise ArtifactBuildError("insufficient_doc_context")
        return build_doc_extract(query=query, route=route, envelope=env)
    if artifact_intent == "plan":
        if previous_plan:
            return build_plan_revision(
                query=query,
                route=route,
                previous_plan=previous_plan,
                new_constraints=list(new_constraints or []),
            )
        env = to_llm_envelope(answer_text)
        return build_plan(query=query, route=route, envelope=env)
    if artifact_intent == "meeting_summary":
        doc_env = to_doc_envelope(answer_text, rag_block)
        env = to_llm_envelope(answer_text)
        return build_meeting_summary(query=query, route=route, envelope=env, doc_envelope=doc_env)
    if artifact_intent == "decision_matrix":
        env = to_llm_envelope(answer_text)
        art = build_decision_matrix(query=query, route=route, envelope=env)
        if len(list(art.get("content", {}).get("options") or [])) < 2:
            raise ArtifactBuildError("insufficient_options")
        return art
    raise ValueError(f"Unsupported artifact intent: {artifact_intent}")


def validate_and_render(artifact: Dict[str, Any]) -> str:
    t = str(artifact.get("artifact_type") or "")
    validator = STRICT_VALIDATORS.get(t)
    renderer = MARKDOWN_RENDERERS.get(t)
    if not validator or not renderer:
        raise ValueError(f"No validator/renderer for type={t}")
    validator(artifact)
    return renderer(artifact)
