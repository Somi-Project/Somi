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
        "research_pulse": {
            "query": "",
            "mode": "standby",
            "summary": "No research pulse yet. Somi will surface search traces here during deeper browsing.",
            "progress_headline": "",
            "trace": [],
            "timeline": [],
            "source_preview": [],
            "sources_count": 0,
            "limitations_count": 0,
            "updated_at": "--",
            "updated_epoch": 0.0,
        },
        "activity_events": deque(maxlen=200),
    }

def build_top_status_strip(self):
    strip = QFrame()
    strip.setObjectName("heroStrip")
    layout = QVBoxLayout(strip)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(6)

    self.time_label = QLabel("--")
    self.time_label.setObjectName("heroClock")
    self.chips_label = QLabel("Online | Model: -- | Memory: Ready | Speech: Idle | Background: Monitoring")
    self.chips_label.setObjectName("heroSubline")
    self.chips_label.setWordWrap(False)
    self.chips_label.setMinimumHeight(20)
    self.chips_label.setMaximumHeight(22)
    self.heartbeat_label = QLabel("Heartbeat: --")
    self.heartbeat_label.setObjectName("heartbeatPill")
    self.metrics_label = QLabel("WX -- | News 0 | Finance 0 | Reminders 0")
    self.metrics_label.setObjectName("metricsPill")

    top_row = QHBoxLayout()
    top_row.setContentsMargins(0, 0, 0, 0)
    top_row.setSpacing(8)
    top_row.addWidget(self.time_label, 1)
    top_row.addWidget(self.heartbeat_label, 0, alignment=Qt.AlignmentFlag.AlignCenter)
    top_row.addWidget(self.metrics_label, 0, alignment=Qt.AlignmentFlag.AlignRight)

    layout.addLayout(top_row)
    layout.addWidget(self.chips_label, 0, alignment=Qt.AlignmentFlag.AlignLeft)
    self.main_layout.addWidget(strip)

def build_center_panel(self):
    row = QHBoxLayout()

    self.core_splitter = QSplitter(Qt.Orientation.Horizontal)
    self.core_splitter.setChildrenCollapsible(False)

    chat_container = QWidget()
    chat_container.setMinimumWidth(560)
    chat_layout = QVBoxLayout(chat_container)
    chat_layout.setContentsMargins(0, 0, 0, 0)
    chat_layout.setSpacing(10)
    self.build_embedded_chat(chat_layout)

    stream_container = QWidget()
    stream_container.setMinimumWidth(280)
    stream_container.setMaximumWidth(420)
    stream_layout = QVBoxLayout(stream_container)
    stream_layout.setContentsMargins(0, 0, 0, 0)
    stream_layout.setSpacing(8)
    self.build_presence_panel(stream_layout)
    self.build_research_pulse_panel(stream_layout)
    self.build_intel_stream(stream_layout)
    self.build_speech_mini_console(stream_layout)
    stream_layout.setStretch(0, 1)
    stream_layout.setStretch(1, 2)
    stream_layout.setStretch(2, 2)
    stream_layout.setStretch(3, 1)

    self.core_splitter.addWidget(chat_container)
    self.core_splitter.addWidget(stream_container)
    self.core_splitter.setStretchFactor(0, 9)
    self.core_splitter.setStretchFactor(1, 3)
    total_w = max(900, self.width() - 120)
    left_w = int(total_w * 0.7)
    self.core_splitter.setSizes([left_w, max(320, total_w - left_w)])
    QTimer.singleShot(0, self._rebalance_core_splitter)
    QTimer.singleShot(160, self._rebalance_core_splitter)

    row.addWidget(self.core_splitter, 1)
    self.main_layout.addLayout(row, 1)

def _rebalance_core_splitter(self):
    splitter = getattr(self, "core_splitter", None)
    if splitter is None or self.chat_is_popped:
        return
    sizes = list(splitter.sizes())
    if len(sizes) < 2:
        return
    total = max(920, splitter.width() or sum(sizes) or max(self.width() - 120, 920))
    left_target = max(620, int(total * 0.7))
    right_target = max(300, total - left_target)
    if sizes[0] <= sizes[1] or sizes[0] < left_target - 36:
        splitter.setSizes([left_target, right_target])

