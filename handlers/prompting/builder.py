from __future__ import annotations

from typing import Dict, List, Tuple

from handlers.prompting.blocks import PromptBlock
from handlers.prompting.budget import estimate_tokens


_TRIM_ORDER = [
    "HISTORY",
    "EVIDENCE",
    "MEMORY_WORKING",
    "MEMORY_PROFILE",
    "ROUTING",
    "OUTPUT_RULES",
    "TIME",
    "TOOLS",
    "POLICIES",
    "PERSONA",
]


def _truncate_head(text: str, target_tokens: int) -> str:
    if target_tokens <= 0:
        return ""
    max_chars = max(0, target_tokens * 4)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:].lstrip()


def _truncate_tail(text: str, target_tokens: int) -> str:
    if target_tokens <= 0:
        return ""
    max_chars = max(0, target_tokens * 4)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _trim_content(block: PromptBlock, target_tokens: int) -> str:
    if block.trim_strategy == "truncate_head":
        return _truncate_head(block.content, target_tokens)
    return _truncate_tail(block.content, target_tokens)


def apply_budgets(blocks: List[PromptBlock], max_tokens: int, reserve_tokens: int) -> Tuple[List[PromptBlock], Dict[str, object]]:
    available = max(1, int(max_tokens) - max(0, int(reserve_tokens)))
    final_blocks = [PromptBlock(**vars(b)) for b in blocks]
    report: Dict[str, object] = {"available_tokens": available, "trimmed": []}

    kernel = next((b for b in final_blocks if b.key == "KERNEL"), None)
    if kernel is None:
        raise ValueError("KERNEL block missing")
    kernel_tokens = estimate_tokens(kernel.content)
    if kernel_tokens > kernel.budget_tokens:
        raise ValueError(f"KERNEL block exceeds block budget ({kernel_tokens}>{kernel.budget_tokens})")
    if kernel_tokens > available:
        raise ValueError(f"KERNEL block exceeds available budget ({kernel_tokens}>{available})")

    for block in final_blocks:
        current = estimate_tokens(block.content)
        if current > block.budget_tokens:
            if block.key == "KERNEL":
                raise ValueError(f"KERNEL block exceeds block budget ({current}>{block.budget_tokens})")
            block.content = _trim_content(block, block.budget_tokens)
            report["trimmed"].append({"key": block.key, "reason": "block_budget", "from": current, "to": estimate_tokens(block.content)})

    def total_tokens() -> int:
        return sum(estimate_tokens(b.content) for b in final_blocks if b.content)

    while total_tokens() > available:
        changed = False
        for key in _TRIM_ORDER:
            block = next((b for b in final_blocks if b.key == key and b.content), None)
            if not block:
                continue
            current = estimate_tokens(block.content)
            if current <= 0:
                continue
            target = max(0, current - min(64, current))
            block.content = _trim_content(block, target)
            changed = True
            report["trimmed"].append({"key": block.key, "reason": "global_budget", "from": current, "to": estimate_tokens(block.content)})
            if total_tokens() <= available:
                break
        if not changed:
            raise ValueError("Unable to fit prompt into budget without trimming KERNEL")

    final_blocks = [b for b in final_blocks if b.content and b.content.strip()]
    return final_blocks, report


def render_blocks(final_blocks: List[PromptBlock]) -> str:
    ordered = sorted(final_blocks, key=lambda b: (b.priority, b.key))
    parts = []
    for block in ordered:
        parts.append(f"## {block.title}\n{block.content.strip()}")
    return "\n\n---\n\n".join(parts).strip()
