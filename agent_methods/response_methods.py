from __future__ import annotations

"""Extracted Agent methods from agents.py (response_methods.py)."""

async def generate_response(
    self,
    prompt: str,
    user_id: str = "default_user",
    dementia_friendly: bool = False,
    long_form: bool = False,
    forced_skill_keys: Optional[List[str]] = None,
    image_spec: Optional[Dict[str, Any]] = None,
) -> str:
    start_total = time.time()
    self.turn_counter += 1
    prompt = (prompt or "").strip()
    if not prompt:
        return "Hey, give me something to work with!"
    # Call-level user_id override (Telegram/WhatsApp multi-chat)
    active_user_id = str(user_id or self.user_id)
    prompt_lower = prompt.lower()
    self._set_last_attachments(active_user_id, [])
    tool_events: List[Dict[str, Any]] = []
    search_citation_map: List[Dict[str, Any]] = []
    search_evidence_contract: Dict[str, Any] = {}
    correction_note, corrected_intent_text = self._extract_user_correction(prompt)
    routing_prompt = corrected_intent_text or prompt
    thread_id = derive_thread_id(routing_prompt)
    turn_trace = self._start_turn_trace(
        prompt=prompt,
        active_user_id=active_user_id,
        thread_id=thread_id,
        routing_prompt=routing_prompt,
        metadata={"entrypoint": "generate_response"},
    )
    decision_route = ""

    def emit_state_event(event_type: str, event_name: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._record_state_event(
            trace=turn_trace,
            event_type=event_type,
            event_name=event_name,
            payload=payload or {},
        )

    def finish_response(
        response_text: str,
        *,
        status: str = "completed",
        route_override: str = "",
        model_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self._finish_turn_trace(
            trace=turn_trace,
            prompt=prompt,
            routing_prompt=routing_prompt,
            content=response_text,
            status=status,
            route=(route_override or decision_route or ""),
            model_name=model_name,
            tool_events=tool_events,
            latency_ms=int((time.time() - start_total) * 1000),
            metadata=metadata or {},
        )
    subagent_cmd = self._handle_subagent_command(
        prompt,
        active_user_id=active_user_id,
        thread_id=thread_id,
        turn_trace=turn_trace,
    )
    if subagent_cmd.get("handled"):
        tool_event = subagent_cmd.get("tool_event")
        if isinstance(tool_event, dict) and tool_event:
            tool_events.append(tool_event)
        event_type = str(subagent_cmd.get("event_type") or "").strip()
        event_name = str(subagent_cmd.get("event_name") or event_type or "subagent")
        if event_type:
            emit_state_event(event_type, event_name, dict(subagent_cmd.get("event_payload") or {}))
        return finish_response(
            str(subagent_cmd.get("response") or ""),
            status=str(subagent_cmd.get("turn_status") or "completed"),
            route_override="subagent_command",
            metadata=dict(subagent_cmd.get("metadata") or {}),
        )
    coding_cmd = self._handle_coding_command_or_intent(
        prompt,
        active_user_id=active_user_id,
        thread_id=thread_id,
        turn_trace=turn_trace,
        source=str(getattr(self, "_last_request_source", "chat") or "chat"),
    )
    if coding_cmd.get("handled"):
        tool_event = coding_cmd.get("tool_event")
        if isinstance(tool_event, dict) and tool_event:
            tool_events.append(tool_event)
        event_type = str(coding_cmd.get("event_type") or "").strip()
        event_name = str(coding_cmd.get("event_name") or event_type or "coding_session")
        if event_type:
            emit_state_event(event_type, event_name, dict(coding_cmd.get("event_payload") or {}))
        return finish_response(
            str(coding_cmd.get("response") or ""),
            status=str(coding_cmd.get("turn_status") or "completed"),
            route_override="coding_mode",
            metadata=dict(coding_cmd.get("metadata") or {}),
        )
    starter_cmd = self._handle_starter_command_or_intent(
        prompt,
        active_user_id=active_user_id,
        source=str(getattr(self, "_last_request_source", "chat") or "chat"),
    )
    if starter_cmd.get("handled"):
        event_type = str(starter_cmd.get("event_type") or "").strip()
        event_name = str(starter_cmd.get("event_name") or event_type or "starter_guide")
        if event_type:
            emit_state_event(event_type, event_name, dict(starter_cmd.get("event_payload") or {}))
        return finish_response(
            str(starter_cmd.get("response") or ""),
            status=str(starter_cmd.get("turn_status") or "completed"),
            route_override="starter_guide",
            metadata=dict(starter_cmd.get("metadata") or {}),
        )
    # ==================== SMART CONTEXTUAL FOLLOW-UPS v3.0 ====================
    follow_ctx = self.tool_context_store.get(active_user_id)
    follow_resolution = None
    if getattr(self, "enable_smart_followups", True):
        follow_resolution = self.followup_resolver.resolve(routing_prompt, follow_ctx)

    force_followup_search = False

    if follow_resolution:
        if follow_resolution.action == "clarify":
            opts = follow_resolution.clarify_options or []
            lines = ["I found multiple possible matches from the last search. Reply with the number:"]
            for o in opts[:5]:
                lines.append(f"{o.get('rank')}. {o.get('title')[:90]}")
            emit_state_event("followup_clarify", "followup_clarify", {"option_count": len(opts)})
            return finish_response(
                "\n".join(lines),
                status="needs_clarification",
                route_override="followup_clarify",
            )

        elif follow_resolution.action in ("open_url_and_summarize", "continue_topic") and follow_resolution.rewritten_query:
            routing_prompt = follow_resolution.rewritten_query
            if follow_resolution.selected_url:
                self.tool_context_store.mark_selected(
                    active_user_id,
                    rank=int(follow_resolution.selected_index or 0),
                    url=str(follow_resolution.selected_url or ""),
                )
            # Force websearch only when opening a URL; for continue_topic, allow router
            # to choose the fastest suitable path (preserves low-latency internal answers).
            force_followup_search = follow_resolution.action == "open_url_and_summarize"
            # Optional: log for debugging
            # print(f"[FOLLOWUP] {follow_resolution.action} | {follow_resolution.context_note}")
    if correction_note:
        self._enqueue_memory_write(
            prompt=f"Correction signal: {prompt}",
            content=correction_note,
            active_user_id=active_user_id,
            should_search=False,
        )
    controller_context = {"user_id": active_user_id}
    pending_ticket = self._pending_tickets_by_user.get(active_user_id)
    if pending_ticket is None:
        pending_ticket = self._load_pending_ticket(active_user_id)
        if pending_ticket is not None:
            self._pending_tickets_by_user[active_user_id] = pending_ticket
    if pending_ticket is not None:
        controller_context["pending_ticket"] = pending_ticket
    toolbox_run = re.match(r"^run tool\s+([a-zA-Z0-9_\-]+)(?:\s+(.*))?$", prompt.strip(), flags=re.IGNORECASE)
    if toolbox_run:
        tool_name = toolbox_run.group(1)
        tool_args = {"name": (toolbox_run.group(2) or "friend").strip()}
        try:
            proposed_ticket = ToolLoader().propose_exec(tool_name, tool_args, job_id=f"chat-{active_user_id}")
            controller_context["proposed_ticket"] = proposed_ticket
        except Exception as e:
            return finish_response(
                f"Unable to prepare tool proposal safely: {e}",
                status="blocked",
                route_override="controller_prepare_failed",
            )
    decision = decide_route(routing_prompt, agent_state={"mode": self.current_mode, "last_tool_type": (follow_ctx.last_tool_type if follow_ctx else ""), "has_tool_context": bool(follow_ctx and follow_ctx.last_results)})
    decision_route = str(decision.route or "")
    self._log_route_snapshot(user_id=active_user_id, prompt=routing_prompt, decision=decision, last_tool_type=(follow_ctx.last_tool_type if follow_ctx else ""))
    capulet_requested = bool(decision.signals.get("capulet_artifact_type"))
    requires_execution = bool(decision.signals.get("requires_execution", False))
    read_only_fast_path = bool(decision.signals.get("read_only", False) and not toolbox_run)
    istari_started = time.time()
    istari_handled, istari_text = self.istari_protocol.handle(prompt, active_user_id, toolbox_run_match=toolbox_run)
    istari_ms = (time.time() - istari_started) * 1000.0
    if istari_handled:
        self._perf_samples.append({"turn": float(self.turn_counter), "route": "istari", "controller_ms": 0.0, "istari_ms": istari_ms, "read_only_fast_path": read_only_fast_path})
        if len(self._perf_samples) > 300:
            self._perf_samples = self._perf_samples[-300:]
        emit_state_event("route_handled", "istari", {"istari_ms": round(istari_ms, 3)})
        return finish_response(
            istari_text,
            route_override="istari",
            metadata={"istari_ms": round(istari_ms, 3)},
        )
    approval_like = bool(re.match(r"^(approve(\s+&\s+run|\s+patch)?|deny|reject|revoke|cancel)\b", prompt.strip(), flags=re.IGNORECASE))
    should_invoke_controller = bool(toolbox_run or requires_execution or approval_like)
    if should_invoke_controller:
        ctl_started = time.time()
        control = handle_turn(prompt, controller_context)
        ctl_ms = (time.time() - ctl_started) * 1000.0
        if control.action_package and control.action_package.get("ticket_hash") and controller_context.get("proposed_ticket") is not None:
            self._pending_tickets_by_user[active_user_id] = controller_context["proposed_ticket"]
            self._persist_pending_ticket(active_user_id, controller_context["proposed_ticket"])
        if control.action_package and control.action_package.get("execute") and pending_ticket is not None:
            try:
                receipt = ApprovalReceipt(
                    ticket_hash=control.action_package.get("ticket_hash", ""),
                    confirmation_method="typed_phrase",
                    timestamp=self.time_handler.get_system_date_time(),
                    typed_phrase=prompt,
                )
                result = ToolLoader().execute_with_approval(pending_ticket, receipt)
                self._pending_tickets_by_user.pop(active_user_id, None)
                self._clear_pending_ticket(active_user_id)
                tool_events.append({"tool": "controller.execution", "status": "ok", "detail": "approved_execution"})
                return finish_response(
                    f"{control.response_text}\nExecution result: {json.dumps(result)}",
                    route_override="controller_execute",
                    metadata={"controller_ms": round(ctl_ms, 3)},
                )
            except Exception as e:
                tool_events.append({"tool": "controller.execution", "status": "blocked", "detail": type(e).__name__})
                return finish_response(
                    f"{control.response_text} Execution blocked: {type(e).__name__}: {e}",
                    status="blocked",
                    route_override="controller_execute",
                    metadata={"controller_ms": round(ctl_ms, 3)},
                )
        if control.handled:
            if prompt_lower.strip() == "cancel":
                self._pending_tickets_by_user.pop(active_user_id, None)
                self._clear_pending_ticket(active_user_id)
            self._perf_samples.append({"turn": float(self.turn_counter), "route": str(decision.route), "controller_ms": ctl_ms, "istari_ms": istari_ms, "read_only_fast_path": read_only_fast_path})
            if len(self._perf_samples) > 300:
                self._perf_samples = self._perf_samples[-300:]
            tool_events.append({"tool": "controller", "status": "ok", "detail": "handled_turn"})
            return finish_response(
                control.response_text,
                route_override="controller",
                metadata={"controller_ms": round(ctl_ms, 3)},
            )
    self._perf_samples.append({"turn": float(self.turn_counter), "route": str(decision.route), "controller_ms": 0.0, "istari_ms": istari_ms, "read_only_fast_path": read_only_fast_path})
    if len(self._perf_samples) > 300:
        self._perf_samples = self._perf_samples[-300:]
    if self.turn_counter % 40 == 0 and self._perf_samples:
        ro = [x for x in self._perf_samples if bool(x.get("read_only_fast_path"))]
        if ro:
            avg = sum(float(x.get("controller_ms") or 0.0) for x in ro) / max(1, len(ro))
            logger.info(f"Perf(read_only_fast_path): n={len(ro)} avg_controller_ms={avg:.3f}")
    skill_cmd = handle_skill_command(prompt)
    if skill_cmd.handled:
        if skill_cmd.forced_skill_keys:
            self._forced_skill_keys_by_user[active_user_id] = list(skill_cmd.forced_skill_keys)
        tool_events.append({"tool": "skill.command", "status": "ok", "detail": "handled"})
        return finish_response(skill_cmd.response, route_override="skill_command")
    self._ensure_async_clients_for_current_loop()
    if self.turn_counter % 25 == 0:
        if self._maintenance_task is None or self._maintenance_task.done():
            self._maintenance_task = asyncio.create_task(self._maintenance_tick())
    # Mode toggles
    if self.current_mode == "normal":
        if prompt_lower == "tell me a story":
            self.current_mode = "story"
            self.story_iterations = 0
        elif any(x in prompt_lower for x in ["lets play hangman", "let's play hangman", "play hangman", "start hangman"]):
            if self.wordgame.start_game("hangman"):
                self.current_mode = "game"
            else:
                return finish_response(
                    "Oops, something went wrong starting Hangman. Try again!",
                    status="failed",
                    route_override="game",
                )
    cmd = prompt_lower.strip()
    if cmd in ("stop", "end", "quit"):
        if self.current_mode == "game":
            self.wordgame.clear_game_state()
            self.current_mode = "normal"
            return finish_response("Game ended. What's next?", route_override="game")
        if self.current_mode == "story":
            self.current_mode = "normal"
            self.story_iterations = 0
            try:
                if os.path.exists(self.story_file):
                    os.remove(self.story_file)
            except Exception:
                pass
            return finish_response("Story ended. What's next?", route_override="story")
    # Game path
    if self.current_mode == "game":
        game_response, game_ended = self.wordgame.process_game_input(prompt)
        if game_response:
            self._push_history_for(active_user_id, prompt, game_response)
            if game_ended:
                self.current_mode = "normal"
            return finish_response(game_response, route_override="game")
    if ROUTING_DEBUG:
        logger.info(f"Routing decision: route={decision.route} veto={decision.tool_veto} reason={decision.reason} signals={decision.signals}")
    artifact_intent = None
    artifact_confidence = 0.0
    force_websearch_for_research = False
    artifact_trigger_reason = {}
    if ENABLE_NL_ARTIFACTS:
        try:
            has_doc = bool(self.rag and getattr(self.rag, "texts", None))
            intent_decision = self.artifact_detector.detect(
                routing_prompt,
                decision.route,
                has_doc=has_doc,
            )
            artifact_intent = intent_decision.artifact_intent
            artifact_confidence = float(intent_decision.confidence)
            artifact_trigger_reason = dict(getattr(intent_decision, "trigger_reason", {}) or {})
            if ROUTING_DEBUG:
                logger.info(
                    f"Artifact intent: intent={artifact_intent} conf={artifact_confidence:.2f} reason={intent_decision.reason}"
                )
        except Exception as e:
            logger.debug(f"Artifact intent detection failed (non-fatal): {e}")
    if self._should_force_research_websearch(decision.route, artifact_intent):
        force_websearch_for_research = True
        if ROUTING_DEBUG:
            logger.info("Artifact intent requested route upgrade: forcing websearch for research_brief")
    idx_snapshot = None
    if ENABLE_NL_ARTIFACTS and not capulet_requested:
        try:
            continuity_signals = {
                "route": decision.route,
                "artifact_intent": artifact_intent,
                "thread_id": None,
                "tags": suggest_tags(user_text=routing_prompt, artifact_type=artifact_intent or "", strong_continuity=True),
            }
            idx_snapshot = self.artifact_store.get_index_snapshot()
            cres = maybe_emit_continuity_artifact(routing_prompt, continuity_signals, idx_snapshot)
            if cres.artifact:
                c_art = cres.artifact
                c_art["tags"] = normalize_tags(c_art.get("tags") or [])
                self.artifact_store.append(active_user_id, c_art)
                emit_state_event(
                    "artifact_created",
                    str(c_art.get("artifact_type") or c_art.get("contract_name") or "artifact"),
                    c_art,
                )
                markdown = validate_and_render(c_art)
                self._push_history_for(active_user_id, prompt, markdown)
                return finish_response(markdown, route_override="continuity_artifact")
        except Exception as e:
            logger.debug(f"Continuity engine failed (non-fatal): {e}")
    active_persona_for_turn = {"temperature": self.temperature}
    if not capulet_requested:
        try:
            profile, active_persona_key, active_persona = self._refresh_profile_and_persona()
            active_persona_for_turn = dict(active_persona or {})
            hb_art = self.heartbeat_engine.choose_artifact(
                user_text=routing_prompt,
                route=decision.route,
                idx_snapshot=idx_snapshot or self.artifact_store.get_index_snapshot(),
                profile=profile,
                active_persona_key=active_persona_key,
                persona=active_persona,
                first_interaction_of_day=self._heartbeat_first_interaction_of_day(active_user_id, profile),
            )
            if hb_art is not None:
                self.artifact_store.append(active_user_id, hb_art)
                emit_state_event(
                    "artifact_created",
                    str(hb_art.get("artifact_type") or hb_art.get("contract_name") or "artifact"),
                    hb_art,
                )
                hb_type = str(hb_art.get("artifact_type") or hb_art.get("contract_name") or "")
                if hb_type == "daily_brief":
                    self.assistant_profile["last_brief_date"] = datetime.now(timezone.utc).date().isoformat()
                self.assistant_profile["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
                save_assistant_profile(self.assistant_profile)
                markdown = validate_and_render(hb_art)
                self._push_history_for(active_user_id, prompt, markdown)
                return finish_response(markdown, route_override="heartbeat_artifact")
        except Exception as e:
            logger.debug(f"Heartbeat engine failed (non-fatal): {e}")
    capulet_type = str(decision.signals.get("capulet_artifact_type") or "").strip()
    if capulet_type:
        try:
            cp = self._get_latest_montague_context_context_pack()
            allowed_ids = [str(x) for x in list(cp.get("relevant_artifact_ids") or [])[:12] if str(x)]
            allowed_set = set(allowed_ids)
            exists_fn = lambda aid: str(aid) in allowed_set
            plan_id = ""
            if capulet_type == "plan_revision":
                prev_plan = self.artifact_store.get_last(active_user_id, "plan") or {}
                plan_id = str(prev_plan.get("artifact_id") or "")
            option_a, option_b = self._extract_tradeoff_options(routing_prompt)
            capulet_artifact = self.strategic_planner.plan(
                user_text=routing_prompt,
                context_pack_v1=cp,
                allowed_artifact_ids=allowed_ids,
                exists_fn=exists_fn,
                artifact_type=capulet_type,
                original_plan_id=plan_id,
                option_a=option_a,
                option_b=option_b,
            )
            envelope = {
                "contract_name": str(capulet_artifact.get("type") or capulet_type),
                "artifact_type": str(capulet_artifact.get("type") or capulet_type),
                "content": capulet_artifact,
                "status": "unknown",
                "tags": suggest_tags(user_text=routing_prompt, artifact_type=str(capulet_artifact.get("type") or capulet_type)),
                "thread_id": derive_thread_id(routing_prompt),
                "trigger_reason": {"explicit_request": True, "matched_phrases": ["capulet"], "structural_signals": ["routing_signal"]},
            }
            self.artifact_store.append(active_user_id, envelope)
            emit_state_event(
                "artifact_created",
                str(envelope.get("artifact_type") or capulet_type or "artifact"),
                envelope,
            )
            payload = json.dumps(capulet_artifact, ensure_ascii=False)
            if bool(STRATEGIC_HUMAN_SUMMARY_ENABLED):
                summary = render_human_summary(capulet_artifact)
                display_text = payload + "\n\n" + summary
            else:
                display_text = payload
            # Keep persisted strategic payload in history lean/structured to avoid
            # markdown summary cluttering subsequent context windows.
            self._push_history_for(active_user_id, prompt, payload)
            return finish_response(display_text, route_override="capulet_artifact")
        except Exception as e:
            logger.warning(f"Capulet strategic planning failed; continuing standard path: {type(e).__name__}: {e}")
    if decision.route == "command":
        cmd = prompt_lower.strip()
        if cmd == "memory doctor":
            try:
                report = await self.memory.memory_doctor(prompt, user_id=active_user_id)
                self._push_history_for(active_user_id, prompt, report)
                return finish_response(report, route_override="memory_doctor")
            except Exception as e:
                msg = f"Memory doctor failed: {type(e).__name__}: {e}"
                self._push_history_for(active_user_id, prompt, msg)
                return finish_response(msg, status="failed", route_override="memory_doctor")
    if decision.route == "local_memory_intent":
        try:
            local = await self._route_local_memory_intents(prompt, active_user_id)
            if local:
                self._push_history_for(active_user_id, prompt, local)
                return finish_response(local, route_override="local_memory_intent")
        except Exception as e:
            logger.debug(f"Local intent routing failed (non-fatal): {e}")
    force_image_from_spec = image_spec is not None
    should_try_image = force_image_from_spec or decision.route == "image_tool" or (decision.route == "conversion_tool" and self._is_chart_keyword_prompt(prompt_lower))
    if should_try_image:
        spec = self._safe_build_image_spec(prompt, image_spec=image_spec)
        if spec is not None:
            try:
                from workshop.toolbox.stacks.image_core.image_generate import generate_image
                attachments = await asyncio.to_thread(generate_image, spec)
                self._set_last_attachments(active_user_id, attachments)
            except Exception as e:
                logger.debug(f"Image generation route failed (non-fatal): {e}")
    if decision.route == "conversion_tool":
        try:
            if self.websearch is None or getattr(self.websearch, "converter", None) is None:
                raise RuntimeError("websearch unavailable")
            async with asyncio.timeout(20.0):
                conv_result = await self.websearch.converter.convert(routing_prompt)
            if conv_result and "Error" not in conv_result and len(conv_result.strip()) > 5:
                self._push_history_for(active_user_id, prompt, conv_result)
                tool_events.append({"tool": "finance.converter", "status": "ok", "detail": "early_conversion"})
                return finish_response(
                    conv_result + "\n(Source: real-time finance data)",
                    route_override="conversion_tool",
                )
        except Exception as e:
            logger.debug(f"Early conversion failed: {e}")
    detail_keywords = ["explain", "detail", "in-depth", "detailed", "elaborate", "expand", "clarify", "iterate"]
    long_form = long_form or any(k in prompt_lower for k in detail_keywords) or self.current_mode == "story"
    base_max_tokens = 650 if long_form or self.current_mode == "story" else 260
    intent_hint = str((decision.signals or {}).get("intent") or "").strip().lower()
    if (
        follow_ctx
        and follow_ctx.last_tool_type == "finance"
        and self._looks_like_historical_price_followup(routing_prompt)
        and (self._is_finance_intent_hint(intent_hint) or self._looks_like_finance_followup(routing_prompt))
    ):
        if self.websearch is None or getattr(self.websearch, "finance_handler", None) is None:
            hist_res = []
        else:
            hist_res = await self.websearch.finance_handler.search_historical_price(routing_prompt)
        if hist_res:
            self.tool_context_store.set(active_user_id, "finance", routing_prompt, hist_res)
            hist_text = self.websearch.format_results(hist_res)

            if self._looks_like_tool_dump(hist_text):
                hist_text = await self._naturalize_search_output(hist_text, prompt)

            self._push_history_for(active_user_id, prompt, hist_text)
            tool_events.append({"tool": "finance.history", "status": "ok", "detail": "historical_followup"})
            return finish_response(hist_text, route_override="finance_history")
    plan = build_query_plan(routing_prompt)
    plan_state = ensure_plan_state(
        active_user_id,
        thread_id,
        prompt=routing_prompt,
        state=load_plan_state(active_user_id, thread_id),
    )
    task_graph = load_task_graph(active_user_id, thread_id)
    logger.info(
        "QUERY_PLAN MODE=%s NEEDS_RECENCY=%s TIME_ANCHOR=%s EVIDENCE_ENABLED=%s REASON=%s",
        plan.mode,
        plan.needs_recency,
        plan.time_anchor,
        plan.evidence_enabled,
        plan.reason,
    )
    # Pipeline: user_text -> decide_route/build_query_plan -> websearch.search -> SearchBundle render -> PromptForge.build_system_prompt.
    should_search = (
        plan.mode in {"SEARCH_ONLY", "DUAL"}
        or force_websearch_for_research
        or force_followup_search
    )
    search_context = ""
    memory_context = "No relevant memories found"
    results: List[Dict[str, Any]] = []
    volatile_search = False
    volatile_category = "general"
    if should_search:
        planned_query = getattr(plan, "search_query", "") or routing_prompt
        try:
            orchestration_budget = ToolOrchestrationBudget(
                max_calls=2,
                max_elapsed_seconds=18.0,
                max_input_chars=4500,
                allow_parallel=bool(getattr(self, "_allow_parallel_tools", True)),
            )
            specs = [
                ToolCallSpec(
                    tool_name="web.intelligence",
                    args={
                        "query": planned_query,
                        "tool_veto": bool(decision.tool_veto),
                        "reason": str(decision.reason or ""),
                        "signals": dict(decision.signals or {}),
                        "route_hint": str(decision.route or ""),
                    },
                    read_only=True,
                    tag="primary",
                )
            ]

            orchestrated = await run_tool_chain(
                run_tool=lambda tool_name, args, ctx: self._run_tool_with_loop_guard(
                    tool_name=tool_name,
                    args=args,
                    ctx=ctx,
                    active_user_id=active_user_id,
                ),
                specs=specs,
                ctx={
                    "source": "agent",
                    "approved": True,
                    "user_id": active_user_id,
                    "channel": "chat",
                    "backend": "local",
                },
                budget=orchestration_budget,
                retryable_check=lambda exc: "timeout" in str(exc).lower() or "connection" in str(exc).lower(),
                registry=getattr(self.toolbox_runtime, "registry", None),
            )
            tool_events.extend(list(orchestrated.events or []))

            primary_out = {}
            for row in list(orchestrated.outputs or []):
                if str(row.get("tool") or "") == "web.intelligence":
                    primary_out = dict(row.get("output") or {})
                    break

            if bool(primary_out):
                results = list(primary_out.get("results") or [])
                search_citation_map = list(primary_out.get("citation_map") or [])
                search_evidence_contract = dict(primary_out.get("evidence_contract") or {})
                formatted = str(primary_out.get("formatted") or "")
                volatile_search, volatile_category = self._is_volatile_results(results)
                tool_type = str((decision.signals or {}).get("intent") or volatile_category or "general")
                if tool_type in {"crypto", "forex", "stock/commodity"}:
                    tool_type = "finance"
                self.tool_context_store.set(active_user_id, tool_type, routing_prompt, results)
                if formatted and "Error" not in formatted:
                    search_cap = max(120, int(BUDGET_SEARCH_TOKENS) * 4)
                    search_context = formatted[:search_cap] if plan.evidence_enabled else ""
                else:
                    search_context = ""
            else:
                raise RuntimeError("empty web.intelligence output")

        except Exception:
            try:
                if self.websearch is None:
                    raise RuntimeError("websearch unavailable")
                results = await self.websearch.search(
                    planned_query,
                    tool_veto=decision.tool_veto,
                    reason=decision.reason,
                    signals=decision.signals,
                    route_hint=decision.route,
                )
                volatile_search, volatile_category = self._is_volatile_results(results)
                bundle = self.websearch.to_search_bundle(planned_query, results, time_anchor=plan.time_anchor, exactness_requested=plan.evidence_enabled)
                formatted = render_search_bundle(bundle, max_results=5, max_snippet_chars=320)
                tool_type = str(decision.signals.get("intent") or volatile_category or "general")
                if tool_type in {"crypto", "forex", "stock/commodity"}:
                    tool_type = "finance"
                self.tool_context_store.set(active_user_id, tool_type, routing_prompt, results)
                if formatted and "Error" not in formatted:
                    search_cap = max(120, int(BUDGET_SEARCH_TOKENS) * 4)
                    search_context = formatted[:search_cap] if plan.evidence_enabled else ""
                else:
                    search_context = ""
            except Exception as e:
                logger.info(f"Web search failed (non-fatal): {e}")
                search_context = ""

    else:
        mem = await self.memory.build_injected_context(routing_prompt, user_id=active_user_id, thread_hint=thread_id)
        due_block = ""
        if self._should_inject_due_context(prompt, active_user_id):
            peek_due = getattr(self.memory, "peek_due_reminders", None)
            due = await peek_due(active_user_id, limit=3) if callable(peek_due) else []
            if due:
                due_lines = [f"- {d.get('title','Reminder')} (due {self._format_due_ts_local(str(d.get('due_ts','soon')))})" for d in due[:3]]
                due_block = "\n".join(due_lines)
                self._mark_due_context_injected(active_user_id)
                emit_state_event(
                    "reminder_due",
                    "due_context_injected",
                    {"count": len(due[:3]), "items": due[:3]},
                )
        if mem and due_block:
            memory_context = f"[Due reminders]\n{due_block}\n\n[Memory]\n{mem}"
        elif mem:
            memory_context = mem
        elif due_block:
            memory_context = f"[Due reminders]\n{due_block}"
        mem_cap = max(120, int(BUDGET_MEMORY_TOKENS) * 4)
        if len(memory_context) > mem_cap:
            memory_context = memory_context[:mem_cap]
    rag_block = self._build_rag_block(routing_prompt, k=2)
    current_time = self.time_handler.get_system_date_time()
    identity_block = self._compose_identity_block()
    mode_context = "Normal mode."
    if self.current_mode == "story":
        mode_context = "Story mode active. Continue the story coherently. End with 'Want more?'"
    extra_blocks = []
    ledger_block = self._state_ledger_block(active_user_id)
    if ledger_block:
        extra_blocks.append(ledger_block)
    extra_blocks.append(render_plan_block(plan_state, max_items=4))
    extra_blocks.append(render_task_graph_block(task_graph, max_items=8))
    extra_blocks.append(
        "## Skills\n"
        "Skills are available via /skill list and runnable with /skill run <name> ..."
    )
    extra_blocks.append(
        "## Skills/Toolbox Truthfulness Rules\n"
        "- Only say a skill/tool was executed if dispatch returned a concrete result.\n"
        "- If blocked, ineligible, or dry-run, state that clearly and provide next safe step.\n"
        "- Prefer /skill commands for user-requested automations over ad-hoc claims."
    )
    extra_blocks.append(
        "## Image Tool Contract\n"
        "When user asks for chart/graph/plot, emit strict JSON only (no prose in JSON):\n"
        "{\n"
        "  \"tool\": \"image.generate\",\n"
        "  \"spec\": {\n"
        "    \"kind\": \"bar\",\n"
        "    \"title\": \"Seizures per month\",\n"
        "    \"labels\": [\"Jan\", \"Feb\", \"Mar\"],\n"
        "    \"values\": [12, 9, 15],\n"
        "    \"y_label\": \"Count\"\n"
        "  }\n"
        "}"
    )
    try:
        skills_snapshot = build_registry_snapshot()
        skill_lines = []
        for item in skills_snapshot.get("snapshot", {}).get("eligible", [])[:20]:
            emoji = (item.get("emoji") or "").strip()
            prefix = f"{emoji} " if emoji else ""
            skill_lines.append(f"- {prefix}{item.get('name')} ({item.get('key')}): {item.get('desc')}")
        if skill_lines:
            extra_blocks.append("## Skills Catalog\n" + "\n".join(skill_lines))
    except Exception:
        pass
    forced_keys_effective = forced_skill_keys or self._forced_skill_keys_by_user.pop(active_user_id, [])
    if forced_keys_effective:
        try:
            skill_state = build_registry_snapshot()
            eligible = skill_state.get("eligible", {})
            inject_blocks = []
            for key in forced_keys_effective:
                doc = eligible.get(key)
                if doc and doc.body_md:
                    inject_blocks.append(f"### Skill: {doc.name} ({doc.skill_key})\n{doc.body_md}")
            if inject_blocks:
                extra_blocks.append("## Forced Skill Guidance\n" + "\n\n".join(inject_blocks))
        except Exception:
            pass
    if rag_block:
        extra_blocks.append(rag_block)
    extra_blocks.append(
        "## Reminder/Goal Rules (STRICT)\n"
        "- Do not mention reminders or goals unless the user asked about them OR a [Due reminders] block is present.\n"
        "- Do not estimate due times. If mentioning a due time, use only the exact due_ts shown in context.\n"
    )
    include_goal_context = self._is_personal_memory_query(routing_prompt) or ("[Due reminders]" in memory_context)
    if include_goal_context:
        try:
            goal_ctx = await self.memory.build_goal_context(active_user_id, scope="task", limit=3)
            if goal_ctx:
                extra_blocks.append("## Active Goals\n" + goal_ctx)
        except Exception:
            pass
    if should_search and plan.evidence_enabled and search_context.strip():
        sources = self._extract_urls_from_results(results, limit=4)
        sources_text = "\n".join([f"- {u}" for u in sources]) if sources else "(No URLs available in results.)"
        evidence_rules = (
            "## Evidence Rules (STRICT)\n"
            "You MUST follow these rules when Web/Search Context is present:\n"
            "1) Use ONLY facts found in Web/Search Context. Do NOT guess or fill in missing details.\n"
            "2) If something is not in the results, say you cannot verify it from the search results.\n"
            "3) For volatile data (prices, rates, weather, breaking news, scientific citations/guidelines): do NOT invent numbers. If you cite a number, it must appear verbatim in the results.\n"
            "4) Include source URL(s) for the claims you make.\n"
            f"Category hint: {volatile_category}\n"
            "Sources available:\n"
            f"{sources_text}\n"
        )
        extra_blocks.append(evidence_rules)
    history_keep = int(HISTORY_MAX_MESSAGES or 10)
    history_msgs = self._history_for_prompt(active_user_id, max_messages=history_keep)
    history_for_system = history_msgs if (PROMPT_ENTERPRISE_ENABLED and not PROMPT_FORCE_LEGACY) else None
    system_prompt = self.promptforge.build_system_prompt(
        identity_block=identity_block,
        current_time=current_time,
        memory_context=memory_context,
        search_context=search_context,
        mode_context=mode_context,
        extra_blocks=extra_blocks if extra_blocks else None,
        history=history_for_system,
        mode="EXECUTE",
        privilege="SAFE",
        evidence_enabled=plan.evidence_enabled,
        query_plan_summary=plan.summary(),
    )
    system_prompt += (
        "\n\nFor currency or crypto conversions (like \"100 AUD to TTD\" or \"0.5 BTC to ETH\"): "
        "please use the finance/conversion tools or search for current rates â€” old numbers from training are usually wrong."
    )
    max_tokens = self._token_budget(routing_prompt, system_prompt, base_max_tokens)
    perf_policy = self.performance_controller.policy_for_turn(
        requested_max_tokens=int(max_tokens),
        should_search=bool(should_search),
    )
    self._current_response_timeout_s = float(perf_policy.response_timeout_seconds)
    self._allow_parallel_tools = bool(perf_policy.allow_parallel_tools)
    max_tokens = min(int(max_tokens), int(perf_policy.max_output_tokens))
    messages = self.promptforge.build_messages(
        system_prompt=system_prompt,
        history=[] if (PROMPT_ENTERPRISE_ENABLED and not PROMPT_FORCE_LEGACY) else history_msgs,
        user_prompt=routing_prompt,
    )
    try:
        est = getattr(self.promptforge, "_estimate_tokens")
        sys_est = int(est(system_prompt))
        mem_est = int(est(memory_context))
        search_est = int(est(search_context))
        hist_est = int(sum(est(str(m.get("content", ""))) for m in history_msgs))
        total_est = int(sys_est + hist_est + est(routing_prompt) + int(BUDGET_OUTPUT_RESERVE_TOKENS or 320))
        logger.info(f"Budget est tokens: system={sys_est} memory={mem_est} search={search_est} history={hist_est} total={total_est}")
    except Exception:
        pass
    direct_tool_reply = ""
    if should_search:
        direct_tool_reply = self._render_direct_volatile_answer(
            results=results,
            intent_hint=intent_hint,
        )

        # If no evidence arrived, do not let the model improvise volatile live facts.
        if plan.evidence_enabled and not direct_tool_reply and not str(search_context or "").strip():
            if intent_hint in {"crypto", "forex", "stock/commodity"}:
                direct_tool_reply = "I couldn't fetch live finance data right now. Please retry in a moment."
            elif intent_hint == "weather":
                direct_tool_reply = "I couldn't fetch live weather data right now. Please retry in a moment."
            elif intent_hint == "news":
                direct_tool_reply = "I couldn't fetch live news results right now. Please retry in a moment."

    validator_issues: List[str] = []
    if direct_tool_reply:
        content = direct_tool_reply
    else:
        content = await self._chat_with_model_failover(
            prompt=routing_prompt,
            messages=messages,
            should_search=bool(should_search),
            route=str(decision.route or "llm_only"),
            memory_intent=bool(self._is_personal_memory_query(routing_prompt)),
            temperature=0.0 if should_search else self._safe_temperature_value(active_persona_for_turn.get("temperature", self.temperature), float(self.temperature)),
            max_tokens=int(max_tokens),
            tool_events=tool_events,
        )

        if self._looks_like_tool_dump(content):
            content = await self._naturalize_search_output(content, prompt)

        evidence_bundle = locals().get("bundle") if "bundle" in locals() else None
        content = mix_answer(routing_prompt, plan=plan, llm_draft=content, evidence=evidence_bundle)

        content = self._clean_think_tags(content)
        content = self._strip_unwanted_json(content)
        content = self._enforce_web_evidence_output(
            content=content,
            should_search=should_search,
            evidence_contract=search_evidence_contract,
            citation_map=search_citation_map,
        )
        content, validator_issues = validate_and_repair_answer(
            content=content,
            intent=str((decision.signals or {}).get("intent") or "general"),
            should_search=bool(should_search),
            evidence_contract=search_evidence_contract,
            citation_map=search_citation_map,
        )
        if validator_issues:
            tool_events.append({"tool": "answer.validator", "status": "repaired", "detail": f"issues={len(validator_issues)}"})

    if direct_tool_reply:
        content = self._clean_think_tags(content)
        content = self._strip_unwanted_json(content)
    content = self._strip_internal_prompt_leakage(content)

    if self.get_last_attachments(active_user_id):
        content = (content or "").strip()
        addon = f"\n\nSaved chart/image to {SESSION_MEDIA_DIR} and attached it above."
        content = (content + addon).strip() if content else f"Saved chart/image to {SESSION_MEDIA_DIR} and attached it above."
    if should_search and volatile_search and not direct_tool_reply:
        content = self._numeric_guard(content, search_context)
        if "http" not in content.lower():
            urls = self._extract_urls_from_results(results, limit=4)
            if urls:
                content = content.rstrip() + "\n\nSources:\n" + "\n".join([f"- {u}" for u in urls])
    if self.current_mode == "story":
        if not content.endswith("Want more?"):
            content = content.rstrip() + " Want more?"
        self.story_iterations += 1
        if self.story_iterations >= 10:
            self.current_mode = "normal"
            self.story_iterations = 0
            content = content.rstrip() + " And so, the story comes to an end."
    if dementia_friendly:
        if len(content) > 420:
            content = content[:390] + "... (kept short and clear)"
        content = content.replace("however", "but").replace("therefore", "so")
    # Memory write-back: non-blocking to reduce user-perceived latency.
    self._enqueue_memory_write(
        prompt=prompt,
        content=content,
        active_user_id=active_user_id,
        should_search=should_search,
    )
    self._schedule_background_task(
        self._memory_ingest_nonblocking(active_user_id=active_user_id),
        label="memory_ingest",
    )
    if ENABLE_NL_ARTIFACTS and artifact_intent:
        try:
            effective_route = "websearch" if should_search else decision.route
            previous_plan = None
            new_constraints: List[str] = []
            if artifact_intent == "plan" and self._is_plan_revision_followup(prompt):
                previous_plan = self._get_plan_for_revision(active_user_id, prompt)
                if previous_plan:
                    new_constraints = self._extract_plan_revision_constraints(prompt)
            artifact = build_artifact_for_intent(
                artifact_intent=artifact_intent,
                query=routing_prompt,
                route=effective_route,
                answer_text=content,
                raw_search_results=results,
                rag_block=rag_block,
                min_sources=int(MIN_SOURCES_FOR_RESEARCH_BRIEF),
                previous_plan=previous_plan,
                new_constraints=new_constraints,
                trigger_reason=artifact_trigger_reason,
            )
            artifact["tags"] = suggest_tags(user_text=routing_prompt, artifact_type=artifact_intent or "")
            artifact["status"] = "open" if artifact_intent in {"plan", "meeting_summary", "task_state"} else "unknown"
            chosen_thread = choose_thread_id_for_request(
                routing_prompt,
                {
                    "route": decision.route,
                    "artifact_intent": artifact_intent,
                    "thread_id": None,
                    "tags": artifact.get("tags") or [],
                },
                idx_snapshot or self.artifact_store.get_index_snapshot(),
            )
            artifact["thread_id"] = chosen_thread
            if artifact.get("revises_artifact_id"):
                artifact["parent_artifact_id"] = artifact.get("revises_artifact_id")
            emit_task_state = artifact_intent in {"plan", "meeting_summary"} and should_emit_task_state(routing_prompt)
            artifact_to_persist = artifact
            if emit_task_state:
                prev_task_state = self.artifact_store.get_last(active_user_id, "task_state")
                if prev_task_state and str(prev_task_state.get("thread_id") or "") != str(artifact.get("thread_id") or ""):
                    prev_task_state = None
                t_art = build_task_state_from_artifact(
                    source_artifact=artifact,
                    thread_id=str(artifact.get("thread_id") or derive_thread_id(routing_prompt)),
                    previous_task_state=prev_task_state,
                    status_hint_text="\n".join([routing_prompt or "", content or ""]),
                )
                t_art["tags"] = suggest_tags(user_text=routing_prompt, artifact_type="task_state")
                t_art["status"] = "open"
                t_art["thread_id"] = artifact.get("thread_id")
                t_art["parent_artifact_id"] = artifact.get("artifact_id")
                t_art["related_artifact_ids"] = [artifact.get("artifact_id")]
                artifact_to_persist = t_art
            markdown = validate_and_render(artifact_to_persist)
            self.artifact_store.append(active_user_id, artifact_to_persist)
            emit_state_event(
                "artifact_created",
                str(artifact_to_persist.get("artifact_type") or artifact_intent or "artifact"),
                artifact_to_persist,
            )
            self.fact_distiller.distill_and_write(
                artifact_to_persist,
                require_doc_page_refs=bool(DOC_FACTS_REQUIRE_PAGE_REFS),
            )
            if len(markdown) > 6000:
                markdown = markdown[:6000].rstrip() + "\n\n[Artifact truncated for safety]"
            if bool(ONE_ARTIFACT_PER_TURN) and markdown.strip():
                content = markdown
        except Exception as e:
            logger.warning(f"Artifact orchestration failed; returning original response: {type(e).__name__}: {e}")
            if artifact_intent == "research_brief":
                insufficient = "insufficient_sources" in str(e).lower()
                search_issue = "web search unavailable" in str(search_context).lower()
                if (insufficient or search_issue) and bool(ARTIFACT_DEGRADE_NOTICE):
                    content = (content or "").rstrip() + "\n\nI couldnâ€™t fetch enough sources right now, so I answered without citations."
    try:
        plan_state = advance_plan_state(
            plan_state,
            tool_events=tool_events,
            assistant_text=content,
        )
        save_plan_state(active_user_id, thread_id, plan_state)
        emit_state_event(
            "plan_state_changed",
            "plan_state_changed",
            {
                "phase": str(plan_state.get("phase") or ""),
                "tool_call_count": int(plan_state.get("tool_call_count") or 0),
                "stop_reason": str(plan_state.get("stop_reason") or ""),
            },
        )
    except Exception as e:
        logger.debug(f"Plan state persistence skipped: {type(e).__name__}: {e}")

    try:
        task_graph = update_task_graph(
            task_graph,
            user_text=prompt,
            assistant_text=content,
            thread_id=thread_id,
        )
        save_task_graph(active_user_id, thread_id, task_graph)
        emit_state_event(
            "task_state_changed",
            "task_state_changed",
            {
                "open_tasks": len([t for t in list(task_graph.get("tasks") or []) if str(t.get("status") or "") != "done"]),
                "task_count": len(list(task_graph.get("tasks") or [])),
            },
        )
    except Exception as e:
        logger.debug(f"Task graph persistence skipped: {type(e).__name__}: {e}")

    selected_model_name = ""
    try:
        selected_model_name = str(
            self._select_response_model(
                routing_prompt,
                should_search=bool(should_search),
                route=str(decision.route or "llm_only"),
                memory_intent=bool(self._is_personal_memory_query(routing_prompt)),
            )
            or ""
        )
        self.performance_controller.observe_turn(
            latency_ms=int((time.time() - start_total) * 1000),
            success=bool(content and "generation failed" not in content.lower()),
            prompt_chars=len(str(routing_prompt or "")),
            history_tokens=self._history_token_estimate(self._get_history_list(active_user_id)),
            model_name=selected_model_name,
        )
    except Exception:
        pass

    self._push_history_for(active_user_id, prompt, content)
    logger.info(f"[{active_user_id}] Total response time: {time.time() - start_total:.2f}s")
    return finish_response(
        content,
        model_name=selected_model_name,
        metadata={"should_search": bool(should_search), "artifact_intent": str(artifact_intent or "")},
    )

def _set_last_attachments(self, user_id: str, attachments: Optional[List[Dict[str, Any]]] = None) -> None:
    self.last_attachments_by_user[str(user_id or self.user_id)] = list(attachments or [])

def get_last_attachments(self, user_id: str = "default_user") -> List[Dict[str, Any]]:
    return list(self.last_attachments_by_user.get(str(user_id or self.user_id), []))

async def generate_response_with_attachments(
    self,
    prompt: str,
    user_id: str = "default_user",
    dementia_friendly: bool = False,
    long_form: bool = False,
    forced_skill_keys: Optional[List[str]] = None,
    image_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    active_user_id = str(user_id or self.user_id)
    self._set_last_attachments(active_user_id, [])
    content = await self.generate_response(
        prompt=prompt,
        user_id=active_user_id,
        dementia_friendly=dementia_friendly,
        long_form=long_form,
        forced_skill_keys=forced_skill_keys,
        image_spec=image_spec,
    )
    return content, self.get_last_attachments(active_user_id)

def _start_turn_trace(
    self,
    *,
    prompt: str,
    active_user_id: str,
    thread_id: str,
    routing_prompt: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    store = getattr(self, "state_store", None)
    if store is None:
        return None
    try:
        return store.start_turn(
            user_id=str(active_user_id or self.user_id),
            thread_id=str(thread_id or "general"),
            user_text=str(prompt or ""),
            routing_prompt=str(routing_prompt or prompt or ""),
            metadata=dict(metadata or {}),
        )
    except Exception as e:
        logger.debug(f"Turn trace start skipped: {type(e).__name__}: {e}")
        return None

def _record_state_event(
    self,
    *,
    trace,
    event_type: str,
    event_name: str,
    payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> None:
    store = getattr(self, "state_store", None)
    if store is None:
        return
    try:
        store.record_event(
            trace=trace,
            user_id=str(user_id or self.user_id),
            thread_id=str(thread_id or "general"),
            event_type=str(event_type or "event"),
            event_name=str(event_name or "event"),
            payload=dict(payload or {}),
        )
    except Exception as e:
        logger.debug(f"State event skipped ({event_type}/{event_name}): {type(e).__name__}: {e}")

def _finish_turn_trace(
    self,
    *,
    trace,
    prompt: str,
    routing_prompt: str,
    content: str,
    status: str,
    route: str = "",
    model_name: str = "",
    tool_events: Optional[List[Dict[str, Any]]] = None,
    latency_ms: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    store = getattr(self, "state_store", None)
    if store is None or trace is None:
        return content
    try:
        attachments = self.get_last_attachments(getattr(trace, "user_id", self.user_id))
    except Exception:
        attachments = []
    try:
        store.finish_turn(
            trace=trace,
            assistant_text=str(content or ""),
            status=str(status or "completed"),
            route=str(route or ""),
            model_name=str(model_name or ""),
            routing_prompt=str(routing_prompt or prompt or ""),
            latency_ms=int(latency_ms or 0),
            tool_events=list(tool_events or []),
            metadata=dict(metadata or {}),
            attachments=list(attachments or []),
        )
    except Exception as e:
        logger.debug(f"Turn trace finish skipped: {type(e).__name__}: {e}")
    try:
        self._refresh_operational_graph(
            str(getattr(trace, "user_id", self.user_id) or self.user_id),
            str(getattr(trace, "thread_id", "general") or "general"),
        )
    except Exception:
        pass
    try:
        ops_control = getattr(self, "ops_control", None)
        if ops_control is not None:
            ops_control.record_model_metric(
                model_name=str(model_name or ""),
                route=str(route or ""),
                latency_ms=int(latency_ms or 0),
                status=str(status or "completed"),
                prompt_chars=len(str(prompt or "")),
                output_chars=len(str(content or "")),
                meta={
                    "thread_id": str(getattr(trace, "thread_id", "general") or "general"),
                    "tool_event_count": len(list(tool_events or [])),
                },
            )
    except Exception:
        pass
    try:
        trajectory_store = getattr(self, "trajectory_store", None)
        if trajectory_store is not None:
            trajectory_store.record_turn(
                user_id=str(getattr(trace, "user_id", self.user_id) or self.user_id),
                thread_id=str(getattr(trace, "thread_id", "general") or "general"),
                session_id=str(getattr(trace, "session_id", "") or ""),
                turn_id=int(getattr(trace, "turn_id", 0) or 0),
                turn_index=int(getattr(trace, "turn_index", 0) or 0),
                prompt=str(prompt or ""),
                response=str(content or ""),
                route=str(route or ""),
                model_name=str(model_name or ""),
                latency_ms=int(latency_ms or 0),
                tool_events=list(tool_events or []),
                metadata=dict(metadata or {}),
            )
    except Exception:
        pass
    return content

async def analyze_image(self, image_path: str, caption: str = "", user_id: str = "default_user") -> str:
    active_user_id = str(user_id or self.user_id)
    self._ensure_async_clients_for_current_loop()
    system_prompt = self._compose_identity_block()
    memory_context = (
        await self.memory.build_injected_context(caption or "image", user_id=active_user_id)
        or "No relevant memories found"
    )
    prompt = (
        f"You received an image with caption: '{caption or 'Describe this image'}'.\n"
        f"Relevant memory:\n{memory_context}\n\n"
        "Describe what you see clearly. If uncertain, say so."
    )
    try:
        with open(image_path, "rb") as img:
            image_data = img.read()
        async with asyncio.timeout(self._vision_timeout_seconds()):
            resp = await self.vision_client.chat(
                model=self.vision_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt, "images": [image_data]},
                ],
                options={"temperature": float(self.temperature), "keep_alive": 300},
            )
        content = resp.get("message", {}).get("content", "") or ""
        content = self._clean_think_tags(content)
        content = self._strip_unwanted_json(content)
        note = f"Image noted: {caption}".strip()
        await self.memory.ingest_turn(note, assistant_text=content, tool_summaries=["vision"], session_id=active_user_id)
        return content or "I couldn't extract anything useful from that image."
    except Exception as e:
        return f"Sorry â€” image analysis failed ({type(e).__name__})."
