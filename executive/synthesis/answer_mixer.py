from __future__ import annotations

import re

from workshop.toolbox.stacks.web_core.search_bundle import SearchBundle
from routing.types import QueryPlan, TimeAnchor


_RECENCY_WORDS = re.compile(r"\b(today|current|latest|now)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+(?:[\.,]\d+)?\b")


def _strip_recency_words(text: str) -> str:
    cleaned = _RECENCY_WORDS.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _append_sources(text: str, evidence: SearchBundle | None, limit: int = 2) -> str:
    if not evidence or not evidence.results:
        return text
    src = [f"- {r.title}: {r.url}" for r in evidence.results[:limit]]
    if not src:
        return text
    body = (text or "").rstrip()
    return f"{body}\n\nSources:\n" + "\n".join(src)


def mix_answer(user_text, plan: QueryPlan, llm_draft: str | None, evidence: SearchBundle | None) -> str:
    draft = (llm_draft or "").strip()

    if plan.mode == "LLM_ONLY":
        out = draft
        if plan.time_anchor and not plan.needs_recency:
            if isinstance(plan.time_anchor, TimeAnchor) and plan.time_anchor.year and str(plan.time_anchor.year) not in out:
                out = f"In {plan.time_anchor.year}, {out}" if out else f"In {plan.time_anchor.year}, I don't have enough detail."
            out = _strip_recency_words(out)
        return out

    if evidence and evidence.warnings:
        caution = "Iâ€™m not fully confident because source timing/details are incomplete."
        if draft:
            return f"{caution} {draft}".strip()
        return caution + " Please specify exchange/date if you need exact figures."

    if plan.needs_recency:
        if draft:
            return _append_sources(draft, evidence)
        if evidence and evidence.results:
            lines = [f"- {r.title}\n  {r.url}" for r in evidence.results[:3]]
            return "Hereâ€™s what current sources show:\n" + "\n".join(lines)
        return "I couldn't verify fresh sources right now. Please retry in a moment."

    if draft:
        if plan.time_anchor and not plan.needs_recency:
            draft = _strip_recency_words(draft)
        return _append_sources(draft, evidence)

    if evidence and evidence.results:
        best = evidence.results[0]
        nums = ", ".join(_NUMBER.findall(best.snippet)[:2])
        hint = f" ({nums})" if nums else ""
        return f"Best available source: {best.title}{hint}\n{best.url}"

    return "Iâ€™m uncertain with the available information and donâ€™t want to invent details."


