from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (layout_methods.py)."""

def build_state_model(self):
    return {
        "system_time_str": "--",
        "timezone": datetime.now().astimezone().tzname() or "Local",
        "model_name": "Unknown",
        "memory_status": "Ready",
        "speech_status": "Idle",
        "background_status": "Monitoring",
        "weather": {"emoji": "WX", "temp": "--", "line": "Weather unavailable", "last_updated": "--"},
        "news": {"headlines": [], "count": 0, "last_updated": "--"},
        "finance_news": {"headlines": [], "count": 0, "last_updated": "--"},
        "developments": {"headlines": [], "count": 0, "last_updated": "--"},
        "reminders": {"due_count": 0, "next_due": "None", "last_updated": "--"},
        "activity_events": deque(maxlen=200),
    }

def build_top_status_strip(self):
    strip = QFrame()
    strip.setObjectName("heroStrip")
    layout = QHBoxLayout(strip)

    self.time_label = QLabel("--")
    self.time_label.setObjectName("heroClock")
    self.chips_label = QLabel("Online | Model: -- | Memory: Ready | Speech: Idle | Background: Monitoring")
    self.chips_label.setObjectName("heroStatus")
    self.heartbeat_label = QLabel("Heartbeat: --")
    self.heartbeat_label.setObjectName("heartbeatPill")
    self.metrics_label = QLabel("WX -- | News 0 | Finance 0 | Reminders 0")
    self.metrics_label.setObjectName("metricsPill")

    layout.addWidget(self.time_label, 1)
    layout.addWidget(self.chips_label, 2, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(self.heartbeat_label, 1, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(self.metrics_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
    self.main_layout.addWidget(strip)

def build_center_panel(self):
    row = QHBoxLayout()

    self.core_splitter = QSplitter(Qt.Orientation.Horizontal)
    self.core_splitter.setChildrenCollapsible(False)

    chat_container = QWidget()
    chat_layout = QVBoxLayout(chat_container)
    chat_layout.setContentsMargins(0, 0, 0, 0)
    chat_layout.setSpacing(10)
    self.build_embedded_chat(chat_layout)

    stream_container = QWidget()
    stream_layout = QVBoxLayout(stream_container)
    stream_layout.setContentsMargins(0, 0, 0, 0)
    stream_layout.setSpacing(10)
    self.build_presence_panel(stream_layout)
    self.build_intel_stream(stream_layout)
    self.build_heartbeat_stream(stream_layout)
    stream_layout.setStretch(0, 1)
    stream_layout.setStretch(1, 1)
    stream_layout.setStretch(2, 2)

    self.core_splitter.addWidget(chat_container)
    self.core_splitter.addWidget(stream_container)
    self.core_splitter.setStretchFactor(0, 7)
    self.core_splitter.setStretchFactor(1, 4)
    total_w = max(900, self.width() - 120)
    left_w = int(total_w * 0.64)
    self.core_splitter.setSizes([left_w, max(320, total_w - left_w)])

    row.addWidget(self.core_splitter, 5)
    self.build_speech_mini_console(row)
    self.main_layout.addLayout(row, 1)

def build_embedded_chat(self, parent_layout):
    card = QFrame()
    card.setObjectName("card")
    card.setMinimumHeight(390)
    self.chat_host_layout = QVBoxLayout(card)
    self.chat_host_layout.setContentsMargins(10, 10, 10, 10)
    self.chat_panel = ChatPanel(self)
    self.chat_host_layout.addWidget(self.chat_panel)
    self.chat_embed_parent = self.chat_host_layout
    self.chat_panel.popout_requested.connect(lambda: self.toggle_chat_popout(force_popout=True))
    self.chat_panel.dock_requested.connect(self.dock_chat_panel)
    self.chat_panel.expand_requested.connect(self.toggle_chat_expand)
    self.chat_panel.restore_requested.connect(self.toggle_chat_expand)
    self.chat_panel.stop_chat_requested.connect(self.stop_chat_worker)
    parent_layout.addWidget(card, 1)

def build_presence_panel(self, parent_layout):
    card = QFrame()
    card.setObjectName("card")
    l = QVBoxLayout(card)
    self.greeting_label = QLabel("Prime console online.")
    self.greeting_label.setObjectName("panelTitle")
    self.last_interaction_label = QLabel("No recent session summary yet.")
    self.last_interaction_label.setObjectName("sectionSubtitle")
    self.urgent_line_label = QLabel("No urgent items right now.")
    self.urgent_line_label.setObjectName("ambientLabel")
    self.bored_button = self._sub_btn("I'm bored", self.trigger_engagement)
    self.context_pack_button = self._sub_btn("Context Pack", self.copy_context_pack)
    ctl = QHBoxLayout()
    ctl.addWidget(self.bored_button)
    ctl.addWidget(self.context_pack_button)
    l.addWidget(self.greeting_label)
    l.addWidget(self.last_interaction_label)
    l.addWidget(self.urgent_line_label)
    l.addLayout(ctl)
    parent_layout.addWidget(card)

def build_intel_stream(self, parent_layout):
    self.intel_card = HoverIntelCard()
    self.intel_card.setObjectName("card")
    self.intel_card.setMinimumHeight(170)
    self.intel_card.hovered.connect(lambda v: setattr(self, "intel_paused", v))
    il = QVBoxLayout(self.intel_card)
    self.intel_title = QLabel("Intelligence Stream")
    self.intel_title.setObjectName("sectionTitle")
    self.intel_text = QLabel("Booting ambient intelligence...")
    self.intel_text.setWordWrap(True)
    self.intel_text.setObjectName("ambientLabel")
    il.addWidget(self.intel_title)
    il.addWidget(self.intel_text)

    self.intel_opacity = QGraphicsOpacityEffect(self.intel_text)
    self.intel_text.setGraphicsEffect(self.intel_opacity)
    self.intel_anim = QPropertyAnimation(self.intel_opacity, b"opacity")
    self.intel_anim.setDuration(260)
    self.intel_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
    self._intel_swap_text_callback = None

    parent_layout.addWidget(self.intel_card)

def build_heartbeat_stream(self, parent_layout):
    card = QFrame()
    card.setObjectName("card")
    self.command_stream_card = card
    l = QVBoxLayout(card)
    title = QLabel("Heartbeat + Command Stream")
    title.setObjectName("sectionTitle")
    l.addWidget(title)

    self.heartbeat_stream_list = QListWidget()
    self.heartbeat_stream_list.setMinimumHeight(160)
    l.addWidget(self.heartbeat_stream_list)

    self.stream_orbit = StatusOrbitWidget()
    l.addWidget(self.stream_orbit)

    chip_row = QHBoxLayout()
    chip_row.setSpacing(8)
    self.stream_status_chips = {}
    for key, title in [("model", "Model"), ("search", "Search"), ("heartbeat", "Heartbeat"), ("task", "Task")]:
        chip = QLabel(f"{title}: --")
        chip.setObjectName("statusChip")
        self.stream_status_chips[key] = chip
        chip_row.addWidget(chip)
    l.addLayout(chip_row)

    parent_layout.addWidget(card)

def build_activity_stream_card(self):
    card = QFrame()
    card.setObjectName("card")
    l = QVBoxLayout(card)
    title = QLabel("Activity Stream")
    title.setObjectName("sectionTitle")
    l.addWidget(title)
    self.activity_list = QListWidget()
    self.idle_label = QLabel("Somi idle - monitoring")
    self.idle_label.setObjectName("ambientLabel")
    l.addWidget(self.activity_list)
    l.addWidget(self.idle_label)
    return card

def build_speech_mini_console(self, parent_layout):
    card = QFrame()
    card.setObjectName("card")
    card.setMaximumWidth(260)
    l = QVBoxLayout(card)
    title = QLabel("Speech Mini-Console")
    title.setObjectName("sectionTitle")
    l.addWidget(title)
    self.mic_state_label = QLabel("Mic: OFF")
    self.voice_state_label = QLabel("Voice: READY")
    self.speech_btn = self._sub_btn("Play Speech", self.toggle_speech_process)
    self.waveform = WaveformWidget()
    l.addWidget(self.mic_state_label)
    l.addWidget(self.voice_state_label)
    l.addWidget(self.speech_btn)
    l.addWidget(self.waveform)
    parent_layout.addWidget(card, 1)

def build_bottom_tabs(self):
    self.tabs = QTabWidget()
    self.tabs.setObjectName("mainTabs")
    activity_tab = QWidget()
    activity_tab.setLayout(QVBoxLayout())
    activity_tab.layout().addWidget(self.build_activity_stream_card())

    self.output_area = QTextEdit()
    self.output_area.setReadOnly(True)
    self.output_area.setObjectName("consoleOutput")
    console_tab = QWidget()
    console_tab.setLayout(QVBoxLayout())
    console_tab.layout().addWidget(self.output_area)

    self.diag_text = QTextEdit()
    self.diag_text.setReadOnly(True)
    self.diag_text.setText("Diagnostics placeholder: weather/news/reminder cache health.")
    self.diag_text.setObjectName("diagnosticPane")
    diag_tab = QWidget()
    diag_tab.setLayout(QVBoxLayout())
    diag_tab.layout().addWidget(self.diag_text)

    self.tabs.addTab(activity_tab, "Activity")
    self.tabs.addTab(console_tab, "Raw Console")
    self.tabs.addTab(diag_tab, "Diagnostics")
    self.tabs.addTab(self.build_control_room_panel(), "Control Room")
    self.tabs.addTab(self.build_research_studio_panel(), "Research")
    self.toolbox_panel = toolboxgui.ToolboxPanel(self)
    self.tabs.addTab(self.toolbox_panel, "Toolbox")
    self.tabs.addTab(self.build_node_manager_panel(), "Nodes")
    self.tabs.addTab(executivegui.ExecutivePanel(self), "Executive")
    self.tabs.setMinimumHeight(190)
    self.tabs.setMaximumHeight(max(230, int(self.height() * 0.36)))
    self.main_layout.addWidget(self.tabs)

def build_quick_action_bar(self):
    bar = QFrame()
    bar.setObjectName("actionBar")
    l = QHBoxLayout(bar)

    self.selected_agent_key = self._load_selected_agent_key()
    l.addWidget(QLabel("Personality:"))
    self.persona_combo = QComboBox()
    self.persona_combo.addItems(self.agent_names)
    cur_name = self.selected_agent_key.replace("Name: ", "")
    if cur_name in self.agent_names:
        self.persona_combo.setCurrentText(cur_name)
    self.persona_combo.currentIndexChanged.connect(lambda _=None: self.on_persona_changed())
    l.addWidget(self.persona_combo)

    for label, cb in [
        ("Talk", self.toggle_speech_process),
        ("Study", lambda: aicoregui.study_material(self)),
        ("Modules", lambda: ModulesDialog(self).exec()),
        ("Studio", self.open_control_room),
        ("Research", self.open_research_studio),
        ("Coding", self.open_coding_studio),
        ("Nodes", self.open_node_manager),
        ("Settings", self.show_model_selections),
        ("Agentpedia", self.open_agentpedia_viewer),
        ("HB Pause", self.pause_heartbeat),
        ("HB Resume", self.resume_heartbeat),
        ("Theme", self.open_theme_selector),
    ]:
        l.addWidget(self._sub_btn(label, cb))
    l.addWidget(self._sub_btn("Background", self.change_background))
    self.main_layout.addWidget(bar)

def wire_signals_and_timers(self):
    self.clock_timer = QTimer(self)
    self.clock_timer.timeout.connect(self.update_clock)
    self.clock_timer.start(1000)

    self.intel_timer = QTimer(self)
    self.intel_timer.timeout.connect(self.rotate_intel)
    self.intel_timer.start(9000)

    self.reminder_timer = QTimer(self)
    self.reminder_timer.timeout.connect(self.refresh_reminders)
    self.reminder_timer.start(120000)

    self.weather_timer = QTimer(self)
    self.weather_timer.timeout.connect(self.refresh_weather)
    self.weather_timer.start(20 * 60 * 1000)

    self.news_timer = QTimer(self)
    self.news_timer.timeout.connect(self.refresh_news)
    self.news_timer.start(40 * 60 * 1000)

    self.finance_news_timer = QTimer(self)
    self.finance_news_timer.timeout.connect(self.refresh_finance_news)
    self.finance_news_timer.start(50 * 60 * 1000)

    self.developments_timer = QTimer(self)
    self.developments_timer.timeout.connect(self.refresh_developments)
    self.developments_timer.start(60 * 60 * 1000)

    self.output_watch_timer = QTimer(self)
    self.output_watch_timer.timeout.connect(self.capture_output_events)
    self.output_watch_timer.start(1400)

    hb_update_s = getattr(self.heartbeat_service.settings_module, "HB_UI_HEARTBEAT_UPDATE_SECONDS", 2)
    hb_label_ms = int(hb_update_s * 1000)
    self.hb_label_timer = QTimer(self)
    self.hb_label_timer.timeout.connect(self.update_heartbeat_label)
    self.hb_label_timer.start(hb_label_ms)

    self.hb_event_timer = QTimer(self)
    self.hb_event_timer.timeout.connect(self.poll_heartbeat_events)
    self.hb_event_timer.start(750)

    self.hb_diag_timer = QTimer(self)
    self.hb_diag_timer.timeout.connect(self.refresh_heartbeat_diagnostics)
    self.hb_diag_timer.start(5000)

    self.stream_meter_timer = QTimer(self)
    self.stream_meter_timer.timeout.connect(self.update_stream_meters)
    self.stream_meter_timer.start(1800)

    self.hud_target_timer = QTimer(self)
    self.hud_target_timer.timeout.connect(self._update_hud_overlay_targets)
    self.hud_target_timer.start(1200)

    self.update_clock()
    self.update_heartbeat_label()
    self.refresh_heartbeat_diagnostics()
    self.update_stream_meters()
    self._update_hud_overlay_targets()

def apply_theme(self):
    theme_name = get_theme_name()
    style = app_stylesheet()
    bg_path = self._custom_background_path

    if not bg_path and theme_name == "cockpit_balanced":
        bg_asset = self.hud_assets.get("bg")
        if bg_asset:
            bg_path = str(bg_asset)

    if bg_path:
        safe = str(bg_path).replace("\\", "/")
        style += f"\nQMainWindow {{ background-image: url('{safe}'); background-position: center; background-repeat: no-repeat; }}\n"
        self.state["background_status"] = "Cockpit" if theme_name == "cockpit_balanced" else "Custom"
    else:
        self.state["background_status"] = "Monitoring"

    self.setStyleSheet(style)
    self._configure_hud_overlay(theme_name == "cockpit_balanced")

def _configure_hud_overlay(self, enabled: bool):
    if enabled:
        if self.hud_overlay is None:
            self.hud_overlay = HudOverlayWidget(self.root, self.hud_assets)
        self.hud_overlay.setGeometry(self.root.rect())
        self.hud_overlay.raise_()
        self.hud_overlay.show()
        self.hud_overlay.set_active(True)
        self._update_hud_overlay_targets()
        return

    if self.hud_overlay is not None:
        self.hud_overlay.set_active(False)
        self.hud_overlay.hide()

def _update_hud_overlay_targets(self):
    if not self.hud_overlay or not self.hud_overlay.isVisible():
        return
    self.hud_overlay.setGeometry(self.root.rect())

    if self.command_stream_card is None:
        self.hud_overlay.set_targets(QPointF(0.0, 0.0), QRect())
        return

    top_left = self.command_stream_card.mapTo(self.root, self.command_stream_card.rect().topLeft())
    rect_root = QRect(top_left, self.command_stream_card.size())
    center = QPointF(float(rect_root.center().x()), float(rect_root.center().y()))
    self.hud_overlay.set_targets(center, rect_root)

def resizeEvent(self, event):
    super(SomiAIGUI, self).resizeEvent(event)
    self._update_hud_overlay_targets()
    if getattr(self, "tabs", None) is not None:
        self.tabs.setMaximumHeight(max(220, int(self.height() * 0.36)))
