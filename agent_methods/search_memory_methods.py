from __future__ import annotations

"""Extracted Agent methods from agents.py (search_memory_methods.py)."""

def _format_due_ts_local(self, due_ts: str) -> str:
    try:
        return self.time_handler.format_iso_to_local(str(due_ts or ""), SYSTEM_TIMEZONE)
    except Exception:
        return str(due_ts or "")

def _is_personal_memory_query(self, prompt: str) -> bool:
    pl = (prompt or "").strip().lower()
    if not pl:
        return False
    # Strong internal-state triggers: never websearch
    internal_triggers = (
        "what do you remember", "remember about me", "summarize everything you remember",
        "summarize what you remember", "summarize my", "everything you remember about me",
        "my name", "my preference", "my preferences",
        "my goals", "my goal", "my reminders", "goals and reminders",
        "due reminders", "any due reminders", "list my", "show my", "what did i have to do again",
        "forget about", "remove my", "delete my",
        "my favorite", "favorite drink",
    )
    if any(t in pl for t in internal_triggers):
        return True
    if re.search(r"\b(my)\s+(name|preferences?|goals?|reminders?|favorite)\b", pl):
        return True
    if re.search(r"\bwhat(?:'|\u2019)?s\s+my\b", pl):
        return True
    if re.search(r"\bwho\s+am\s+i\b", pl):
        return True
    if ("remind me" in pl) and not any(k in pl for k in ("news", "weather", "price", "quote", "market")):
        return True
    return False

def _should_inject_due_context(self, prompt: str, active_user_id: str) -> bool:
    """
    Avoid due-reminder context pollution on unrelated turns.
    Always allow on explicit memory/reminder queries; otherwise throttle.
    """
    if self._is_personal_memory_query(prompt):
        return True
    now = time.time()
    uid = str(active_user_id or self.user_id)
    last = float(self._last_due_injected_at.get(uid, 0.0) or 0.0)
    return (now - last) >= float(self._due_inject_cooldown_seconds)

def _mark_due_context_injected(self, active_user_id: str) -> None:
    uid = str(active_user_id or self.user_id)
    self._last_due_injected_at[uid] = time.time()

