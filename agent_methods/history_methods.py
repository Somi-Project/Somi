from __future__ import annotations

"""Extracted Agent methods from agents.py (history_methods.py)."""

def _should_use_per_user_history(self, active_user_id: str) -> bool:
    au = str(active_user_id or "").strip()
    if not au:
        return False
    return au != str(self.user_id)

def _get_history_list(self, active_user_id: str) -> List[Dict[str, str]]:
    if self._should_use_per_user_history(active_user_id):
        return self.history_by_user.setdefault(active_user_id, [])
    return self.history

def _history_limits(self) -> Tuple[int, int]:
    max_messages = max(20, int(TRANSCRIPT_MAX_MESSAGES or 160))
    max_chars = max(200, int(TRANSCRIPT_MAX_MESSAGE_CHARS or 6000))
    return max_messages, max_chars

def _estimate_text_tokens_rough(self, text: str) -> int:
    t = str(text or "").strip()
    if not t:
        return 0
    return max(1, (len(t) // 4) + 1)

def _history_token_estimate(self, history: List[Dict[str, str]]) -> int:
    total = 0
    for item in history or []:
        if not isinstance(item, dict):
            continue
        total += 8 + self._estimate_text_tokens_rough(str(item.get("content") or ""))
    return total

def _resolve_history_compaction_thresholds(self) -> Tuple[int, int, int]:
    max_ctx = max(1024, int(MAX_CONTEXT_TOKENS or 8192))
    trigger_tokens_cfg = int(HISTORY_AUTO_COMPACT_TRIGGER_TOKENS or 0)
    target_tokens_cfg = int(HISTORY_AUTO_COMPACT_TARGET_TOKENS or 0)
    trigger_tokens = trigger_tokens_cfg if trigger_tokens_cfg > 0 else int(max_ctx * 0.55)
    target_tokens = target_tokens_cfg if target_tokens_cfg > 0 else int(max_ctx * 0.35)
    if target_tokens >= trigger_tokens:
        target_tokens = max(128, trigger_tokens - 256)
    min_keep = max(2, int(HISTORY_AUTO_COMPACT_MIN_KEEP_MESSAGES or 6))
    return trigger_tokens, target_tokens, min_keep

def _state_ledger_for_user(self, active_user_id: str) -> Dict[str, Any]:
    uid = str(active_user_id or self.user_id)
    cached = self._state_ledger_cache_by_user.get(uid)
    if isinstance(cached, dict) and cached:
        return dict(cached)
    loaded = load_state_ledger(uid)
    self._state_ledger_cache_by_user[uid] = dict(loaded)
    return dict(loaded)

def _state_ledger_block(self, active_user_id: str) -> str:
    try:
        ledger = self._state_ledger_for_user(active_user_id)
        return render_state_ledger_block(ledger, max_items=5)
    except Exception as e:
        logger.debug(f"State ledger render skipped: {type(e).__name__}: {e}")
        return ""

def _history_for_prompt(self, active_user_id: str, *, max_messages: Optional[int] = None) -> List[Dict[str, str]]:
    hist = self._get_history_list(active_user_id)
    lim_messages, lim_chars = self._history_limits()
    cleaned = sanitize_history_messages(
        hist if bool(TRANSCRIPT_HYGIENE_ENABLED) else list(hist),
        max_messages=lim_messages,
        max_message_chars=lim_chars,
    )
    prompt_limit = max(1, int(max_messages or HISTORY_MAX_MESSAGES or 10))
    if not cleaned:
        return []
    summary = None
    first = cleaned[0]
    if first.get("role") in {"system", "assistant"} and str(first.get("content") or "").startswith(COMPACTION_PREFIX):
        summary = first
    tail = cleaned[-prompt_limit:]
    if summary and (not tail or tail[0].get("content") != summary.get("content")):
        if len(tail) >= prompt_limit:
            tail = tail[1:]
        tail = [summary] + tail
    return tail

def _compact_history_if_needed(self, active_user_id: str) -> None:
    if not bool(HISTORY_AUTO_COMPACTION_ENABLED):
        return
    hist = self._get_history_list(active_user_id)
    trigger_msgs = max(8, int(HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES or 28))
    keep_recent = max(4, int(HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES or 12))
    trigger_tokens, target_tokens, min_keep = self._resolve_history_compaction_thresholds()
    if len(hist) <= trigger_msgs and self._history_token_estimate(hist) <= trigger_tokens:
        return

    lim_messages, lim_chars = self._history_limits()
    cleaned = sanitize_history_messages(hist, max_messages=lim_messages, max_message_chars=lim_chars)
    prior_summary = ""
    body = cleaned
    if body and body[0].get("role") in {"system", "assistant"} and str(body[0].get("content") or "").startswith(COMPACTION_PREFIX):
        prior_summary = str(body[0].get("content") or "")
        body = body[1:]
    if len(body) <= keep_recent:
        hist[:] = cleaned[-lim_messages:]
        return

    older = body[:-keep_recent]
    recent = body[-keep_recent:]
    summary = build_compaction_summary(
        older,
        prior_summary=prior_summary,
        max_items=max(2, int(HISTORY_COMPACTION_MAX_ITEMS or 8)),
        max_chars=max(220, int(HISTORY_COMPACTION_SUMMARY_MAX_CHARS or 1200)),
        state_ledger=self._state_ledger_for_user(active_user_id),
    )
    compacted = [{"role": "assistant", "content": summary}] + recent

    while len(recent) > min_keep and self._history_token_estimate(compacted) > target_tokens:
        recent = recent[1:]
        compacted = [{"role": "assistant", "content": summary}] + recent

    hist[:] = compacted[-lim_messages:]

def _push_history_for(self, active_user_id: str, user_prompt: str, assistant_content: str) -> None:
    hist = self._get_history_list(active_user_id)
    _, lim_chars = self._history_limits()
    if bool(TRANSCRIPT_HYGIENE_ENABLED):
        user_text = sanitize_text(user_prompt, max_chars=lim_chars)
        assistant_text = sanitize_text(assistant_content, max_chars=lim_chars)
    else:
        user_text = str(user_prompt or "").strip()
        assistant_text = str(assistant_content or "").strip()

    if user_text:
        hist.append({"role": "user", "content": user_text})
    if assistant_text:
        hist.append({"role": "assistant", "content": assistant_text})

    self._compact_history_if_needed(active_user_id)

    try:
        ledger = self._state_ledger_for_user(active_user_id)
        ledger = update_state_ledger(
            active_user_id,
            user_text=user_text,
            assistant_text=assistant_text,
            ledger=ledger,
        )
        persisted = save_state_ledger(active_user_id, ledger)
        self._state_ledger_cache_by_user[str(active_user_id or self.user_id)] = dict(persisted)
    except Exception as e:
        logger.debug(f"State ledger update skipped: {type(e).__name__}: {e}")

    lim_messages, lim_chars = self._history_limits()
    if bool(TRANSCRIPT_HYGIENE_ENABLED):
        hist[:] = sanitize_history_messages(hist, max_messages=lim_messages, max_message_chars=lim_chars)
    elif len(hist) > 60:
        del hist[:-60]

    if self.use_flow:
        if user_text:
            self.conversation_cache.append({"role": "user", "content": user_text})
        if assistant_text:
            self.conversation_cache.append({"role": "assistant", "content": assistant_text})
        if len(self.conversation_cache) > 10:
            self.conversation_cache = self.conversation_cache[-10:]

def _tool_loop_config(self) -> ToolLoopConfig:
    return ToolLoopConfig(
        enabled=bool(TOOL_LOOP_DETECTION_ENABLED),
        history_size=max(1, int(TOOL_LOOP_HISTORY_SIZE or 30)),
        warning_threshold=max(1, int(TOOL_LOOP_WARNING_THRESHOLD or 10)),
        critical_threshold=max(2, int(TOOL_LOOP_CRITICAL_THRESHOLD or 20)),
        global_circuit_breaker_threshold=max(3, int(TOOL_LOOP_GLOBAL_CIRCUIT_BREAKER_THRESHOLD or 30)),
        detect_generic_repeat=bool(TOOL_LOOP_DETECT_GENERIC_REPEAT),
        detect_no_progress=bool(TOOL_LOOP_DETECT_NO_PROGRESS),
        detect_ping_pong=bool(TOOL_LOOP_DETECT_PING_PONG),
    )

def _tool_call_history(self, active_user_id: str) -> List[Dict[str, Any]]:
    uid = str(active_user_id or self.user_id)
    return self._tool_call_history_by_user.setdefault(uid, [])

def _tool_loop_warning_cache(self, active_user_id: str) -> Dict[str, bool]:
    cache = getattr(self, "_tool_loop_warning_cache_by_user", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(self, "_tool_loop_warning_cache_by_user", cache)
    uid = str(active_user_id or self.user_id)
    bucket = cache.get(uid)
    if not isinstance(bucket, dict):
        bucket = {}
        cache[uid] = bucket
    return bucket

async def _run_tool_with_loop_guard(
    self,
    *,
    tool_name: str,
    args: Dict[str, Any],
    ctx: Dict[str, Any],
    active_user_id: str,
) -> Dict[str, Any]:
    safe_args = sanitize_tool_args(tool_name, dict(args or {}))
    cfg = self._tool_loop_config()
    history = self._tool_call_history(active_user_id)
    pre = detect_tool_loop(history, tool_name=tool_name, args=safe_args, cfg=cfg)

    if pre.stuck and pre.level == "critical":
        return {
            "_loop_blocked": True,
            "_loop_message": pre.message,
            "_loop_detector": pre.detector,
            "_loop_count": pre.count,
        }

    if pre.stuck and pre.level == "warning":
        warning_cache = _tool_loop_warning_cache(self, active_user_id)
        warning_key = str(pre.warning_key or f"{tool_name}:{pre.detector}:{pre.count}")
        if not bool(warning_cache.get(warning_key)):
            logger.warning(f"Tool loop warning for {tool_name}: {pre.message}")
            warning_cache[warning_key] = True

    record_tool_call(history, tool_name=tool_name, args=safe_args, cfg=cfg)
    try:
        out = await asyncio.to_thread(self.toolbox_runtime.run, tool_name, safe_args, ctx)
    except Exception as exc:
        record_tool_call_outcome(
            history,
            tool_name=tool_name,
            args=safe_args,
            error=f"{type(exc).__name__}: {exc}",
            cfg=cfg,
        )
        raise

    record_tool_call_outcome(history, tool_name=tool_name, args=safe_args, result=out, cfg=cfg)

    if pre.stuck and pre.level == "warning" and isinstance(out, dict):
        out.setdefault("_loop_warning", pre.message)
        out.setdefault("_loop_detector", pre.detector)
        out.setdefault("_loop_count", pre.count)

    return out if isinstance(out, dict) else {"result": out}
