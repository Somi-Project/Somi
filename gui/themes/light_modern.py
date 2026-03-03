"""Soft beach-inspired light theme with rounded controls and gentle contrast."""

COLORS = {
    "bg_main": "#e8f4fb",       # sky haze
    "bg_card": "#f8fbfd",       # cloud white
    "bg_surface": "#eef7fb",    # sea mist
    "bg_input": "#fffdfa",      # warm sand white
    "text": "#1f3442",
    "text_muted": "#5f7d90",
    "border": "#c9dde8",
    "border_soft": "#dbeaf2",
    "button": "#e6f2f9",
    "button_hover": "#d8ebf6",
    "accent": "#4fa3c7",        # lagoon blue
    "accent_ok": "#0f9d58",
}


def app_stylesheet() -> str:
    return f"""
    QMainWindow {{ background-color: {COLORS['bg_main']}; color: {COLORS['text']}; }}
    QLabel {{ color: {COLORS['text']}; }}
    QFrame#card {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border_soft']};
        border-radius: 14px;
    }}
    QPushButton {{
        background:{COLORS['button']};
        border:1px solid {COLORS['border']};
        border-radius:16px;
        padding:8px 16px;
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
        border-radius:13px;
        padding:6px 9px;
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
        border-radius:16px;
        padding:8px 16px;
    }}
    QPushButton:hover {{ background:{COLORS['button_hover']}; }}
    QTabBar::tab {{
        padding:12px 20px;
        min-width:120px;
        background:{COLORS['bg_surface']};
        border:1px solid {COLORS['border']};
        color:{COLORS['text_muted']};
    }}
    QTabBar::tab:selected {{ background:{accent_color}; color:white; font-weight:bold; border-radius:10px; }}
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
