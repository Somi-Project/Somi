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

from gui import aicoregui, speechgui, telegramgui, twittergui
from gui.themes import app_stylesheet, dialog_stylesheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

PERSONALITY_CONFIG = Path("config/personalC.json")
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

        self.root = QWidget()
        self.setCentralWidget(self.root)
        self.main_layout = QVBoxLayout(self.root)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        self.build_top_status_strip()
        self.build_center_panel()
        self.build_bottom_tabs()
        self.build_quick_action_bar()
        self.apply_theme()
        self.wire_signals_and_timers()

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
        self.metrics_label = QLabel("🌡 -- • 📰 0 • ⏰ 0")

        layout.addWidget(self.time_label, 1)
        layout.addWidget(self.chips_label, 2, alignment=Qt.AlignmentFlag.AlignCenter)
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

        diag = QTextEdit()
        diag.setReadOnly(True)
        diag.setText("Diagnostics placeholder: weather/news/reminder cache health.")
        diag_tab = QWidget()
        diag_tab.setLayout(QVBoxLayout())
        diag_tab.layout().addWidget(diag)

        self.tabs.addTab(activity_tab, "Activity")
        self.tabs.addTab(console_tab, "Raw Console")
        self.tabs.addTab(diag_tab, "Diagnostics")
        self.main_layout.addWidget(self.tabs)

    def build_quick_action_bar(self):
        bar = QFrame()
        bar.setObjectName("card")
        l = QHBoxLayout(bar)
        for label, cb in [
            ("Chat", self.open_chat),
            ("Talk", self.toggle_speech_process),
            ("Study", lambda: aicoregui.study_material(self)),
            ("Modules", lambda: ModulesDialog(self).exec()),
            ("Settings", self.show_model_selections),
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

        self.update_clock()

    def apply_theme(self):
        self.setStyleSheet(app_stylesheet())

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
                self.push_activity("ambient", "Weather refreshed")
            else:
                self.state["weather"] = {"emoji": "🌡", "temp": "--", "line": "Weather unavailable", "last_updated": now_stamp}
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

    def toggle_ai_model(self):
        aicoregui.ai_model_start_stop(self)
        self.push_activity("core", "AI model toggled")

    def open_chat(self):
        self.refresh_agent_names()
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
