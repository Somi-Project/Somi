# promptforge.py
# PromptForge: lightweight context builder for Somi
# Adds deterministic budget enforcement (approx tokens) to respect MAX_CONTEXT_TOKENS
# without needing a tokenizer dependency.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.settings import MAX_CONTEXT_TOKENS


@dataclass
class PromptForge:
    workspace: str = "."

    # -----------------------------
    # Token budgeting (approximate)
    # -----------------------------
    def _estimate_tokens(self, text: str) -> int:
        """
        Rough, stable estimate: ~4 chars/token (English-ish).
        Safer than nothing and avoids tokenizer deps.
        """
        if not text:
            return 0
        return max(1, int(len(text) / 4))

    def _trim_to_chars(self, text: str, max_chars: int, suffix: str = "\n...[truncated]") -> str:
        if not text:
            return ""
        t = text.strip()
        if len(t) <= max_chars:
            return t
        keep = max(0, max_chars - len(suffix))
        return (t[:keep].rstrip() + suffix).strip()

    def _trim_to_token_budget(self, text: str, budget_tokens: int) -> str:
        """
        Trim by chars based on token estimate. Keeps deterministic behavior.
        """
        if not text:
            return ""
        if budget_tokens <= 0:
            return ""
        est = self._estimate_tokens(text)
        if est <= budget_tokens:
            return text.strip()

        max_chars = max(64, int(budget_tokens * 4))
        return self._trim_to_chars(text, max_chars=max_chars)

    def _assemble_system_prompt(
        self,
        identity_block: str,
        current_time: str,
        memory_context: str,
        search_context: str,
        mode_context: str,
        extra_blocks: Optional[List[str]],
    ) -> str:
        parts: List[str] = []

        parts.append(identity_block.strip())
        parts.append(f"## Current Time\n{current_time}".strip())
        parts.append(f"## Mode\n{mode_context}".strip())

        # Memory + Search always present for stable structure
        parts.append("## Memory Context\n" + (memory_context.strip() if memory_context else "None"))
        parts.append("## Web/Search Context\n" + (search_context.strip() if search_context else "None"))

        if extra_blocks:
            for b in extra_blocks:
                if b and b.strip():
                    parts.append(b.strip())

        parts.append(
            "\n".join(
                [
                    "## Output Rules",
                    "- If Memory Context contains relevant facts/preferences/instructions, use them.",
                    "- Do NOT treat Web/Search Context as authoritative unless it contains direct results (it may be empty).",
                    "- If you are unsure, say you are unsure rather than inventing details.",
                    "- Be practical and direct.",
                ]
            )
        )

        return "\n\n---\n\n".join(parts).strip()

    def build_system_prompt(
        self,
        identity_block: str,
        current_time: str,
        memory_context: str,
        search_context: str,
        mode_context: str = "Normal mode.",
        extra_blocks: Optional[List[str]] = None,
    ) -> str:
        # Note: final budget enforcement happens in build_messages()
        return self._assemble_system_prompt(
            identity_block=identity_block,
            current_time=current_time,
            memory_context=memory_context,
            search_context=search_context,
            mode_context=mode_context,
            extra_blocks=extra_blocks,
        )

    def _budget_system_prompt(
        self,
        system_prompt: str,
        *,
        user_prompt: str,
        history: Optional[List[Dict[str, Any]]],
        max_context_tokens: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Enforce a hard-ish context cap by trimming:
        1) Old history first
        2) Oversized system prompt (which includes Memory/Search/Extra blocks)
        We keep the user prompt always; we do NOT trim user prompt here.
        """

        reserve_for_user = max(48, self._estimate_tokens(user_prompt) + 24)

        msgs_history: List[Dict[str, Any]] = []
        if history:
            for m in history:
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                content = m.get("content")
                if role in ("user", "assistant", "system") and isinstance(content, str) and content.strip():
                    msgs_history.append({"role": role, "content": content.strip()})

        sys_text = system_prompt.strip()
        sys_tokens = self._estimate_tokens(sys_text)

        remaining = max_context_tokens - reserve_for_user
        if remaining < 120:
            remaining = 120

        # If system prompt is too large, trim it first.
        if sys_tokens > int(remaining * 0.70):
            sys_budget = int(remaining * 0.70)
            sys_text = self._trim_to_token_budget(sys_text, sys_budget)
            sys_tokens = self._estimate_tokens(sys_text)

        history_budget = max(0, remaining - sys_tokens)
        if history_budget <= 0 or not msgs_history:
            return sys_text, []

        # Keep newest history first; drop oldest until it fits.
        kept: List[Dict[str, Any]] = []
        used = 0
        for m in reversed(msgs_history):
            mt = self._estimate_tokens(m["content"])
            if used + mt > history_budget:
                continue
            kept.append(m)
            used += mt

        kept.reverse()
        return sys_text, kept

    def build_messages(
        self,
        system_prompt: str,
        history: Optional[List[Dict[str, Any]]],
        user_prompt: str,
    ) -> List[Dict[str, Any]]:
        user_prompt = (user_prompt or "").strip()
        system_prompt = (system_prompt or "").strip()

        max_tokens = int(MAX_CONTEXT_TOKENS) if isinstance(MAX_CONTEXT_TOKENS, int) else 8192
        max_tokens = max(1024, max_tokens)

        sys_text, kept_history = self._budget_system_prompt(
            system_prompt,
            user_prompt=user_prompt,
            history=history,
            max_context_tokens=max_tokens,
        )

        msgs: List[Dict[str, Any]] = [{"role": "system", "content": sys_text}]
        for m in kept_history:
            msgs.append(m)

        msgs.append({"role": "user", "content": user_prompt})
        return msgs
