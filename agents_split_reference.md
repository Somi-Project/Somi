# agents.py split reference

- Backup: `backups/agents.py.pre_split.20260313_141234.bak`
- Compatibility surface: `from agents import Agent` remains unchanged.
- Bound methods keep the `agents.py` module globals so existing monkeypatch-based tests can keep targeting `agents`.

## Extracted modules
- `model_methods.py`: `_select_generation_mode`, `_select_response_model`, `_model_role_for_generation_mode`, `_model_retryable_error_markers`, `_is_retryable_model_error`, `_record_model_success`, `_record_model_failure`, `_model_candidate_chain`, `_chat_with_model_failover`
- `text_methods.py`: `_clean_think_tags`, `_strip_unwanted_json`, `_looks_like_tool_dump`, `_strip_search_meta_leakage`, `_strip_internal_prompt_leakage`, `_naturalize_search_output`
- `history_methods.py`: `_should_use_per_user_history`, `_get_history_list`, `_history_limits`, `_estimate_text_tokens_rough`, `_history_token_estimate`, `_resolve_history_compaction_thresholds`, `_state_ledger_for_user`, `_state_ledger_block`, `_history_for_prompt`, `_compact_history_if_needed`, `_push_history_for`, `_tool_loop_config`, `_tool_call_history`, `_run_tool_with_loop_guard`
- `search_memory_methods.py`: `_format_due_ts_local`, `_is_personal_memory_query`, `_should_inject_due_context`, `_mark_due_context_injected`, `_route_local_memory_intents`, `_should_websearch`, `_build_rag_block`, `_maintenance_tick`, `_persist_memory_serial`, `_memory_scope_for_prompt`, `_response_timeout_seconds`, `_vision_timeout_seconds`, `_token_budget`, `_extract_urls_from_results`, `_extract_urls_from_citation_map`, `_enforce_web_evidence_output`, `_is_volatile_results`, `_safe_build_image_spec`, `_is_chart_keyword_prompt`, `_numeric_guard`, `_is_finance_intent_hint`, `_looks_like_historical_price_followup`, `_looks_like_finance_followup`, `_render_direct_finance_answer`, `_render_direct_volatile_answer`
- `response_methods.py`: `generate_response`, `_set_last_attachments`, `get_last_attachments`, `generate_response_with_attachments`, `analyze_image`
