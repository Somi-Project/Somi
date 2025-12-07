import sys
import os
import json
import re
import subprocess
import signal
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QWidget, QPushButton, QTextEdit, QLabel, QDialog, QMessageBox,
    QFileDialog, QLineEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

import logging
from gui import telegramgui, twittergui, aicoregui, speechgui

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

PERSONALITY_CONFIG = Path("config/personalC.json")

class HelpWindow(QDialog):
    def __init__(self, parent, title, content):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(150, 150, 500, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setText(content)
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: rgba(42, 42, 42, 0.8);
                color: #D3D3D3;
                border: 1px solid #6A6A6A;
                border-radius: 4px;
                font: 10pt 'Segoe UI', 'Arial';
                padding: 10px;
            }
        """)
        layout.addWidget(text_edit)

        close_button = QPushButton("Close")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #4A4A4A;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5A5A5A, stop:1 #4A4A4A);
                color: #E0E0E0;
                border: 1px solid #6A6A6A;
                border-radius: 4px;
                padding: 6px;
                font: 10pt 'Segoe UI', 'Arial';
                text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                transition: all 0.2s ease;
            }
            QPushButton:hover {
                background-color: #5A5A5A;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6A6A6A, stop:1 #5A5A5A);
                box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
            }
            QPushButton:pressed {
                background-color: #3A3A3A;
                border: 1px solid #5A5A5A;
                box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
            }
        """)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

class SocialMediaDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Social Media Agent")
        self.setGeometry(150, 100, 680, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setHorizontalSpacing(25)
        grid.setVerticalSpacing(15)
        row = 0

        # Twitter Section
        grid.addWidget(QLabel("Twitter"), row, 0, 1, 2)
        row += 1
        grid.addWidget(parent._sub_btn("Twitter Autotweet Start", lambda: [parent.refresh_agent_names(), twittergui.twitter_autotweet_toggle(parent)]), row, 0)
        grid.addWidget(parent._sub_btn("Twitter Autoresponse Start", lambda: [parent.refresh_agent_names(), twittergui.twitter_autoresponse_toggle(parent)]), row, 1)
        row += 1
        grid.addWidget(parent._sub_btn("Developer Tweet", lambda: twittergui.twitter_developer_tweet(parent)), row, 0)
        grid.addWidget(parent._sub_btn("Twitter Login", lambda: twittergui.twitter_login(parent)), row, 1)
        row += 1
        grid.addWidget(parent._sub_btn("Twitter Settings", lambda: twittergui.twitter_settings(parent)), row, 0)
        grid.addWidget(parent._sub_btn("Twitter Help", lambda: parent.show_help("Twitter")), row, 1)
        row += 1

        # Telegram Section
        grid.addWidget(QLabel("Telegram"), row, 0, 1, 2)
        row += 1
        grid.addWidget(parent._sub_btn("Telegram Bot Start", lambda: [parent.refresh_agent_names(), telegramgui.telegram_bot_toggle(parent)]), row, 0)
        grid.addWidget(parent._sub_btn("Telegram Settings", lambda: telegramgui.telegram_settings(parent)), row, 1)
        row += 1
        grid.addWidget(parent._sub_btn("Telegram Help", lambda: parent.show_help("Telegram")), row, 0)

        layout.addLayout(grid)
        layout.addStretch()

class AudioDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Audio Agent")
        self.setGeometry(300, 150, 400, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        layout.addWidget(parent._sub_btn("Alex-AI Start/Stop", lambda: [parent.refresh_agent_names(), speechgui.alex_ai_toggle(parent)]))
        layout.addWidget(parent._sub_btn("Audio Settings", lambda: speechgui.audio_settings(parent)))
        layout.addStretch()

class SomiAIGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("Initializing SomiAIGUI...")
        self.setWindowTitle("Somi AI GUI")
        self.setGeometry(100, 100, 960, 700)

        # Process tracking
        self.telegram_process = None
        self.twitter_autotweet_process = None
        self.twitter_autoresponse_process = None
        self.alex_process = None
        self.ai_model_process = None
        
        self.ai_model_start_button = QPushButton("AI Model Start/Stop")  # keeps aicoregui.py happy
        self.ai_model_start_button.setVisible(False)  # invisible, but exists so no crash

        self.agent_keys, self.agent_names = self.load_agent_names()

        # Main layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_layout.setSpacing(18)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_widget.setLayout(main_layout)

        # Background
        self.assets_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        self.default_background = os.path.join(self.assets_folder, "default_background.jpg")
        self.background_path = self.default_background if os.path.exists(self.default_background) else ""
        self.update_stylesheet()

        # === 8 MAIN BUTTONS ===
        grid = QGridLayout()
        grid.setSpacing(18)
        main_layout.addLayout(grid)

        grid.addWidget(self._main_btn("Initiate.", self.toggle_ai_model), 0, 0)
        grid.addWidget(self._main_btn("Study Injection", lambda: aicoregui.study_material(self)), 0, 1)
        grid.addWidget(self._main_btn("Secret Chat", self.open_chat), 1, 0)
        grid.addWidget(self._main_btn("Guide", lambda: self.show_help("aicore")), 2, 1)
        grid.addWidget(self._main_btn("Social Media", lambda: SocialMediaDialog(self).exec()), 2, 0)
        grid.addWidget(self._main_btn("Audio Interface (experimental)", lambda: AudioDialog(self).exec()), 3, 0)
        grid.addWidget(self._main_btn("Personality", self.run_personality_editor),1, 1)
        grid.addWidget(self._main_btn("General Settings", self.show_model_selections), 3, 1)

        main_layout.addStretch()

        # Output Log
        output_label = QLabel("Output Log")
        main_layout.addWidget(output_label)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        main_layout.addWidget(self.output_area)

        # Background changer
        change_bg = QPushButton("+")
        change_bg.setFixedSize(30, 30)
        change_bg.setStyleSheet("border-radius:15px; background:#4A4A4A; color:#E0E0E0; font:12pt;")
        change_bg.clicked.connect(self.change_background)
        main_layout.addWidget(change_bg, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        self.resizeEvent = self.on_resize

    def _main_btn(self, text, callback):
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                                          stop:0 #5A5A5A, stop:1 #444444);
                color: #E0E0E0;
                border: 1px solid #666666;
                border-radius: 8px;
                padding: 10px 20px;
                font: bold 11pt 'Segoe UI';
                min-height: 100px;
                min-width: 112px;
            
            QPushButton:hover {
                background: #5A5A5A;
                border: 1px solid #888888;
            }
            QPushButton:pressed {
                background: #3A3A3A;
            }
        """)
        btn.clicked.connect(callback)
        return btn

    def _sub_btn(self, text, callback):
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #4A4A4A;
                color: #E0E0E0;
                border: 1px solid #6A6A6A;
                border-radius: 4px;
                padding: 8px;
                font: 10pt 'Segoe UI';
            }
            QPushButton:hover { background: #5A5A5A; }
        """)
        btn.clicked.connect(callback)
        return btn

    # === ALL YOUR ORIGINAL METHODS — FULL AND UNCHANGED ===

    def update_stylesheet(self):
        background_style = f"background-image: url({self.background_path}); background-size: cover;" if self.background_path and os.path.exists(self.background_path) else ""
        self.setStyleSheet(f"""
            SomiAIGUI {{
                {background_style}
                background-repeat: no-repeat;
                background-position: center;
                background-color: #121212;
            }}
            QLabel {{
                color: #D3D3D3;
                font: bold 12pt 'Segoe UI', 'Arial';
                text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
            }}
            QPushButton {{
                background-color: #4A4A4A;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #5A5A5A, stop:1 #4A4A4A);
                color: #E0E0E0;
                border: 1px solid #6A6A6A;
                border-radius: 4px;
                padding: 6px;
                font: 10pt 'Segoe UI', 'Arial';
                min-width: 120px;
                text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                transition: all 0.2s ease;
            }}
            QPushButton:hover {{
                background-color: #5A5A5A;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #6A6A6A, stop:1 #5A5A5A);
                box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
            }}
            QPushButton:pressed {{
                background-color: #3A3A3A;
                border: 1px solid #5A5A5A;
                box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
            }}
            QTextEdit {{
                background-color: rgba(42, 42, 42, 0.8);
                color: #D3D3D3;
                border: 1px solid #6A6A6A;
                border-radius: 4px;
                min-height: 150px;
                font: 10pt 'Segoe UI', 'Arial';
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }}
        """)

    def on_resize(self, event):
        self.output_area.setFixedHeight(int(self.height() * 0.25))
        self.update_stylesheet()
        super().resizeEvent(event)

    def load_agent_names(self):
        try:
            with open(PERSONALITY_CONFIG, "r") as f:
                characters = json.load(f)
            agent_keys = list(characters.keys())
            agent_names = [key.replace("Name: ", "") for key in agent_keys]
            return agent_keys, agent_names
        except FileNotFoundError:
            logger.error(f"{PERSONALITY_CONFIG} not found.")
            return [], []
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in {PERSONALITY_CONFIG}.")
            return [], []

    def refresh_agent_names(self):
        self.agent_keys, self.agent_names = self.load_agent_names()
        logger.info("Refreshed agent names.")

    def toggle_ai_model(self):
        from gui import aicoregui
        if not hasattr(self, 'ollama_process') or self.ollama_process is None or self.ollama_process.poll() is not None:
            aicoregui.ai_model_start_stop(self)
        else:
            aicoregui.ai_model_start_stop(self)

    def open_chat(self):
        self.refresh_agent_names()
        aicoregui.ai_chat(self)

    def run_personality_editor(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            persona_path = os.path.join(base_dir, "persona.py")
            if not os.path.exists(persona_path):
                logger.error("persona.py not found.")
                QMessageBox.critical(self, "Error", "persona.py not found in the script directory.")
                return
            subprocess.Popen(["python", persona_path], shell=False)
            logger.info("Launched persona.py successfully.")
            self.output_area.append("Personality Editor launched.")
            self.output_area.ensureCursorVisible()
        except Exception as e:
            logger.error(f"Failed to launch persona.py: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to launch Personality Editor: {str(e)}")

    def read_settings(self):
        import re
        model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
        settings = {
            "DEFAULT_MODEL": "dolphin3",
            "MEMORY_MODEL": "codellama",
            "DEFAULT_TEMP": "0.7",
            "VISION_MODEL": "Gemma3:4b"
        }
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(base_dir, "config", "settings.py")
            if not os.path.exists(settings_path):
                logger.error("config/settings.py not found.")
                return settings
            with open(settings_path, "r") as f:
                content = f.read()
            for key in model_keys:
                pattern = rf'^{key}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^"\s]+))'
                match = re.search(pattern, content, re.MULTILINE)
                if match:
                    value = match.group(1) or match.group(2) or match.group(3)
                    settings[key] = value.strip()
            logger.info(f"Read settings: {settings}")
            return settings
        except Exception as e:
            logger.error(f"Error reading config/settings.py: {str(e)}")
            return settings

    def show_model_selections(self):
        try:
            settings = self.read_settings()
            model_window = QWidget()
            model_window.setWindowTitle("AI Model Selections")
            model_window.setGeometry(100, 100, 400, 300)
            layout = QVBoxLayout()
            layout.setSpacing(10)

            label = QLabel("Model Settings")
            label.setStyleSheet("font: bold 12pt 'Segoe UI', 'Arial'; color: #D3D3D3; text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);")
            layout.addWidget(label)

            model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
            for key in model_keys:
                value = settings.get(key, "Not set")
                frame = QWidget()
                frame_layout = QHBoxLayout()
                frame_layout.setSpacing(10)
                frame.setLayout(frame_layout)
                key_label = QLabel(f"{key}:")
                key_label.setFixedWidth(150)
                key_label.setStyleSheet("color: #D3D3D3; font: 10pt 'Segoe UI', 'Arial'; text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);")
                frame_layout.addWidget(key_label)
                value_label = QLabel(value)
                value_label.setStyleSheet("color: #D3D3D3; font: 10pt 'Segoe UI', 'Arial'; text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);")
                frame_layout.addWidget(value_label)
                frame_layout.addStretch()
                layout.addWidget(frame)

            edit_button = QPushButton("Edit Settings")
            edit_button.setStyleSheet("""
                QPushButton {
                    background-color: #4A4A4A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #5A5A5A, stop:1 #4A4A4A);
                    color: #E0E0E0;
                    border: 1px solid #6A6A6A;
                    border-radius: 4px;
                    padding: 6px;
                    font: 10pt 'Segoe UI', 'Arial';
                    text-shadow: 1px 1px 1px rgba(0, 0 0 0.3);
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    transition: all 0.2s ease;
                }
                QPushButton:hover {
                    background-color: #5A5A5A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #6A6A6A, stop:1 #5A5A5A);
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
                }
                QPushButton:pressed {
                    background-color: #3A3A3A;
                    border: 1px solid #5A5A5A;
                    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
                }
            """)
            edit_button.clicked.connect(lambda: self.edit_model_settings(settings, model_window))
            layout.addWidget(edit_button)

            layout.addStretch()
            model_window.setLayout(layout)
            model_window.setStyleSheet("""
                QWidget {
                    background-color: #2A2A2A;
                    border: 1px solid #6A6A6A;
                    border-radius: 4px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }
            """)
            model_window.show()

        except Exception as e:
            logger.error(f"Error showing model selections: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to show model selections: {str(e)}")

    def edit_model_settings(self, current_settings, parent_window):
        try:
            edit_window = QWidget()
            edit_window.setWindowTitle("Edit Model Settings")
            edit_window.setGeometry(100, 100, 400, 400)
            layout = QVBoxLayout()
            layout.setSpacing(10)

            label = QLabel("Edit Model Settings")
            label.setStyleSheet("font: bold 12pt 'Segoe UI', 'Arial'; color: #D3D3D3; text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);")
            layout.addWidget(label)

            entries = {}
            model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
            for key in model_keys:
                frame = QWidget()
                frame_layout = QHBoxLayout()
                frame_layout.setSpacing(10)
                frame.setLayout(frame_layout)
                key_label = QLabel(f"{key}:")
                key_label.setFixedWidth(150)
                key_label.setStyleSheet("color: #D3D3D3; font: 10pt 'Segoe UI', 'Arial'; text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);")
                frame_layout.addWidget(key_label)
                entry = QLineEdit()
                entry.setStyleSheet("""
                    QLineEdit {
                        background-color: #2A2A2A;
                        color: #D3D3D3;
                        border: 1px solid #6A6A6A;
                        border-radius: 4px;
                        padding: 4px;
                        font: 10pt 'Segoe UI', 'Arial';
                        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    }
                    QLineEdit:focus {
                        border: 1px solid #8A8A8A;
                    }
                """)
                entry.setText(current_settings.get(key, ""))
                frame_layout.addWidget(entry)
                entries[key] = entry
                layout.addWidget(frame)

            def save_settings():
                try:
                    new_settings = {key: entry.text().strip() for key, entry in entries.items()}
                    try:
                        temp = float(new_settings["DEFAULT_TEMP"])
                        if not 0.0 <= temp <= 1.0:
                            raise ValueError("DEFAULT_TEMP must be between 0.0 and 1.0")
                    except ValueError as ve:
                        QMessageBox.critical(edit_window, "Error", str(ve))
                        return

                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    settings_path = os.path.join(base_dir, "config", "settings.py")
                    if not os.path.exists(settings_path):
                        logger.error("config/settings.py not found.")
                        QMessageBox.critical(edit_window, "Error", "config/settings.py not found.")
                        return

                    with open(settings_path, "r") as f:
                        lines = f.readlines()
                    new_lines = []
                    updated_keys = set()
                    for line in lines:
                        stripped_line = line.strip()
                        for key in new_settings:
                            if stripped_line.startswith(f"{key} ="):
                                value = new_settings[key]
                                if key == "DEFAULT_TEMP":
                                    new_line = f"{key} = {value}\n"
                                else:
                                    new_line = f"{key} = \"{value}\"\n"
                                new_lines.append(new_line)
                                updated_keys.add(key)
                                break
                        else:
                            new_lines.append(line)

                    for key in new_settings:
                        if key not in updated_keys:
                            value = new_settings[key]
                            if key == "DEFAULT_TEMP":
                                new_lines.append(f"{key} = {value}\n")
                            else:
                                new_lines.append(f"{key} = \"{value}\"\n")

                    with open(settings_path, "w") as f:
                        f.writelines(new_lines)

                    logger.info(f"Updated config/settings.py with: {new_settings}")
                    self.output_area.append("Model settings updated successfully.")
                    self.output_area.ensureCursorVisible()
                    QMessageBox.information(edit_window, "Success", "Model settings updated successfully!")
                    edit_window.close()
                    parent_window.close()
                    self.show_model_selections()

                except Exception as e:
                    logger.error(f"Error saving settings: {str(e)}")
                    QMessageBox.critical(edit_window, "Error", f"Failed to save settings: {str(e)}")

            save_button = QPushButton("Save")
            save_button.setStyleSheet("""
                QPushButton {
                    background-color: #4A4A4A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #5A5A5A, stop:1 #4A4A4A);
                    color: #E0E0E0;
                    border: 1px solid #6A6A6A;
                    border-radius: 4px;
                    padding: 6px;
                    font: 10pt 'Segoe UI', 'Arial';
                    text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    transition: all 0.2s ease;
                }
                QPushButton:hover {
                    background-color: #5A5A5A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #6A6A6A, stop:1 #5A5A5A);
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
                }
                QPushButton:pressed {
                    background-color: #3A3A3A;
                    border: 1px solid #5A5A5A;
                    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
                }
            """)
            save_button.clicked.connect(save_settings)
            layout.addWidget(save_button)

            cancel_button = QPushButton("Cancel")
            cancel_button.setStyleSheet("""
                QPushButton {
                    background-color: #4A4A4A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #5A5A5A, stop:1 #4A4A4A);
                    color: #E0E0E0;
                    border: 1px solid #6A6A6A;
                    border-radius: 4px;
                    padding: 6px;
                    font: 10pt 'Segoe UI', 'Arial';
                    text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    transition: all 0.2s ease;
                }
                QPushButton:hover {
                    background-color: #5A5A5A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #6A6A6A, stop:1 #5A5A5A);
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
                }
                QPushButton:pressed {
                    background-color: #3A3A3A;
                    border: 1px solid #5A5A5A;
                    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
                }
            """)
            cancel_button.clicked.connect(edit_window.close)
            layout.addWidget(cancel_button)

            layout.addStretch()
            edit_window.setLayout(layout)
            edit_window.setStyleSheet("""
                QWidget {
                    background-color: #2A2A2A;
                    border: 1px solid #6A6A6A;
                    border-radius: 4px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }
            """)
            edit_window.show()

        except Exception as e:
            logger.error(f"Error editing model settings: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to edit model settings: {str(e)}")

    def change_background(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Background Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp)")
        if file_name:
            if os.path.exists(file_name):
                self.background_path = file_name
                self.update_stylesheet()
                logger.info(f"Background changed to {self.background_path}")
                self.output_area.append(f"Background changed to {os.path.basename(file_name)}")
                self.output_area.append("Note: For best readability, use a dark-themed background image.")
                self.output_area.ensureCursorVisible()
            else:
                logger.error(f"Selected background image does not exist: {file_name}")
                QMessageBox.warning(self, "Error", "Selected image file does not exist.")

    def closeEvent(self, event):
        for process in [self.telegram_process, self.twitter_autotweet_process, self.twitter_autoresponse_process, self.alex_process, self.ai_model_process]:
            if process and process.poll() is None:
                try:
                    os.kill(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        event.accept()

    def read_help_file(self, filename):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "help", filename + ".txt")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                return f"Help file '{filename}.txt' not found at {file_path}."
        except Exception as e:
            return f"Error reading help file '{filename}.txt': {str(e)}"

    def show_help(self, section):
        help_content = self.read_help_file(section)
        if "not found" in help_content or "Error" in help_content:
            QMessageBox.warning(self, "Error", help_content)
        else:
            help_window = HelpWindow(self, f"Help - {section}", help_content)
            help_window.exec()

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = QApplication(sys.argv)
    window = SomiAIGUI()
    window.show()
    sys.exit(app.exec())
    window.show()

    sys.exit(app.exec())
