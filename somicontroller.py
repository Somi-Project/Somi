import json
import logging
import math
import os
import random
import re
import signal
import subprocess
import sys
import importlib
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from pathlib import Path

from gui.qt import (
    QApplication,
    QComboBox,
    QDialog,
    QEasingCurve,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QIcon,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPainter,
    QPixmap,
    QPointF,
    QPropertyAnimation,
    QPushButton,
    QRect,
    QRectF,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QThread,
    QTimer,
    QTransform,
    QVBoxLayout,
    QWidget,
    QColor,
    Qt,
    pyqtSignal,
)

from gui import aicoregui, executivegui, speechgui, telegramgui, toolboxgui, twittergui
from gui.chatpanel import ChatPanel
from gui.chatpopout import ChatPopoutWindow
from gui.codingstudio import CodingStudioWindow
from gui.codingstudio_data import CodingStudioSnapshotBuilder
from gui.controlroom import ControlRoomPanel
from gui.controlroom_data import ControlRoomSnapshotBuilder
from gui.nodemanager import NodeManagerPanel
from gui.nodemanager_data import NodeManagerSnapshotBuilder
from gui.researchstudio import ResearchStudioPanel
from gui.researchstudio_data import ResearchStudioSnapshotBuilder
from gui.themes import app_stylesheet, dialog_stylesheet, get_theme_name, list_themes, set_theme
from automations import AutomationEngine, AutomationStore
from gateway import DeliveryGateway, GatewayService
from heartbeat.integrations.gui_bridge import HeartbeatGUIBridge
from heartbeat.service import HeartbeatService
from executive.memory import Memory3Manager
from ontology import SomiOntology
from ops import OpsControlPlane
from state import SessionEventStore
from subagents import SubagentRegistry, SubagentStatusStore
from workshop.skills import SkillManager, SkillMarketplaceService, StarterStudioService
from workshop.toolbox.coding import CodingSessionService
from workflow_runtime import WorkflowManifestStore, WorkflowRunStore
from workshop.toolbox.registry import ToolRegistry
from workshop.toolbox.runtime import InternalToolRuntime
from workshop.toolbox.agent_core.heartbeat import load_assistant_profile, save_assistant_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

PERSONALITY_CONFIG = Path("config/personalC.json")
GUI_SETTINGS_PATH = Path("config/gui_settings.json")
ASSISTANT_PROFILE_PATH = Path("config/assistant_profile.json")
FACTS = [
    "Octopuses have three hearts, and two of them stop when swimming.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries are not.",
    "Your brain runs on about 20 watts, roughly a dim light bulb.",
    "Sharks existed before trees on Earth.",
    "Honey can stay edible for years when properly sealed.",
]

JOKES = [
    "Why don't programmers like nature? Too many bugs.",
    "I changed my password to 'incorrect' so prompts keep helping me.",
    "Why did the query break up? It needed better context.",
    "I would tell a UDP joke, but you might not get it.",
]

DEV_UPDATES = [
    "Pipeline note: crawlies retrieval is active for research fallback paths.",
    "Stability note: heartbeat and stream diagnostics are running in monitor mode.",
    "System note: weather and headline caches are healthy.",
    "Ops note: model warmups reduce first-token latency in chat sessions.",
]

HUD_ASSET_STEMS = {
    "bg": "bg_cockpit_balanced_1920x1080",
    "frame": "ov_frame_cockpit_balanced_1920x1080",
    "connectors": "ov_connectors_sparse_1920x1080",
    "ring_outer": "hud_ring_outer_orange_1024",
    "ring_inner": "hud_ring_inner_cyan_reticle_1024",
    "glow": "fx_glow_pulse_orange_1024",
    "stream_frame": "panel_stream_heartbeat_frame_920x820",
}


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



