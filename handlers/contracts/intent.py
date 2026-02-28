from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

PRECEDENCE = [
    "meeting_summary",
    "action_items",
    "decision_matrix",
    "status_update",
    "research_brief",
    "doc_extract",
    "plan",
]


@dataclass
class ArtifactIntentDecision:
    artifact_intent: Optional[str]
    confidence: float
    reason: str
    trigger_reason: Dict[str, Any] = field(default_factory=dict)


class ArtifactIntentDetector:
    def __init__(self, threshold: float = 0.75):
        self.threshold = float(threshold)

    def detect(self, user_text: str, route: str, *, has_doc: bool = False) -> ArtifactIntentDecision:
        text_raw = (user_text or "").strip()
        text = text_raw.lower()
        route = (route or "").strip().lower()

        if route in {"command", "local_memory_intent", "conversion_tool"}:
            return ArtifactIntentDecision(None, 0.0, f"route_blocked:{route}")
        if len(text) < 12:
            return ArtifactIntentDecision(None, 0.0, "too_short")
        if re.search(r"^(hi|hello|hey|yo|sup|how are you|good morning|good night)[!. ]*$", text):
            return ArtifactIntentDecision(None, 0.0, "smalltalk")

        candidates: Dict[str, Dict[str, Any]] = {
            "meeting_summary": self._meeting_evidence(text, text_raw),
            "action_items": self._action_items_evidence(text, text_raw),
            "decision_matrix": self._decision_evidence(text, text_raw),
            "status_update": self._status_evidence(text),
            "research_brief": self._research_evidence(text, route),
            "doc_extract": self._doc_evidence(text, has_doc),
            "plan": self._plan_evidence(text),
        }

        explicit = [k for k, v in candidates.items() if v["explicit_request"] and v["eligible"]]
        ordered = [k for k in PRECEDENCE if k in explicit] if explicit else [k for k in PRECEDENCE if candidates[k]["eligible"]]
        if not ordered:
            return ArtifactIntentDecision(None, 0.0, "below_threshold:none")

        selected = ordered[0]
        tie_break = None
        if len(ordered) > 1:
            tie_break = f"precedence:{' > '.join(ordered)}"
        ev = candidates[selected]
        conf = float(ev["score"])
        if conf < self.threshold:
            return ArtifactIntentDecision(None, conf, f"below_threshold:{selected}")

        trigger_reason = {
            "explicit_request": bool(ev["explicit_request"]),
            "matched_phrases": ev["matched_phrases"],
            "structural_signals": ev["structural_signals"],
            "tie_break": tie_break,
        }
        return ArtifactIntentDecision(selected, conf, f"best:{selected}", trigger_reason=trigger_reason)

    def _meeting_evidence(self, text: str, text_raw: str) -> Dict[str, Any]:
        phrases = []
        explicit = bool(re.search(r"\b(meeting summary|meeting minutes|summarize (this )?transcript|summarize meeting notes)\b", text))
        if explicit:
            phrases.append("meeting_summary_request")
        structure = []
        if re.search(r"\b\d{1,2}:\d{2}\b", text_raw):
            structure.append("timestamps")
        if re.search(r"(^|\n)\s*[A-Z][A-Za-z0-9 _-]{1,24}:\s+", text_raw):
            structure.append("speaker_labels")
        for marker, signal in [("attendees:", "attendees_heading"), ("asistentes:", "attendees_heading_es"), ("agenda:", "agenda_heading"), ("decisions:", "decisions_heading"), ("decisiones:", "decisions_heading_es")]:
            if marker in text:
                structure.append(signal)
        line_count = len([ln for ln in text_raw.splitlines() if ln.strip()])
        eligible = explicit or len(structure) >= 2 or ("timestamps" in structure and line_count >= 3)
        return {"eligible": eligible, "score": 0.93 if explicit else (0.82 if eligible else 0.0), "explicit_request": explicit, "matched_phrases": phrases, "structural_signals": structure}

    def _action_items_evidence(self, text: str, text_raw: str) -> Dict[str, Any]:
        phrases = []
        explicit = bool(re.search(r"\b(extract action items|action items only|extract todos|extract to[- ]?dos|next steps list)\b", text))
        if explicit:
            phrases.append("action_items_request")
        structure = []
        for marker, signal in [("action items:", "action_items_heading"), ("todo:", "todo_heading"), ("next steps:", "next_steps_heading"), ("assigned to:", "assigned_to_heading"), ("tareas:", "action_items_heading_es"), ("próximos pasos:", "next_steps_heading_es"), ("proximos pasos:", "next_steps_heading_es")]:
            if marker in text:
                structure.append(signal)
        eligible = explicit or len(structure) >= 1
        return {"eligible": eligible, "score": 0.9 if explicit else (0.8 if eligible else 0.0), "explicit_request": explicit, "matched_phrases": phrases, "structural_signals": structure}

    def _decision_evidence(self, text: str, text_raw: str) -> Dict[str, Any]:
        framework = bool(re.search(r"\b(help me decide|decision matrix|which should i choose|compare .* (and|vs|versus) .*)\b", text))
        phrases = ["decision_request"] if framework else []
        options = 2 if re.search(r"between\s+.+\s+(and|vs\.?|versus)\s+.+", text_raw, flags=re.IGNORECASE) else 0
        options += len([1 for ln in text_raw.splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)]|option\s+[a-z0-9])\s+", ln, flags=re.IGNORECASE)])
        structure = ["options_detected"] if options >= 2 else []
        eligible = framework and options >= 2
        return {"eligible": eligible, "score": 0.88 if eligible else 0.0, "explicit_request": framework, "matched_phrases": phrases, "structural_signals": structure}

    def _status_evidence(self, text: str) -> Dict[str, Any]:
        explicit = bool(re.search(r"\b(status update|standup update|weekly update|write a standup|actualizacion de estado|actualización de estado)\b", text))
        phrases = ["status_update_request"] if explicit else []
        structure = []
        for marker, signal in [("done:", "done_heading"), ("doing:", "doing_heading"), ("blocked:", "blocked_heading"), ("hecho:", "done_heading_es"), ("haciendo:", "doing_heading_es"), ("bloqueado:", "blocked_heading_es")]:
            if marker in text:
                structure.append(signal)
        eligible = explicit or len(structure) >= 3
        return {"eligible": eligible, "score": 0.86 if explicit else (0.8 if eligible else 0.0), "explicit_request": explicit, "matched_phrases": phrases, "structural_signals": structure}

    def _research_evidence(self, text: str, route: str) -> Dict[str, Any]:
        explicit = bool(re.search(r"\b(research brief|research .* with citations|with citations|source-backed)\b", text))
        phrases = ["research_request"] if explicit else []
        score = 0.0
        if explicit:
            score += 0.82
        if route == "websearch":
            score += 0.1
        return {"eligible": explicit or score >= 0.8, "score": min(score, 0.95), "explicit_request": explicit, "matched_phrases": phrases, "structural_signals": []}

    def _doc_evidence(self, text: str, has_doc: bool) -> Dict[str, Any]:
        explicit = bool(re.search(r"\b(doc extract|extract from (the )?(document|pdf)|summarize this doc)\b", text))
        phrases = ["doc_extract_request"] if explicit else []
        eligible = explicit and has_doc
        return {"eligible": eligible, "score": 0.85 if eligible else 0.0, "explicit_request": explicit, "matched_phrases": phrases, "structural_signals": ["document_context"] if has_doc else []}

    def _plan_evidence(self, text: str) -> Dict[str, Any]:
        explicit = bool(re.search(r"\b(plan|checklist|roadmap|next steps)\b", text))
        phrases = ["plan_request"] if explicit else []
        educational = bool(re.search(r"\b(steps of|what is|explain)\b", text))
        personal = bool(re.search(r"\b(i need|help me|for me|my goal|my)\b", text))
        eligible = explicit and personal and not educational
        return {"eligible": eligible, "score": 0.82 if eligible else 0.0, "explicit_request": explicit, "matched_phrases": phrases, "structural_signals": ["task_intent"] if personal else []}
