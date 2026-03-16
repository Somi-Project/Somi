from __future__ import annotations

"""Extracted Agent methods from agents.py (text_methods.py)."""

def _clean_think_tags(self, text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

def _strip_unwanted_json(self, text: str) -> str:
    if self.current_mode != "game":
        text = re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.DOTALL)
    return text.strip()

def _looks_like_tool_dump(self, text: str) -> bool:
    """Heuristic gate: only naturalize clear tool/search dumps."""
    if not text:
        return False
    t = str(text)
    tl = t.lower()
    strong_markers = (
        "## web/search context",
        "reply 'expand",
        "reply expand",
        "top results",
    )
    if any(m in tl for m in strong_markers):
        return True
    url_count = len(re.findall(r"https?://[^\s\]\)]+", t, flags=re.IGNORECASE))
    dump_markers = 0
    dump_markers += len(re.findall(r"(?im)^\s*(?:[-*]|\d+\.)\s+.+https?://", t))
    dump_markers += len(re.findall(r"(?im)^\s*(?:title|source|url)\s*:\s*", t))
    dump_markers += len(re.findall(r"(?im)^\s*\[[0-9]+\]\s+", t))
    if url_count >= 2 and dump_markers >= 2:
        return True
    return False

def _strip_search_meta_leakage(self, text: str) -> str:
    """Conservative post-filter to remove common cleanup meta narration lines."""
    if not text:
        return text
    banned_line_patterns = [
        r"(?i)\bas an ai\b.*",
        r"(?i)\bbased on the provided\b.*",
        r"(?i)^\s*to provide\b.*",
        r"(?i)^\s*i would summarize\b.*",
        r"(?i)^\s*i hope this explanation helps\b.*",
        r"(?i)^\s*if you have any further questions\b.*",
        r"(?i)\braw search response\b.*",
        r"(?i)\btool output\b.*",
    ]
    kept_lines = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        has_url = bool(re.search(r"https?://", stripped, flags=re.IGNORECASE))
        has_number = bool(re.search(r"\d", stripped))
        is_meta = any(re.search(p, stripped) for p in banned_line_patterns)
        if is_meta and not has_url and not has_number:
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()

def _strip_internal_prompt_leakage(self, text: str) -> str:
    t = str(text or "")
    if not t:
        return t

    lines = t.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return t

    first = lines[idx].strip().lower()
    leak_starts = (
        "### conversation state ledger",
        "## planner/executor state",
        "## task graph",
    )
    if not any(first.startswith(s) for s in leak_starts):
        return t

    def _is_promptish_line(s: str) -> bool:
        sl = s.strip()
        if not sl:
            return True
        ll = sl.lower()
        if sl.startswith("#") or sl.startswith("-") or sl.startswith("{") or sl.startswith("}"):
            return True
        if ll.startswith("skills are available via"):
            return True
        if ll.startswith("when user asks for chart"):
            return True
        promptish_prefixes = (
            "no_autonomy:",
            "last_user_intent:",
            "ledger_empty:",
            "instruction:",
            "phase:",
            "objective:",
            "tool_call_count:",
            "no_progress_turns:",
            "stop_limits:",
            "verification_checks:",
            "open_tasks:",
            "no_open_tasks:",
        )
        if any(ll.startswith(p) for p in promptish_prefixes):
            return True
        return False

    cut = idx
    while cut < len(lines) and _is_promptish_line(lines[cut]):
        cut += 1

    cleaned = "\n".join(lines[cut:]).strip()
    return cleaned or t

async def _naturalize_search_output(self, raw_content: str, original_prompt: str) -> str:
    """Use the configured INSTRUCT_MODEL to turn raw websearch dumps into natural, friendly answers.
    This runs AFTER the FollowUpResolver has done its job â€” resolver abilities are 100% preserved."""
    if not self._looks_like_tool_dump(raw_content):
        return raw_content  # nothing to clean

    system_prompt = (
        "You are a rewrite engine that outputs only final user-facing answer text.\n"
        "Rules:\n"
        "- Output ONLY the final answer. No preface, no analysis, no process narration.\n"
        "- Do NOT mention being an AI.\n"
        "- Do NOT mention raw response, tool output, cleanup, summarizing, or transformation steps.\n"
        "- Do NOT include technical headers like '## Web/Search Context' or 'Top results'.\n"
        "- Preserve all numbers, dates, times, percentages, and ranges exactly as shown in the input.\n"
        "- If any URLs are present in the input, include a 'Sources:' section listing those URLs.\n"
        "- Keep the answer concise and natural.\n"
    )
    user_prompt = (
        f"Original user question:\n{original_prompt}\n\n"
        "Tool output to rewrite:\n"
        f"{raw_content}\n\n"
        "Output ONLY the final answer text. Preserve numbers/dates/ranges exactly."
    )

    try:
        resp = await self.ollama_client.chat(
            model=INSTRUCT_MODEL,   # â† comes from config/settings.py
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.1, "max_tokens": 600, "keep_alive": 300},
        )
        cleaned = resp.get("message", {}).get("content", "") or raw_content
        scrubbed = self._strip_search_meta_leakage(cleaned)
        return scrubbed if scrubbed else raw_content
    except Exception as e:
        logger.warning(f"Search naturalize failed (non-fatal): {e}")
        return raw_content  # safe fallback
