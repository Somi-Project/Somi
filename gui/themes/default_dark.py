"""Shared default dark theme tokens and reusable stylesheet helpers."""

COLORS = {
    "bg_main": "#121212",
    "bg_card": "#1a1a1a",
    "bg_surface": "#171717",
    "bg_input": "#2d2d2d",
    "text": "#d8d8d8",
    "text_muted": "#aaaaaa",
    "border": "#404040",
    "border_soft": "#3b3b3b",
    "button": "#303030",
    "button_hover": "#3a3a3a",
    "accent": "#00ddff",
    "accent_ok": "#00ff88",
}


def app_stylesheet() -> str:
    return f"""
    QMainWindow {{ background-color: {COLORS['bg_main']}; color: {COLORS['text']}; }}
    QLabel {{ color: {COLORS['text']}; }}
    QFrame#card {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border_soft']};
        border-radius: 6px;
    }}
    QPushButton {{
        background:{COLORS['button']};
        border:1px solid #565656;
        border-radius:4px;
        padding:7px 10px;
        color:#e8e8e8;
    }}
    QPushButton:hover {{ background:{COLORS['button_hover']}; }}
    QTextEdit, QListWidget, QTabWidget::pane {{
        background:{COLORS['bg_surface']};
        border:1px solid {COLORS['border']};
        color: {COLORS['text']};
    }}
    QLineEdit, QComboBox {{
        background:{COLORS['bg_input']};
        color:{COLORS['text']};
        border:1px solid {COLORS['border']};
        border-radius:4px;
        padding:4px;
    }}
    """


def dialog_stylesheet(accent: str | None = None) -> str:
    accent_color = accent or COLORS["accent"]
    return f"""
    QDialog, QWidget {{ background:{COLORS['bg_card']}; color:{COLORS['text']}; font-family:'Segoe UI'; }}
    QLabel {{ color:{COLORS['text']}; }}
    QPushButton {{
        background:{COLORS['button']};
        color:{COLORS['text']};
        border:1px solid #5a5a5a;
        border-radius:5px;
        padding:7px 10px;
    }}
    QPushButton:hover {{ background:{COLORS['button_hover']}; }}
    QTabBar::tab {{
        padding:12px 20px;
        min-width:120px;
        background:#2a2a2a;
        border:1px solid {COLORS['border']};
        color:{COLORS['text_muted']};
    }}
    QTabBar::tab:selected {{ background:{accent_color}; color:black; font-weight:bold; }}
    QTextEdit, QTableWidget {{
        background:#202020;
        color:{COLORS['text']};
        border:1px solid {COLORS['border']};
    }}
    QHeaderView::section {{
        background:#2f2f2f;
        color:{COLORS['text']};
        border:1px solid {COLORS['border']};
        padding:6px;
    }}
    """

