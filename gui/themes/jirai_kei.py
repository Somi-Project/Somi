"""Jirai Kei-inspired dark theme tokens and stylesheet helpers."""

COLORS = {
    "bg_main": "#141018",
    "bg_card": "#1c1622",
    "bg_surface": "#241b2d",
    "bg_input": "#2b2133",
    "text": "#f1e8f5",
    "text_muted": "#c7b6cc",
    "border": "#4b3a59",
    "border_soft": "#3a2f46",
    "button": "#35263f",
    "button_hover": "#463353",
    "accent": "#d79bb7",
    "accent_ok": "#b8a2d9",
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
    QTabBar::tab:selected {{ background:{accent_color}; color:black; font-weight:bold; }}
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
