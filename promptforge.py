# promptforge.py
# PromptForge: lightweight context builder for Somi

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from config.settings import MAX_CONTEXT_TOKENS
from handlers.prompting.blocks import PromptBlock
from handlers.prompting.builder import apply_budgets, render_blocks
from handlers.prompting.budget import estimate_tokens
from handlers.prompting.firewall import apply_evidence_firewall
from handlers.prompting.kernel import build_kernel_v1_1
from handlers.prompting.persona import load_persona_text
from handlers.prompting.policies import build_policy_pack
from handlers.prompting.snapshot import write_prompt_snapshot


@dataclass
class PromptForge:
    workspace: str = "."

    def _estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def _trim_to_chars(self, text: str, max_chars: int, suffix: str = "\n...[truncated]") -> str:
        if not text:
            return ""
        t = text.strip()
        if len(t) <= max_chars:
            return t
        keep = max(0, max_chars - len(suffix))
        return (t[:keep].rstrip() + suffix).strip()

    def _trim_to_token_budget(self, text: str, budget_tokens: int) -> str:
        if not text:
            return ""
        if budget_tokens <= 0:
            return ""
        est = self._estimate_tokens(text)
        if est <= budget_tokens:
            return text.strip()

        max_chars = max(64, int(budget_tokens * 4))
        return self._trim_to_chars(text, max_chars=max_chars)

    def _assemble_legacy_system_prompt(
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

    def _build_enterprise_blocks(
        self,
        identity_block: str,
        current_time: str,
        memory_context: str,
        search_context: str,
        mode_context: str,
        extra_blocks: Optional[List[str]],
        history: Optional[List[Dict[str, Any]]],
        mode: str,
        privilege: str,
    ) -> List[PromptBlock]:
        evidence_text = search_context.strip() if search_context else ""
        if getattr(settings, "PROMPT_FIREWALL_ENABLED", False):
            evidence_text, _ = apply_evidence_firewall(evidence_text)

        routing_summary = ""
        if mode_context:
            routing_summary = mode_context.strip()
        if mode and mode.strip():
            routing_summary = (routing_summary + f"\nMODE={mode.strip().upper()}").strip()
        if privilege and privilege.strip():
            routing_summary = (routing_summary + f"\nPRIVILEGE={privilege.strip().upper()}").strip()

        tools_summary = identity_block.strip()
        memory_profile = ""
        memory_working = memory_context.strip() if memory_context else ""
        output_rules = "\n".join(
            [
                "- Use Memory Context when relevant.",
                "- Prefer evidence-backed claims when EVIDENCE exists.",
                "- Be direct and practical.",
            ]
        )
        if extra_blocks:
            output_rules = "\n".join([output_rules] + [b.strip() for b in extra_blocks if b and b.strip()])

        history_text = ""
        if history:
            chunks = []
            for m in history:
                role = str(m.get("role", "user"))
                content = str(m.get("content", "")).strip()
                if content:
                    chunks.append(f"[{role}] {content}")
            history_text = "\n".join(chunks)

        return [
            PromptBlock("KERNEL", "KERNEL", 0, int(getattr(settings, "PROMPT_BUDGET_KERNEL", 700)), build_kernel_v1_1(settings), "truncate_tail"),
            PromptBlock("POLICIES", "POLICIES", 1, int(getattr(settings, "PROMPT_BUDGET_POLICIES", 320)), build_policy_pack(settings), "truncate_tail"),
            PromptBlock("PERSONA", "PERSONA", 2, int(getattr(settings, "PROMPT_BUDGET_PERSONA", 700)), load_persona_text(settings), "truncate_tail"),
            PromptBlock("TIME", "TIME", 3, int(getattr(settings, "PROMPT_BUDGET_TIME", 80)), current_time.strip(), "truncate_tail"),
            PromptBlock("ROUTING", "ROUTING", 4, int(getattr(settings, "PROMPT_BUDGET_ROUTING", 140)), routing_summary, "truncate_tail"),
            PromptBlock("TOOLS", "TOOLS", 5, int(getattr(settings, "PROMPT_BUDGET_TOOLS", 450)), tools_summary, "truncate_tail"),
            PromptBlock("MEMORY_PROFILE", "MEMORY_PROFILE", 6, int(getattr(settings, "PROMPT_BUDGET_MEMORY_PROFILE", 500)), memory_profile, "truncate_tail"),
            PromptBlock("MEMORY_WORKING", "MEMORY_WORKING", 7, int(getattr(settings, "PROMPT_BUDGET_MEMORY_WORKING", 700)), memory_working, "truncate_tail"),
            PromptBlock("EVIDENCE", "EVIDENCE", 8, int(getattr(settings, "PROMPT_BUDGET_EVIDENCE", 1200)), evidence_text, "truncate_tail"),
            PromptBlock("OUTPUT_RULES", "OUTPUT_RULES", 9, 1200, output_rules, "truncate_tail"),
            PromptBlock("HISTORY", "HISTORY", 10, int(getattr(settings, "PROMPT_BUDGET_HISTORY", 2200)), history_text, "truncate_head"),
        ]

    def build_system_prompt(
        self,
        identity_block: str,
        current_time: str,
        memory_context: str,
        search_context: str,
        mode_context: str = "Normal mode.",
        extra_blocks: Optional[List[str]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        mode: str = "EXECUTE",
        privilege: str = "SAFE",
        max_context_tokens: Optional[int] = None,
    ) -> str:
        if getattr(settings, "PROMPT_FORCE_LEGACY", False):
            return self._assemble_legacy_system_prompt(identity_block, current_time, memory_context, search_context, mode_context, extra_blocks)

        if not getattr(settings, "PROMPT_ENTERPRISE_ENABLED", True):
            return self._assemble_legacy_system_prompt(identity_block, current_time, memory_context, search_context, mode_context, extra_blocks)

        max_tokens = int(max_context_tokens or MAX_CONTEXT_TOKENS or 8192)
        reserve = int(getattr(settings, "PROMPT_BUDGET_USER_RESERVE", 450))

        blocks = self._build_enterprise_blocks(
            identity_block=identity_block,
            current_time=current_time,
            memory_context=memory_context,
            search_context=search_context,
            mode_context=mode_context,
            extra_blocks=extra_blocks,
            history=history,
            mode=mode,
            privilege=privilege,
        )

        flags = {
            "enterprise_enabled": bool(getattr(settings, "PROMPT_ENTERPRISE_ENABLED", False)),
            "force_legacy": bool(getattr(settings, "PROMPT_FORCE_LEGACY", False)),
            "firewall_enabled": bool(getattr(settings, "PROMPT_FIREWALL_ENABLED", False)),
        }

        try:
            final_blocks, report = apply_budgets(blocks, max_tokens=max_tokens, reserve_tokens=reserve)
            final_prompt = render_blocks(final_blocks)
        except Exception as e:
            if getattr(settings, "PROMPT_SNAPSHOT_LOG_ENABLED", False):
                fail_report = {"error": str(e), "available_tokens": max_tokens - reserve, "trimmed": []}
                write_prompt_snapshot(settings, {**flags, "status": "failed"}, blocks, fail_report, "")
            raise

        if getattr(settings, "PROMPT_SNAPSHOT_LOG_ENABLED", False):
            write_prompt_snapshot(settings, {**flags, "status": "ok"}, final_blocks, report, final_prompt)

        return final_prompt

    def _budget_system_prompt(
        self,
        system_prompt: str,
        *,
        user_prompt: str,
        history: Optional[List[Dict[str, Any]]],
        max_context_tokens: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
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

        if sys_tokens > int(remaining * 0.70):
            sys_budget = int(remaining * 0.70)
            sys_text = self._trim_to_token_budget(sys_text, sys_budget)
            sys_tokens = self._estimate_tokens(sys_text)

        history_budget = max(0, remaining - sys_tokens)
        if history_budget <= 0 or not msgs_history:
            return sys_text, []

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