def build_embedded_chat(self, parent_layout):
    card = QFrame()
    card.setObjectName("chatCard")
    card.setMinimumHeight(430)
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
    card.setObjectName("presenceCard")
    card.setMaximumHeight(132)
    l = QVBoxLayout(card)
    l.setContentsMargins(12, 10, 12, 10)
    l.setSpacing(5)
    self.greeting_label = QLabel("Prime console online.")
    self.greeting_label.setObjectName("panelTitle")
    self.last_interaction_label = QLabel("No recent session summary yet.")
    self.last_interaction_label.setObjectName("sectionSubtitle")
    self.urgent_line_label = QLabel("No urgent items right now.")
    self.urgent_line_label.setObjectName("ambientLabel")
    self.bored_button = self._sub_btn("I'm bored", self.trigger_engagement)
    self.context_pack_button = self._sub_btn("Context Pack", self.copy_context_pack)
    self.bored_button.setObjectName("quickActionButton")
    self.context_pack_button.setObjectName("quickActionButton")
    ctl = QHBoxLayout()
    ctl.setContentsMargins(0, 0, 0, 0)
    ctl.setSpacing(6)
    ctl.addWidget(self.bored_button)
    ctl.addWidget(self.context_pack_button)
    l.addWidget(self.greeting_label)
    l.addWidget(self.last_interaction_label)
    l.addWidget(self.urgent_line_label)
    l.addLayout(ctl)
    parent_layout.addWidget(card)

def build_intel_stream(self, parent_layout):
    self.intel_card = HoverIntelCard()
    self.intel_card.setObjectName("intelCard")
    self.intel_card.setMinimumHeight(220)
    self.intel_card.setMaximumHeight(252)
    self.intel_card.hovered.connect(lambda v: setattr(self, "intel_paused", v))
    self.command_stream_card = self.intel_card
    il = QVBoxLayout(self.intel_card)
    il.setContentsMargins(10, 10, 10, 10)
    il.setSpacing(6)
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    self.intel_title = QLabel("Ops Stream")
    self.intel_title.setObjectName("sectionTitle")
    stream_chip = QLabel("Ambient + heartbeat")
    stream_chip.setObjectName("statusChip")
    header.addWidget(self.intel_title)
    header.addStretch(1)
    header.addWidget(stream_chip)
    self.intel_text = QLabel("Booting ambient intelligence...")
    self.intel_text.setWordWrap(True)
    self.intel_text.setObjectName("ambientLabel")
    self.intel_stream_label = QLabel("Recent ops and heartbeat events")
    self.intel_stream_label.setObjectName("sectionSubtitle")
    self.heartbeat_stream_list = QListWidget()
    self.heartbeat_stream_list.setMinimumHeight(88)
    self.heartbeat_stream_list.setMaximumHeight(114)
    lower_row = QHBoxLayout()
    lower_row.setContentsMargins(0, 0, 0, 0)
    lower_row.setSpacing(6)
    self.stream_orbit = StatusOrbitWidget()
    self.stream_orbit.setMinimumHeight(84)
    self.stream_orbit.setMaximumHeight(84)
    lower_row.addWidget(self.stream_orbit, 0)
    chips_col = QVBoxLayout()
    chips_col.setContentsMargins(0, 0, 0, 0)
    chips_col.setSpacing(4)
    self.stream_status_chips = {}
    for row_items in (
        (("model", "Model"), ("search", "Search")),
        (("heartbeat", "Heartbeat"), ("task", "Task")),
    ):
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(6)
        for key, title in row_items:
            chip = QLabel(f"{title}: --")
            chip.setObjectName("statusChip")
            self.stream_status_chips[key] = chip
            chip_row.addWidget(chip)
        chips_col.addLayout(chip_row)
    lower_row.addLayout(chips_col, 1)
    il.addLayout(header)
    il.addWidget(self.intel_text)
    il.addWidget(self.intel_stream_label)
    il.addWidget(self.heartbeat_stream_list)
    il.addLayout(lower_row)

    self.intel_opacity = QGraphicsOpacityEffect(self.intel_text)
    self.intel_text.setGraphicsEffect(self.intel_opacity)
    self.intel_anim = QPropertyAnimation(self.intel_opacity, b"opacity")
    self.intel_anim.setDuration(260)
    self.intel_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
    self._intel_swap_text_callback = None

    parent_layout.addWidget(self.intel_card)

