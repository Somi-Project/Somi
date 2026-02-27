from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ArtifactIntentDecision:
    artifact_intent: Optional[str]
    confidence: float
    reason: str


class ArtifactIntentDetector:
    def __init__(self, threshold: float = 0.75):
        self.threshold = float(threshold)

    def detect(self, user_text: str, route: str, *, has_doc: bool = False) -> ArtifactIntentDecision:
        text = (user_text or "").strip().lower()
        route = (route or "").strip().lower()

        # Never trigger artifacts on deterministic command/tool routing paths.
        if route in {"command", "local_memory_intent", "conversion_tool"}:
            return ArtifactIntentDecision(None, 0.0, f"route_blocked:{route}")

        if len(text) < 12:
            return ArtifactIntentDecision(None, 0.0, "too_short")

        if re.search(r"^(hi|hello|hey|yo|sup|how are you|good morning|good night)[!. ]*$", text):
            return ArtifactIntentDecision(None, 0.0, "smalltalk")

        research_score = self._score_research(text, route)
        doc_score = self._score_doc(text, route, has_doc)
        plan_score = self._score_plan(text, route)

        scored = [
            ("research_brief", research_score),
            ("doc_extract", doc_score),
            ("plan", plan_score),
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_type, best_score = scored[0]

        if best_score < self.threshold:
            return ArtifactIntentDecision(None, float(best_score), f"below_threshold:{best_type}")

        # hard gate: doc_extract requires document context
        if best_type == "doc_extract" and not has_doc:
            return ArtifactIntentDecision(None, float(best_score), "doc_extract_blocked_no_doc_context")

        return ArtifactIntentDecision(best_type, float(best_score), f"best:{best_type}")

    def _score_research(self, text: str, route: str) -> float:
        score = 0.0
        if route == "websearch":
            score += 0.45
        if re.search(r"\b(citations?|sources?|evidence|consensus|pros and cons|compare|synthesize|synthesis)\b", text):
            score += 0.35
        if re.search(r"\b(research brief|briefing|literature|state of the art|what do studies say)\b", text):
            score += 0.25
        if re.search(r"\b(news|latest|today)\b", text):
            score += 0.05
        return min(score, 0.99)

    def _score_doc(self, text: str, route: str, has_doc: bool) -> float:
        score = 0.0
        if has_doc:
            score += 0.45
        if re.search(r"\b(document|pdf|file|page|section|extract|summarize this doc|from the doc)\b", text):
            score += 0.35
        if re.search(r"\b(table|fields|values|page ref|quote)\b", text):
            score += 0.15
        if route == "llm_only" and has_doc:
            score += 0.05
        return min(score, 0.99)

    def _score_plan(self, text: str, route: str) -> float:
        score = 0.0
        personal = bool(re.search(r"\b(i need|help me|for me|my|i want|i'm|im|my goal|my plan)\b", text))
        memory_profile_only = bool(re.search(r"\b(my name is|remember this|what do you remember|my favorite)\b", text))
        action = bool(re.search(r"\b(plan|roadmap|steps|schedule|organize|next steps|action plan|todo)\b", text))

        if personal:
            score += 0.35
        if action:
            score += 0.35
        if route == "llm_only":
            score += 0.1
        if re.search(r"\b(today|this week|this month|deadline|priority)\b", text):
            score += 0.1

        # hard personalization requirement for plan
        if not personal or memory_profile_only:
            return 0.0
        return min(score, 0.99)
