from __future__ import annotations

from typing import Any, Dict, Optional

from handlers.contracts.envelopes import to_doc_envelope, to_llm_envelope, to_search_envelope
from handlers.contracts.pipelines import build_doc_extract, build_plan, build_research_brief
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
        env = to_llm_envelope(answer_text)
        return build_plan(query=query, route=route, envelope=env)
    raise ValueError(f"Unsupported artifact intent: {artifact_intent}")


def validate_and_render(artifact: Dict[str, Any]) -> str:
    t = str(artifact.get("artifact_type") or "")
    validator = STRICT_VALIDATORS.get(t)
    renderer = MARKDOWN_RENDERERS.get(t)
    if not validator or not renderer:
        raise ValueError(f"No validator/renderer for type={t}")
    validator(artifact)
    return renderer(artifact)
