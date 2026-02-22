from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptBlock:
    key: str
    title: str
    priority: int
    budget_tokens: int
    content: str
    trim_strategy: str = "truncate_tail"