def _find_hud_asset(stem: str) -> Path | None:
    roots = [Path("gui/assets/cockpit_balanced"), Path("gui/assets")]
    exts = [".png", ".webp", ".jpg", ".jpeg", ".bmp"]

    for root in roots:
        for ext in exts:
            p = root / f"{stem}{ext}"
            if p.exists():
                return p

    for root in roots:
        if not root.exists():
            continue
        matches = sorted(root.glob(f"{stem}*"))
        if matches:
            return matches[0]

    return None


def _load_hud_pixmap(path: Path | None, *, chroma_key_green: bool = False) -> QPixmap:
    if not path:
        return QPixmap()
    pix = QPixmap(str(path))
    if pix.isNull():
        return pix
    if chroma_key_green:
        mask = pix.createMaskFromColor(QColor(0, 255, 0), Qt.MaskMode.MaskOutColor)
        if not mask.isNull():
            pix.setMask(mask)
    return pix


class HudOverlayWidget(QWidget):
    def __init__(self, parent: QWidget, assets: dict[str, Path | None]):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.frame = _load_hud_pixmap(assets.get("frame"), chroma_key_green=True)
        self.connectors = _load_hud_pixmap(assets.get("connectors"), chroma_key_green=True)
        self.ring_outer = _load_hud_pixmap(assets.get("ring_outer"), chroma_key_green=True)
        self.ring_inner = _load_hud_pixmap(assets.get("ring_inner"), chroma_key_green=True)
        self.glow = _load_hud_pixmap(assets.get("glow"), chroma_key_green=True)
        self.stream_frame = _load_hud_pixmap(assets.get("stream_frame"), chroma_key_green=True)

        self.outer_angle = 0.0
        self.inner_angle = 0.0
        self.pulse_phase = 0.0
        self.core_center = QPointF(0.0, 0.0)
        self.stream_rect = QRect()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(40)  # balanced 25 FPS

    def set_targets(self, core_center: QPointF, stream_rect: QRect):
        self.core_center = core_center
        self.stream_rect = stream_rect
        self.update()

    def set_active(self, active: bool):
        if active and not self.timer.isActive():
            self.timer.start(40)
        if not active and self.timer.isActive():
            self.timer.stop()

    def tick(self):
        self.outer_angle = (self.outer_angle + 0.38) % 360.0
        self.inner_angle = (self.inner_angle - 0.26) % 360.0
        self.pulse_phase += 0.12
        self.update()

    def _draw_rotating_ring(self, painter: QPainter, pix: QPixmap, center: QPointF, diameter: float, angle: float, opacity: float):
        if pix.isNull() or diameter <= 1:
            return
        size = int(max(24, diameter))
        scaled = pix.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.save()
        painter.setOpacity(opacity)
        transform = QTransform()
        transform.translate(center.x(), center.y())
        transform.rotate(angle)
        transform.translate(-(scaled.width() / 2.0), -(scaled.height() / 2.0))
        painter.setTransform(transform, combine=False)
        painter.drawPixmap(0, 0, scaled)
        painter.restore()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if not self.frame.isNull():
            painter.setOpacity(0.58)
            painter.drawPixmap(self.rect(), self.frame)

        if not self.connectors.isNull():
            painter.setOpacity(0.22)
            painter.drawPixmap(self.rect(), self.connectors)

        if not self.stream_frame.isNull() and not self.stream_rect.isNull():
            target = QRectF(self.stream_rect.adjusted(-8, -8, 8, 8))
            painter.setOpacity(0.36)
            painter.drawPixmap(target.toRect(), self.stream_frame)

        cx, cy = self.core_center.x(), self.core_center.y()
        if cx <= 0 or cy <= 0:
            cx = self.width() * 0.72
            cy = self.height() * 0.48
        center = QPointF(cx, cy)

        if not self.glow.isNull():
            glow_size = int(min(self.width(), self.height()) * 0.42)
            glow_rect = QRectF(cx - glow_size / 2, cy - glow_size / 2, glow_size, glow_size)
            pulse = 0.07 + 0.05 * ((math.sin(self.pulse_phase) + 1.0) * 0.5)
            painter.setOpacity(pulse)
            painter.drawPixmap(glow_rect.toRect(), self.glow)

        base = max(160.0, min(self.width(), self.height()) * 0.24)
        self._draw_rotating_ring(painter, self.ring_outer, center, base, self.outer_angle, 0.30)
        self._draw_rotating_ring(painter, self.ring_inner, center, base * 0.66, self.inner_angle, 0.36)