async def _route_local_memory_intents(self, prompt: str, active_user_id: str) -> Optional[str]:
    """
    Handle obvious memory/goals/reminders intents deterministically.
    Returns a final user-facing string if handled, else None (continue normal pipeline).
    """
    pl = (prompt or "").strip()
    pll = pl.lower()
    if not pll:
        return None
    if pll.strip() == "memory doctor":
        try:
            report = await self.memory.memory_doctor(prompt, user_id=active_user_id)
            return report
        except Exception as e:
            return f"Memory doctor failed: {type(e).__name__}: {e}"

    # Name set: "my name is Kai" / "call me Kai"
    m = re.search(r"^(?:my\s+name\s+is|call\s+me|i\s+am|i(?:'|\u2019)m)\s+([a-zA-Z0-9 _'\-]{1,40})\s*$", pl, flags=re.IGNORECASE)
    if m:
        raw_name = (m.group(1) or "").strip(" .,!?:;\"'")
        if raw_name:
            await self.memory.upsert_fact(
                {"key": "name", "value": raw_name, "kind": "profile", "confidence": 0.99},
                user_id=active_user_id,
            )
            return f"Got it - I will remember your name is {raw_name}."

    # Name recall: "what's my name" / "who am i"
    if re.search(r"\b(what(?:'|\u2019)?s\s+my\s+name|what\s+is\s+my\s+name|who\s+am\s+i)\b", pll):
        profile_ctx = await self.memory.retrieve_relevant_memories(
            "name", active_user_id, min_score=0.0, scope="profile"
        )
        mm = re.search(r"(?im)^\s*-\s*name\s*:\s*(.+)\s*$", str(profile_ctx or ""))
        if mm:
            name = (mm.group(1) or "").strip()
            if name and name.lower() not in {"(none)", "unknown", "n/a"}:
                return f"Your name is {name}."
        return "I don't have your name saved yet. You can tell me by saying: my name is <name>."

    recall_query = (
        "what did we decide" in pll
        or "what did we discuss" in pll
        or "what happened last week" in pll
        or "what happened earlier" in pll
        or pll.startswith("session search ")
        or pll.startswith("search my sessions ")
        or ("last week" in pll and any(word in pll for word in ("decid", "discuss", "said", "planned", "worked on")))
    )
    if recall_query:
        session_search = getattr(self, "session_search", None)
        if session_search is None:
            return "Session search is not available right now."
        search_query = pl
        if pll.startswith("session search "):
            search_query = pl[len("session search "):].strip()
        elif pll.startswith("search my sessions "):
            search_query = pl[len("search my sessions "):].strip()
        try:
            return session_search.answer_recall(search_query, user_id=active_user_id, limit=6)
        except Exception as e:
            return f"Session search failed: {type(e).__name__}: {e}"

    # 1) One-time reminders: supports common natural phrasing + shorthand units
    reminder_prefix = r"(?:remind me\s+(?:to|about)|set\s+(?:a\s+)?reminder\s+to)"
    m = re.search(
        rf"^{reminder_prefix}\s+(.+?)\s+in\s+(\d+)\s+(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\s*$",
        pl,
        flags=re.IGNORECASE,
    )
    if m:
        title = m.group(1).strip()
        n = int(m.group(2))
        unit = m.group(3).strip().lower()
        rid = await self.memory.add_reminder(active_user_id, title=title, when=f"in {n} {unit}", scope="task")
        if rid:
            return f"Got it â€” reminder set: '{title}' in {n} {unit}."
        return "I couldn't schedule that reminder time. Try: remind me to <task> in 2 minutes."
    m = re.search(rf"^{reminder_prefix}\s+(.+?)\s+in\s+(a|an)\s+(minute|hour|day)\s*$", pl, flags=re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        article = m.group(2).strip().lower()
        unit = m.group(3).strip().lower()
        rid = await self.memory.add_reminder(active_user_id, title=title, when=f"in {article} {unit}", scope="task")
        if rid:
            return f"Got it â€” reminder set: '{title}' in {article} {unit}."
        return "I couldn't schedule that reminder time. Try: remind me to <task> in 2 minutes."
    m = re.search(rf"^{reminder_prefix}\s+(.+?)\s+in\s+half\s+an?\s+hour\s*$", pl, flags=re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        rid = await self.memory.add_reminder(active_user_id, title=title, when="in half an hour", scope="task")
        if rid:
            return f"Got it â€” reminder set: '{title}' in half an hour."
        return "I couldn't schedule that reminder time. Try: remind me to <task> in 2 minutes."
    m = re.search(rf"^{reminder_prefix}\s+(.+?)\s+at\s+(.+)\s*$", pl, flags=re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        at_when = m.group(2).strip().lower()
        rid = await self.memory.add_reminder(active_user_id, title=title, when=f"at {at_when}", scope="task")
        if rid:
            return f"Got it â€” reminder set: '{title}' at {at_when}."
        return "I couldn't schedule that reminder time. Try: remind me to <task> at 8:30 pm."
    m = re.search(rf"^{reminder_prefix}\s+(.+?)\s+tomorrow\s+at\s+(.+)\s*$", pl, flags=re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        at_when = m.group(2).strip().lower()
        rid = await self.memory.add_reminder(active_user_id, title=title, when=f"tomorrow at {at_when}", scope="task")
        if rid:
            return f"Got it â€” reminder set: '{title}' tomorrow at {at_when}."
        return "I couldn't schedule that reminder time. Try: remind me to <task> tomorrow at 8 am."
    # 2) Due reminders: "any due reminders" / "are there any due reminders right now"
    if ("due reminder" in pll) or ("due reminders" in pll) or ("what did i have to do again" in pll):
        peek_due = getattr(self.memory, "peek_due_reminders", None)
        due = await peek_due(active_user_id, limit=10) if callable(peek_due) else []
        if not due:
            active = await self.memory.list_active_reminders(active_user_id, scope="task", limit=5)
            if not active:
                return "No reminders right now."
            lines = ["**Active reminders:**"]
            for d in active[:5]:
                lines.append(f"- {d.get('title','Reminder')} (due {self._format_due_ts_local(str(d.get('due_ts','soon')))})")
            return "\n".join(lines)
        lines = ["**Due reminders:**"]
        for d in due:
            title = str(d.get("title", "Reminder"))
            due_ts = self._format_due_ts_local(str(d.get("due_ts", "soon")))
            lines.append(f"- {title} (due {due_ts})")
        return "\n".join(lines)
    # 3) Save goal (and split off trailing reminder request)
    if pll.startswith("my goal is "):
        tail = pl[len("my goal is "):].strip()
        goal_text = tail
        reminder_tail = ""
        # Split on ". remind me ..." or " remind me ..."
        mm = re.search(r"^(.*?)(?:\.\s*remind me| remind me)\s+(.+)$", tail, flags=re.IGNORECASE)
        if mm:
            goal_text = (mm.group(1) or "").strip()
            reminder_tail = (mm.group(2) or "").strip()
        if goal_text:
            await self.memory.upsert_goal(active_user_id, title=goal_text, scope="task", progress=0.0, confidence=0.7)
        # If they asked for recurring reminders, be honest (recurring reminders are not implemented yet)
        if reminder_tail:
            # common patterns humans use
            if any(k in reminder_tail.lower() for k in ("every ", "daily", "each day", "every day", "every afternoon", "every morning", "every night")):
                return (
                    f"Goal saved: {goal_text}\n"
                    "Recurring reminders (e.g., every day at 3pm) arenâ€™t wired up yet. "
                    "Right now I can do one-time reminders like: â€œremind me to drink water in 2 hoursâ€."
                )
            # If it's a one-time phrasing like "in 2 hours", let the normal reminder parser handle it
            # by returning None (continue pipeline) OR we can try to schedule directly:
            rm = re.search(r"\bin\s+(\d+)\s+(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b", reminder_tail.lower())
            if rm:
                n = int(rm.group(1))
                unit = rm.group(2)
                rid = await self.memory.add_reminder(active_user_id, title=goal_text, when=f"in {n} {unit}", scope="task")
                if rid:
                    return f"Goal saved: {goal_text}\nAlso set a reminder in {n} {unit}."
            return f"Goal saved: {goal_text}"
        return f"Goal saved: {goal_text}" if goal_text else "I didnâ€™t catch the goal. Try: My goal is <something>."
    # 4) Update goal progress: "update goal <title> to <progress%>"
    if pll.startswith("update goal ") and " to " in pll:
        tail = pl[len("update goal "):].strip()
        parts = tail.rsplit(" to ", 1)
        if len(parts) == 2 and parts[0].strip():
            pct_txt = parts[1].strip().rstrip("%")
            if pct_txt.replace(".", "", 1).isdigit():
                prog = max(0.0, min(1.0, float(pct_txt) / 100.0))
                await self.memory.upsert_goal(active_user_id, title=parts[0].strip(), scope="task", progress=prog, confidence=0.72)
                return f"Updated goal '{parts[0].strip()}' to {int(prog * 100)}%."
    # 5) List goals and/or reminders (best-effort; reminders listing may not exist yet)
    if re.search(r"\b(list|show)\b.*\b(goals?|reminders?)\b", pll) or ("goals and reminders" in pll):
        lines: List[str] = []
        # Goals
        try:
            goals = await self.memory.list_active_goals(active_user_id, scope="task", limit=25)
        except Exception:
            goals = []
        lines.append("**Goals**:")
        if goals:
            for g in goals:
                title = str(g.get("title", "(untitled)"))
                progress = g.get("progress", 0.0)
                try:
                    pct = int(float(progress) * 100)
                except Exception:
                    pct = 0
                lines.append(f"- {title} (progress {pct}%)")
        else:
            lines.append("- (none)")
        # Reminders (only if the method exists; otherwise be honest)
        lines.append("\n**Reminders**:")
        list_rem = getattr(self.memory, "list_active_reminders", None)
        if callable(list_rem):
            try:
                rems = await list_rem(active_user_id, scope="task", limit=25)
            except Exception:
                rems = []
            if rems:
                for r in rems:
                    title = str(r.get("title", "(untitled)"))
                    due_ts = self._format_due_ts_local(str(r.get("due_ts", "(unknown)")))
                    lines.append(f"- {title} (due {due_ts})")
            else:
                lines.append("- (none)")
        else:
            lines.append("- (listing not available yet â€” I can only announce reminders when they become due)")
        return "\n".join(lines)
    # 6) Summarize what you remember about me (offline; no websearch)
    if ("remember about me" in pll) or ("what do you remember" in pll) or ("summarize everything you remember" in pll):
        # Pull profile + small conversation summary + goals
        profile = await self.memory.retrieve_relevant_memories("name preferences profile", active_user_id, min_score=0.0, scope="profile")
        conv = await self.memory.retrieve_relevant_memories("key facts", active_user_id, min_score=0.25, scope="conversation")
        goal_ctx = None
        try:
            goal_ctx = await self.memory.build_goal_context(active_user_id, scope="task", limit=10)
        except Exception:
            goal_ctx = None
        parts: List[str] = ["Hereâ€™s what I have stored about you:"]
        if profile:
            parts.append("\n**Profile**\n" + profile)
        if goal_ctx:
            parts.append("\n**Goals**\n" + goal_ctx)
        if conv:
            parts.append("\n**Recent memory**\n" + conv)
        if len(parts) == 1:
            return "I donâ€™t have anything stored about you yet."
        return "\n".join(parts)
    # 7) Forget/remove/delete (best-effort: goals/reminders if delete methods exist; otherwise forget_phrase filter)
    if re.search(r"^(forget|remove|delete)\b", pll):
        # Extract target phrase
        mm = re.search(r"^(?:forget|remove|delete)\s+(?:about\s+)?(.+)$", pl, flags=re.IGNORECASE)
        target = (mm.group(1).strip() if mm else "").strip()
        if not target:
            return "Tell me what to forget/remove. Example: â€œforget about my water goalâ€."
        removed_any = False
        # Try goal deletion if available
        del_goal = getattr(self.memory, "delete_goal_by_title", None)
        if callable(del_goal):
            try:
                ok = await del_goal(active_user_id, title=target, scope="task")
                removed_any = removed_any or bool(ok)
            except Exception:
                pass
        # Try reminder deletion if available
        del_rem = getattr(self.memory, "delete_reminder_by_title", None)
        if callable(del_rem):
            try:
                n = await del_rem(active_user_id, title=target, scope="task")
                removed_any = removed_any or (int(n) > 0)
            except Exception:
                pass
        # Always add forget-phrase filter as fallback for recall (prevents resurfacing)
        try:
            ok2 = await self.memory.forget_phrase(active_user_id, phrase=target, scope="task")
            removed_any = removed_any or bool(ok2)
        except Exception:
            pass
        return "Done â€” Iâ€™ll stop using that." if removed_any else "I couldnâ€™t find anything matching that to remove, but Iâ€™ll avoid bringing it up."
    return None

def _should_websearch(self, prompt: str) -> bool:
    """
    Network decision gate (natural-language-first):
    - Default to LLM-only.
    - Search only when user intent requires freshness/volatility/citations or research.
    """
    pl = (prompt or "").strip().lower()
    if not pl:
        return False
    # Hard block: internal state / memory/goals/reminders must never websearch
    if self._is_personal_memory_query(pl) or re.search(r"\bwhat(?:'|\u2019)?s\s+my\b", pl):
        return False
    explicit = any(k in pl for k in (
        "search", "look up", "google", "find online", "check online",
        "source", "sources", "cite", "citation", "link", "verify", "confirm online",
    ))
    recency = any(k in pl for k in (
        "latest", "current", "today", "now", "right now", "this week", "updated", "newest",
        "breaking", "live", "recent",
    ))
    volatile = any(k in pl for k in (
        "price", "quote", "market", "stock", "shares",
        "bitcoin", "btc", "ethereum", "eth", "crypto", "coin",
        "exchange rate", "fx", "forex",
        "weather", "forecast", "temperature", "rain",
        "news", "headline", "current events",
    ))
    research_keywords = (
        "evidence", "paper", "papers", "study", "studies", "literature", "review",
        "systematic review", "meta-analysis", "metaanalysis",
        "rct", "randomized", "randomised", "trial", "clinical trial",
        "guideline", "practice guideline", "consensus", "position statement",
        "pmid", "pubmed", "doi", "arxiv", "openalex", "semantic scholar", "crossref",
        "clinicaltrials", "clinicaltrials.gov", "nct",
    )
    research = any(k in pl for k in research_keywords) or bool(
        re.search(r"\b(10\.\d{4,9}/\S+|pmid\s*\d{6,9}|nct\s*\d{8}|arxiv\s*:\s*\d{4}\.\d{4,5})\b", pl)
    )
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", pl)]
    has_year = bool(years)
    near_present = any(y >= 2023 for y in years)
    historical_only = has_year and not (explicit or recency or volatile or research) and not near_present
    if historical_only:
        return False
    return bool(explicit or recency or volatile or research or (has_year and near_present))

def _build_rag_block(self, prompt: str, k: int = 2) -> str:
    if not self.use_studies:
        return ""
    try:
        hits = self.rag.retrieve(prompt, k=k)
        if not hits:
            return ""
        parts = []
        for h in hits[:k]:
            src = str(h.get("source", ""))[:120]
            content = str(h.get("content", ""))[:500]
            if content.strip():
                parts.append(f"- Source: {src}\n  Content: {content}")
        if not parts:
            return ""
        return "## RAG Context (use only if relevant)\n" + "\n".join(parts)
    except Exception as e:
        logger.debug(f"RAG retrieval failed (non-fatal): {e}")
        return ""

async def _maintenance_tick(self) -> None:
    try:
        async with asyncio.timeout(4.0):
            await self.memory.prune_old_memories()
    except Exception:
        pass

async def _persist_memory_serial(self, mem_content: str, user_id: str, mem_type: str, source: str, scope: str = "conversation") -> None:
    try:
        async with self._mem_write_sem:
            await self.memory.ingest_turn(mem_content, assistant_text="", tool_summaries=[source], session_id=user_id)
    except Exception:
        pass

def _memory_scope_for_prompt(self, prompt: str, should_search: bool = False) -> str:
    pl = (prompt or "").lower()
    if self.current_mode == "story":
        return "task"
    if any(k in pl for k in ("remember", "always", "preference", "my favorite", "i prefer", "call me")):
        return "profile"
    if should_search:
        return "task"
    return "conversation"

def _response_timeout_seconds(self) -> float:
    try:
        dynamic = float(getattr(self, "_current_response_timeout_s", 0.0) or 0.0)
        if dynamic > 0:
            return dynamic
    except Exception:
        pass
    profile = str(self.context_profile or "").lower()
    if profile in {"4k", "fast"}:
        return 45.0
    if profile in {"16k", "32k", "quality"}:
        return 120.0
    return 75.0

def _vision_timeout_seconds(self) -> float:
    profile = str(self.context_profile or "").lower()
    if profile in {"4k", "fast"}:
        return 90.0
    if profile in {"16k", "32k", "quality"}:
        return 180.0
    return 120.0

def _token_budget(self, prompt: str, system_prompt: str, base_max: int) -> int:
    total_chars = len(prompt) + len(system_prompt)
    if total_chars > 14000:
        return max(120, int(base_max * 0.35))
    if total_chars > 9000:
        return max(160, int(base_max * 0.55))
    if total_chars > 6000:
        return max(180, int(base_max * 0.70))
    return base_max

def _extract_urls_from_results(self, results: List[Dict[str, Any]], limit: int = 4) -> List[str]:
    urls = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        u = (r.get("url") or "").strip()
        if u and u.startswith("http"):
            urls.append(u)
        if len(urls) >= limit:
            break
    return urls

def _extract_urls_from_citation_map(self, citation_map: List[Dict[str, Any]], limit: int = 4) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in (citation_map or []):
        try:
            u = str((row or {}).get("url") or "").strip()
        except Exception:
            u = ""
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out

def _enforce_web_evidence_output(
    self,
    *,
    content: str,
    should_search: bool,
    evidence_contract: Optional[Dict[str, Any]],
    citation_map: Optional[List[Dict[str, Any]]],
) -> str:
    if not should_search:
        return content

    text = str(content or "").strip()
    contract = dict(evidence_contract or {})
    if not text or not contract:
        return text

    found = int(contract.get("found_sources") or 0)
    satisfied = bool(contract.get("satisfied", False))
    has_url = bool(re.search(r"https?://", text, flags=re.IGNORECASE))
    has_citation = bool(re.search(r"\[[0-9]{1,2}\]", text))

    if not satisfied:
        has_uncertainty = bool(
            re.search(
                r"\b(uncertain|insufficient|limited evidence|could not verify|not sure|cannot confirm|not enough sources)\b",
                text.lower(),
            )
        )
        if not has_uncertainty:
            text = (
                "Evidence note: available sources were limited, so treat details as provisional until verified.\n\n"
                + text
            )

    if found > 0 and (not has_url) and (not has_citation):
        urls = self._extract_urls_from_citation_map(list(citation_map or []), limit=3)
        if urls:
            text = text.rstrip() + "\n\nSources:\n" + "\n".join([f"- {u}" for u in urls])

    return text

def _is_volatile_results(self, results: List[Dict[str, Any]]) -> Tuple[bool, str]:
    volatile = False
    cat = "general"
    for r in results or []:
        if not isinstance(r, dict):
            continue
        if r.get("category"):
            cat = str(r.get("category"))
        if bool(r.get("volatile", False)):
            volatile = True
    return volatile, cat

def _safe_build_image_spec(self, prompt: str, image_spec: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        from workshop.toolbox.stacks.image_core.image_generate import spec_from_text
        return spec_from_text(prompt, provided_spec=image_spec)
    except Exception as e:
        logger.debug(f"Image spec build failed: {e}")
        return None

def _is_chart_keyword_prompt(self, prompt_lower: str) -> bool:
    return any(k in prompt_lower for k in ("chart", "graph", "plot", "bar chart", "bar graph", "line chart"))

def _numeric_guard(self, content: str, search_context: str) -> str:
    """
    Replace numeric tokens not present in search_context with [see source].
    Uses word-boundary regex replacement to avoid partial replacements.
    """
    try:
        if not content or not search_context:
            return content
        ctx = search_context.lower()
        ctx_norm = ctx.replace(",", "").replace(" ", "")
        numbers = re.findall(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\b", content)
        if not numbers:
            return content
        out = content
        for n in set(numbers):
            n_norm = n.lower().replace(",", "").replace(" ", "")
            if n_norm not in ctx_norm:
                out = re.sub(rf"\b{re.escape(n)}\b", "[see source]", out)
        return out
    except Exception:
        return content

def _is_finance_intent_hint(self, intent_hint: str) -> bool:
    return str(intent_hint or "").strip().lower() in {"crypto", "forex", "stock/commodity"}

def _looks_like_historical_price_followup(self, text: str) -> bool:
    tl = str(text or "").strip().lower()
    if not tl:
        return False
    return bool(
        re.search(r"\b(what was|historical|history|previous|back in|last year|past year|all[- ]time|in\s+(?:19|20)\d{2})\b", tl)
        or re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\s+(?:19|20)\d{2}\b", tl)
    )

def _looks_like_finance_followup(self, text: str) -> bool:
    tl = str(text or "").strip().lower()
    if not tl:
        return False

    finance_markers = (
        "price", "rate", "ticker", "stock", "share", "shares", "market cap",
        "crypto", "bitcoin", "btc", "ethereum", "eth", "forex", "fx",
        "exchange rate", "usd", "eur", "jpy", "gbp", "aud", "cad", "ttd",
        "gold", "oil", "nasdaq", "dow", "s&p", "sp500",
    )
    if any(k in tl for k in finance_markers):
        return True

    if self._looks_like_historical_price_followup(tl):
        if re.search(r"\b(it|that|this|same|one)\b", tl):
            non_finance_markers = ("news", "headline", "weather", "forecast", "article", "story")
            return not any(k in tl for k in non_finance_markers)

    return False

def _render_direct_finance_answer(
    self,
    *,
    results: List[Dict[str, Any]],
    intent_hint: str,
) -> str:
    if not results:
        return ""

    intent_l = str(intent_hint or "").strip().lower()
    finance_cats = {"crypto", "forex", "stock/commodity"}
    finance_sources = ("yfinance", "yahooquery", "binance", "finance")

    picked: Optional[Dict[str, Any]] = None
    fallback_pick: Optional[Dict[str, Any]] = None
    for row in results:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category") or "").strip().lower()
        src = str(row.get("source") or row.get("provider") or "").strip().lower()
        desc = str(row.get("description") or "").strip()
        is_candidate = (
            cat in finance_cats
            or intent_l in finance_cats
            or any(src.startswith(s) for s in finance_sources)
            or any(tok in desc.lower() for tok in ("current price:", "exchange rate", "historical range"))
        )
        if not is_candidate:
            continue
        if fallback_pick is None:
            fallback_pick = row
        if desc:
            picked = row
            break

    picked = picked or fallback_pick
    if not picked:
        return ""

    desc = str(picked.get("description") or "").strip()
    if not desc:
        desc = str(picked.get("title") or "").strip()
    if not desc:
        return ""

    desc = re.sub(r"\s*Do not alter this number\.?\s*", " ", desc, flags=re.IGNORECASE).strip()

    urls: List[str] = []
    seen_urls: set[str] = set()
    for row in results:
        if not isinstance(row, dict):
            continue
        u = str(row.get("url") or "").strip()
        if not u or not u.startswith("http") or u in seen_urls:
            continue
        seen_urls.add(u)
        urls.append(u)
        if len(urls) >= 2:
            break

    out = desc
    if urls:
        out = out.rstrip() + "\n\nSource:\n" + "\n".join([f"- {u}" for u in urls])
    return out

def _render_direct_volatile_answer(
    self,
    *,
    results: List[Dict[str, Any]],
    intent_hint: str,
) -> str:
    intent_l = str(intent_hint or "").strip().lower()
    if not results:
        return ""

    if intent_l in {"crypto", "forex", "stock/commodity"}:
        return self._render_direct_finance_answer(results=results, intent_hint=intent_l)

    urls: List[str] = []
    seen: set[str] = set()
    for row in results:
        if not isinstance(row, dict):
            continue
        u = str(row.get("url") or "").strip()
        if not u or not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        urls.append(u)
        if len(urls) >= 4:
            break

    if intent_l == "weather":
        picked: Optional[Dict[str, Any]] = None
        for row in results:
            if not isinstance(row, dict):
                continue
            cat = str(row.get("category") or "").strip().lower()
            title = str(row.get("title") or "").strip().lower()
            desc = str(row.get("description") or "").strip()
            if not desc:
                continue
            if cat == "weather" or "weather" in title or "forecast" in title:
                picked = row
                break
        if not picked:
            return ""
        desc = str(picked.get("description") or "").strip()
        out = desc
        if urls:
            out += "\n\nSource:\n" + "\n".join([f"- {u}" for u in urls[:2]])
        return out

    if intent_l == "news":
        items: List[tuple[str, str, str]] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            desc = str(row.get("description") or "").strip()
            if not title or not url:
                continue
            desc = re.sub(r"^\[[^\]]+\]\s*", "", desc).strip()
            if len(desc) > 180:
                desc = desc[:180].rstrip() + "..."
            items.append((title, url, desc))
            if len(items) >= 5:
                break

        if not items:
            return ""

        lines = ["Latest reported items:"]
        for title, _, desc in items:
            if desc:
                lines.append(f"- {title}: {desc}")
            else:
                lines.append(f"- {title}")

        lines.append("")
        lines.append("Sources:")
        for _, url, _ in items[:4]:
            lines.append(f"- {url}")
        return "\n".join(lines)

    return ""