def build_research_pulse_panel(self, parent_layout):
    card = QFrame()
    card.setObjectName("researchPulseCard")
    card.setMinimumHeight(178)
    card.setMaximumHeight(208)
    self.research_pulse_card = card
    l = QVBoxLayout(card)
    l.setContentsMargins(10, 10, 10, 10)
    l.setSpacing(5)

    title_row = QHBoxLayout()
    title = QLabel("Research Pulse")
    title.setObjectName("sectionTitle")
    self.research_mode_label = QLabel("STANDBY | 0 src")
    self.research_mode_label.setObjectName("statusChip")
    title_row.addWidget(title)
    title_row.addStretch(1)
    title_row.addWidget(self.research_mode_label)

    self.research_query_label = QLabel("No research pulse yet.")
    self.research_query_label.setObjectName("researchPulseQuery")
    self.research_query_label.setWordWrap(True)
    self.research_query_label.setMaximumHeight(26)
    self.research_signal_meter = ResearchSignalMeterWidget()
    self.research_signal_meter.setObjectName("researchSignalMeter")
    self.research_summary_label = QLabel("Somi will surface search traces here during deeper browsing.")
    self.research_summary_label.setObjectName("researchPulseSummary")
    self.research_summary_label.setWordWrap(True)
    self.research_summary_label.setMaximumHeight(36)
    self.research_trace_label = QLabel("Trace will appear once Somi plans and reads sources.")
    self.research_trace_label.setObjectName("researchPulseTrace")
    self.research_trace_label.setWordWrap(True)
    self.research_trace_label.setMaximumHeight(22)
    self.research_feed_list = QListWidget()
    self.research_feed_list.setObjectName("researchPulseFeed")
    self.research_feed_list.setMinimumHeight(72)
    self.research_feed_list.setMaximumHeight(90)
    self.research_timeline_label = None
    self.research_timeline_list = None
    self.research_sources_label = None
    self.research_sources_list = None
    self.research_meta_label = QLabel("Updated -- | cautions 0")
    self.research_meta_label.setObjectName("researchPulseMeta")

    l.addLayout(title_row)
    l.addWidget(self.research_signal_meter)
    l.addWidget(self.research_query_label)
    l.addWidget(self.research_summary_label)
    l.addWidget(self.research_trace_label)
    l.addWidget(self.research_feed_list)
    l.addWidget(self.research_meta_label)
    parent_layout.addWidget(card)

def build_heartbeat_stream(self, parent_layout):
    # Kept for compatibility with older call sites. The heartbeat list now
    # lives inside the compact Ops Stream card built by `build_intel_stream`.
    if getattr(self, "intel_card", None) is None:
        self.build_intel_stream(parent_layout)

