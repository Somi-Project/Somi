from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from handlers.tool_context import ToolContext


_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "what", "when", "where", "which", "who", "whom",
    "about", "into", "have", "has", "had", "was", "were", "will", "would", "could", "should", "can",
    "you", "your", "our", "they", "them", "their", "there", "then", "than", "just", "more", "info",
    "news", "latest", "today", "tomorrow", "yesterday", "next", "again", "please", "tell", "show", "give",
}

_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
}


@dataclass
class FollowUpResolution:
    action: str
    url: str = ""
    rewritten_query: str = ""
    clarify_options: Optional[List[Dict[str, str]]] = None
    previous_query: str = ""
    context_note: str = ""


class FollowUpResolver:
    def __init__(
        self,
        fuzzy_threshold: float = 0.52,
        margin: float = 0.10,
        title_match_threshold: float = 0.65,
        continuation_threshold: float = 0.22,
    ):
        self.fuzzy_threshold = float(fuzzy_threshold)
        self.margin = float(margin)
        self.title_match_threshold = float(title_match_threshold)
        self.continuation_threshold = float(continuation_threshold)

    # ==================== HELPERS (unchanged from original + improvements) ====================
    def _extract_url(self, text: str) -> str:
        m = re.search(r"https?://\S+", text or "", flags=re.IGNORECASE)
        if not m:
            return ""
        url = m.group(0).rstrip(")],.!?;:")
        try:
            p = urlparse(url)
            if p.scheme in {"http", "https"} and p.netloc:
                return url
        except Exception:
            return ""
        return ""

    def _looks_like_followup(self, text: str) -> bool:
        tl = (text or "").lower()
        return bool(
            re.search(
                r"\b(expand|open|summarize|summarise|tell me more|more details|what happened next|"
                r"that story|this story|the one about|first|second|third|"
                r"link\s*#?\d+|result\s*#?\d+|paper\s*#?\d+|"
                r"elaborate|details about|more on|tell me about|what about|can you expand|"
                r"how about|any updates|any news|updates on|more info|what's next|"
                r"compare|versus|vs|how does|will it|is it|which one|the cheapest|the best|"
                r"previously?|back in|historically?|at that time|then|earlier|before|last time|again|"
                r"tomorrow|next week|next month|yesterday|today|last night|recently|latest)\b",
                tl,
            )
        )

    def _has_temporal_continuation(self, text: str) -> bool:
        tl = (text or "").lower()
        return bool(
            re.search(
                r"\b(previously?|back in|in (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|20[0-2]\d)|"
                r"historically?|at that time|then|last year|this year|earlier|before|"
                r"tomorrow|next|yesterday|today|last night|recently)\b",
                tl,
            )
        )

    def _tokenize(self, text: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}

    def _score(self, query: str, candidate: Dict[str, str]) -> float:
        q = self._tokenize(query)
        c = self._tokenize(f"{candidate.get('title','')} {candidate.get('snippet','')}")
        if not q or not c:
            return 0.0
        return len(q & c) / max(1, len(q | c))

    def _title_reference_score(self, msg: str, title: str) -> float:
        if not title or not msg:
            return 0.0
        t_lower = title.lower()
        m_lower = msg.lower()
        if t_lower in m_lower or m_lower in t_lower:
            return 1.0
        t_tokens = self._tokenize(title)
        m_tokens = self._tokenize(msg)
        overlap = len(t_tokens & m_tokens) / max(1, len(t_tokens))
        return overlap

    def _find_best_title_match(self, msg: str, results: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        best_score = 0.0
        best_item = None
        for item in results:
            score = self._title_reference_score(msg, item.get("title", ""))
            if score > best_score:
                best_score = score
                best_item = item
        return best_item if best_score >= self.title_match_threshold else None

    def _topic_overlap(self, msg: str, last_query: str) -> float:
        if not last_query:
            return 0.0
        q = self._tokenize(msg)
        c = self._tokenize(last_query)
        if not q or not c:
            return 0.0
        return len(q & c) / max(1, len(q | c))

    def _is_brief_followup(self, text: str) -> bool:
        tokens = self._tokenize(text)
        if not tokens or len(tokens) > 5:
            return False
        tl = (text or "").lower()
        return bool(re.search(r"\b(how about|what about|tomorrow|next|updates?|latest|again|then)\b", tl))

    def _content_tokens(self, text: str) -> set[str]:
        return {t for t in self._tokenize(text) if t not in _STOPWORDS}

    def _looks_like_standalone_query(self, msg: str, last_query: str) -> bool:
        """Guardrail: avoid hijacking fresh broad/general questions as follow-ups."""
        if not msg:
            return False
        msg_l = msg.lower().strip()
        if any(k in msg_l for k in ("that", "this", "those", "these", "the one", "result", "link", "story", "again")):
            return False

        question_like = bool(re.match(r"^(who|what|when|where|why|how|is|are|can|could|should|will)\b", msg_l))
        asks_new_search = bool(re.search(r"\b(latest|news|price|weather|forecast|explain|define|compare|trend|happening|update)\b", msg_l))

        msg_tokens = self._content_tokens(msg)
        prev_tokens = self._content_tokens(last_query or "")
        if len(msg_tokens) < 2:
            return False

        overlap = len(msg_tokens & prev_tokens) / max(1, len(msg_tokens | prev_tokens))
        return (question_like or asks_new_search) and overlap < 0.12

    def _ordinal_rank(self, text: str) -> Optional[int]:
        tl = (text or "").lower()
        m = re.search(r"(?:result|link|story|item|number|paper|#)\s*(\d{1,2})\b", tl)
        if m:
            return int(m.group(1))
        m2 = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", tl)
        if m2 and any(k in tl for k in ("result", "link", "story", "item", "paper", "that", "the")):
            return int(m2.group(1))
        for k, v in _ORDINALS.items():
            if re.search(rf"\b{k}\b", tl):
                return v
        return None

    def _build_options(self, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        opts = []
        for item in rows[:5]:
            opts.append(
                {
                    "rank": str(item.get("rank", "")),
                    "title": str(item.get("title", "")),
                    "url": str(item.get("url", "")),
                }
            )
        return opts

    # ==================== MAIN RESOLVE LOGIC ====================
    def resolve(self, user_text: str, ctx: Optional[ToolContext]) -> Optional[FollowUpResolution]:
        if not user_text:
            return None
        msg = user_text.strip()
        if not msg:
            return None

        # 1. Explicit URL (original behaviour)
        explicit = self._extract_url(msg)
        if explicit:
            return FollowUpResolution(
                action="open_url_and_summarize",
                url=explicit,
                rewritten_query=f"summarize this URL: {explicit}",
            )

        if not ctx or not ctx.last_results:
            return None

        # 2. Explicit ordinal (highest priority – unchanged)
        rank = self._ordinal_rank(msg)
        if rank is not None and rank > 0:
            for item in ctx.last_results:
                if int(item.get("rank", 0)) == rank and item.get("url"):
                    return FollowUpResolution(
                        action="open_url_and_summarize",
                        url=str(item.get("url")),
                        rewritten_query=f"summarize this URL: {item.get('url')}",
                    )

        # 3. Strong title reference – PERFECT for news elaboration
        title_match = self._find_best_title_match(msg, ctx.last_results)
        if title_match and title_match.get("url"):
            title = title_match.get("title", "")[:120]
            return FollowUpResolution(
                action="open_url_and_summarize",
                url=str(title_match.get("url")),
                rewritten_query=f"summarize this URL: {title_match.get('url')}",
                previous_query=ctx.last_query,
                context_note=f"news elaboration on: {title}",
            )

        # 4. Strong fuzzy match to any single result
        scored: List[tuple[float, Dict[str, str]]] = []
        for item in ctx.last_results:
            s = self._score(msg, item)
            if s > 0:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)

        if scored:
            best_score, best = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0.0
            if best_score >= self.fuzzy_threshold and (best_score - second_score) >= self.margin and best.get("url"):
                return FollowUpResolution(
                    action="open_url_and_summarize",
                    url=str(best.get("url")),
                    rewritten_query=f"summarize this URL: {best.get('url')}",
                )

        # 5. Natural language / topic / temporal continuation (the magic)
        looks_followup = self._looks_like_followup(msg)
        temporal = self._has_temporal_continuation(msg)
        topic_score = self._topic_overlap(msg, ctx.last_query) if ctx.last_query else 0.0

        is_standalone = self._looks_like_standalone_query(msg, ctx.last_query)

        is_strong_continuation = (looks_followup or temporal) and not is_standalone and (
            topic_score >= self.continuation_threshold or self._is_brief_followup(msg)
        )

        if is_strong_continuation:
            context_prefix = f'Previous query: "{ctx.last_query}"\n'
            if ctx.last_results:
                top = ctx.last_results[0].get("title", "")[:150]
                context_prefix += f"Previous top result: {top}\n"

            enriched = (
                f"{context_prefix}Now answer this follow-up: {msg}\n"
                "Build directly on the previous context and search results."
            )

            return FollowUpResolution(
                action="continue_topic",
                rewritten_query=enriched,
                previous_query=ctx.last_query,
                context_note="natural language continuation",
            )

        # 6. Weak follow-up → show clarification options
        if looks_followup and not is_standalone:
            return FollowUpResolution(
                action="clarify",
                clarify_options=self._build_options([x[1] for x in scored] or list(ctx.last_results)),
            )

        return None
