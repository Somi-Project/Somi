from __future__ import annotations

import unittest

from gui.themes import (
    app_stylesheet,
    dialog_stylesheet,
    get_theme_name,
    list_themes,
    normalize_theme_name,
    set_theme,
)


class GuiThemeTests(unittest.TestCase):
    def test_registry_exposes_three_premium_modes(self) -> None:
        self.assertEqual(
            list_themes(),
            [
                ("premium_light", "\u2600"),
                ("premium_shadowed", "\u25d0"),
                ("premium_dark", "\u263e"),
            ],
        )

    def test_legacy_theme_names_normalize_to_premium_modes(self) -> None:
        self.assertEqual(normalize_theme_name("light_modern"), "premium_light")
        self.assertEqual(normalize_theme_name("cockpit_balanced"), "premium_shadowed")
        self.assertEqual(normalize_theme_name("default_dark"), "premium_dark")
        self.assertEqual(normalize_theme_name("jirai_kei"), "premium_dark")

    def test_premium_stylesheets_include_dashboard_switch_selectors(self) -> None:
        set_theme("premium_shadowed")
        self.assertEqual(get_theme_name(), "premium_shadowed")
        css = app_stylesheet()
        dialog_css = dialog_stylesheet()
        self.assertIn("QFrame#modeSwitchPill", css)
        self.assertIn("QFrame#personaCluster", css)
        self.assertIn("QFrame#studioCluster", css)
        self.assertIn("QFrame#opsCluster", css)
        self.assertIn("QFrame#heartbeatCluster", css)
        self.assertIn("QPushButton#modeIcon", css)
        self.assertIn("QPushButton#quickActionButton", css)
        self.assertIn("QSlider#modeSlider::groove:horizontal", css)
        self.assertIn("QFrame#chatCard", css)
        self.assertIn("QFrame#researchPulseCard", css)
        self.assertIn("QLabel#researchPulseQuery", css)
        self.assertIn("QLabel#clusterLabel", css)
        self.assertIn("QLabel#modeCaption", css)
        self.assertIn("QWidget#researchSignalMeter", css)
        self.assertIn("QComboBox#personaCombo", css)
        self.assertIn("QCheckBox::indicator:checked", css)
        self.assertIn("QScrollBar::handle:vertical", css)
        self.assertIn("QLineEdit#chatPromptEntry", css)
        self.assertIn("QTabBar::tab:selected", dialog_css)


if __name__ == "__main__":
    unittest.main()