def build_activity_stream_card(self):
    card = QFrame()
    card.setObjectName("activityCard")
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
    card.setObjectName("speechCard")
    card.setMinimumHeight(108)
    card.setMaximumHeight(118)
    l = QHBoxLayout(card)
    l.setContentsMargins(12, 10, 12, 10)
    l.setSpacing(10)
    left_col = QVBoxLayout()
    left_col.setContentsMargins(0, 0, 0, 0)
    left_col.setSpacing(4)
    title = QLabel("Speech")
    title.setObjectName("sectionTitle")
    left_col.addWidget(title)
    self.mic_state_label = QLabel("Mic: OFF")
    self.mic_state_label.setObjectName("speechMeta")
    self.voice_state_label = QLabel("Voice: READY")
    self.voice_state_label.setObjectName("speechMeta")
    self.speech_btn = self._sub_btn("Play Speech", self.toggle_speech_process)
    self.speech_btn.setObjectName("quickActionButton")
    self.waveform = WaveformWidget()
    self.waveform.setMaximumHeight(26)
    left_col.addWidget(self.mic_state_label)
    left_col.addWidget(self.voice_state_label)
    right_col = QVBoxLayout()
    right_col.setContentsMargins(0, 0, 0, 0)
    right_col.setSpacing(6)
    right_col.addStretch(1)
    right_col.addWidget(self.speech_btn)
    right_col.addWidget(self.waveform)
    l.addLayout(left_col, 0)
    l.addLayout(right_col, 1)
    parent_layout.addWidget(card)

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
    self.tabs.setMinimumHeight(156)
    self.tabs.setMaximumHeight(max(190, int(self.height() * 0.28)))
    self.main_layout.addWidget(self.tabs)

