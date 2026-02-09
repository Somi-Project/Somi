# gui/speechgui.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox,
    QMessageBox, QLineEdit, QSpinBox, QDoubleSpinBox, QWidget
)
from PyQt6.QtCore import QTimer
import subprocess
import queue
import os
import signal
import threading
import sys
from datetime import datetime
import logging
import ast
import re
from pathlib import Path

# gui/speechgui.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox,
    QMessageBox, QLineEdit, QSpinBox, QDoubleSpinBox, QWidget
)
from PyQt6.QtCore import QTimer
import subprocess
import queue
import os
import signal
import threading
import sys
from datetime import datetime
import logging
import ast
import re
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def _find_button(app, partial_text):
    """Safely find a button in the main window by partial text match."""
    for btn in app.findChildren(QPushButton):
        if partial_text in btn.text():
            return btn
    return None

def alex_ai_toggle(app):
    """Toggle the Alex AI (speech.py) process with selected agent and optional use-studies flag."""
    logger.info("Initiating Alex AI Toggle...")

    # Find the Alex button in the main window
    alex_btn = _find_button(app, "Alex-AI")

    if app.alex_process and app.alex_process.poll() is None:
        # Alex AI is running → stop it
        logger.info("Stopping Alex AI...")
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Alex AI...")
        app.output_area.ensureCursorVisible()

        try:
            termination_signal = signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM
            os.kill(app.alex_process.pid, termination_signal)
            logger.info(f"Sent termination signal {termination_signal} to PID {app.alex_process.pid}")
            try:
                app.alex_process.wait(timeout=5)
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Alex AI stopped successfully.")
                app.output_area.ensureCursorVisible()
                QMessageBox.information(app, "Success", "Alex AI stopped successfully!")
            except subprocess.TimeoutExpired:
                logger.warning("Alex AI process did not terminate gracefully, killing...")
                app.alex_process.kill()
                app.alex_process.wait(timeout=2)
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Alex AI forcefully stopped.")
                app.output_area.ensureCursorVisible()
        except Exception as e:
            logger.error(f"Error stopping Alex AI: {str(e)}")
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error stopping Alex AI: {str(e)}")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error stopping Alex AI: {str(e)}")

        app.alex_process = None
        if alex_btn:
            alex_btn.setText("Alex-AI Start")
        if hasattr(app, 'alex_timer'):
            app.alex_timer.stop()
            del app.alex_timer

    else:
        # Alex AI is not running → start it
        dialog = QDialog(app)
        dialog.setWindowTitle("Select Alex AI Agent")
        dialog.setGeometry(100, 100, 400, 250)
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Agent Name:"))
        name_combo = QComboBox()
        name_combo.addItems(app.agent_names)
        if app.agent_names:
            name_combo.setCurrentText(app.agent_names[0])
        layout.addWidget(name_combo)

        use_studies_check = QCheckBox("Use Studies (RAG)")
        use_studies_check.setChecked(True)
        layout.addWidget(use_studies_check)

        button_layout = QHBoxLayout()
        start_button = QPushButton("Start")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(start_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        layout.addStretch()
        dialog.setLayout(layout)

        def start_alex():
            selected_name = name_combo.currentText()
            try:
                agent_key = app.agent_keys[app.agent_names.index(selected_name)]
            except (ValueError, IndexError):
                QMessageBox.critical(dialog, "Error", "Invalid or missing agent.")
                return

            use_studies = use_studies_check.isChecked()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Alex AI with {selected_name} {'using studies' if use_studies else ''}...")
            app.output_area.ensureCursorVisible()

            cmd = ["python", "speech.py", "--name", agent_key] + (["--use-studies"] if use_studies else [])
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            try:
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                app.alex_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                    bufsize=1,
                    env=env,
                    creationflags=creationflags
                )
                logger.info(f"Started Alex AI process with PID {app.alex_process.pid}")

                app.alex_stderr_queue = queue.Queue()
                threading.Thread(target=read_stderr, args=(app.alex_process, app.alex_stderr_queue), daemon=True).start()

                app.alex_timer = QTimer(app)
                app.alex_timer.timeout.connect(lambda: check_stderr_queue(app, app.alex_stderr_queue))
                app.alex_timer.start(100)

                QTimer.singleShot(1000, lambda: check_process_status(app, selected_name))

                if alex_btn:
                    alex_btn.setText("Alex-AI Stop")

            except Exception as e:
                logger.error(f"Error starting Alex AI: {str(e)}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(app, "Error", str(e))
                app.alex_process = None
                if alex_btn:
                    alex_btn.setText("Alex-AI Start")
                if hasattr(app, 'alex_timer'):
                    app.alex_timer.stop()
                    del app.alex_timer

            dialog.close()

        start_button.clicked.connect(start_alex)
        cancel_button.clicked.connect(dialog.close)
        dialog.exec()

def read_stderr(process, q):
    """Read stderr lines and put them into the queue."""
    while True:
        line = process.stderr.readline()
        if line:
            q.put(line.strip())
        else:
            break

def check_stderr_queue(app, q):
    """Check the stderr queue and update output_area in the main thread."""
    try:
        while not q.empty():
            line = q.get_nowait()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Alex AI stderr: {line}")
            app.output_area.ensureCursorVisible()
    except queue.Empty:
        pass

def check_process_status(app, selected_name):
    """Check if the Alex AI process is still running after startup."""
    alex_btn = _find_button(app, "Alex-AI")
    if app.alex_process and app.alex_process.poll() is None:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Alex AI started successfully with {selected_name}.")
        app.output_area.ensureCursorVisible()
        QMessageBox.information(app, "Success", f"Alex AI started successfully with {selected_name}!")
    else:
        error_msg = "Alex AI failed to start. Check output log for details."
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        app.output_area.ensureCursorVisible()
        QMessageBox.critical(app, "Error", error_msg)
        app.alex_process = None
        if alex_btn:
            alex_btn.setText("Alex-AI Start")
        if hasattr(app, 'alex_timer'):
            app.alex_timer.stop()
            del app.alex_timer

def audio_settings(app):
    """Display and edit audio settings from config/audiosettings.py."""
    logger.info("Opening Audio Settings dialog...")
    settings_dialog = QDialog(app)
    settings_dialog.setWindowTitle("Audio Settings")
    settings_dialog.setGeometry(100, 100, 600, 500)
    layout = QVBoxLayout()

    def read_audio_settings():
        """Read settings from config/audiosettings.py."""
        settings = {}
        settings_path = Path(__file__).parent.parent / "config" / "audiosettings.py"
        try:
            with open(settings_path, "r") as f:
                content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                key = target.id
                                try:
                                    value = ast.literal_eval(node.value)
                                    settings[key] = value
                                except:
                                    continue
            logger.info(f"Read audio settings: {settings}")
            return settings
        except FileNotFoundError:
            logger.error(f"{settings_path} not found.")
            return {}
        except Exception as e:
            logger.error(f"Error reading {settings_path}: {str(e)}")
            return {}

    def display_settings():
        """Display current audio settings."""
        settings = read_audio_settings()
        layout.addWidget(QLabel("Audio Settings:"))
        
        display_keys = [
            "WAKE_WORDS", "CESSATION_WORDS", "WAKE_SESSION_TIMEOUT", "SAMPLE_RATE",
            "AUDIO_GAIN", "WHISPER_MODEL", "TTS_MODEL", "INCHIME_FREQUENCIES", "OUTCHIME_FREQUENCIES"
        ]
        
        for key in display_keys:
            value = settings.get(key, "Not set")
            frame = QWidget()
            frame_layout = QHBoxLayout()
            frame.setLayout(frame_layout)
            key_label = QLabel(f"{key}:")
            key_label.setFixedWidth(200)
            key_label.setStyleSheet("color: #00FFFF; text-shadow: 1px 1px 3px #000000;")
            frame_layout.addWidget(key_label)
            value_label = QLabel(str(value))
            value_label.setStyleSheet("color: #00FFFF; text-shadow: 1px 1px 3px #000000;")
            value_label.setWordWrap(True)
            frame_layout.addWidget(value_label)
            frame_layout.addStretch()
            layout.addWidget(frame)

    display_settings()

    def edit_settings():
        """Open dialog to edit audio settings."""
        settings = read_audio_settings()
        edit_dialog = QDialog(settings_dialog)
        edit_dialog.setWindowTitle("Edit Audio Settings")
        edit_dialog.setGeometry(100, 100, 600, 600)
        edit_layout = QVBoxLayout()

        entries = {}
        edit_keys = [
            ("WAKE_WORDS", "Comma-separated wake words", QLineEdit, lambda x: ", ".join(x)),
            ("CESSATION_WORDS", "Comma-separated cessation words", QLineEdit, lambda x: ", ".join(x)),
            ("WAKE_SESSION_TIMEOUT", "Wake session timeout (seconds)", QDoubleSpinBox, lambda x: x),
            ("SAMPLE_RATE", "Sample rate (Hz)", QSpinBox, lambda x: x),
            ("AUDIO_GAIN", "Audio gain", QDoubleSpinBox, lambda x: x),
            ("WHISPER_MODEL", "Whisper model name", QLineEdit, lambda x: x),
            ("TTS_MODEL", "TTS model name", QLineEdit, lambda x: x),
            ("INCHIME_FREQUENCIES", "Comma-separated InChime frequencies (Hz)", QLineEdit, lambda x: ", ".join(str(i) for i in x)),
            ("OUTCHIME_FREQUENCIES", "Comma-separated OutChime frequencies (Hz)", QLineEdit, lambda x: ", ".join(str(i) for i in x)),
        ]

        for key, label, widget_type, formatter in edit_keys:
            frame = QWidget()
            frame_layout = QHBoxLayout()
            frame.setLayout(frame_layout)
            key_label = QLabel(f"{label}:")
            key_label.setFixedWidth(250)
            key_label.setStyleSheet("color: #00FFFF; text-shadow: 1px 1px 3px #000000;")
            frame_layout.addWidget(key_label)

            value = settings.get(key, "")
            widget = None
            if widget_type == QLineEdit:
                widget = QLineEdit()
                widget.setText(formatter(value) if value else "")
            elif widget_type == QSpinBox:
                widget = QSpinBox()
                widget.setMinimum(1)
                widget.setMaximum(1000000)
                widget.setValue(int(value) if value else 16000)
            elif widget_type == QDoubleSpinBox:
                widget = QDoubleSpinBox()
                widget.setMinimum(0.0)
                widget.setMaximum(1000.0)
                widget.setSingleStep(0.1)
                widget.setValue(float(value) if value else 5.0)

            widget.setStyleSheet("background-color: rgba(0, 0, 0, 0.5); color: #00FFFF; border: 1px solid #00FFFF;")
            frame_layout.addWidget(widget)
            entries[key] = (widget, widget_type)
            edit_layout.addWidget(frame)

        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 255, 255, 0.3);
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 5px;
                padding: 5px;
                font: 10pt 'Arial';
                text-shadow: 1px 1px 3px #000000;
            }
            QPushButton:hover {
                background-color: rgba(0, 255, 255, 0.5);
            }
        """)
        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 255, 255, 0.3);
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 5px;
                padding: 5px;
                font: 10pt 'Arial';
                text-shadow: 1px 1px 3px #000000;
            }
            QPushButton:hover {
                background-color: rgba(0, 255, 255, 0.5);
            }
        """)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        edit_layout.addLayout(button_layout)
        edit_layout.addStretch()

        def save_settings():
            """Save edited settings to config/audiosettings.py."""
            try:
                new_settings = {}
                for key, (widget, widget_type) in entries.items():
                    if widget_type == QLineEdit:
                        value = widget.text().strip()
                        if key in ["WAKE_WORDS", "CESSATION_WORDS", "INCHIME_FREQUENCIES", "OUTCHIME_FREQUENCIES"]:
                            value = [v.strip() for v in value.split(",") if v.strip()]
                            if not value:
                                QMessageBox.warning(edit_dialog, "Warning", f"{key} cannot be empty.")
                                return
                        else:
                            if not value:
                                QMessageBox.warning(edit_dialog, "Warning", f"{key} cannot be empty.")
                                return
                        new_settings[key] = value
                    elif widget_type == QSpinBox:
                        new_settings[key] = widget.value()
                    elif widget_type == QDoubleSpinBox:
                        new_settings[key] = widget.value()

                settings_path = Path(__file__).parent.parent / "config" / "audiosettings.py"
                if not settings_path.exists():
                    logger.error(f"{settings_path} not found.")
                    QMessageBox.critical(edit_dialog, "Error", f"Settings file not found: {settings_path}")
                    return

                with open(settings_path, "r") as f:
                    lines = f.readlines()
                new_lines = []
                updated_keys = set()

                for line in lines:
                    s = line.strip()
                    m = re.match(r'^(\w+)\s*=\s*.+$', s)
                    if m:
                        key = m.group(1)
                        if key in new_settings:
                            value = new_settings[key]
                            if isinstance(value, list):
                                new_line = f"{key} = {value}\n"
                            elif isinstance(value, str):
                                new_line = f'{key} = "{value}"\n'
                            else:
                                new_line = f"{key} = {value}\n"
                            new_lines.append(new_line)
                            updated_keys.add(key)
                            continue
                    new_lines.append(line)

                for key in new_settings:
                    if key not in updated_keys:
                        value = new_settings[key]
                        if isinstance(value, list):
                            new_lines.append(f"{key} = {value}\n")
                        elif isinstance(value, str):
                            new_lines.append(f'{key} = "{value}"\n')
                        else:
                            new_lines.append(f"{key} = {value}\n")

                with open(settings_path, "w") as f:
                    f.writelines(new_lines)

                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Audio settings updated successfully.")
                app.output_area.ensureCursorVisible()
                QMessageBox.information(edit_dialog, "Success", "Audio settings updated successfully!")
                edit_dialog.close()
                settings_dialog.close()

            except Exception as e:
                logger.error(f"Error saving audio settings: {str(e)}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error saving audio settings: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(edit_dialog, "Error", f"Failed to save settings: {str(e)}")

        save_button.clicked.connect(save_settings)
        cancel_button.clicked.connect(edit_dialog.close)
        edit_dialog.setLayout(edit_layout)
        edit_dialog.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 0.7);
                border: 2px solid #00FFFF;
                border-radius: 5px;
            }
        """)
        edit_dialog.exec()

    edit_button = QPushButton("Edit")
    edit_button.setStyleSheet("""
        QPushButton {
            background-color: rgba(0, 255, 255, 0.3);
            color: #00FFFF;
            border: 2px solid #00FFFF;
            border-radius: 5px;
            padding: 5px;
            font: 10pt 'Arial';
            text-shadow: 1px 1px 3px #000000;
        }
        QPushButton:hover {
            background-color: rgba(0, 255, 255, 0.5);
        }
    """)
    edit_button.clicked.connect(edit_settings)
    layout.addWidget(edit_button)

    close_button = QPushButton("Close")
    close_button.setStyleSheet("""
        QPushButton {
            background-color: rgba(0, 255, 255, 0.3);
            color: #00FFFF;
            border: 2px solid #00FFFF;
            border-radius: 5px;
            padding: 5px;
            font: 10pt 'Arial';
            text-shadow: 1px 1px 3px #000000;
        }
        QPushButton:hover {
            background-color: rgba(0, 255, 255, 0.5);
        }
    """)
    close_button.clicked.connect(settings_dialog.close)
    layout.addWidget(close_button)
    layout.addStretch()

    settings_dialog.setLayout(layout)
    settings_dialog.setStyleSheet("""
        QDialog {
            background-color: rgba(0, 0, 0, 0.7);
            border: 2px solid #00FFFF;
            border-radius: 5px;
        }
    """)
    settings_dialog.exec()