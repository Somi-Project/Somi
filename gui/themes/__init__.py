from __future__ import annotations

from . import default_dark, jirai_kei, light_modern

_THEME_REGISTRY = {
    "default_dark": default_dark,
    "jirai_kei": jirai_kei,
    "light_modern": light_modern,
}

_THEME_LABELS = {
    "default_dark": "Default Dark",
    "jirai_kei": "Jirai Kei",
    "light_modern": "Light Modern",
}

_active_theme = "default_dark"

# Mutable dict so imports like `from gui.themes import COLORS` stay updated.
COLORS = dict(default_dark.COLORS)


def list_themes() -> list[tuple[str, str]]:
    return [(key, _THEME_LABELS.get(key, key)) for key in _THEME_REGISTRY]


def get_theme_name() -> str:
    return _active_theme


def set_theme(name: str) -> None:
    global _active_theme
    if name not in _THEME_REGISTRY:
        name = "default_dark"
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
    "set_theme",
    "get_theme_name",
]
