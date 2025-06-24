import sys
import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton,
    QTextEdit, QLabel, QDialog, QComboBox, QMessageBox, QFileDialog, QLineEdit
)
from PyQt6.QtCore import Qt, QRect
from datetime import datetime
import logging
import signal
import subprocess
from gui import telegramgui, twittergui, aicoregui, speechgui

# Set up logging
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

class SomiAIGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("Initializing SomiAIGUI...")
        self.setWindowTitle("Somi AI GUI")
        self.setGeometry(100, 100, 800, 600)

        # Initialize process variables
        self.telegram_process = None
        self.twitter_autotweet_process = None
        self.twitter_autoresponse_process = None
        self.alex_process = None
        self.ai_model_process = None

        # Load agent names
        self.agent_keys, self.agent_names = self.load_agent_names()
        logger.info(f"Loaded agent keys: {self.agent_keys}, display names: {self.agent_names}")

        try:
            # Main widget and layout
            main_widget = QWidget()
            self.setCentralWidget(main_widget)
            main_layout = QVBoxLayout()
            main_layout.setSpacing(10)  # Increased spacing for clean layout
            main_widget.setLayout(main_layout)

            # Set up background path
            self.assets_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            self.default_background = os.path.join(self.assets_folder, "default_background.jpg")
            if os.path.exists(self.default_background):
                self.background_path = self.default_background
            else:
                self.background_path = ""  # Fallback to solid color if default image is missing
                logger.warning(f"Default background image not found at {self.default_background}. Using solid color.")
            self.update_stylesheet()

            # Section 1: AI Core
            ai_core_label = QLabel("AI Core")
            main_layout.addWidget(ai_core_label)

            ai_core_frame = QWidget()
            ai_core_layout = QHBoxLayout()
            ai_core_layout.setSpacing(10)
            ai_core_frame.setLayout(ai_core_layout)
            main_layout.addWidget(ai_core_frame)

            ai_chat_button = QPushButton("AI Chat")
            ai_chat_button.clicked.connect(lambda: [self.refresh_agent_names(), aicoregui.ai_chat(self)])
            ai_core_layout.addWidget(ai_chat_button)

            self.ai_model_start_button = QPushButton("AI Model Start/Stop")
            self.ai_model_start_button.clicked.connect(self.toggle_ai_model)
            ai_core_layout.addWidget(self.ai_model_start_button)

            study_material_button = QPushButton("Study Material")
            study_material_button.clicked.connect(lambda: aicoregui.study_material(self))
            ai_core_layout.addWidget(study_material_button)

            ai_guide_button = QPushButton("AI Guide")
            ai_guide_button.clicked.connect(lambda: self.show_help("aicore"))
            ai_core_layout.addWidget(ai_guide_button)

            # Section 2: Telegram
            telegram_label = QLabel("Telegram")
            main_layout.addWidget(telegram_label)

            telegram_frame = QWidget()
            telegram_layout = QHBoxLayout()
            telegram_layout.setSpacing(10)
            telegram_frame.setLayout(telegram_layout)
            main_layout.addWidget(telegram_frame)

            self.telegram_toggle_button = QPushButton("Telegram Bot Start")
            self.telegram_toggle_button.clicked.connect(lambda: [self.refresh_agent_names(), telegramgui.telegram_bot_toggle(self)])
            telegram_layout.addWidget(self.telegram_toggle_button)

            telegram_settings_button = QPushButton("Telegram Settings")
            telegram_settings_button.clicked.connect(lambda: telegramgui.telegram_settings(self))
            telegram_layout.addWidget(telegram_settings_button)

            telegram_help_button = QPushButton("Telegram Help")
            telegram_help_button.clicked.connect(lambda: self.show_help("Telegram"))
            telegram_layout.addWidget(telegram_help_button)

            # Section 3: Twitter
            twitter_label = QLabel("Twitter")
            main_layout.addWidget(twitter_label)

            twitter_frame = QWidget()
            twitter_layout = QHBoxLayout()
            twitter_layout.setSpacing(10)
            twitter_frame.setLayout(twitter_layout)
            main_layout.addWidget(twitter_frame)

            self.twitter_autotweet_toggle_button = QPushButton("Twitter Autotweet Start")
            self.twitter_autotweet_toggle_button.clicked.connect(lambda: [self.refresh_agent_names(), twittergui.twitter_autotweet_toggle(self)])
            twitter_layout.addWidget(self.twitter_autotweet_toggle_button)

            self.twitter_autoresponse_toggle_button = QPushButton("Twitter Autoresponse Start")
            self.twitter_autoresponse_toggle_button.clicked.connect(lambda: [self.refresh_agent_names(), twittergui.twitter_autoresponse_toggle(self)])
            twitter_layout.addWidget(self.twitter_autoresponse_toggle_button)

            twitter_developer_tweet_button = QPushButton("Developer Tweet")
            twitter_developer_tweet_button.clicked.connect(lambda: twittergui.twitter_developer_tweet(self))
            twitter_layout.addWidget(twitter_developer_tweet_button)

            twitter_settings_button = QPushButton("Twitter Settings")
            twitter_settings_button.clicked.connect(lambda: twittergui.twitter_settings(self))
            twitter_layout.addWidget(twitter_settings_button)

            twitter_login_button = QPushButton("Twitter Login")
            twitter_login_button.clicked.connect(lambda: twittergui.twitter_login(self))
            twitter_layout.addWidget(twitter_login_button)

            twitter_help_button = QPushButton("Twitter Help")
            twitter_help_button.clicked.connect(lambda: self.show_help("Twitter"))
            twitter_layout.addWidget(twitter_help_button)

            # Section 4: Audio & Models
            audio_label = QLabel("Audio & Models")
            main_layout.addWidget(audio_label)

            audio_frame = QWidget()
            audio_layout = QHBoxLayout()
            audio_layout.setSpacing(10)
            audio_frame.setLayout(audio_layout)
            main_layout.addWidget(audio_frame)

            self.alex_toggle_button = QPushButton("Alex-AI Start")
            self.alex_toggle_button.clicked.connect(lambda: [self.refresh_agent_names(), speechgui.alex_ai_toggle(self)])
            audio_layout.addWidget(self.alex_toggle_button)

            audio_settings_button = QPushButton("Audio Settings")
            audio_settings_button.clicked.connect(lambda: speechgui.audio_settings(self))
            audio_layout.addWidget(audio_settings_button)

            personality_editor_button = QPushButton("Personality Editor")
            personality_editor_button.clicked.connect(self.run_personality_editor)
            audio_layout.addWidget(personality_editor_button)

            model_selections_button = QPushButton("AI Model Selections")
            model_selections_button.clicked.connect(self.show_model_selections)
            audio_layout.addWidget(model_selections_button)

            # Output Area
            output_label = QLabel("Output Log")
            main_layout.addWidget(output_label)

            self.output_area = QTextEdit()
            self.output_area.setReadOnly(True)
            main_layout.addWidget(self.output_area)

            # Add stretch to push content up and keep output log at bottom
            main_layout.addStretch()

            # Add small "+" button at bottom right
            change_bg_button = QPushButton("+")
            change_bg_button.setFixedSize(30, 30)
            change_bg_button.setStyleSheet("""
                QPushButton {
                    background-color: #4A4A4A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #5A5A5A, stop:1 #4A4A4A);
                    color: #E0E0E0;
                    border: 1px solid #6A6A6A;
                    border-radius: 15px;
                    font: 12pt 'Segoe UI', 'Arial';
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }
                QPushButton:hover {
                    background-color: #5A5A5A;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #6A6A6A, stop:1 #5A5A5A);
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
                }
                QPushButton:pressed {
                    background-color: #3A3A4A;
                    border: 1px solid #5A5A5A;
                    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
                }
            """)
            change_bg_button.clicked.connect(self.change_background)
            main_layout.addWidget(change_bg_button, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

            # Connect resize event
            self.resizeEvent = self.on_resize

            logger.info("SomiAIGUI initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing SomiAIGUI: {str(e)}")
            QMessageBox.critical(self, "Error", f"GUI initialization failed: {str(e)}")
            raise

    def update_stylesheet(self):
        """Update the stylesheet with the current background and dynamic sizes."""
        background_style = f"background-image: url({self.background_path}); background-size: cover;" if self.background_path and os.path.exists(self.background_path) else ""
        self.setStyleSheet(f"""
            SomiAIGUI {{
                {background_style}
                background-repeat: no-repeat;
                background-position: center;
                background-color: #121212; /* Deep charcoal */
            }}
            QLabel {{
                color: #D3D3D3; /* Light gray */
                font: bold 12pt 'Segoe UI', 'Arial';
                text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
            }}
            QPushButton {{
                background-color: #4A4A4A; /* Silver-gray */
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #5A5A5A, stop:1 #4A4A4A);
                color: #E0E0E0; /* Light silver text */
                border: 1px solid #6A6A6A; /* Subtle silver border */
                border-radius: 4px; /* Rounded corners */
                padding: 6px;
                font: 10pt 'Segoe UI', 'Arial';
                min-width: 120px;
                text-shadow: 1px 1px 1px rgba(0, 0, 0, 0.3);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                transition: all 0.2s ease; /* Smooth transitions */
            }}
            QPushButton:hover {{
                background-color: #5A5A5A; /* Lighter silver on hover */
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #6A6A6A, stop:1 #5A5A5A);
                box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15);
            }}
            QPushButton:pressed {{
                background-color: #3A3A3A; /* Darker silver when pressed */
                border: 1px solid #5A5A5A;
                box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2);
            }}
            QTextEdit {{
                background-color: rgba(42, 42, 42, 0.8); /* Slightly lighter dark, semi-transparent */
                color: #D3D3D3; /* Light gray text */
                border: 1px solid #6A6A6A; /* Subtle silver border */
                border-radius: 4px;
                min-height: 150px;
                font: 10pt 'Segoe UI', 'Arial';
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }}
            QWidget#frame {{
                background-color: transparent; /* Ensure frames blend with main background */
            }}
        """)

    def on_resize(self, event):
        """Handle window resize to adjust component sizes."""
        width = self.width()
        height = self.height()
        # Adjust output area height dynamically (e.g., 25% of window height)
        self.output_area.setFixedHeight(int(height * 0.25))
        # Ensure buttons scale with layout (handled by QHBoxLayout)
        self.update_stylesheet()
        super().resizeEvent(event)

    def load_agent_names(self):
        """Load agent names from personalC.json."""
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
        """Refresh agent names in the combo box."""
        self.agent_keys, self.agent_names = self.load_agent_names()
        logger.info(f"Refreshed agent names and keys.")

    def validate_agent_name(self, name):
        """Validate if the agent name exists in personalC.json."""
        return name in self.agent_keys

    def toggle_ai_model(self):
        """Toggle AI model start/stop."""
        from gui import aicoregui
        if not hasattr(self, 'ollama_process') or self.ollama_process is None or self.ollama_process.poll() is not None:
            self.ai_model_start_button.setText("AI Model Stop")
            aicoregui.ai_model_start_stop(self)
        else:
            self.ai_model_start_button.setText("AI Model Start")
            aicoregui.ai_model_start_stop(self)

    def run_personality_editor(self):
        """Run the persona.py script as a separate process."""
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
        """Read model-related settings from config/settings.py."""
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
        """Display model settings in a new window with an Edit button."""
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
            edit_button.clicked.connect(lambda: self.edit_model_settings(settings, model_window))
            layout.addWidget(edit_button)

            layout.addStretch()
            model_window.setLayout(layout)
            model_window.setStyleSheet("""
                QWidget {
                    background-color: #2A2A2A; /* Slightly lighter dark */
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
        """Open a window to edit model settings and save to config/settings.py."""
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
                        background-color: #2A2A2A; /* Slightly lighter dark */
                        color: #D3D3D3;
                        border: 1px solid #6A6A6A;
                        border-radius: 4px;
                        padding: 4px;
                        font: 10pt 'Segoe UI', 'Arial';
                        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    }
                    QLineEdit:focus {
                        border: 1px solid #8A8A8A; /* Lighter border on focus */
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
                    background-color: #2A2A2A; /* Slightly lighter dark */
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
        """Open file dialog to change the background image."""
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
        """Handle application close event to terminate processes."""
        for process in [self.telegram_process, self.twitter_autotweet_process, self.twitter_autoresponse_process, self.alex_process, self.ai_model_process]:
            if process and process.poll() is None:
                try:
                    os.kill(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        event.accept()

    def read_help_file(self, filename):
        """Read the content of the specified help text file from the help subfolder."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "help", filename + ".txt")
            print(f"Looking for: {file_path}")  # Debug print
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                return f"Help file '{filename}.txt' not found at {file_path}."
        except Exception as e:
            return f"Error reading help file '{filename}.txt': {str(e)}"

    def show_help(self, section):
        """Display the help content in a separate subwindow."""
        help_content = self.read_help_file(section)
        if "not found" in help_content or "Error" in help_content:
            QMessageBox.warning(self, "Error", help_content)
        else:
            help_window = HelpWindow(self, f"Help - {section}", help_content)
            help_window.exec()

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # Ensure working directory is script's directory
    app = QApplication(sys.argv)
    window = SomiAIGUI()
    window.show()
    sys.exit(app.exec())