"""Cockpit-balanced theme with glass panels, bright telemetry accents, and calmer hierarchy."""

COLORS = {
    "bg_main": "#05070d",
    "bg_card": "rgba(8, 14, 28, 0.82)",
    "bg_surface": "rgba(9, 19, 37, 0.90)",
    "bg_input": "rgba(10, 22, 42, 0.96)",
    "text": "#eef5ff",
    "text_muted": "#9fb0c7",
    "border": "rgba(255, 156, 48, 0.52)",
    "border_soft": "rgba(73, 138, 201, 0.34)",
    "button": "rgba(17, 31, 54, 0.92)",
    "button_hover": "rgba(29, 47, 78, 0.98)",
    "accent": "#ff9624",
    "accent_ok": "#35c8ff",
}


def app_stylesheet() -> str:
    return f"""
    QMainWindow {{
        background-color: {COLORS['bg_main']};
        color: {COLORS['text']};
    }}
    QWidget {{
        font-family: 'Segoe UI Variable Text', 'Bahnschrift', 'Segoe UI';
        font-size: 10pt;
        color: {COLORS['text']};
        outline: none;
    }}
    QLabel {{
        color: {COLORS['text']};
        background: transparent;
    }}
    QFrame#heroStrip {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(7, 15, 30, 0.96),
            stop:0.55 rgba(11, 23, 43, 0.94),
            stop:1 rgba(24, 18, 8, 0.88));
        border: 1px solid rgba(255, 156, 48, 0.35);
        border-radius: 18px;
    }}
    QFrame#card {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(8, 14, 28, 0.88),
            stop:1 rgba(12, 24, 46, 0.84));
        border: 1px solid {COLORS['border_soft']};
        border-radius: 18px;
    }}
    QFrame#actionBar {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(8, 16, 31, 0.92),
            stop:1 rgba(17, 24, 44, 0.92));
        border: 1px solid rgba(53, 200, 255, 0.24);
        border-radius: 18px;
    }}
    QFrame#codingHero {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(9, 18, 38, 0.98),
            stop:0.55 rgba(12, 28, 54, 0.95),
            stop:1 rgba(34, 18, 6, 0.92));
        border: 1px solid rgba(255, 156, 48, 0.42);
        border-radius: 20px;
    }}
    QPushButton {{
        background: {COLORS['button']};
        border: 1px solid rgba(255, 156, 48, 0.28);
        border-radius: 12px;
        padding: 8px 14px;
        color: {COLORS['text']};
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {COLORS['button_hover']};
        border: 1px solid rgba(53, 200, 255, 0.40);
    }}
    QPushButton:pressed {{
        background: rgba(16, 34, 58, 1.0);
    }}
    QPushButton#chatHeaderButton {{
        padding: 6px 12px;
        min-height: 28px;
        max-height: 34px;
        font-size: 9.4pt;
        border-radius: 10px;
    }}
    QPushButton#codingPromptButton {{
        min-width: 160px;
        font-weight: 700;
        color: #0d0f14;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #49d2ff,
            stop:1 #ffb347);
        border: 1px solid rgba(73, 210, 255, 0.82);
    }}
    QPushButton#codingPromptButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #67dcff,
            stop:1 #ffc164);
    }}
    QPushButton#codingActionButton {{
        min-height: 34px;
    }}
    QPushButton#chatSendButton {{
        min-width: 110px;
        font-weight: 700;
        color: #0d0f14;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #ffb347,
            stop:1 #ff7a1a);
        border: 1px solid rgba(255, 179, 71, 0.92);
    }}
    QPushButton#chatSendButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #ffc164,
            stop:1 #ff8c2e);
    }}
    QTextEdit, QListWidget, QTreeWidget, QTableWidget, QTabWidget::pane {{
        background: {COLORS['bg_surface']};
        border: 1px solid {COLORS['border_soft']};
        color: {COLORS['text']};
        border-radius: 16px;
        padding: 4px;
    }}
    QTreeWidget::item, QListWidget::item {{
        padding: 6px 8px;
        border-radius: 8px;
    }}
    QTextEdit#chatTranscript {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(7, 13, 24, 0.98),
            stop:1 rgba(12, 18, 32, 0.98));
        color: #eaf2fb;
        border: 1px solid rgba(66, 126, 186, 0.38);
        border-radius: 18px;
        selection-background-color: rgba(53, 200, 255, 0.34);
    }}
    QTextEdit#consoleOutput, QTextEdit#diagnosticPane, QTextEdit#controlOverview, QTextEdit#controlDetail {{
        background: rgba(7, 13, 24, 0.94);
        border-radius: 16px;
    }}
    QTreeWidget#controlTree {{
        alternate-background-color: rgba(10, 18, 33, 0.54);
    }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background: rgba(255, 150, 36, 0.24);
        border: 1px solid rgba(255, 150, 36, 0.45);
    }}
    QLineEdit, QComboBox {{
        background: {COLORS['bg_input']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border_soft']};
        border-radius: 12px;
        padding: 7px 10px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background: rgba(8, 14, 28, 0.98);
        border: 1px solid rgba(53, 200, 255, 0.30);
        selection-background-color: rgba(255, 150, 36, 0.24);
    }}
    QLineEdit#chatPromptEntry {{
        background: rgba(14, 24, 42, 0.98);
        border: 2px solid rgba(255, 150, 36, 0.78);
        border-radius: 16px;
        padding: 10px 14px;
        font-size: 11pt;
        selection-background-color: rgba(53, 200, 255, 0.38);
    }}
    QLineEdit#chatPromptEntry:focus {{
        border: 2px solid rgba(53, 200, 255, 0.92);
        background: rgba(10, 20, 38, 1.0);
    }}
    QLineEdit#codingPromptEntry {{
        background: rgba(11, 21, 40, 0.98);
        border: 2px solid rgba(73, 210, 255, 0.48);
        border-radius: 16px;
        padding: 10px 14px;
        font-size: 10.5pt;
    }}
    QLineEdit#codingPromptEntry:focus {{
        border: 2px solid rgba(255, 156, 48, 0.88);
        background: rgba(8, 18, 34, 1.0);
    }}
    QLabel#heroClock {{
        font-size: 16pt;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: #f3f8ff;
    }}
    QLabel#heroStatus {{
        background: rgba(10, 18, 33, 0.64);
        border: 1px solid rgba(53, 200, 255, 0.20);
        border-radius: 12px;
        padding: 10px 14px;
        color: #d9e8f8;
        font-size: 10pt;
    }}
    QLabel#heartbeatPill, QLabel#metricsPill, QLabel#chatStatusPill, QLabel#chatMetaLabel {{
        background: rgba(9, 18, 33, 0.82);
        border: 1px solid rgba(53, 200, 255, 0.22);
        border-radius: 12px;
        padding: 8px 12px;
        color: #d6e5f6;
    }}
    QLabel#panelTitle, QLabel#sectionTitle {{
        font-size: 12pt;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: #f1f7ff;
    }}
    QLabel#codingTitle {{
        font-size: 16pt;
        font-weight: 800;
        letter-spacing: 0.05em;
        color: #f8fbff;
    }}
    QLabel#codingSubtitle {{
        color: #bdd0e8;
        font-size: 10.2pt;
    }}
    QLabel#codingSectionTitle {{
        font-size: 11.5pt;
        font-weight: 700;
        color: #eff7ff;
        letter-spacing: 0.03em;
    }}
    QLabel#codingChip {{
        background: rgba(6, 14, 28, 0.74);
        border: 1px solid rgba(73, 210, 255, 0.24);
        border-radius: 13px;
        padding: 8px 12px;
        color: #dcecff;
        font-weight: 600;
    }}
    QLabel#sectionSubtitle {{
        color: #b9c8d9;
    }}
    QLabel#ambientLabel {{
        color: #9fb0c7;
        font-size: 10pt;
    }}
    QLabel#statusChip {{
        background: rgba(12, 20, 34, 0.92);
        border: 1px solid rgba(66, 126, 186, 0.34);
        border-radius: 12px;
        padding: 8px 12px;
        color: #c9d7e9;
        font-weight: 600;
    }}
    QTabBar::tab {{
        background: rgba(9, 18, 33, 0.88);
        border: 1px solid rgba(53, 200, 255, 0.14);
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        padding: 10px 18px;
        margin-right: 6px;
        color: #8ea7c4;
    }}
    QTabBar::tab:selected {{
        color: #f4f8ff;
        background: rgba(17, 34, 58, 0.98);
        border: 1px solid rgba(255, 150, 36, 0.44);
    }}
    QHeaderView::section {{
        background: rgba(14, 24, 42, 0.96);
        color: {COLORS['text']};
        border: none;
        border-bottom: 1px solid rgba(53, 200, 255, 0.16);
        padding: 8px 10px;
        font-weight: 700;
    }}
    QTextEdit#codingConsole {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(7, 13, 24, 0.98),
            stop:1 rgba(12, 20, 35, 0.96));
        border: 1px solid rgba(73, 210, 255, 0.18);
        border-radius: 18px;
        padding: 8px;
    }}
    QListWidget#codingList {{
        background: rgba(9, 17, 31, 0.94);
        border: 1px solid rgba(73, 210, 255, 0.18);
        border-radius: 16px;
        padding: 6px;
    }}
    QListWidget#codingList::item {{
        padding: 7px 9px;
        border-radius: 10px;
    }}
    QListWidget#codingList::item:selected {{
        background: rgba(73, 210, 255, 0.16);
        border: 1px solid rgba(255, 156, 48, 0.42);
    }}
    QSplitter::handle {{
        background: rgba(53, 200, 255, 0.12);
    }}
    QSplitter::handle:pressed {{
        background: rgba(255, 150, 36, 0.22);
    }}
    QProgressBar {{
        border: 1px solid rgba(53, 200, 255, 0.40);
        border-radius: 6px;
        background: rgba(3, 10, 22, 0.65);
        color: {COLORS['text']};
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #ff7a1a, stop:1 #ffb84d);
        border-radius: 6px;
    }}
    QScrollBar:vertical {{
        background: rgba(7, 12, 22, 0.55);
        width: 12px;
        margin: 8px 3px 8px 3px;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(78, 126, 179, 0.55);
        min-height: 24px;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(255, 150, 36, 0.68);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar:horizontal, QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
        border: none;
    }}
    QToolTip {{
        background: rgba(8, 14, 28, 0.98);
        color: {COLORS['text']};
        border: 1px solid rgba(255, 156, 48, 0.45);
        padding: 8px 10px;
    }}
    """


