from __future__ import annotations

from .premium_base import app_stylesheet as _app_stylesheet
from .premium_base import dialog_stylesheet as _dialog_stylesheet

COLORS = {
    "bg_main": "#090b0f",
    "bg_card": "rgba(15, 18, 24, 0.94)",
    "bg_surface": "rgba(18, 22, 28, 0.96)",
    "bg_transcript": "rgba(10, 13, 18, 0.98)",
    "bg_console": "rgba(12, 15, 20, 0.96)",
    "bg_input": "rgba(15, 19, 24, 0.98)",
    "bg_input_focus": "rgba(9, 13, 18, 1.0)",
    "text": "#eef2f4",
    "text_muted": "#9aa6b1",
    "border": "rgba(255, 140, 26, 0.72)",
    "border_soft": "rgba(132, 145, 156, 0.34)",
    "button": "rgba(27, 31, 38, 0.96)",
    "button_alt": "rgba(36, 41, 49, 0.96)",
    "button_hover": "rgba(38, 43, 52, 0.98)",
    "button_hover_alt": "rgba(50, 56, 66, 0.98)",
    "button_pressed": "rgba(22, 26, 32, 1.0)",
    "accent": "#ff8c1a",
    "accent_soft": "#ffb04d",
    "accent_deep": "#da7200",
    "accent_ok": "#92c5ff",
    "accent_text": "#121417",
    "hero_start": "rgba(11, 14, 18, 0.96)",
    "hero_mid": "rgba(18, 22, 28, 0.96)",
    "hero_end": "rgba(39, 25, 10, 0.94)",
    "card_start": "rgba(17, 21, 27, 0.95)",
    "card_end": "rgba(24, 28, 36, 0.95)",
    "action_start": "rgba(15, 18, 24, 0.96)",
    "action_end": "rgba(24, 28, 34, 0.96)",
    "pill_bg": "rgba(18, 21, 27, 0.82)",
    "tab_bg": "rgba(16, 20, 26, 0.92)",
    "tab_active": "rgba(27, 33, 40, 0.98)",
    "selection": "rgba(255, 140, 26, 0.22)",
    "mode_pill_bg": "rgba(14, 17, 22, 0.92)",
    "mode_segment_hover": "rgba(255, 140, 26, 0.12)",
    "shadow": "rgba(0, 0, 0, 0.35)",
    "accent_hover_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffbc63, stop:1 #ff9729)",
}


def app_stylesheet() -> str:
    return _app_stylesheet(COLORS, mode="shadowed")


def dialog_stylesheet(accent: str | None = None) -> str:
    return _dialog_stylesheet(COLORS, mode="shadowed", accent=accent)
