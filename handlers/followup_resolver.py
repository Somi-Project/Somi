from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from handlers.tool_context import ToolContext


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


class FollowUpResolver:
    def __init__(self, fuzzy_threshold: float = 0.58, margin: float = 0.1):
        self.fuzzy_threshold = float(fuzzy_threshold)
        self.margin = float(margin)

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
                r"\b(expand|open|summarize|summarise|tell me more|more details|what happened next|that story|this story|"
                r"the one about|first|second|third|link\s*#?\d+|result\s*#?\d+|paper\s*#?\d+)\b",
                tl,
            )
        )

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

    def _tokenize(self, text: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}

    def _score(self, query: str, candidate: Dict[str, str]) -> float:
        q = self._tokenize(query)
        c = self._tokenize(f"{candidate.get('title','')} {candidate.get('snippet','')}")
        if not q or not c:
            return 0.0
        return len(q & c) / max(1, len(q | c))

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

        rank = self._ordinal_rank(msg)
        if rank is not None and rank > 0:
            for item in ctx.last_results:
                if int(item.get("rank", 0)) == rank and item.get("url"):
                    return FollowUpResolution(
                        action="open_url_and_summarize",
                        url=str(item.get("url")),
                        rewritten_query=f"summarize this URL: {item.get('url')}",
                    )

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

            # Clarify not only near-tie: also when follow-up-like phrasing is present but confidence is weak.
            if self._looks_like_followup(msg):
                if (best_score < self.fuzzy_threshold) or (len(scored) > 1 and abs(best_score - second_score) < self.margin):
                    return FollowUpResolution(action="clarify", clarify_options=self._build_options([x[1] for x in scored]))

        # If user clearly asks a follow-up but no fuzzy score hit, offer ranked options from last results.
        if self._looks_like_followup(msg):
            return FollowUpResolution(action="clarify", clarify_options=self._build_options(list(ctx.last_results)))

        return None