def dialog_stylesheet(accent: str | None = None) -> str:
    accent_color = accent or COLORS["accent"]
    return f"""
    QDialog, QWidget {{
        background:{COLORS['bg_surface']};
        color:{COLORS['text']};
        font-family:'Segoe UI Variable Text','Bahnschrift','Segoe UI';
    }}
    QLabel {{ color:{COLORS['text']}; }}
    QLabel#dialogTitle {{
        font-size: 14pt;
        font-weight: 700;
        color: #f3f8ff;
    }}
    QLabel#dialogSubtitle {{
        color: {COLORS['text_muted']};
        font-size: 10pt;
    }}
    QPushButton {{
        background:{COLORS['button']};
        color:{COLORS['text']};
        border:1px solid rgba(255, 156, 48, 0.28);
        border-radius:12px;
        padding:8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background:{COLORS['button_hover']}; }}
    QTabBar::tab {{
        padding:11px 18px;
        min-width:120px;
        background:rgba(12,20,34,0.95);
        border:1px solid {COLORS['border_soft']};
        color:{COLORS['text_muted']};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
    }}
    QTabBar::tab:selected {{ background:{accent_color}; color:black; font-weight:bold; }}
    QTextEdit, QTableWidget, QTreeWidget {{
        background:rgba(8,14,28,0.90);
        color:{COLORS['text']};
        border:1px solid {COLORS['border_soft']};
        border-radius: 14px;
    }}
    QHeaderView::section {{
        background:rgba(19,29,48,0.95);
        color:{COLORS['text']};
        border:1px solid {COLORS['border_soft']};
        padding:8px;
        font-weight: 700;
    }}
    QLineEdit, QComboBox {{
        background:{COLORS['bg_input']};
        color:{COLORS['text']};
        border:1px solid rgba(53, 200, 255, 0.18);
        border-radius: 12px;
        padding: 7px 10px;
    }}
    """
