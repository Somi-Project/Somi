"""Light high-contrast theme for accessibility and daytime use."""

COLORS = {
    "bg_main": "#f3f5f7",
    "bg_card": "#ffffff",
    "bg_surface": "#f9fbfd",
    "bg_input": "#ffffff",
    "text": "#1d2430",
    "text_muted": "#56637a",
    "border": "#cfd8e3",
    "border_soft": "#dbe3ed",
    "button": "#e8eef7",
    "button_hover": "#dce7f6",
    "accent": "#3b82f6",
    "accent_ok": "#0f9d58",
}


def app_stylesheet() -> str:
    return f"""
    QMainWindow {{ background-color: {COLORS['bg_main']}; color: {COLORS['text']}; }}
    QLabel {{ color: {COLORS['text']}; }}
    QFrame#card {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border_soft']};
        border-radius: 8px;
    }}
    QPushButton {{
        background:{COLORS['button']};
        border:1px solid {COLORS['border']};
        border-radius:6px;
        padding:7px 10px;
        color:{COLORS['text']};
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
        border-radius:6px;
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
        border:1px solid {COLORS['border']};
        border-radius:6px;
        padding:7px 10px;
    }}
    QPushButton:hover {{ background:{COLORS['button_hover']}; }}
    QTabBar::tab {{
        padding:12px 20px;
        min-width:120px;
        background:{COLORS['bg_surface']};
        border:1px solid {COLORS['border']};
        color:{COLORS['text_muted']};
    }}
    QTabBar::tab:selected {{ background:{accent_color}; color:white; font-weight:bold; }}
    QTextEdit, QTableWidget {{
        background:{COLORS['bg_surface']};
        color:{COLORS['text']};
        border:1px solid {COLORS['border']};
    }}
    QHeaderView::section {{
        background:{COLORS['button']};
        color:{COLORS['text']};
        border:1px solid {COLORS['border']};
        padding:6px;
    }}
    """
