from __future__ import annotations

from typing import List, Dict, Optional

from config.settings import (
    SUMMARY_UPDATE_EVERY_N_TURNS,
    SUMMARY_LAST_TURNS_TO_SUMMARIZE,
    SUMMARY_MAX_TOKENS,
)


def _char_cap_from_tokens(tok: int) -> int:
    return max(120, int(tok) * 4)


def should_update_summary(turn_counter: int, last_updated_turn: int) -> bool:
    every = max(1, int(SUMMARY_UPDATE_EVERY_N_TURNS or 8))
    if turn_counter <= 0:
        return False
    if (turn_counter - int(last_updated_turn or 0)) < every:
        return False
    return (turn_counter % every) == 0


def build_summary_from_recent_turns(turns: List[Dict]) -> str:
    n = max(4, int(SUMMARY_LAST_TURNS_TO_SUMMARIZE or 12))
    sample = turns[-n:]
    user_bits = []
    assistant_bits = []
    for t in sample:
        role = str(t.get("role", ""))
        content = str(t.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            user_bits.append(content[:120])
        elif role == "assistant":
            assistant_bits.append(content[:120])

    summary = "User intents: " + " | ".join(user_bits[-6:])
    if assistant_bits:
        summary += " || Assistant actions: " + " | ".join(assistant_bits[-4:])

    return summary[: _char_cap_from_tokens(int(SUMMARY_MAX_TOKENS or 220))]


def trim_summary_text(text: str) -> str:
    return (text or "").strip()[: _char_cap_from_tokens(int(SUMMARY_MAX_TOKENS or 220))]
