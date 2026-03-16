from __future__ import annotations

"""Extracted Agent methods from agents.py (model_methods.py)."""

def _select_generation_mode(
    self,
    prompt: str,
    *,
    should_search: bool,
    route: str = "llm_only",
    memory_intent: bool = False,
) -> str:
    if self._is_explicit_coding_intent(prompt):
        return "coding"
    if bool(memory_intent) or self._is_personal_memory_query(prompt):
        return "memory"
    if bool(should_search) or str(route or "").strip().lower() == "websearch":
        return "websearch"
    if self._is_analysis_intent(prompt):
        return "analysis"
    return "general"

def _select_response_model(
    self,
    prompt: str,
    *,
    should_search: bool = False,
    route: str = "llm_only",
    memory_intent: bool = False,
) -> str:
    mode = self._select_generation_mode(
        prompt,
        should_search=should_search,
        route=route,
        memory_intent=memory_intent,
    )
    if mode == "coding":
        return self.coding_model
    if mode == "memory":
        return self.memory_model or self.model
    if mode == "websearch":
        return WEBSEARCH_MODEL or self.model
    return self.model

def _model_role_for_generation_mode(self, mode: str) -> str:
    m = str(mode or "general").strip().lower()
    if m in {"coding", "memory", "websearch"}:
        return m
    return "general"

def _model_retryable_error_markers(self) -> Tuple[str, ...]:
    markers = tuple(
        str(x).strip().lower()
        for x in (MODEL_FAILOVER_RETRYABLE_ERRORS or [])
        if str(x).strip()
    )
    if markers:
        return markers
    return ("timeout", "connection", "unavailable", "model not found")

def _is_retryable_model_error(self, exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in msg for marker in self._model_retryable_error_markers())

def _record_model_success(self, model_name: str) -> None:
    key = str(model_name or "").strip()
    if not key:
        return
    self._model_failures_by_name[key] = 0
    self._model_cooldowns_by_name.pop(key, None)

def _record_model_failure(self, model_name: str) -> None:
    key = str(model_name or "").strip()
    if not key:
        return
    failures = int(self._model_failures_by_name.get(key, 0)) + 1
    self._model_failures_by_name[key] = failures
    threshold = max(1, int(MODEL_FAILOVER_FAILS_BEFORE_COOLDOWN or 2))
    cooldown_seconds = max(0, int(MODEL_FAILOVER_COOLDOWN_SECONDS or 0))
    if failures >= threshold and cooldown_seconds > 0:
        self._model_cooldowns_by_name[key] = time.time() + float(cooldown_seconds)

def _model_candidate_chain(
    self,
    *,
    prompt: str,
    should_search: bool,
    route: str = "llm_only",
    memory_intent: bool = False,
) -> List[str]:
    mode = self._select_generation_mode(
        prompt,
        should_search=should_search,
        route=route,
        memory_intent=memory_intent,
    )
    primary = str(
        self._select_response_model(
            prompt,
            should_search=should_search,
            route=route,
            memory_intent=memory_intent,
        )
        or self.model
    ).strip()

    raw: List[str] = [primary]
    if mode == "coding":
        raw.extend([self.coding_model, self.model, WEBSEARCH_MODEL, self.memory_model])
    elif mode == "websearch":
        raw.extend([WEBSEARCH_MODEL, self.model, self.memory_model, self.coding_model])
    elif mode == "memory":
        raw.extend([self.memory_model, self.model, self.coding_model, WEBSEARCH_MODEL])
    else:
        raw.extend([self.model, self.coding_model, WEBSEARCH_MODEL, self.memory_model])

    deduped: List[str] = []
    for item in raw:
        candidate = str(item or "").strip()
        if candidate and candidate not in deduped:
            deduped.append(candidate)

    try:
        deduped = self.performance_controller.reorder_models_for_load(deduped)
    except Exception:
        pass

    if not bool(MODEL_FAILOVER_ENABLED):
        return deduped[:1] if deduped else [str(self.model)]

    now_ts = time.time()
    ready: List[str] = []
    pinned = deduped[0] if deduped else primary
    for candidate in deduped:
        cooldown_until = float(self._model_cooldowns_by_name.get(candidate, 0.0) or 0.0)
        if candidate != pinned and cooldown_until > now_ts:
            continue
        ready.append(candidate)

    if not ready:
        return [pinned] if pinned else [str(self.model)]
    return ready

async def _chat_with_model_failover(
    self,
    *,
    prompt: str,
    messages: List[Dict[str, Any]],
    should_search: bool,
    route: str = "llm_only",
    memory_intent: bool = False,
    temperature: float,
    max_tokens: int,
    tool_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    mode = self._select_generation_mode(
        prompt,
        should_search=should_search,
        route=route,
        memory_intent=memory_intent,
    )
    role = self._model_role_for_generation_mode(mode)
    candidates = self._model_candidate_chain(
        prompt=prompt,
        should_search=should_search,
        route=route,
        memory_intent=memory_intent,
    )
    attempt_cap = max(1, int(MODEL_FAILOVER_MAX_ATTEMPTS or 1))
    attempt_models = candidates[:attempt_cap]

    last_error: Optional[Exception] = None
    for attempt, model_name in enumerate(attempt_models, start=1):
        try:
            async with asyncio.timeout(self._response_timeout_seconds()):
                resp = await self.ollama_client.chat(
                    model=model_name,
                    messages=messages,
                    options=build_ollama_chat_options(
                        model=model_name,
                        role=role,
                        temperature=float(temperature),
                        max_tokens=int(max_tokens),
                    ),
                )
            content = (resp.get("message", {}) or {}).get("content", "") or ""
            self._record_model_success(model_name)
            if isinstance(tool_events, list):
                tool_events.append({"tool": "model.router", "status": "used", "detail": f"model={model_name};attempt={attempt}"})
            return content
        except Exception as exc:
            last_error = exc
            self._record_model_failure(model_name)
            retryable = self._is_retryable_model_error(exc)
            is_last = attempt >= len(attempt_models)
            if is_last or (not bool(MODEL_FAILOVER_ENABLED)) or (not retryable):
                break
            if isinstance(tool_events, list):
                tool_events.append({"tool": "model.failover", "status": "retry", "detail": f"model={model_name};error={type(exc).__name__}"})
            continue

    if last_error is not None:
        logger.exception(f"Ollama chat failed after failover attempts: {type(last_error).__name__}: {last_error}")
    return "Sorry - generation failed. Try again."
