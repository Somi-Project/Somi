from __future__ import annotations

from .premium_base import app_stylesheet as _app_stylesheet
from .premium_base import dialog_stylesheet as _dialog_stylesheet

COLORS = {
    "bg_main": "#040506",
    "bg_card": "rgba(9, 11, 13, 0.96)",
    "bg_surface": "rgba(12, 14, 17, 0.98)",
    "bg_transcript": "rgba(8, 10, 12, 0.99)",
    "bg_console": "rgba(8, 10, 12, 0.97)",
    "bg_input": "rgba(13, 16, 19, 0.99)",
    "bg_input_focus": "rgba(7, 9, 11, 1.0)",
    "text": "#f3f5f6",
    "text_muted": "#95a0aa",
    "border": "rgba(255, 140, 26, 0.78)",
    "border_soft": "rgba(118, 128, 138, 0.28)",
    "button": "rgba(18, 21, 25, 0.98)",
    "button_alt": "rgba(26, 30, 35, 0.98)",
    "button_hover": "rgba(30, 34, 40, 0.98)",
    "button_hover_alt": "rgba(37, 42, 49, 0.98)",
    "button_pressed": "rgba(14, 16, 20, 1.0)",
    "accent": "#ff8c1a",
    "accent_soft": "#ffb55b",
    "accent_deep": "#dc7403",
    "accent_ok": "#9fd3ff",
    "accent_text": "#111316",
    "hero_start": "rgba(6, 8, 10, 0.98)",
    "hero_mid": "rgba(12, 14, 17, 0.98)",
    "hero_end": "rgba(32, 19, 7, 0.95)",
    "card_start": "rgba(10, 12, 15, 0.98)",
    "card_end": "rgba(18, 21, 26, 0.98)",
    "action_start": "rgba(10, 12, 15, 0.98)",
    "action_end": "rgba(18, 21, 24, 0.98)",
    "pill_bg": "rgba(13, 16, 19, 0.86)",
    "tab_bg": "rgba(11, 13, 16, 0.94)",
    "tab_active": "rgba(21, 25, 30, 0.98)",
    "selection": "rgba(255, 140, 26, 0.24)",
    "mode_pill_bg": "rgba(10, 12, 15, 0.94)",
    "mode_segment_hover": "rgba(255, 140, 26, 0.13)",
    "shadow": "rgba(0, 0, 0, 0.42)",
    "accent_hover_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffc36d, stop:1 #ff982b)",
}


def app_stylesheet() -> str:
    return _app_stylesheet(COLORS, mode="dark")


def dialog_stylesheet(accent: str | None = None) -> str:
    return _dialog_stylesheet(COLORS, mode="dark", accent=accent)
