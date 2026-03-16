from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (bootstrap_methods.py)."""

def __init__(self):
    super(SomiAIGUI, self).__init__()
    self.setWindowTitle("SOMI")
    self.setWindowIcon(QIcon("workshop/assets/icon.ico"))
    self._configure_startup_geometry()

    self.telegram_process = None
    self.twitter_autotweet_process = None
    self.twitter_autoresponse_process = None
    self.alex_process = None
    self.ai_model_process = None
    self.preloaded_agent = None
    self.agent_warmup_worker = None
    self.chat_worker = None
    self.chat_panel = None
    self.chat_host_layout = None
    self.chat_embed_parent = None
    self.chat_popout = None
    self.chat_is_popped = False
    self._chat_docking_in_progress = False
    self._startup_chat_message_sent = False
    self.ai_model_start_button = QPushButton("AI Model Start/Stop")
    self.ai_model_start_button.setVisible(False)

    self.agent_keys, self.agent_names = self.load_agent_names()
    self.state = self.build_state_model()
    self.workers = []
    self.intel_index = 0
    self.intel_paused = False
    self.last_console_line_count = 0
    self.speech_active = False
    self.speech_os_profile = "auto"
    self.speech_input_device = ""
    self.speech_output_device = ""
    self.model_settings_window = None
    self.edit_settings_window = None
    self._runtime_diagnostics_running = False
    self.ops_control = OpsControlPlane()
    self.toolbox_runtime = InternalToolRuntime(ops_control=self.ops_control)
    self.coding_user_id = "default_user"
    self.coding_service = CodingSessionService()
    self.coding_studio_builder = CodingStudioSnapshotBuilder(coding_service=self.coding_service)
    self.coding_studio_window = None
    self.toolbox_panel = None
    self.research_studio_builder = ResearchStudioSnapshotBuilder()
    self.research_studio_panel = None
    self.skill_manager = SkillManager()
    self.skill_marketplace_service = SkillMarketplaceService(manager=self.skill_manager)
    self.heartbeat_service = HeartbeatService()
    self.heartbeat_bridge = HeartbeatGUIBridge(self.heartbeat_service)
    self.memory3 = Memory3Manager(user_id="default_user")
    self.state_store = getattr(getattr(self.memory3, "session_search", None), "state_store", None) or SessionEventStore()
    self.delivery_gateway = DeliveryGateway()
    self.gateway_service = GatewayService(delivery_gateway=self.delivery_gateway)
    self.gateway_session = self.gateway_service.register_session(
        user_id="default_user",
        surface="gui",
        client_id="desktop-ui",
        client_label="Somi Desktop",
        platform=str(sys.platform or "desktop"),
        auth_mode="local",
        metadata={"pane": "main_window"},
    )
    self._last_gateway_sync_ts = 0.0
    self.automation_store = AutomationStore()
    self.automation_engine = AutomationEngine(
        store=self.automation_store,
        gateway=self.delivery_gateway,
        session_search=self.memory3.session_search,
        timezone_name=str(getattr(self.heartbeat_service.settings_module, "SYSTEM_TIMEZONE", "UTC")),
    )
    self.tool_registry = ToolRegistry()
    self.subagent_registry = SubagentRegistry()
    self.subagent_status_store = SubagentStatusStore()
    self.workflow_store = WorkflowRunStore()
    self.workflow_manifest_store = WorkflowManifestStore()
    self.start_here_service = StarterStudioService(
        tool_registry=self.tool_registry,
        workflow_manifest_store=self.workflow_manifest_store,
    )
    self.ontology = SomiOntology(
        state_store=self.state_store,
        memory_store=getattr(self.memory3, "store", None),
        automation_store=self.automation_store,
        gateway_service=self.gateway_service,
        refresh_ttl_seconds=0.0,
    )
    self.control_room_builder = ControlRoomSnapshotBuilder(
        state_store=self.state_store,
        ontology=self.ontology,
        memory_manager=self.memory3,
        automation_engine=self.automation_engine,
        automation_store=self.automation_store,
        delivery_gateway=self.delivery_gateway,
        gateway_service=self.gateway_service,
        tool_registry=self.tool_registry,
        subagent_registry=self.subagent_registry,
        subagent_status_store=self.subagent_status_store,
        workflow_store=self.workflow_store,
        workflow_manifest_store=self.workflow_manifest_store,
        ops_control=self.ops_control,
    )
    self.node_manager_builder = NodeManagerSnapshotBuilder(gateway_service=self.gateway_service)
    self.node_manager_panel = None
    self.hud_assets = {k: _find_hud_asset(v) for k, v in HUD_ASSET_STEMS.items()}
    self.hud_overlay = None
    self.command_stream_card = None
    self.core_splitter = None
    self.heartbeat_stream_list = None
    self.stream_meters = {}
    self.stream_orbit = None
    self.stream_status_chips = {}
    self._custom_background_path = ""
    self.control_room_panel = None
    self.heartbeat_service.set_shared_context(
        HB_CACHED_WEATHER_LINE="",
        HB_CACHED_WEATHER_TS="",
        HB_CACHED_WEATHER_PAYLOAD=None,
        HB_CACHED_URGENT_HEADLINE="",
        HB_CACHED_AGENTPEDIA_FACT="",
        HB_REMINDER_PROVIDER=self._heartbeat_due_reminders_provider,
        HB_GOAL_NUDGE_PROVIDER=self._heartbeat_goal_nudge_provider,
        HB_MEMORY_HYGIENE_PROVIDER=self.memory3.run_hygiene_check,
        HB_AUTOMATION_PROVIDER=self._heartbeat_automation_provider,
    )

    self.root = QWidget()
    self.setCentralWidget(self.root)
    self.main_layout = QVBoxLayout(self.root)
    self.main_layout.setContentsMargins(16, 16, 16, 16)
    self.main_layout.setSpacing(12)

    self.build_top_status_strip()
    self.build_center_panel()
    self.build_bottom_tabs()
    self.build_quick_action_bar()
    self.load_gui_theme_preference()
    self.load_gui_model_profile_preference()
    self.apply_theme()
    self.wire_signals_and_timers()
    self.preload_default_agent_and_chat_worker()
    self.heartbeat_service.start()

    self.push_activity("system", "Prime Console booted")
    self.refresh_reminders()
    self._sync_gateway_status(force=True)
    self.startup_refresh_timer = QTimer(self)
    self.startup_refresh_timer.setSingleShot(True)
    self.startup_refresh_timer.timeout.connect(self.kickoff_startup_refreshes)
    self.startup_refresh_timer.start(900)

def _configure_startup_geometry(self):
    screen = QApplication.primaryScreen()
    self.setMinimumSize(920, 620)
    if screen is None:
        self.resize(1200, 760)
        return

    avail = screen.availableGeometry()
    target_w = max(1020, min(1540, avail.width() - 40))
    target_h = max(680, min(940, avail.height() - 48))
    self.resize(target_w, target_h)

def _selected_agent_name(self) -> str:
    key = str(getattr(self, "selected_agent_key", "") or "")
    if key and key in self.agent_keys:
        return key.replace("Name: ", "")
    return self.agent_names[0] if self.agent_names else "Somi"

def _load_selected_agent_key(self) -> str:
    prof = load_assistant_profile(str(ASSISTANT_PROFILE_PATH))
    requested = str(prof.get("active_persona_key") or "").strip()
    if requested and requested in self.agent_keys:
        return requested
    return self._default_agent_key()

def _persist_selected_agent_key(self, agent_key: str) -> None:
    prof = load_assistant_profile(str(ASSISTANT_PROFILE_PATH))
    prof["active_persona_key"] = str(agent_key)
    save_assistant_profile(prof, str(ASSISTANT_PROFILE_PATH))

def on_persona_changed(self):
    idx = self.persona_combo.currentIndex() if getattr(self, "persona_combo", None) else -1
    if idx < 0 or idx >= len(self.agent_keys):
        return
    agent_key = self.agent_keys[idx]
    self.selected_agent_key = agent_key
    self._persist_selected_agent_key(agent_key)
    self.push_activity("core", f"Personality switched to {agent_key.replace('Name: ', '')}")

    try:
        from gui.aicoregui import ChatWorker
        if self.chat_worker and self.chat_worker.isRunning():
            if self.chat_worker.is_busy():
                self.push_activity("core", "Chat worker busy; personality will apply next turn")
                return
            current_use_studies = bool(getattr(self.chat_worker, "use_studies", True))
            changed = self.chat_worker.update_agent(agent_key, current_use_studies)
            if changed:
                self.push_activity("core", "Chat worker updated for new personality")
    except Exception as exc:
        logger.warning("Failed to update chat worker after persona switch: %s", exc)
