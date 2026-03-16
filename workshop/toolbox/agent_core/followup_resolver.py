from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from workshop.toolbox.agent_core.tool_context import ToolContext


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

_EXPLICIT_REF_RE = re.compile(
    r"\b("
    r"open\s*#?\d+|"
    r"result\s*#?\d+|link\s*#?\d+|headline\s*#?\d+|article\s*#?\d+|story\s*#?\d+|item\s*#?\d+|"
    r"open\s+(?:the\s+)?(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth)\b|"
    r"the\s+(first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)?)\s+(result|link|headline|article|story|item)|"
    r"expand\s+(?:on\s+)?(?:headline|article|story|result|link)\s*#?\d+|"
    r"summari(?:ze|se)\s+(?:the\s+)?(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth)\s+(?:result|link|headline|article|story|item)|"
    r"that\s+story|this\s+story"
    r")\b",
    re.IGNORECASE,
)


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
    """Explicit-reference resolver only.

    This intentionally avoids fuzzy/semantic query rewriting so normal
    context retention remains the primary follow-up mechanism.
    """

    def __init__(
        self,
        fuzzy_threshold: float = 0.52,
        margin: float = 0.10,
        title_match_threshold: float = 0.65,
        continuation_threshold: float = 0.25,
    ):
        # Kept for backward compatibility with existing constructor calls.
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

    def _extract_quoted_reference(self, text: str) -> str:
        m = re.search(r"[\"']([^\"']{3,160})[\"']", text or "")
        if not m:
            return ""
        return (m.group(1) or "").strip()

    def _ordinal_rank(self, text: str) -> Optional[int]:
        tl = (text or "").lower()
        m = re.search(r"(?:open|result|link|story|item|headline|article|number|paper|#)\s*(\d{1,2})\b", tl)
        if m:
            return int(m.group(1))
        m2 = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", tl)
        if m2 and any(k in tl for k in ("open", "result", "link", "story", "item", "headline", "article", "paper", "that", "the")):
            return int(m2.group(1))
        for k, v in _ORDINALS.items():
            if re.search(rf"\b{k}\b", tl):
                return v
        return None

    def _build_options(self, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        opts: List[Dict[str, str]] = []
        for item in rows[:5]:
            opts.append(
                {
                    "rank": str(item.get("rank", "")),
                    "title": str(item.get("title", "")),
                    "url": str(item.get("url", "")),
                }
            )
        return opts

    def _open_resolution_from_item(
        self,
        item: Dict[str, str],
        *,
        previous_query: str = "",
        context_note: str = "",
    ) -> FollowUpResolution:
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

    def is_explicit_reference(self, text: str) -> bool:
        tl = (text or "").strip().lower()
        if not tl:
            return False
        if self._extract_url(tl):
            return True
        return bool(_EXPLICIT_REF_RE.search(tl) or self._extract_quoted_reference(tl))

    def resolve(self, user_text: str, ctx: Optional[ToolContext]) -> Optional[FollowUpResolution]:
        msg = (user_text or "").strip()
        if not msg:
            return None

        explicit_url = self._extract_url(msg)
        if explicit_url:
            return FollowUpResolution(
                action="open_url_and_summarize",
                url=explicit_url,
                rewritten_query=f"summarize this URL: {explicit_url}",
            )

        if not ctx or not ctx.last_results:
            return None
        if not self.is_explicit_reference(msg):
            return None

        rank = self._ordinal_rank(msg)
        if rank is not None and rank > 0:
            for item in ctx.last_results:
                if int(item.get("rank", 0)) == rank and item.get("url"):
                    return self._open_resolution_from_item(item, previous_query=ctx.last_query, context_note="rank_reference")

        quoted_ref = self._extract_quoted_reference(msg).lower()
        if quoted_ref:
            for item in ctx.last_results:
                title = str(item.get("title") or "").lower()
                if title and (quoted_ref in title or title in quoted_ref):
                    if item.get("url"):
                        return self._open_resolution_from_item(item, previous_query=ctx.last_query, context_note="quoted_title_reference")

        msg_l = msg.lower()
        if any(k in msg_l for k in ("that story", "this story", "that article", "this article")):
            if ctx.last_selected_url:
                return FollowUpResolution(
                    action="open_url_and_summarize",
                    url=str(ctx.last_selected_url),
                    rewritten_query=f"summarize this URL: {ctx.last_selected_url}",
                    previous_query=ctx.last_query,
                    context_note="selected_story_reference",
                    selected_index=int(ctx.last_selected_index or 0),
                    selected_url=str(ctx.last_selected_url),
                )

        if len(ctx.last_results) == 1 and ctx.last_results[0].get("url"):
            return self._open_resolution_from_item(
                ctx.last_results[0],
                previous_query=ctx.last_query,
                context_note="single_result_fallback",
            )

        return FollowUpResolution(
            action="clarify",
            clarify_options=self._build_options(list(ctx.last_results)),
            previous_query=ctx.last_query,
            context_note="ambiguous_explicit_reference",
        )