class StatusOrbitWidget(QWidget):
    """Low-cost circular status widget for model/search/task/heartbeat visibility."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(136)
        self._phase = 0.0
        self._items = [
            ("MODEL", "--", QColor("#35c8ff")),
            ("SEARCH", "--", QColor("#ff9624")),
            ("MODE", "--", QColor("#ffb347")),
        ]
        self._heartbeat = "STEADY"
        self._heartbeat_color = QColor("#35c8ff")

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(90)

    def _tick(self):
        self._phase = (self._phase + 0.11) % (math.pi * 2.0)
        self.update()

    def _search_color(self, mode: str) -> QColor:
        m = str(mode or "").upper()
        if m == "LIVE":
            return QColor("#35c8ff")
        if m == "HYBRID":
            return QColor("#ffb347")
        return QColor("#7f8ea3")

    def _task_color(self, mode: str) -> QColor:
        m = str(mode or "").upper()
        if m == "CODING":
            return QColor("#ff9624")
        if m in {"CHAT", "RESPOND"}:
            return QColor("#35c8ff")
        return QColor("#7f8ea3")

    def _heartbeat_color_for(self, state: str) -> QColor:
        s = str(state or "").upper()
        if s in {"ALERT", "ERROR"}:
            return QColor("#ff5e57")
        if s in {"WATCH", "WARN"}:
            return QColor("#ffb347")
        if s == "PAUSED":
            return QColor("#7f8ea3")
        return QColor("#35c8ff")

    def set_values(self, model: str, search_mode: str, task_mode: str, heartbeat_state: str):
        model_short = str(model or "--").strip().upper()
        self._items = [
            ("MODEL", model_short[:14], QColor("#35c8ff")),
            ("SEARCH", str(search_mode or "--").upper(), self._search_color(search_mode)),
            ("MODE", str(task_mode or "--").upper(), self._task_color(task_mode)),
        ]
        self._heartbeat = str(heartbeat_state or "STEADY").upper()
        self._heartbeat_color = self._heartbeat_color_for(self._heartbeat)
        self.update()

    def _draw_orbit(self, painter: QPainter, center: QPointF, radius: float, color: QColor):
        glow = QColor(color)
        glow.setAlpha(90)
        pen = painter.pen()
        pen.setWidth(2)
        pen.setColor(glow)
        painter.setPen(pen)
        painter.drawEllipse(center, radius, radius)

        sweep = 70.0 + 30.0 * (math.sin(self._phase) + 1.0)
        start = int((-35.0 + (self._phase * 28.0)) * 16.0)
        arc_pen = painter.pen()
        arc_pen.setWidth(3)
        arc_pen.setColor(color)
        painter.setPen(arc_pen)
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        painter.drawArc(rect, start, int(sweep * 16.0))

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = max(1, self.width())
        h = max(1, self.height())
        base_y = h * 0.58
        spacing = w / 3.0
        radius = max(22.0, min(40.0, h * 0.20))
        centers = [
            QPointF(spacing * 0.5, base_y),
            QPointF(spacing * 1.5, base_y),
            QPointF(spacing * 2.5, base_y),
        ]

        for i, (label, value, color) in enumerate(self._items):
            c = centers[i]
            self._draw_orbit(painter, c, radius, color)
            painter.setPen(QColor("#9fb0c7"))
            painter.drawText(
                QRectF(c.x() - 70, c.y() - radius - 18, 140, 16),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
            painter.setPen(QColor("#e6ebf2"))
            painter.drawText(
                QRectF(c.x() - 90, c.y() - 10, 180, 22),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                value,
            )


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
        layout.addWidget(parent._sub_btn("Run Diagnostics", parent.run_runtime_diagnostics))
        layout.addWidget(parent._sub_btn("AICore Help", lambda: parent.show_help("aicore")))


class SomiAIGUI(QMainWindow):
    pass
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


























































































import types as _somi_types
from somicontroller_parts.bootstrap_methods import (
    __init__,
    _configure_startup_geometry,
    _selected_agent_name,
    _load_selected_agent_key,
    _persist_selected_agent_key,
    on_persona_changed,
)
from somicontroller_parts.layout_methods import (
    build_state_model,
    build_top_status_strip,
    build_center_panel,
    build_embedded_chat,
    build_presence_panel,
    build_intel_stream,
    build_heartbeat_stream,
    build_activity_stream_card,
    build_speech_mini_console,
    build_bottom_tabs,
    build_quick_action_bar,
    wire_signals_and_timers,
    apply_theme,
    _configure_hud_overlay,
    _update_hud_overlay_targets,
    resizeEvent,
)
from somicontroller_parts.studio_methods import (
    build_control_room_panel,
    build_research_studio_panel,
    build_node_manager_panel,
    open_control_room,
    open_research_studio,
    open_node_manager,
    refresh_control_room,
    refresh_research_studio,
    refresh_node_manager,
    ensure_coding_session,
    open_coding_studio,
    refresh_coding_studio,
    _coding_runtime_ctx,
    run_coding_profile_check,
    run_coding_verify_loop,
    bootstrap_coding_workspace,
    draft_coding_skill,
    open_coding_workspace_folder,
    send_coding_prompt,
)
from somicontroller_parts.settings_methods import (
    read_gui_settings,
    write_gui_settings,
    load_gui_theme_preference,
    _model_profile_options,
    _normalize_model_profile,
    _effective_model_profile,
    _reload_runtime_model_stack,
    load_gui_model_profile_preference,
    apply_model_profile,
    _runtime_model_snapshot,
    open_theme_selector,
    _sub_btn,
    read_settings,
    show_model_selections,
    edit_model_settings,
    change_background,
    read_help_file,
    show_help,
)
from somicontroller_parts.status_methods import (
    push_activity,
    update_clock,
    update_heartbeat_label,
    poll_heartbeat_events,
    _sync_gateway_status,
    _heartbeat_goal_nudge_provider,
    _heartbeat_due_reminders_provider,
    _heartbeat_automation_provider,
    refresh_heartbeat_diagnostics,
    pause_heartbeat,
    resume_heartbeat,
    update_top_strip,
    update_presence,
    _build_intel_items,
    rotate_intel,
    update_stream_meters,
    capture_output_events,
)
from somicontroller_parts.fetch_methods import (
    kickoff_startup_refreshes,
    refresh_weather,
    refresh_news,
    refresh_finance_news,
    refresh_developments,
    refresh_reminders,
    _start_worker,
    on_fetch_result,
    fetch_weather,
    _fetch_rss_headlines,
    fetch_news,
    fetch_finance_news,
    fetch_developments,
    load_reminders,
    trigger_engagement,
    copy_context_pack,
)
from somicontroller_parts.runtime_methods import (
    open_agentpedia_viewer,
    toggle_speech_process,
    load_agent_names,
    refresh_agent_names,
    _default_agent_key,
    preload_default_agent_and_chat_worker,
    _on_agent_warmed,
    toggle_ai_model,
    open_chat,
    ensure_chat_worker_running,
    stop_chat_worker,
    toggle_chat_popout,
    dock_chat_panel,
    toggle_chat_expand,
    open_data_agent,
    run_personality_editor,
    _extract_json_block,
    fetch_runtime_diagnostics,
    run_runtime_diagnostics,
    closeEvent,
)

def _bind_somi_method(func):
    bound = _somi_types.FunctionType(
        func.__code__,
        globals(),
        name=func.__name__,
        argdefs=func.__defaults__,
        closure=func.__closure__,
    )
    bound.__kwdefaults__ = getattr(func, "__kwdefaults__", None)
    bound.__annotations__ = dict(getattr(func, "__annotations__", {}))
    bound.__doc__ = func.__doc__
    bound.__module__ = __name__
    return bound

_EXTRACTED_SOMI_GUI_METHODS = [
    __init__,
    _configure_startup_geometry,
    _selected_agent_name,
    _load_selected_agent_key,
    _persist_selected_agent_key,
    on_persona_changed,
    build_state_model,
    build_top_status_strip,
    build_center_panel,
    build_embedded_chat,
    build_presence_panel,
    build_intel_stream,
    build_heartbeat_stream,
    build_activity_stream_card,
    build_speech_mini_console,
    build_bottom_tabs,
    build_quick_action_bar,
    wire_signals_and_timers,
    apply_theme,
    _configure_hud_overlay,
    _update_hud_overlay_targets,
    resizeEvent,
    build_control_room_panel,
    build_research_studio_panel,
    build_node_manager_panel,
    open_control_room,
    open_research_studio,
    open_node_manager,
    refresh_control_room,
    refresh_research_studio,
    refresh_node_manager,
    ensure_coding_session,
    open_coding_studio,
    refresh_coding_studio,
    _coding_runtime_ctx,
    run_coding_profile_check,
    run_coding_verify_loop,
    bootstrap_coding_workspace,
    draft_coding_skill,
    open_coding_workspace_folder,
    send_coding_prompt,
    read_gui_settings,
    write_gui_settings,
    load_gui_theme_preference,
    _model_profile_options,
    _normalize_model_profile,
    _effective_model_profile,
    _reload_runtime_model_stack,
    load_gui_model_profile_preference,
    apply_model_profile,
    _runtime_model_snapshot,
    open_theme_selector,
    _sub_btn,
    read_settings,
    show_model_selections,
    edit_model_settings,
    change_background,
    read_help_file,
    show_help,
    push_activity,
    update_clock,
    update_heartbeat_label,
    poll_heartbeat_events,
    _sync_gateway_status,
    _heartbeat_goal_nudge_provider,
    _heartbeat_due_reminders_provider,
    _heartbeat_automation_provider,
    refresh_heartbeat_diagnostics,
    pause_heartbeat,
    resume_heartbeat,
    update_top_strip,
    update_presence,
    _build_intel_items,
    rotate_intel,
    update_stream_meters,
    capture_output_events,
    kickoff_startup_refreshes,
    refresh_weather,
    refresh_news,
    refresh_finance_news,
    refresh_developments,
    refresh_reminders,
    _start_worker,
    on_fetch_result,
    fetch_weather,
    _fetch_rss_headlines,
    fetch_news,
    fetch_finance_news,
    fetch_developments,
    load_reminders,
    trigger_engagement,
    copy_context_pack,
    open_agentpedia_viewer,
    toggle_speech_process,
    load_agent_names,
    refresh_agent_names,
    _default_agent_key,
    preload_default_agent_and_chat_worker,
    _on_agent_warmed,
    toggle_ai_model,
    open_chat,
    ensure_chat_worker_running,
    stop_chat_worker,
    toggle_chat_popout,
    dock_chat_panel,
    toggle_chat_expand,
    open_data_agent,
    run_personality_editor,
    _extract_json_block,
    fetch_runtime_diagnostics,
    run_runtime_diagnostics,
    closeEvent,
]

for _somi_method in _EXTRACTED_SOMI_GUI_METHODS:
    _bound_method = _bind_somi_method(_somi_method)
    _bound_method.__qualname__ = f"SomiAIGUI.{_somi_method.__name__}"
    setattr(SomiAIGUI, _somi_method.__name__, _bound_method)

del _somi_method
del _bound_method
del _EXTRACTED_SOMI_GUI_METHODS
del _bind_somi_method
del _somi_types

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = QApplication(sys.argv)
    window = SomiAIGUI()
    window.show()
    sys.exit(app.exec())
