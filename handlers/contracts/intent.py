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
        text_raw = (user_text or "").strip()
        text = text_raw.lower()
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
        meeting_score = self._score_meeting_summary(text, text_raw)
        decision_score = self._score_decision_matrix(text, text_raw)

        scored = [
            ("research_brief", research_score),
            ("doc_extract", doc_score),
            ("plan", plan_score),
            ("meeting_summary", meeting_score),
            ("decision_matrix", decision_score),
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_type, best_score = scored[0]

        if best_score < self.threshold:
            return ArtifactIntentDecision(None, float(best_score), f"below_threshold:{best_type}")

        # hard gate: doc_extract requires document context
        if best_type == "doc_extract" and not has_doc:
            return ArtifactIntentDecision(None, float(best_score), "doc_extract_blocked_no_doc_context")

        # hard gate: meeting summary requires stronger evidence + enough length
        if best_type == "meeting_summary":
            if len(text_raw) < 80:
                return ArtifactIntentDecision(None, float(best_score), "meeting_summary_blocked_too_short")
            if not self._meeting_trigger_eligible(text, text_raw):
                return ArtifactIntentDecision(None, float(best_score), "meeting_summary_blocked_missing_signals")

        # hard gate: decision matrix requires at least 2 options
        if best_type == "decision_matrix":
            if self._detect_option_count(text_raw) < 2:
                return ArtifactIntentDecision(None, float(best_score), "decision_matrix_blocked_insufficient_options")

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

    def _meeting_trigger_eligible(self, text: str, text_raw: str) -> bool:
        explicit = bool(
            re.search(
                r"\b(summarize (these )?meeting notes|summarize (this )?transcript|meeting notes|meeting minutes|minutes of meeting|\bmom\b|transcript)\b",
                text,
            )
        )
        transcript_like = bool(
            re.search(r"\b\d{1,2}:\d{2}\b", text_raw)
            or re.search(r"(^|\n)\s*[A-Z][A-Za-z0-9 _-]{1,24}:\s+", text_raw)
        ) and len(text_raw.splitlines()) >= 3
        section_hits = sum(
            1
            for marker in ["agenda:", "attendees:", "action items:", "decisions:", "next steps:"]
            if marker in text
        )
        return explicit or transcript_like or section_hits >= 2

    def _score_meeting_summary(self, text: str, text_raw: str) -> float:
        if len(text_raw) < 80:
            return 0.0
        score = 0.0
        if self._meeting_trigger_eligible(text, text_raw):
            score += 0.66
        if re.search(r"\b(meeting|minutes|transcript|attendees|agenda|action items|decisions)\b", text):
            score += 0.2
        if len(text_raw.splitlines()) >= 4:
            score += 0.1
        return min(score, 0.99)

    def _detect_option_count(self, text_raw: str) -> int:
        lines = [ln.strip() for ln in text_raw.splitlines() if ln.strip()]
        explicit_opts = []
        for ln in lines:
            if re.match(r"^(?:[-*]|\d+[.)]|option\s+[a-z0-9])\s+", ln, flags=re.IGNORECASE):
                explicit_opts.append(ln)
        if len(explicit_opts) >= 2:
            return len(explicit_opts)

        vs_match = re.search(r"between\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:[?.!,]|$)", text_raw, flags=re.IGNORECASE)
        if vs_match:
            return 2
        return 0

    def _score_decision_matrix(self, text: str, text_raw: str) -> float:
        score = 0.0
        option_count = self._detect_option_count(text_raw)
        framework_ask = bool(
            re.search(
                r"\b(help me decide|decision matrix|weighted criteria|which should i choose|compare .* vs .*|compare .* versus .*|compare .* and .* for me)\b",
                text,
            )
        )
        criteria_signals = bool(re.search(r"\b(criteria|weights?|score|trade[- ]?off|matrix|rank)\b", text))

        if framework_ask:
            score += 0.55
        if option_count >= 2:
            score += 0.32
        if criteria_signals:
            score += 0.12

        if option_count < 2:
            return 0.0
        return max(0.0, min(score, 0.99))
