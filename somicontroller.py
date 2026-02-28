import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui import aicoregui, executivegui, speechgui, telegramgui, toolboxgui, twittergui
from gui.themes import app_stylesheet, dialog_stylesheet, get_theme_name, list_themes, set_theme
from heartbeat.integrations.gui_bridge import HeartbeatGUIBridge
from heartbeat.service import HeartbeatService
from handlers.memory import Memory3Manager
from handlers.research.agentpedia import Agentpedia
from handlers.heartbeat import load_assistant_profile, save_assistant_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

PERSONALITY_CONFIG = Path("config/personalC.json")
GUI_SETTINGS_PATH = Path("config/gui_settings.json")
ASSISTANT_PROFILE_PATH = Path("config/assistant_profile.json")
FACTS = [
    "Octopuses have three hearts, and two of them stop when swimming.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries are not.",
    "Your brain runs on about 20 watts—roughly a dim light bulb.",
]


class FetchWorker(QThread):
    result = pyqtSignal(str, object)

    def __init__(self, kind, fn):
        super().__init__()
        self.kind = kind
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.kind, self.fn())
        except Exception as exc:
            logger.exception("Fetch error for %s", self.kind)
            self.result.emit(self.kind, {"error": str(exc)})


class AgentWarmupWorker(QThread):
    warmed = pyqtSignal(bool, str)

    def __init__(self, agent_name: str, user_id: str, use_studies: bool):
        super().__init__()
        self.agent_name = agent_name
        self.user_id = user_id
        self.use_studies = use_studies
        self.agent = None

    def run(self):
        try:
            from agents import Agent

            self.agent = Agent(name=self.agent_name, user_id=self.user_id, use_studies=self.use_studies)
            self.warmed.emit(True, self.agent.name)
        except Exception as exc:
            logger.exception("Agent warmup failed")
            self.warmed.emit(False, str(exc))


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.levels = [0.1] * 20
        self.active = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def set_active(self, active: bool):
        self.active = active
        if active and not self.timer.isActive():
            self.timer.start(120)
        if not active:
            self.timer.stop()
            self.levels = [0.1] * 20
            self.update()

    def tick(self):
        self.levels = [random.uniform(0.15, 1.0) if self.active else 0.1 for _ in self.levels]
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        bar_w = max(2, w // (len(self.levels) * 2))
        spacing = bar_w
        x = 4
        for level in self.levels:
            bar_h = int((h - 8) * level)
            y = (h - bar_h) // 2
            painter.fillRect(x, y, bar_w, bar_h, Qt.GlobalColor.green)
            x += bar_w + spacing


class HoverIntelCard(QFrame):
    hovered = pyqtSignal(bool)

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)


class HelpWindow(QDialog):
    def __init__(self, parent, title, content):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 420)
        self.setStyleSheet(dialog_stylesheet())
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setText(content)
        layout.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(close)


class SocialMediaDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Social Media Agent")
        self.resize(680, 520)
        self.setStyleSheet(dialog_stylesheet())
        layout = QVBoxLayout(self)
        layout.addWidget(parent._sub_btn("Twitter Autotweet Start", lambda: [parent.refresh_agent_names(), twittergui.twitter_autotweet_toggle(parent)]))
        layout.addWidget(parent._sub_btn("Twitter Autoresponse Start", lambda: [parent.refresh_agent_names(), twittergui.twitter_autoresponse_toggle(parent)]))
        layout.addWidget(parent._sub_btn("Developer Tweet", lambda: twittergui.twitter_developer_tweet(parent)))
        layout.addWidget(parent._sub_btn("Twitter Login", lambda: twittergui.twitter_login(parent)))
        layout.addWidget(parent._sub_btn("Twitter Settings", lambda: twittergui.twitter_settings(parent)))
        layout.addWidget(parent._sub_btn("Twitter Help", lambda: parent.show_help("Twitter")))
        layout.addWidget(parent._sub_btn("Telegram Bot Start", lambda: [parent.refresh_agent_names(), telegramgui.telegram_bot_toggle(parent)]))
        layout.addWidget(parent._sub_btn("Telegram Settings", lambda: telegramgui.telegram_settings(parent)))
        layout.addWidget(parent._sub_btn("Telegram Help", lambda: parent.show_help("Telegram")))


class AudioDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Audio Agent")
        self.resize(420, 260)
        self.setStyleSheet(dialog_stylesheet())
        layout = QVBoxLayout(self)
        layout.addWidget(parent._sub_btn("Alex-AI Start/Stop", lambda: [parent.refresh_agent_names(), speechgui.alex_ai_toggle(parent)]))
        layout.addWidget(parent._sub_btn("Audio Settings", lambda: speechgui.audio_settings(parent)))


class ModulesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Modules")
        self.resize(420, 380)
        self.setStyleSheet(dialog_stylesheet())
        layout = QVBoxLayout(self)
        layout.addWidget(parent._sub_btn("Social Media", lambda: SocialMediaDialog(parent).exec()))
        layout.addWidget(parent._sub_btn("Audio", lambda: AudioDialog(parent).exec()))
        layout.addWidget(parent._sub_btn("Data Agent", parent.open_data_agent))
        layout.addWidget(parent._sub_btn("Personality", parent.run_personality_editor))
        layout.addWidget(parent._sub_btn("Model Settings", parent.show_model_selections))
        layout.addWidget(parent._sub_btn("AICore Help", lambda: parent.show_help("aicore")))


class SomiAIGUI(QMainWindow):
    """Prime Console dashboard.

    Timers:
    - clock timer: 1000ms
    - intel rotation: 12s
    - reminders refresh: 120s
    - weather refresh: 20m
    - news refresh: 40m

    Integration notes:
    - Replace `load_reminders` to wire real memory/reminder storage.
    - Replace speech waveform state toggles with real amplitude/listening signals when available.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SOMI")
        self.setWindowIcon(QIcon("assets/icon.ico"))
        self.resize(1200, 760)

        self.telegram_process = None
        self.twitter_autotweet_process = None
        self.twitter_autoresponse_process = None
        self.alex_process = None
        self.ai_model_process = None
        self.preloaded_agent = None
        self.agent_warmup_worker = None
        self.chat_worker = None
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
        self.agentpedia_client = Agentpedia(write_back=False)
        self.heartbeat_service = HeartbeatService()
        self.heartbeat_bridge = HeartbeatGUIBridge(self.heartbeat_service)
        self.memory3 = Memory3Manager(user_id="default_user")
        self.heartbeat_service.set_shared_context(
            HB_CACHED_WEATHER_LINE="",
            HB_CACHED_WEATHER_TS="",
            HB_CACHED_WEATHER_PAYLOAD=None,
            HB_CACHED_URGENT_HEADLINE="",
            HB_CACHED_AGENTPEDIA_FACT="",
            HB_REMINDER_PROVIDER=self._heartbeat_due_reminders_provider,
            HB_GOAL_NUDGE_PROVIDER=self._heartbeat_goal_nudge_provider,
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
        self.apply_theme()
        self.wire_signals_and_timers()
        self.preload_default_agent_and_chat_worker()
        self.heartbeat_service.start()

        self.push_activity("system", "Prime Console booted")
        self.refresh_weather()
        self.refresh_news()
        self.refresh_reminders()

    def build_state_model(self):
        return {
            "system_time_str": "--",
            "timezone": datetime.now().astimezone().tzname() or "Local",
            "model_name": "Unknown",
            "memory_status": "Ready",
            "speech_status": "Idle",
            "background_status": "Monitoring",
            "weather": {"emoji": "🌡", "temp": "--", "line": "Weather unavailable", "last_updated": "--"},
            "news": {"headlines": [], "count": 0, "last_updated": "--"},
            "reminders": {"due_count": 0, "next_due": "None", "last_updated": "--"},
            "activity_events": deque(maxlen=200),
        }

    def build_top_status_strip(self):
        strip = QFrame()
        strip.setObjectName("card")
        layout = QHBoxLayout(strip)

        self.time_label = QLabel("--")
        self.chips_label = QLabel("Online • Model: -- • Memory: Ready • Speech: Idle • Background: Monitoring")
        self.heartbeat_label = QLabel("Heartbeat: --")
        self.metrics_label = QLabel("🌡 -- • 📰 0 • ⏰ 0")

        layout.addWidget(self.time_label, 1)
        layout.addWidget(self.chips_label, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.heartbeat_label, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.metrics_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
        self.main_layout.addWidget(strip)

    def build_center_panel(self):
        row = QHBoxLayout()

        self.build_activity_stream(row)

        middle = QVBoxLayout()
        self.build_presence_panel(middle)
        self.build_intel_stream(middle)
        row.addLayout(middle, 2)

        self.build_speech_mini_console(row)
        self.main_layout.addLayout(row, 1)

    def build_presence_panel(self, parent_layout):
        card = QFrame()
        card.setObjectName("card")
        l = QVBoxLayout(card)
        self.greeting_label = QLabel("Welcome back.")
        self.last_interaction_label = QLabel("No recent session summary")
        self.urgent_line_label = QLabel("Nothing urgent right now.")
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
        self.intel_card.hovered.connect(lambda v: setattr(self, "intel_paused", v))
        il = QVBoxLayout(self.intel_card)
        self.intel_title = QLabel("Intelligence Stream")
        self.intel_text = QLabel("Booting ambient intelligence…")
        self.intel_text.setWordWrap(True)
        il.addWidget(self.intel_title)
        il.addWidget(self.intel_text)

        self.intel_opacity = QGraphicsOpacityEffect(self.intel_text)
        self.intel_text.setGraphicsEffect(self.intel_opacity)
        self.intel_anim = QPropertyAnimation(self.intel_opacity, b"opacity")
        self.intel_anim.setDuration(250)
        self.intel_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        parent_layout.addWidget(self.intel_card)

    def build_activity_stream(self, parent_layout):
        card = QFrame()
        card.setObjectName("card")
        l = QVBoxLayout(card)
        l.addWidget(QLabel("Activity Stream"))
        self.activity_list = QListWidget()
        self.idle_label = QLabel("Somi idle • monitoring")
        l.addWidget(self.activity_list)
        l.addWidget(self.idle_label)
        parent_layout.addWidget(card, 1)

    def build_speech_mini_console(self, parent_layout):
        card = QFrame()
        card.setObjectName("card")
        l = QVBoxLayout(card)
        l.addWidget(QLabel("Speech Mini-Console"))
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
        activity_tab = QWidget()
        activity_tab.setLayout(QVBoxLayout())
        activity_tab.layout().addWidget(QLabel("Use left activity stream for live events."))

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        console_tab = QWidget()
        console_tab.setLayout(QVBoxLayout())
        console_tab.layout().addWidget(self.output_area)

        self.diag_text = QTextEdit()
        self.diag_text.setReadOnly(True)
        self.diag_text.setText("Diagnostics placeholder: weather/news/reminder cache health.")
        diag_tab = QWidget()
        diag_tab.setLayout(QVBoxLayout())
        diag_tab.layout().addWidget(self.diag_text)

        self.tabs.addTab(activity_tab, "Activity")
        self.tabs.addTab(console_tab, "Raw Console")
        self.tabs.addTab(diag_tab, "Diagnostics")
        self.tabs.addTab(toolboxgui.ToolboxPanel(self), "Toolbox")
        self.tabs.addTab(executivegui.ExecutivePanel(self), "Executive")
        self.main_layout.addWidget(self.tabs)

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

    def build_quick_action_bar(self):
        bar = QFrame()
        bar.setObjectName("card")
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
            ("Chat", self.open_chat),
            ("Talk", self.toggle_speech_process),
            ("Study", lambda: aicoregui.study_material(self)),
            ("Modules", lambda: ModulesDialog(self).exec()),
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
        self.intel_timer.start(12000)

        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.refresh_reminders)
        self.reminder_timer.start(120000)

        self.weather_timer = QTimer(self)
        self.weather_timer.timeout.connect(self.refresh_weather)
        self.weather_timer.start(20 * 60 * 1000)

        self.news_timer = QTimer(self)
        self.news_timer.timeout.connect(self.refresh_news)
        self.news_timer.start(40 * 60 * 1000)

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

        self.update_clock()
        self.update_heartbeat_label()
        self.refresh_heartbeat_diagnostics()

    def apply_theme(self):
        self.setStyleSheet(app_stylesheet())

    def read_gui_settings(self):
        if not GUI_SETTINGS_PATH.exists():
            return {}
        try:
            return json.loads(GUI_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write_gui_settings(self, payload):
        try:
            GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            GUI_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write GUI settings: %s", exc)

    def load_gui_theme_preference(self):
        data = self.read_gui_settings()
        set_theme(str(data.get("theme", "default_dark")))


    def open_theme_selector(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Theme")
        dialog.resize(360, 170)
        dialog.setStyleSheet(dialog_stylesheet())

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select interface theme:"))
        combo = QComboBox()
        options = list_themes()
        for key, label in options:
            combo.addItem(label, key)

        current = get_theme_name()
        for i, (key, _label) in enumerate(options):
            if key == current:
                combo.setCurrentIndex(i)
                break
        layout.addWidget(combo)

        buttons = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        cancel_btn = QPushButton("Cancel")
        buttons.addWidget(apply_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        def apply_theme_change():
            selected = combo.currentData()
            selected_name = str(selected or "default_dark")
            set_theme(selected_name)
            data = self.read_gui_settings()
            data["theme"] = selected_name
            self.write_gui_settings(data)
            self.apply_theme()
            self.push_activity("system", f"Theme changed to {combo.currentText()}")
            dialog.accept()

        apply_btn.clicked.connect(apply_theme_change)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _sub_btn(self, text, callback):
        btn = QPushButton(text)
        btn.clicked.connect(callback)
        return btn

    def push_activity(self, kind, message, ts=None, level="info"):
        stamp = ts or datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.state["activity_events"].append({"kind": kind, "message": message, "ts": stamp, "level": level})
        self.activity_list.addItem(QListWidgetItem(line))
        self.activity_list.scrollToBottom()
        self.idle_label.setVisible(False)

    def update_clock(self):
        now = datetime.now().astimezone()
        self.state["system_time_str"] = now.strftime("%a %d %b %Y • %H:%M:%S")
        self.state["timezone"] = now.tzname() or "Local"
        self.time_label.setText(f"{self.state['system_time_str']} ({self.state['timezone']})")
        self.update_presence()
        self.update_top_strip()

    def update_heartbeat_label(self):
        self.heartbeat_label.setText(self.heartbeat_bridge.get_label_text())
        self.heartbeat_label.setToolTip(self.heartbeat_bridge.get_status_tooltip())

    def poll_heartbeat_events(self):
        events = self.heartbeat_bridge.poll_events()
        for event in events:
            title = event.get("title", "Heartbeat event")
            detail = event.get("detail")
            level = str(event.get("level", "INFO")).lower()
            message = f"{title}: {detail}" if detail and title != "Heartbeat steady" else title
            self.push_activity("heartbeat", message, level="warn" if level == "warn" else "info")

    def _heartbeat_goal_nudge_provider(self):
        try:
            return self.memory3.list_active_goals_sync("default_user", scope="task", limit=1)
        except Exception:
            return []

    def _heartbeat_due_reminders_provider(self):
        try:
            return self.memory3.consume_due_reminders_sync("default_user", limit=3)
        except Exception:
            return []

    def refresh_heartbeat_diagnostics(self):
        status = self.heartbeat_service.get_status()
        state = status.get("state", {})
        events = status.get("events", [])[-10:]
        lines = [
            "Heartbeat Diagnostics",
            f"Mode: {state.get('mode', 'MONITOR')}",
            f"Running: {state.get('running', False)}",
            f"Paused: {state.get('paused', False)}",
            f"Last action: {state.get('last_action', 'Idle')}",
            "Recent events:",
        ]
        for event in events:
            lines.append(f"- {event.get('ts', '')} [{event.get('level', 'INFO')}] {event.get('title', '')}")
        if state.get("last_greeting_date"):
            lines.append(f"Morning brief ready: {state.get('last_greeting_date')}")
        if state.get("last_weather_check_ts"):
            lines.append(f"Last weather check: {state.get('last_weather_check_ts')}")
        if state.get("last_weather_warning_ts"):
            lines.append(f"Last weather warning: {state.get('last_weather_warning_ts')}")
        if state.get("last_delight_ts"):
            lines.append(f"Last delight: {state.get('last_delight_ts')}")
        if state.get("last_agentpedia_run_ts"):
            lines.append(f"Last Agentpedia run: {state.get('last_agentpedia_run_ts')}")
        if state.get("last_agentpedia_topic"):
            lines.append(f"Last Agentpedia topic: {state.get('last_agentpedia_topic')}")
        if state.get("last_agentpedia_role"):
            lines.append(f"Last Agentpedia role: {state.get('last_agentpedia_role')}")
        if state.get("last_agentpedia_style"):
            lines.append(f"Last Agentpedia style: {state.get('last_agentpedia_style')}")
        configured_role = getattr(self.heartbeat_service.settings_module, "CAREER_ROLE", None)
        lines.append(f"Configured Career Role: {configured_role or 'General'}")
        lines.append(f"Agentpedia facts: {state.get('agentpedia_facts_count', 0)}")
        if state.get("last_agentpedia_error"):
            lines.append(f"Agentpedia error: {state.get('last_agentpedia_error')}")
        if state.get("last_error"):
            lines.append(f"Last error: {state['last_error']}")
        self.diag_text.setPlainText("\n".join(lines))

    def pause_heartbeat(self):
        self.heartbeat_service.pause()

    def resume_heartbeat(self):
        self.heartbeat_service.resume()

    def open_agentpedia_viewer(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Agentpedia")
        dialog.resize(920, 560)
        dialog.setStyleSheet(dialog_stylesheet())

        layout = QVBoxLayout(dialog)
        row = QHBoxLayout()

        topics = QListWidget()
        viewer = QTextEdit()
        viewer.setReadOnly(True)

        row.addWidget(topics, 1)
        row.addWidget(viewer, 2)
        layout.addLayout(row)

        refresh_btn = QPushButton("Refresh")
        layout.addWidget(refresh_btn)

        def load_topics():
            topics.clear()
            try:
                for item in self.agentpedia_client.list_topics(limit=200):
                    topics.addItem(str(item.get("topic") or "Unknown"))
            except Exception as exc:
                viewer.setPlainText(f"Failed to load Agentpedia topics: {exc}")

        def on_pick():
            it = topics.currentItem()
            if not it:
                return
            topic = it.text().strip()
            try:
                md = self.agentpedia_client.get_topic_page(topic)
                viewer.setPlainText(md)
            except Exception as exc:
                viewer.setPlainText(f"Failed to load topic page: {exc}")

        refresh_btn.clicked.connect(load_topics)
        topics.itemSelectionChanged.connect(on_pick)

        load_topics()
        dialog.exec()

    def update_top_strip(self):
        model_name = self.read_settings().get("DEFAULT_MODEL", "--")
        self.chips_label.setText(
            f"Online • Model: {model_name} • Memory: {self.state['memory_status']} • Speech: {self.state['speech_status']} • Background: {self.state['background_status']}"
        )
        w = self.state["weather"]
        n = self.state["news"]
        r = self.state["reminders"]
        self.metrics_label.setText(
            f"{w['emoji']} {w['temp']} • 📰 {n['count']} • ⏰ {r['due_count']} • W:{w['last_updated']} N:{n['last_updated']}"
        )

    def update_presence(self):
        hour = datetime.now().hour
        greeting = "Good evening" if hour >= 18 else "Good afternoon" if hour >= 12 else "Good morning"
        self.greeting_label.setText(f"{greeting}. SOMI is online.")
        if self.state["activity_events"]:
            last = self.state["activity_events"][-1]
            self.last_interaction_label.setText(f"Last interaction: {last['message']}")
        if self.state["reminders"]["due_count"]:
            self.urgent_line_label.setText(f"{self.state['reminders']['due_count']} reminder(s) due soon.")
        elif self.state["weather"]["line"] != "Weather unavailable":
            self.urgent_line_label.setText(self.state["weather"]["line"])
        else:
            self.urgent_line_label.setText("Nothing urgent right now.")

    def rotate_intel(self):
        if self.intel_paused:
            return
        items = []
        w = self.state["weather"]
        n = self.state["news"]
        r = self.state["reminders"]
        if w["line"]:
            items.append(f"🌤 Weather insight: {w['line']}")
        if n["headlines"]:
            items.append(f"📰 Headline: {n['headlines'][0]}")
        if r["due_count"]:
            items.append(f"⏰ Reminder nudge: {r['due_count']} due. Next: {r['next_due']}")
        items.append(f"🧠 Knowledge: {random.choice(FACTS)}")

        self.intel_index = (self.intel_index + 1) % len(items)
        next_text = items[self.intel_index]

        self.intel_anim.stop()
        try:
            self.intel_anim.finished.disconnect()
        except Exception:
            pass
        self.intel_anim.setStartValue(1.0)
        self.intel_anim.setEndValue(0.2)

        def swap_text():
            self.intel_text.setText(next_text)
            try:
                self.intel_anim.finished.disconnect(swap_text)
            except Exception:
                pass
            self.intel_anim.setStartValue(0.2)
            self.intel_anim.setEndValue(1.0)
            self.intel_anim.start()

        self.intel_anim.finished.connect(swap_text)
        self.intel_anim.start()

    def capture_output_events(self):
        lines = [l for l in self.output_area.toPlainText().splitlines() if l.strip()]
        if len(lines) <= self.last_console_line_count:
            return
        new_lines = lines[self.last_console_line_count :]
        self.last_console_line_count = len(lines)
        for line in new_lines[-6:]:
            plain = line[-180:]
            lowered = plain.lower()
            if "stored memory" in lowered:
                self.push_activity("memory", "Stored memory")
            elif "starting telegram bot" in lowered:
                self.push_activity("module", "Started Telegram bot")
            elif "telegram bot stopped" in lowered:
                self.push_activity("module", "Stopped Telegram bot")
            elif "starting twitter autotweet" in lowered:
                self.push_activity("module", "Started Twitter auto-tweet")
            elif "twitter autotweet stopped" in lowered:
                self.push_activity("module", "Stopped Twitter auto-tweet")
            elif "starting ollama" in lowered:
                self.push_activity("core", "AI model online")
            elif "ollama stopped" in lowered:
                self.push_activity("core", "AI model offline")
            else:
                self.push_activity("console", plain)

    def refresh_weather(self):
        self.push_activity("ambient", "Refreshing weather")
        self._start_worker("weather", self.fetch_weather)

    def refresh_news(self):
        self.push_activity("ambient", "Refreshing news")
        self._start_worker("news", self.fetch_news)

    def refresh_reminders(self):
        self.state["reminders"] = self.load_reminders()
        self.push_activity("ambient", "Reminders refreshed")
        self.update_top_strip()

    def _start_worker(self, kind, fn):
        worker = FetchWorker(kind, fn)
        worker.result.connect(self.on_fetch_result)
        worker.finished.connect(lambda: self.workers.remove(worker) if worker in self.workers else None)
        self.workers.append(worker)
        worker.start()

    def on_fetch_result(self, kind, data):
        now_stamp = datetime.now().strftime("%H:%M")
        if kind == "weather":
            if data.get("ok"):
                self.state["weather"].update(data)
                self.state["weather"]["last_updated"] = now_stamp
                self.heartbeat_service.set_shared_context(
                    HB_CACHED_WEATHER_LINE=self.state["weather"].get("line", ""),
                    HB_CACHED_WEATHER_TS=datetime.now().astimezone().isoformat(),
                    HB_CACHED_WEATHER_PAYLOAD={
                        "temp_c": data.get("temp"),
                        "description": self.state["weather"].get("line", ""),
                        "source": "gui_weather_refresh",
                    },
                )
                self.push_activity("ambient", "Weather refreshed")
            else:
                self.state["weather"] = {"emoji": "🌡", "temp": "--", "line": "Weather unavailable", "last_updated": now_stamp}
                self.heartbeat_service.set_shared_context(HB_CACHED_WEATHER_LINE="", HB_CACHED_WEATHER_TS="", HB_CACHED_WEATHER_PAYLOAD=None)
                self.push_activity("ambient", "Weather unavailable", level="warn")
        if kind == "news":
            if data.get("ok"):
                self.state["news"] = {
                    "headlines": data.get("headlines", []),
                    "count": len(data.get("headlines", [])),
                    "last_updated": now_stamp,
                }
                self.push_activity("ambient", "News refreshed")
            else:
                self.state["news"] = {"headlines": [], "count": 0, "last_updated": now_stamp}
                self.push_activity("ambient", "News unavailable", level="warn")
        self.update_top_strip()
        self.rotate_intel()

    def fetch_weather(self):
        try:
            url = "https://wttr.in/?format=j1"
            with urllib.request.urlopen(url, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
            current = data.get("current_condition", [{}])[0]
            temp = current.get("temp_C", "--")
            code = int(current.get("weatherCode", 0)) if str(current.get("weatherCode", "")).isdigit() else 0
            emoji = "☀️" if code in (0, 1) else "☁️" if code in (2, 3) else "🌧"
            line = f"Feels like {current.get('FeelsLikeC', '--')}°C with {current.get('weatherDesc', [{'value': 'conditions unknown'}])[0].get('value')}"
            return {"ok": True, "emoji": emoji, "temp": f"{temp}°C", "line": line}
        except Exception:
            return {"ok": False}

    def fetch_news(self):
        try:
            url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
            with urllib.request.urlopen(url, timeout=10) as response:
                xml_text = response.read().decode("utf-8", errors="ignore")
            root = ET.fromstring(xml_text)
            headlines = []
            for item in root.findall("./channel/item/title")[:6]:
                t = (item.text or "").strip()
                if t:
                    headlines.append(t)
            return {"ok": True, "headlines": headlines}
        except Exception:
            return {"ok": False}

    def load_reminders(self):
        reminders_file = Path("memory/reminders.json")
        due_count = 0
        next_due = "None"
        if reminders_file.exists():
            try:
                payload = json.loads(reminders_file.read_text(encoding="utf-8"))
                due = [r for r in payload if str(r.get("status", "")).lower() != "done"]
                due_count = len(due)
                if due:
                    next_due = due[0].get("due", "Soon")
            except Exception:
                pass
        return {"due_count": due_count, "next_due": next_due, "last_updated": datetime.now().strftime("%H:%M")}

    def trigger_engagement(self):
        picks = [
            random.choice(FACTS),
            "Try a 2-minute rapid study burst—pick one topic and summarize it.",
            "Ask SOMI for a contrarian take on your current project.",
            self.state["news"]["headlines"][0] if self.state["news"]["headlines"] else "No live headline right now—want a curiosity prompt instead?",
        ]
        msg = random.choice(picks)
        self.intel_text.setText(msg)
        self.push_activity("engage", f"I'm bored trigger: {msg}")

    def copy_context_pack(self):
        headline = self.state["news"]["headlines"][0] if self.state["news"]["headlines"] else "No headline"
        pack = (
            f"Time: {self.state['system_time_str']} {self.state['timezone']}\n"
            f"Weather: {self.state['weather']['line']}\n"
            f"Top headline: {headline}\n"
            f"Reminders due: {self.state['reminders']['due_count']} (next: {self.state['reminders']['next_due']})"
        )
        QApplication.clipboard().setText(pack)
        self.push_activity("context", "Context pack copied to clipboard")

    def toggle_speech_process(self):
        if self.alex_process and self.alex_process.poll() is None:
            speechgui.alex_ai_toggle(self)
            self.speech_active = False
            self.state["speech_status"] = "Idle"
            self.mic_state_label.setText("Mic: OFF")
            self.voice_state_label.setText("Voice: READY")
            self.speech_btn.setText("Play Speech")
            self.waveform.set_active(False)
            self.push_activity("speech", "Speech stopped")
        else:
            self.refresh_agent_names()
            speechgui.alex_ai_toggle(self)
            self.speech_active = True
            self.state["speech_status"] = "Listening"
            self.mic_state_label.setText("Mic: ON")
            self.voice_state_label.setText("Voice: SPEAKING")
            self.speech_btn.setText("Pause Speech")
            self.waveform.set_active(True)
            self.push_activity("speech", "Speech listening")
        self.update_top_strip()

    def load_agent_names(self):
        try:
            characters = json.loads(PERSONALITY_CONFIG.read_text(encoding="utf-8"))
            agent_keys = list(characters.keys())
            agent_names = [k.replace("Name: ", "") for k in agent_keys]
            return agent_keys, agent_names
        except Exception:
            return [], []

    def refresh_agent_names(self):
        self.agent_keys, self.agent_names = self.load_agent_names()
        previous_key = str(getattr(self, "selected_agent_key", "") or "")
        if previous_key not in self.agent_keys:
            self.selected_agent_key = self._default_agent_key()
            if str(self.selected_agent_key or "") and str(self.selected_agent_key) != previous_key:
                try:
                    self._persist_selected_agent_key(self.selected_agent_key)
                except Exception:
                    pass
        if getattr(self, "persona_combo", None):
            previous = self.persona_combo.currentText()
            self.persona_combo.blockSignals(True)
            self.persona_combo.clear()
            self.persona_combo.addItems(self.agent_names)
            target = self.selected_agent_key.replace("Name: ", "")
            if target in self.agent_names:
                self.persona_combo.setCurrentText(target)
            elif previous in self.agent_names:
                self.persona_combo.setCurrentText(previous)
            self.persona_combo.blockSignals(False)

    def _default_agent_key(self):
        if self.agent_keys:
            return self.agent_keys[0]
        return "Name: Somi"

    def preload_default_agent_and_chat_worker(self):
        self.refresh_agent_names()
        agent_key = str(getattr(self, "selected_agent_key", "") or self._default_agent_key())
        if agent_key not in self.agent_keys:
            agent_key = self._default_agent_key()
        self.push_activity("core", f"Preloading agent {agent_key.replace('Name: ', '')}")

        self.agent_warmup_worker = AgentWarmupWorker(agent_name=agent_key, user_id="default_user", use_studies=True)
        self.agent_warmup_worker.warmed.connect(self._on_agent_warmed)
        self.agent_warmup_worker.start()

    def _on_agent_warmed(self, ok: bool, detail: str):
        if ok:
            if self.agent_warmup_worker:
                self.preloaded_agent = self.agent_warmup_worker.agent
            self.push_activity("core", f"Agent warmup ready: {detail}")
            try:
                from gui.aicoregui import ChatWorker

                if self.chat_worker and self.chat_worker.isRunning():
                    return

                agent_key = str(getattr(self, "selected_agent_key", "") or self._default_agent_key())
                if agent_key not in self.agent_keys:
                    agent_key = self._default_agent_key()
                self.chat_worker = ChatWorker(self, agent_key, True, preloaded_agent=self.preloaded_agent)
                self.chat_worker.error_signal.connect(lambda msg: self.push_activity("core", f"Chat worker error: {msg}"))
                self.chat_worker.status_signal.connect(lambda status: self.push_activity("core", f"Chat worker status: {status}"))
                self.chat_worker.start()
                self.push_activity("core", "Chat worker pre-initialized")
            except Exception as exc:
                logger.exception("Failed to pre-initialize chat worker")
                self.push_activity("core", f"Chat worker preload failed: {exc}")
        else:
            self.push_activity("core", f"Agent warmup failed: {detail}")

    def toggle_ai_model(self):
        aicoregui.ai_model_start_stop(self)
        self.push_activity("core", "AI model toggled")

    def open_chat(self):
        self.refresh_agent_names()
        if getattr(self, "persona_combo", None):
            idx = self.persona_combo.currentIndex()
            if 0 <= idx < len(self.agent_keys):
                self.selected_agent_key = self.agent_keys[idx]
        aicoregui.ai_chat(self)
        self.push_activity("core", "User opened chat")

    def open_data_agent(self):
        from gui import dataagentgui

        dialog = dataagentgui.DataAgentWindow(self)
        dialog.exec()
        self.push_activity("module", "User opened data agent")

    def run_personality_editor(self):
        try:
            subprocess.Popen([sys.executable, "persona.py"], shell=False)
            self.output_area.append("Personality Editor launched.")
            self.push_activity("module", "Personality editor opened")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to launch Personality Editor: {exc}")

    def read_settings(self):
        settings = {"DEFAULT_MODEL": "dolphin3", "MEMORY_MODEL": "codellama", "DEFAULT_TEMP": "0.7", "VISION_MODEL": "Gemma3:4b"}
        path = Path("config/settings.py")
        if not path.exists():
            return settings
        content = path.read_text(encoding="utf-8")
        for key in settings:
            m = re.search(rf"^{key}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\n#]+))", content, re.MULTILINE)
            if m:
                settings[key] = (m.group(1) or m.group(2) or m.group(3)).strip()
        return settings

    def show_model_selections(self):
        try:
            settings = self.read_settings()
            model_window = QWidget()
            model_window.setWindowTitle("AI Model Selections")
            model_window.setGeometry(100, 100, 440, 320)
            model_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            layout = QVBoxLayout(model_window)
            layout.setSpacing(10)

            label = QLabel("Model Settings")
            layout.addWidget(label)

            model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
            for key in model_keys:
                value = settings.get(key, "Not set")
                frame = QWidget()
                frame_layout = QHBoxLayout(frame)
                key_label = QLabel(f"{key}:")
                key_label.setFixedWidth(150)
                value_label = QLabel(value)
                frame_layout.addWidget(key_label)
                frame_layout.addWidget(value_label)
                frame_layout.addStretch()
                layout.addWidget(frame)

            edit_button = QPushButton("Edit Settings")
            edit_button.clicked.connect(lambda: self.edit_model_settings(settings, model_window))
            layout.addWidget(edit_button)
            model_window.show()
            self.model_settings_window = model_window
            self.push_activity("module", "Opened model settings")
        except Exception as e:
            logger.error(f"Error showing model selections: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to show model selections: {str(e)}")

    def edit_model_settings(self, current_settings, parent_window):
        try:
            edit_window = QWidget()
            edit_window.setWindowTitle("Edit Model Settings")
            edit_window.setGeometry(120, 120, 440, 360)
            edit_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            layout = QVBoxLayout(edit_window)
            entries = {}
            model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
            for key in model_keys:
                frame = QWidget()
                frame_layout = QHBoxLayout(frame)
                key_label = QLabel(f"{key}:")
                key_label.setFixedWidth(150)
                entry = QLineEdit()
                entry.setText(current_settings.get(key, ""))
                frame_layout.addWidget(key_label)
                frame_layout.addWidget(entry)
                entries[key] = entry
                layout.addWidget(frame)

            def save_settings():
                try:
                    new_settings = {key: entry.text().strip() for key, entry in entries.items()}
                    temp = float(new_settings["DEFAULT_TEMP"])
                    if not 0.0 <= temp <= 1.0:
                        raise ValueError("DEFAULT_TEMP must be between 0.0 and 1.0")

                    settings_path = Path("config/settings.py")
                    if not settings_path.exists():
                        QMessageBox.critical(edit_window, "Error", "config/settings.py not found.")
                        return

                    lines = settings_path.read_text(encoding="utf-8").splitlines(keepends=True)
                    new_lines = []
                    updated_keys = set()
                    for line in lines:
                        stripped = line.strip()
                        replaced = False
                        for key, value in new_settings.items():
                            if stripped.startswith(f"{key} ="):
                                new_line = f"{key} = {value}\n" if key == "DEFAULT_TEMP" else f'{key} = "{value}"\n'
                                new_lines.append(new_line)
                                updated_keys.add(key)
                                replaced = True
                                break
                        if not replaced:
                            new_lines.append(line)

                    for key, value in new_settings.items():
                        if key not in updated_keys:
                            new_lines.append(f"{key} = {value}\n" if key == "DEFAULT_TEMP" else f'{key} = "{value}"\n')

                    settings_path.write_text("".join(new_lines), encoding="utf-8")
                    self.output_area.append("Model settings updated successfully.")
                    self.output_area.ensureCursorVisible()
                    self.push_activity("module", "Updated model settings")
                    QMessageBox.information(edit_window, "Success", "Model settings updated successfully!")
                    edit_window.close()
                    parent_window.close()
                    self.show_model_selections()
                except ValueError as ve:
                    QMessageBox.critical(edit_window, "Error", str(ve))
                except Exception as e:
                    logger.error(f"Error saving settings: {str(e)}")
                    QMessageBox.critical(edit_window, "Error", f"Failed to save settings: {str(e)}")

            save_button = QPushButton("Save")
            save_button.clicked.connect(save_settings)
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(edit_window.close)
            layout.addWidget(save_button)
            layout.addWidget(cancel_button)
            edit_window.show()
            self.edit_settings_window = edit_window
        except Exception as e:
            logger.error(f"Error editing model settings: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to edit model settings: {str(e)}")

    def change_background(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp)",
        )
        if not file_name:
            return
        if not os.path.exists(file_name):
            QMessageBox.warning(self, "Error", "Selected image file does not exist.")
            return
        safe_path = file_name.replace("\\", "/")
        self.setStyleSheet(
            self.styleSheet()
            + f"\nQMainWindow {{ background-image: url('{safe_path}'); background-position: center; background-repeat: no-repeat; }}"
        )
        self.output_area.append(f"Background changed to {os.path.basename(file_name)}")
        self.output_area.ensureCursorVisible()
        self.push_activity("ui", "Background updated")

    def read_help_file(self, filename):
        path = Path("help") / f"{filename}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else f"Help file '{filename}.txt' not found."

    def show_help(self, section):
        content = self.read_help_file(section)
        if "not found" in content:
            QMessageBox.warning(self, "Error", content)
            return
        HelpWindow(self, f"Help - {section}", content).exec()

    def closeEvent(self, event):
        self.heartbeat_service.stop()
        if self.chat_worker and self.chat_worker.isRunning():
            self.chat_worker.stop()
            self.chat_worker.wait(1500)
        if self.agent_warmup_worker and self.agent_warmup_worker.isRunning():
            self.agent_warmup_worker.quit()
            self.agent_warmup_worker.wait(1000)
        for process in [self.telegram_process, self.twitter_autotweet_process, self.twitter_autoresponse_process, self.alex_process, self.ai_model_process]:
            if process and process.poll() is None:
                try:
                    os.kill(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        super().closeEvent(event)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = QApplication(sys.argv)
    window = SomiAIGUI()
    window.show()
    sys.exit(app.exec())
