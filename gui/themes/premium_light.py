from __future__ import annotations

from .premium_base import app_stylesheet as _app_stylesheet
from .premium_base import dialog_stylesheet as _dialog_stylesheet

COLORS = {
    "bg_main": "#edf1f4",
    "bg_card": "#f8fafc",
    "bg_surface": "#ffffff",
    "bg_transcript": "#ffffff",
    "bg_console": "#f5f7fa",
    "bg_input": "#ffffff",
    "bg_input_focus": "#ffffff",
    "text": "#1c232b",
    "text_muted": "#66707c",
    "border": "#ff8c1a",
    "border_soft": "#d5dbe3",
    "button": "#fbfcfd",
    "button_alt": "#eef2f6",
    "button_hover": "#ffffff",
    "button_hover_alt": "#e5ebf1",
    "button_pressed": "#dde5ee",
    "accent": "#ff8c1a",
    "accent_soft": "#ffb45c",
    "accent_deep": "#cf6d00",
    "accent_ok": "#2d6ea8",
    "accent_text": "#171a1f",
    "hero_start": "rgba(255,255,255,0.94)",
    "hero_mid": "rgba(245,247,250,0.96)",
    "hero_end": "rgba(255,239,220,0.92)",
    "card_start": "rgba(255,255,255,0.94)",
    "card_end": "rgba(244,247,251,0.96)",
    "action_start": "rgba(248,250,252,0.96)",
    "action_end": "rgba(239,243,248,0.96)",
    "pill_bg": "rgba(255,255,255,0.78)",
    "tab_bg": "rgba(243,246,250,0.98)",
    "tab_active": "rgba(255,255,255,1.0)",
    "selection": "rgba(255,140,26,0.18)",
    "mode_pill_bg": "rgba(255,255,255,0.86)",
    "mode_segment_hover": "rgba(255,140,26,0.10)",
    "shadow": "rgba(129,142,155,0.18)",
    "accent_hover_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffc06a, stop:1 #ff982b)",
}


def app_stylesheet() -> str:
    return _app_stylesheet(COLORS, mode="light")


def dialog_stylesheet(accent: str | None = None) -> str:
    return _dialog_stylesheet(COLORS, mode="light", accent=accent)
