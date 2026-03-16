"""Soft light theme with rounded controls inspired by classic desktop glass-era UIs."""

COLORS = {
    "bg_main": "#eef1f5",
    "bg_card": "#fbfcfe",
    "bg_surface": "#f6f8fb",
    "bg_input": "#ffffff",
    "text": "#1f2935",
    "text_muted": "#64748b",
    "border": "#cfd7e2",
    "border_soft": "#e3e8ef",
    "button": "#f2f5f9",
    "button_hover": "#e9eef6",
    "accent": "#6d8fc9",
    "accent_ok": "#0f9d58",
}


def app_stylesheet() -> str:
    return f"""
    QMainWindow {{ background-color: {COLORS['bg_main']}; color: {COLORS['text']}; }}
    QLabel {{ color: {COLORS['text']}; }}
    QFrame#card {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border_soft']};
        border-radius: 12px;
    }}
    QPushButton {{
        background:{COLORS['button']};
        border:1px solid {COLORS['border']};
        border-radius:14px;
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
        border-radius:12px;
        padding:5px 8px;
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
        border-radius:14px;
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
