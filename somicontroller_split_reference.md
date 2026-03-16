# somicontroller.py split reference

- Backup: `backups/somicontroller.py.pre_split.20260313_143841.bak`
- Compatibility surface: `SomiAIGUI` and the `__main__` entrypoint remain in `somicontroller.py`.
- Extracted methods are rebound onto `SomiAIGUI` with `somicontroller.py` globals preserved.

## Extracted modules
- `bootstrap_methods.py`: `__init__`, `_configure_startup_geometry`, `_selected_agent_name`, `_load_selected_agent_key`, `_persist_selected_agent_key`, `on_persona_changed`
- `layout_methods.py`: `build_state_model`, `build_top_status_strip`, `build_center_panel`, `build_embedded_chat`, `build_presence_panel`, `build_intel_stream`, `build_heartbeat_stream`, `build_activity_stream_card`, `build_speech_mini_console`, `build_bottom_tabs`, `build_quick_action_bar`, `wire_signals_and_timers`, `apply_theme`, `_configure_hud_overlay`, `_update_hud_overlay_targets`, `resizeEvent`
- `settings_methods.py`: `read_gui_settings`, `write_gui_settings`, `load_gui_theme_preference`, `_model_profile_options`, `_normalize_model_profile`, `_effective_model_profile`, `_reload_runtime_model_stack`, `load_gui_model_profile_preference`, `apply_model_profile`, `_runtime_model_snapshot`, `open_theme_selector`, `_sub_btn`, `read_settings`, `show_model_selections`, `edit_model_settings`, `change_background`, `read_help_file`, `show_help`
- `status_methods.py`: `push_activity`, `update_clock`, `update_heartbeat_label`, `poll_heartbeat_events`, `_heartbeat_goal_nudge_provider`, `_heartbeat_due_reminders_provider`, `refresh_heartbeat_diagnostics`, `pause_heartbeat`, `resume_heartbeat`, `update_top_strip`, `update_presence`, `_build_intel_items`, `rotate_intel`, `update_stream_meters`, `capture_output_events`
- `fetch_methods.py`: `refresh_weather`, `refresh_news`, `refresh_finance_news`, `refresh_developments`, `refresh_reminders`, `_start_worker`, `on_fetch_result`, `fetch_weather`, `_fetch_rss_headlines`, `fetch_news`, `fetch_finance_news`, `fetch_developments`, `load_reminders`, `trigger_engagement`, `copy_context_pack`
- `runtime_methods.py`: `open_agentpedia_viewer`, `toggle_speech_process`, `load_agent_names`, `refresh_agent_names`, `_default_agent_key`, `preload_default_agent_and_chat_worker`, `_on_agent_warmed`, `toggle_ai_model`, `open_chat`, `ensure_chat_worker_running`, `stop_chat_worker`, `toggle_chat_popout`, `dock_chat_panel`, `toggle_chat_expand`, `open_data_agent`, `run_personality_editor`, `_extract_json_block`, `fetch_runtime_diagnostics`, `run_runtime_diagnostics`, `closeEvent`
