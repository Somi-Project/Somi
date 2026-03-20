from __future__ import annotations

from . import premium_dark, premium_light, premium_shadowed

_THEME_REGISTRY = {
    "premium_light": premium_light,
    "premium_shadowed": premium_shadowed,
    "premium_dark": premium_dark,
}

_THEME_LABELS = {
    "premium_light": "☀️",
    "premium_shadowed": "🌆",
    "premium_dark": "🌙",
}

_THEME_ALIASES = {
    "light": "premium_light",
    "shadowed": "premium_shadowed",
    "dark": "premium_dark",
    "light_modern": "premium_light",
    "cockpit_balanced": "premium_shadowed",
    "default_dark": "premium_dark",
    "jirai_kei": "premium_dark",
}

# Rebind theme labels with ASCII-safe escapes so UI controls do not inherit
# mojibake if a prior write corrupted the original glyph literals.
_THEME_LABELS = {
    "premium_light": "\u2600",
    "premium_shadowed": "\u25d0",
    "premium_dark": "\u263e",
}

_active_theme = "premium_shadowed"

# Mutable dict so imports like `from gui.themes import COLORS` stay updated.
COLORS = dict(premium_shadowed.COLORS)


def normalize_theme_name(name: str) -> str:
    raw = str(name or "").strip().lower()
    if raw in _THEME_REGISTRY:
        return raw
    return _THEME_ALIASES.get(raw, "premium_shadowed")


def list_themes() -> list[tuple[str, str]]:
    return [(key, _THEME_LABELS.get(key, key)) for key in _THEME_REGISTRY]


def get_theme_name() -> str:
    return _active_theme


def set_theme(name: str) -> None:
    global _active_theme
    name = normalize_theme_name(name)
    _active_theme = name
    COLORS.clear()
    COLORS.update(_THEME_REGISTRY[name].COLORS)


def app_stylesheet() -> str:
    return _THEME_REGISTRY[_active_theme].app_stylesheet()


def dialog_stylesheet(accent: str | None = None) -> str:
    return _THEME_REGISTRY[_active_theme].dialog_stylesheet(accent=accent)


__all__ = [
    "COLORS",
    "app_stylesheet",
    "dialog_stylesheet",
    "list_themes",
    "normalize_theme_name",
    "set_theme",
    "get_theme_name",
]
