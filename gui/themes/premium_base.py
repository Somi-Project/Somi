from __future__ import annotations


def app_stylesheet(colors: dict[str, str], *, mode: str) -> str:
    is_light = mode == "light"
    card_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors['card_start']}, stop:1 {colors['card_end']})"
    )
    hero_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {colors['hero_start']}, stop:0.58 {colors['hero_mid']}, stop:1 {colors['hero_end']})"
    )
    action_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {colors['action_start']}, stop:1 {colors['action_end']})"
    )
    button_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors['button']}, stop:1 {colors['button_alt']})"
    )
    button_hover_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors['button_hover']}, stop:1 {colors['button_hover_alt']})"
    )
    accent_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors['accent_soft']}, stop:1 {colors['accent']})"
    )
    prompt_border = colors["accent"] if not is_light else colors["accent_deep"]

    return f"""
    QMainWindow {{
        background-color: {colors['bg_main']};
        color: {colors['text']};
    }}
    QWidget {{
        font-family: 'Segoe UI Variable Display', 'Bahnschrift', 'Segoe UI', 'Arial', 'Helvetica', sans-serif;
        font-size: 10pt;
        color: {colors['text']};
        outline: none;
    }}
    QLabel {{
        color: {colors['text']};
        background: transparent;
    }}
    QFrame#heroStrip {{
        background: {hero_gradient};
        border: 1px solid {colors['border']};
        border-radius: 22px;
    }}
    QFrame#chatCard, QFrame#presenceCard, QFrame#researchPulseCard, QFrame#intelCard, QFrame#heartbeatCard, QFrame#speechCard, QFrame#activityCard, QFrame#codingHero {{
        background: {card_gradient};
        border: 1px solid {colors['border_soft']};
        border-radius: 20px;
    }}
    QFrame#chatCard {{
        border: 1px solid {colors['border']};
    }}
    QFrame#presenceCard, QFrame#intelCard {{
        border: 1px solid {colors['border_soft']};
    }}
    QFrame#researchPulseCard {{
        border: 1px solid {colors['accent']};
    }}
    QFrame#heartbeatCard {{
        border: 1px solid {colors['border']};
    }}
    QFrame#speechCard {{
        border: 1px solid {colors['border_soft']};
    }}
    QFrame#activityCard {{
        border: 1px solid {colors['border_soft']};
    }}
    QFrame#actionBar {{
        background: {action_gradient};
        border: 1px solid {colors['border']};
        border-radius: 18px;
    }}
    QFrame#personaCluster, QFrame#cabinCluster, QFrame#studioCluster, QFrame#opsCluster, QFrame#heartbeatCluster {{
        background: {colors['bg_surface']};
        border: 1px solid {colors['border_soft']};
        border-radius: 16px;
    }}
    QFrame#studioCluster, QFrame#opsCluster {{
        border: 1px solid {colors['border']};
    }}
    QFrame#modeSwitchPill {{
        background: {colors['mode_pill_bg']};
        border: 1px solid {colors['border_soft']};
        border-radius: 14px;
        min-width: 62px;
    }}
    QPushButton {{
        background: {button_gradient};
        border: 1px solid {colors['border_soft']};
        border-radius: 13px;
        padding: 8px 14px;
        color: {colors['text']};
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {button_hover_gradient};
        border: 1px solid {colors['border']};
    }}
    QPushButton:pressed {{
        background: {colors['button_pressed']};
    }}
    QPushButton#chatHeaderButton {{
        padding: 4px 10px;
        min-height: 24px;
        max-height: 28px;
        font-size: 8.7pt;
        border-radius: 11px;
    }}
    QPushButton#chatSendButton {{
        min-width: 110px;
        font-weight: 700;
        color: {colors['accent_text']};
        background: {accent_gradient};
        border: 1px solid {colors['accent']};
    }}
    QPushButton#chatSendButton:hover, QPushButton#codingPromptButton:hover {{
        background: {colors['accent_hover_gradient']};
    }}
    QPushButton#codingPromptButton {{
        min-width: 170px;
        font-weight: 700;
        color: {colors['accent_text']};
        background: {accent_gradient};
        border: 1px solid {colors['accent']};
    }}
    QPushButton#codingActionButton {{
        min-height: 34px;
    }}
    QPushButton#modeIcon {{
        min-width: 16px;
        max-width: 16px;
        min-height: 16px;
        max-height: 16px;
        padding: 0px;
        border-radius: 6px;
        border: 1px solid transparent;
        background: transparent;
        color: {colors['text_muted']};
        font-weight: 700;
    }}
    QPushButton#quickActionButton {{
        min-height: 22px;
        padding: 4px 8px;
        border-radius: 9px;
        font-size: 8.3pt;
    }}
    QPushButton#quickActionButton:hover {{
        background: {button_hover_gradient};
        border: 1px solid {colors['border']};
    }}
    QPushButton#modeIcon:hover {{
        background: {colors['mode_segment_hover']};
        border: 1px solid {colors['border_soft']};
        color: {colors['text']};
    }}
    QPushButton#modeIcon:checked {{
        background: {accent_gradient};
        border: 1px solid {colors['accent']};
        color: {colors['accent_text']};
    }}
    QSlider#modeSlider {{
        background: transparent;
    }}
    QSlider#modeSlider::groove:horizontal {{
        height: 2px;
        background: {colors['bg_surface']};
        border: 1px solid {colors['border_soft']};
        border-radius: 2px;
    }}
    QSlider#modeSlider::sub-page:horizontal {{
        background: {accent_gradient};
        border-radius: 2px;
    }}
    QSlider#modeSlider::add-page:horizontal {{
        background: {colors['pill_bg']};
        border-radius: 2px;
    }}
    QSlider#modeSlider::handle:horizontal {{
        background: {accent_gradient};
        border: 1px solid {colors['accent']};
        width: 7px;
        margin: -3px 0;
        border-radius: 3px;
    }}
    QSlider#modeSlider::handle:horizontal:hover {{
        background: {colors['accent_hover_gradient']};
    }}
    QTextEdit, QListWidget, QTreeWidget, QTableWidget, QTabWidget::pane {{
        background: {colors['bg_surface']};
        border: 1px solid {colors['border_soft']};
        color: {colors['text']};
        border-radius: 16px;
        padding: 4px;
    }}
    QTextEdit#chatTranscript {{
        background: {colors['bg_transcript']};
        border: 1px solid {colors['border_soft']};
        border-radius: 18px;
        selection-background-color: {colors['selection']};
    }}
    QTextEdit#consoleOutput, QTextEdit#diagnosticPane, QTextEdit#controlOverview, QTextEdit#controlDetail, QTextEdit#codingConsole {{
        background: {colors['bg_console']};
        border-radius: 16px;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 6px 8px;
        border-radius: 9px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background: {colors['selection']};
        border: 1px solid {colors['accent']};
    }}
    QCheckBox {{
        spacing: 8px;
        color: {colors['text']};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 5px;
        border: 1px solid {colors['border_soft']};
        background: {colors['bg_input']};
    }}
    QCheckBox::indicator:checked {{
        background: {accent_gradient};
        border: 1px solid {colors['accent']};
    }}
    QLineEdit, QComboBox {{
        background: {colors['bg_input']};
        color: {colors['text']};
        border: 1px solid {colors['border_soft']};
        border-radius: 12px;
        padding: 7px 10px;
    }}
    QComboBox#personaCombo {{
        min-width: 170px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background: {colors['bg_surface']};
        border: 1px solid {colors['border_soft']};
        selection-background-color: {colors['selection']};
    }}
    QLineEdit#chatPromptEntry {{
        background: {colors['bg_input']};
        border: 2px solid {prompt_border};
        border-radius: 17px;
        padding: 8px 13px;
        font-size: 10.4pt;
        selection-background-color: {colors['selection']};
    }}
    QLineEdit#chatPromptEntry:focus {{
        border: 2px solid {colors['accent']};
        background: {colors['bg_input_focus']};
    }}
    QLineEdit#codingPromptEntry {{
        background: {colors['bg_input']};
        border: 2px solid {colors['border']};
        border-radius: 16px;
        padding: 10px 14px;
        font-size: 10.5pt;
    }}
    QLineEdit#codingPromptEntry:focus {{
        border: 2px solid {colors['accent']};
        background: {colors['bg_input_focus']};
    }}
    QLabel#heroClock {{
        font-size: 17pt;
        font-weight: 800;
        letter-spacing: 0.05em;
        color: {colors['text']};
    }}
    QLabel#clusterLabel {{
        font-size: 8.2pt;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {colors['text_muted']};
    }}
    QLabel#clusterMeta, QLabel#modeCaption {{
        color: {colors['accent_soft']};
        font-size: 8.6pt;
        font-weight: 700;
    }}
    QWidget#researchSignalMeter {{
        min-height: 24px;
        max-height: 24px;
    }}
    QLabel#heartbeatPill, QLabel#metricsPill, QLabel#chatStatusPill, QLabel#chatMetaLabel, QLabel#codingChip, QLabel#statusChip {{
        background: {colors['pill_bg']};
        border: 1px solid {colors['border_soft']};
        border-radius: 13px;
        padding: 8px 12px;
        color: {colors['text']};
        font-weight: 600;
    }}
    QLabel#heroSubline {{
        color: {colors['text_muted']};
        font-size: 9.1pt;
        font-weight: 600;
        padding: 0px 2px 0px 2px;
    }}
    QLabel#panelTitle, QLabel#sectionTitle {{
        font-size: 11.2pt;
        font-weight: 800;
        letter-spacing: 0.03em;
        color: {colors['text']};
    }}
    QLabel#codingTitle {{
        font-size: 16pt;
        font-weight: 800;
        letter-spacing: 0.05em;
        color: {colors['text']};
    }}
    QLabel#codingSubtitle, QLabel#sectionSubtitle, QLabel#ambientLabel, QLabel#dialogSubtitle, QLabel#speechMeta {{
        color: {colors['text_muted']};
    }}
    QLabel#researchPulseQuery {{
        font-size: 10.0pt;
        font-weight: 700;
        color: {colors['text']};
    }}
    QLabel#researchPulseSummary {{
        color: {colors['text_muted']};
        font-size: 8.9pt;
    }}
    QLabel#researchPulseTrace, QLabel#researchPulseMeta, QLabel#speechMeta {{
        color: {colors['text_muted']};
        font-size: 8.5pt;
    }}
    QListWidget#researchPulseFeed {{
        background: {colors['bg_console']};
        border: 1px solid {colors['border_soft']};
        border-radius: 12px;
        padding: 3px;
    }}
    QListWidget#researchPulseFeed::item {{
        padding: 4px 7px;
        margin: 1px 0px;
        border-radius: 8px;
        background: {colors['pill_bg']};
        border: 1px solid {colors['border_soft']};
        color: {colors['text']};
    }}
    QLabel#dialogTitle {{
        font-size: 14pt;
        font-weight: 800;
        color: {colors['text']};
    }}
    QTabBar::tab {{
        background: {colors['tab_bg']};
        border: 1px solid {colors['border_soft']};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        padding: 7px 14px;
        margin-right: 6px;
        color: {colors['text_muted']};
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: {colors['tab_active']};
        border-color: {colors['accent']};
        color: {colors['text']};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 6px 2px 6px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {colors['button_alt']};
        border-radius: 6px;
        min-height: 28px;
        border: 1px solid {colors['border_soft']};
    }}
    QScrollBar::handle:vertical:hover {{
        background: {colors['button_hover_alt']};
        border: 1px solid {colors['border']};
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 12px;
        margin: 2px 6px 2px 6px;
    }}
    QScrollBar::handle:horizontal {{
        background: {colors['button_alt']};
        border-radius: 6px;
        min-width: 28px;
        border: 1px solid {colors['border_soft']};
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {colors['button_hover_alt']};
        border: 1px solid {colors['border']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        background: none;
        border: none;
    }}
    QSplitter::handle {{
        background: {colors['shadow']};
        width: 6px;
        margin: 2px;
        border-radius: 3px;
    }}
    """