def build_quick_action_bar(self):
    bar = QFrame()
    bar.setObjectName("actionBar")
    self.action_bar = bar
    outer = QVBoxLayout(bar)
    outer.setContentsMargins(10, 6, 10, 6)
    outer.setSpacing(6)
    top_row = QHBoxLayout()
    top_row.setContentsMargins(0, 0, 0, 0)
    top_row.setSpacing(8)

    def _cluster_frame(name, title, meta=""):
        frame = QFrame()
        frame.setObjectName(name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("clusterLabel")
        header.addWidget(title_label)
        header.addStretch(1)
        if meta:
            meta_label = QLabel(meta)
            meta_label.setObjectName("clusterMeta")
            header.addWidget(meta_label)
        layout.addLayout(header)
        return frame, layout

    def _action_button(label, callback):
        btn = self._sub_btn(label, callback)
        btn.setObjectName("quickActionButton")
        return btn

    def _add_action_rows(layout, rows):
        for row_items in rows:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            for label, cb in row_items:
                row.addWidget(_action_button(label, cb))
            layout.addLayout(row)

    self.selected_agent_key = self._load_selected_agent_key()
    persona_cluster, persona_layout = _cluster_frame("personaCluster", "Persona", "Live")
    self.persona_combo = QComboBox()
    self.persona_combo.setObjectName("personaCombo")
    self.persona_combo.setMinimumWidth(150)
    self.persona_combo.addItems(self.agent_names)
    cur_name = self.selected_agent_key.replace("Name: ", "")
    if cur_name in self.agent_names:
        self.persona_combo.setCurrentText(cur_name)
    self.persona_combo.currentIndexChanged.connect(lambda _=None: self.on_persona_changed())
    persona_layout.addWidget(self.persona_combo)
    top_row.addWidget(persona_cluster, 2)

    cabin_cluster, cabin_layout = _cluster_frame("cabinCluster", "Cabin", "Mood")
    self.theme_mode_frame = QFrame()
    self.theme_mode_frame.setObjectName("modeSwitchPill")
    theme_mode_layout = QVBoxLayout(self.theme_mode_frame)
    theme_mode_layout.setContentsMargins(5, 3, 5, 2)
    theme_mode_layout.setSpacing(1)

    icon_row = QHBoxLayout()
    icon_row.setContentsMargins(0, 0, 0, 0)
    icon_row.setSpacing(2)
    self.theme_mode_buttons = {}
    for emoji, key, label in self._theme_mode_definitions():
        button = QPushButton(self._theme_mode_emoji(key))
        button.setObjectName("modeIcon")
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setMinimumSize(16, 16)
        button.setMaximumSize(16, 16)
        button.setToolTip(label)
        button.setAccessibleName(f"{label} display mode")
        button.clicked.connect(lambda _checked=False, theme_key=key: self._apply_theme_mode(theme_key))
        self.theme_mode_buttons[key] = button
        icon_row.addWidget(button)
    theme_mode_layout.addLayout(icon_row)

    self.theme_mode_slider = QSlider(Qt.Orientation.Horizontal)
    self.theme_mode_slider.setObjectName("modeSlider")
    self.theme_mode_slider.setRange(0, len(self._theme_mode_definitions()) - 1)
    self.theme_mode_slider.setSingleStep(1)
    self.theme_mode_slider.setPageStep(1)
    self.theme_mode_slider.setFixedWidth(44)
    self.theme_mode_slider.setFixedHeight(8)
    self.theme_mode_slider.setTracking(True)
    self.theme_mode_slider.valueChanged.connect(
        lambda value: None if getattr(self, "theme_mode_syncing", False) else self._apply_theme_mode(self._theme_key_from_slider(value))
    )
    theme_mode_layout.addWidget(self.theme_mode_slider, alignment=Qt.AlignmentFlag.AlignCenter)
    self._sync_theme_mode_controls(get_theme_name())
    cabin_layout.addWidget(self.theme_mode_frame, alignment=Qt.AlignmentFlag.AlignLeft)
    self.theme_mode_caption = QLabel(self._theme_mode_emoji(get_theme_name()))
    self.theme_mode_caption.setObjectName("modeCaption")
    self.theme_mode_caption.setToolTip(self._theme_mode_label(get_theme_name()))
    cabin_layout.addWidget(self.theme_mode_caption)
    top_row.addWidget(cabin_cluster, 0)

    studio_cluster, studio_layout = _cluster_frame("studioCluster", "Studios", "Flow")
    _add_action_rows(
        studio_layout,
        [
            [
                ("Talk", self.toggle_speech_process),
                ("Study", lambda: aicoregui.study_material(self)),
                ("Research", self.open_research_studio),
            ],
            [
                ("Studio", self.open_control_room),
                ("Coding", self.open_coding_studio),
                ("Nodes", self.open_node_manager),
            ],
        ],
    )
    top_row.addWidget(studio_cluster, 3)

    ops_cluster, ops_layout = _cluster_frame("opsCluster", "Console", "Ops")
    _add_action_rows(
        ops_layout,
        [
            [
                ("Modules", lambda: ModulesDialog(self).exec()),
                ("Settings", self.show_model_selections),
                ("Agentpedia", self.open_agentpedia_viewer),
            ],
            [
                ("Display", self.open_theme_selector),
                ("Background", self.change_background),
            ],
        ],
    )
    top_row.addWidget(ops_cluster, 2)

    heartbeat_cluster, heartbeat_layout = _cluster_frame("heartbeatCluster", "Heartbeat", "Guard")
    _add_action_rows(
        heartbeat_layout,
        [
            [
                ("HB Pause", self.pause_heartbeat),
                ("HB Resume", self.resume_heartbeat),
            ]
        ],
    )
    top_row.addWidget(heartbeat_cluster, 1)
    top_row.addStretch(1)
    outer.addLayout(top_row)
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

    use_hud = theme_name in {"premium_shadowed", "premium_dark"}

    if not bg_path and theme_name in {"premium_shadowed", "premium_dark"}:
        bg_asset = self.hud_assets.get("bg")
        if bg_asset:
            bg_path = str(bg_asset)

    if bg_path:
        safe = str(bg_path).replace("\\", "/")
        style += f"\nQMainWindow {{ background-image: url('{safe}'); background-position: center; background-repeat: no-repeat; }}\n"
        self.state["background_status"] = "Premium" if use_hud else "Custom"
    else:
        self.state["background_status"] = "Monitoring"

    self.setStyleSheet(style)
    self._sync_theme_mode_controls(theme_name)
    self._configure_hud_overlay(use_hud)
    self.update_research_pulse()

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
    self._rebalance_core_splitter()
    if getattr(self, "tabs", None) is not None:
        self.tabs.setMaximumHeight(max(190, int(self.height() * 0.28)))
