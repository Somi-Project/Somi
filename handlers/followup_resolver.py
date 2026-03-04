from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from handlers.tool_context import ToolContext


_ORDINALS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "fifth": 5, "5th": 5,
}

_FINANCE_SUBJECT = re.compile(
    r"\b(bitcoin|btc|ethereum|eth|solana|sol|oil|wti|brent|gold|silver|eurusd|gbpusd|usdjpy|forex|fx|apple|tesla|amazon|microsoft|nvidia|aapl|tsla|amzn|msft|nvda)\b",
    re.IGNORECASE,
)
_TEMPORAL = re.compile(
    r"\b((?:19|20)\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\s+(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_STORY_REF = re.compile(r"\b(that story|this story|second one|third one|first one|link\s*#?\d+|result\s*#?\d+)\b", re.IGNORECASE)
_WHAT_ABOUT = re.compile(r"\b(?:what about|and)\s+([a-z0-9\-/ ]{2,80})\??$", re.IGNORECASE)


@dataclass
class FollowUpResolution:
    action: str
    url: str = ""
    rewritten_query: str = ""
    clarify_options: Optional[List[Dict[str, str]]] = None
    previous_query: str = ""
    context_note: str = ""
    selected_index: int = 0
    selected_url: str = ""


class FollowUpResolver:
    def __init__(
        self,
        fuzzy_threshold: float = 0.52,
        margin: float = 0.10,
        title_match_threshold: float = 0.65,
        continuation_threshold: float = 0.25,
    ):
        self.fuzzy_threshold = float(fuzzy_threshold)
        self.margin = float(margin)
        self.title_match_threshold = float(title_match_threshold)
        self.continuation_threshold = float(continuation_threshold)

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

    def is_explicit_reference(self, text: str) -> bool:
        tl = (text or "").lower().strip()
        if not tl:
            return False
        if self._extract_url(tl):
            return True
        return bool(
            re.search(
                r"\b("
                r"result\s*#?\d+|link\s*#?\d+|headline\s*#?\d+|article\s*#?\d+|story\s*#?\d+|item\s*#?\d+|"
                r"the\s+(first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)?)\s+(result|link|headline|article|story|item)|"
                r"expand\s+(?:on\s+)?(?:headline|article|story|result|link)\s*#?\d+|"
                r"summari(?:ze|se)\s+(?:the\s+)?(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth)\s+(?:result|link|headline|article|story|item)"
                r")\b",
                tl,
            )
        )

    def is_mode_switch_explanation(self, text: str) -> bool:
        tl = (text or "").lower().strip()
        if not tl:
            return False
        return bool(
            re.search(
                r"\b("
                r"teach me about|explain|give me an overview|give me a primer|"
                r"what is|how does|help me understand|walk me through|"
                r"break down|intro to|introduction to|basics of|"
                r"tell me about|describe"
                r")\b",
                tl,
            )
        )

    def _looks_like_followup(self, text: str) -> bool:
        tl = (text or "").lower()
        return bool(
            re.search(
                r"\b(expand|open|summarize|summarise|tell me more|more details|what happened next|"
                r"that story|this story|the one about|first|second|third|"
                r"link\s*#?\d+|result\s*#?\d+|paper\s*#?\d+|"
                r"elaborate|details about|more on|tell me about|what about|can you expand|"
                r"how about|any updates|updates on|more info|what's next|"
                r"compare|versus|vs|how does|will it|is it|which one|"
                r"what was|how much was|what was it|how much was it|it was|the price in|"
                r"previously?|back in|historically?|at that time|then|earlier|before|again|in\s+\d{4})\b",
                tl,
            )
        )

    def _has_temporal_continuation(self, text: str) -> bool:
        tl = (text or "").lower()
        return bool(
            re.search(
                r"\b(in (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|20[0-2]\d)|"
                r"previously?|back in|historically?|at that time|then|earlier|before|"
                r"tomorrow|yesterday|last year|this year|\d{4}-\d{2}-\d{2}|in\s+\d{4})\b",
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

    def _extract_quoted_reference(self, text: str) -> str:
        m = re.search(r"[\"']([^\"']{3,140})[\"']", text or "")
        if not m:
            return ""
        return (m.group(1) or "").strip()

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

    def _ordinal_rank(self, text: str) -> Optional[int]:
        tl = (text or "").lower()
        m = re.search(r"(?:result|link|story|item|headline|article|number|paper|#)\s*(\d{1,2})\b", tl)
        if m:
            return int(m.group(1))
        m2 = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", tl)
        if m2 and any(k in tl for k in ("result", "link", "story", "item", "headline", "article", "paper", "that", "the")):
            return int(m2.group(1))
        for k, v in _ORDINALS.items():
            if re.search(rf"\b{k}\b", tl):
                return v
        return None

    def _build_options(self, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        opts = []
        for item in rows[:5]:
            opts.append({
                "rank": str(item.get("rank", "")),
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
            })
        return opts

    def _extract_subject(self, text: str) -> str:
        raw = text or ""
        ticker_m = re.search(r"\(([A-Z]{1,5})\)", raw)
        if ticker_m:
            return ticker_m.group(1).upper()

        m = _FINANCE_SUBJECT.search(raw)
        if not m:
            return ""
        v = m.group(1)
        vl = v.lower()
        if vl == "btc":
            return "bitcoin"
        if vl == "eth":
            return "ethereum"
        return vl

    def _extract_temporal_constraint(self, text: str) -> str:
        m = _TEMPORAL.search(text or "")
        return (m.group(1) if m else "").strip()

    def _rewrite_followup_query(self, msg: str, ctx: ToolContext) -> str:
        raw = (msg or "").strip()
        msg_l = raw.lower()
        last_query = str(ctx.last_query or "").strip()

        subject_from_ctx = self._extract_subject(last_query)
        subject_from_msg = self._extract_subject(raw)
        temporal = self._extract_temporal_constraint(raw)

        wm = _WHAT_ABOUT.search(raw)
        if wm:
            candidate = (wm.group(1) or "").strip(" ?.,")
            if candidate and len(candidate.split()) <= 5 and not re.search(r"\b(it|that|this|one)\b", candidate, re.I):
                if temporal:
                    return f"{candidate} price {temporal}".strip()
                return f"{candidate} price".strip()

        subject = subject_from_msg or subject_from_ctx

        if temporal:
            if subject:
                if "price" in msg_l or "price" in last_query.lower() or ctx.last_tool_type == "finance":
                    return f"{subject} price {temporal}".strip()
                return f"{subject} {temporal}".strip()
            return f"{raw} {temporal}".strip()

        if subject and ("price" in msg_l or ctx.last_tool_type == "finance"):
            return f"{subject} price".strip()

        if subject:
            return subject

        if _STORY_REF.search(raw) and ctx.last_selected_title:
            return str(ctx.last_selected_title).strip()

        return raw or last_query

    def _open_resolution_from_item(self, item: Dict[str, str], *, previous_query: str = "", context_note: str = "") -> FollowUpResolution:
        url = str(item.get("url") or "")
        rank = int(item.get("rank") or 0)
        return FollowUpResolution(
            action="open_url_and_summarize",
            url=url,
            rewritten_query=f"summarize this URL: {url}",
            previous_query=previous_query,
            context_note=context_note,
            selected_index=rank,
            selected_url=url,
        )

    def resolve(self, user_text: str, ctx: Optional[ToolContext]) -> Optional[FollowUpResolution]:
        if not user_text:
            return None
        msg = user_text.strip()
        if not msg:
            return None

        explicit = self._extract_url(msg)
        if explicit:
            return FollowUpResolution(
                action="open_url_and_summarize",
                url=explicit,
                rewritten_query=f"summarize this URL: {explicit}",
            )

        if not ctx or not ctx.last_results:
            return None

        if self.is_mode_switch_explanation(msg) and not self.is_explicit_reference(msg):
            return None

        rank = self._ordinal_rank(msg)
        if rank is not None and rank > 0:
            for item in ctx.last_results:
                if int(item.get("rank", 0)) == rank and item.get("url"):
                    return self._open_resolution_from_item(item)

        quoted_ref = self._extract_quoted_reference(msg)
        if quoted_ref:
            quoted_match = self._find_best_title_match(quoted_ref, ctx.last_results)
            if quoted_match and quoted_match.get("url"):
                return self._open_resolution_from_item(quoted_match, previous_query=ctx.last_query, context_note="quoted_title_match")

        title_match = self._find_best_title_match(msg, ctx.last_results)
        if title_match and title_match.get("url"):
            return self._open_resolution_from_item(title_match, previous_query=ctx.last_query, context_note="title_match")

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
                return self._open_resolution_from_item(best)

        if _STORY_REF.search(msg) and len(ctx.last_results) > 1:
            return FollowUpResolution(
                action="clarify",
                clarify_options=self._build_options([x[1] for x in scored] or list(ctx.last_results)),
            )

        looks_followup = self._looks_like_followup(msg)
        temporal = self._has_temporal_continuation(msg)
        topic_score = self._topic_overlap(msg, ctx.last_query) if ctx.last_query else 0.0
        if looks_followup or temporal or (topic_score >= self.continuation_threshold):
            rewritten = self._rewrite_followup_query(msg, ctx)
            return FollowUpResolution(
                action="rewrite_query",
                rewritten_query=rewritten,
                previous_query=ctx.last_query,
                context_note="rewrite_query_from_context",
            )

        return None