def dialog_stylesheet(colors: dict[str, str], *, mode: str, accent: str | None = None) -> str:
    accent_color = accent or colors["accent"]
    return f"""
    QDialog, QWidget {{
        background: {colors['bg_card']};
        color: {colors['text']};
        font-family: 'Segoe UI Variable Display', 'Bahnschrift', 'Segoe UI', 'Arial', 'Helvetica', sans-serif;
    }}
    QLabel {{
        color: {colors['text']};
    }}
    QPushButton {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors['button']}, stop:1 {colors['button_alt']});
        color: {colors['text']};
        border: 1px solid {colors['border_soft']};
        border-radius: 13px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors['button_hover']}, stop:1 {colors['button_hover_alt']});
        border: 1px solid {colors['border']};
    }}
    QLineEdit, QComboBox, QTextEdit, QListWidget, QTreeWidget, QTableWidget {{
        background: {colors['bg_surface']};
        color: {colors['text']};
        border: 1px solid {colors['border_soft']};
        border-radius: 12px;
        padding: 6px 9px;
    }}
    QHeaderView::section {{
        background: {colors['tab_bg']};
        color: {colors['text']};
        border: 1px solid {colors['border_soft']};
        padding: 6px;
    }}
    QTabBar::tab {{
        padding: 11px 18px;
        min-width: 110px;
        background: {colors['tab_bg']};
        border: 1px solid {colors['border_soft']};
        color: {colors['text_muted']};
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
    }}
    QTabBar::tab:selected {{
        background: {accent_color};
        color: {colors['accent_text']};
        border-color: {accent_color};
        font-weight: 700;
    }}
    """
