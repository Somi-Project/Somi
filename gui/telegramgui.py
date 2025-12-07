# gui/telegramgui.py
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QLineEdit, QMessageBox
from PyQt6.QtCore import Qt, QTimer
import subprocess
import queue
import os
import signal
import threading
import sys
from datetime import datetime
import importlib
import logging
from config import settings

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def telegram_bot_toggle(app):
    """Toggle the Telegram bot (start/stop) with selected agent and optional use-studies flag."""
    logger.info("Initiating Telegram Bot Toggle...")
    
    if app.telegram_process and app.telegram_process.poll() is None:
        # Bot is running, stop it
        telegram_bot_stop(app)
    else:
        # Bot is not running, start it
        # Open dialog for agent selection
        dialog = QDialog(app)
        dialog.setWindowTitle("Select Telegram Bot Agent")
        dialog.setGeometry(100, 100, 400, 250)
        layout = QVBoxLayout()

        # Agent Name Selection
        label = QLabel("Agent Name:")
        layout.addWidget(label)
        name_combo = QComboBox()
        name_combo.addItems(app.agent_names)
        name_combo.setCurrentText(app.agent_names[0])
        layout.addWidget(name_combo)

        # Use Studies Checkbox
        use_studies_check = QCheckBox("Use Studies (RAG)")
        use_studies_check.setChecked(True)
        layout.addWidget(use_studies_check)

        # Buttons
        button_layout = QHBoxLayout()
        start_button = QPushButton("Start")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(start_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        layout.addStretch()

        dialog.setLayout(layout)

        def start_bot():
            selected_name = name_combo.currentText()
            agent_key = app.agent_keys[app.agent_names.index(selected_name)]

            # Validate agent name
            if not app.validate_agent_name(agent_key):
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid agent name: {selected_name}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(dialog, "Error", f"Invalid agent name: {selected_name}")
                dialog.close()
                app.telegram_toggle_button.setText("Telegram Bot Start")
                return

            use_studies = use_studies_check.isChecked()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Telegram Bot with {selected_name} {'using studies' if use_studies else ''}...")
            app.output_area.ensureCursorVisible()

            # Construct command
            cmd = ["python", "somi.py", "telegram", "--name", agent_key] + (["--use-studies"] if use_studies else [])
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            try:
                # Create a new process group on Windows
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                # Start the subprocess
                app.telegram_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                    bufsize=1,
                    env=env,
                    creationflags=creationflags
                )
                logger.info(f"Started Telegram process with PID {app.telegram_process.pid}")

                # Create stderr queue and start reading in a separate thread
                app.stderr_queue = queue.Queue()
                threading.Thread(target=read_stderr, args=(app.telegram_process, app.stderr_queue), daemon=True).start()

                # Set up QTimer for stderr checking in the main thread
                app.timer = QTimer(app)  # Create timer with app as parent
                app.timer.timeout.connect(lambda: check_stderr_queue(app, app.stderr_queue))
                app.timer.start(100)

                # Schedule process status check after 1 second
                QTimer.singleShot(1000, lambda: check_process_status(app, selected_name))

                app.telegram_toggle_button.setText("Telegram Bot Stop")

            except Exception as e:
                logger.error(f"Unexpected error starting Telegram Bot: {str(e)}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(app, "Error", f"Unexpected error: {str(e)}")
                app.telegram_process = None
                app.telegram_toggle_button.setText("Telegram Bot Start")
                if hasattr(app, 'timer'):
                    app.timer.stop()
                    del app.timer

            dialog.close()

        def cancel():
            dialog.close()

        start_button.clicked.connect(start_bot)
        cancel_button.clicked.connect(cancel)
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
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Telegram stderr: {line}")
            app.output_area.ensureCursorVisible()
    except queue.Empty:
        pass

def check_process_status(app, selected_name):
    """Check if the Telegram process is still running after startup."""
    if app.telegram_process and app.telegram_process.poll() is None:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Telegram Bot started successfully with {selected_name}.")
        app.output_area.ensureCursorVisible()
        QMessageBox.information(app, "Success", f"Telegram Bot started successfully with {selected_name}!")
    else:
        error_msg = "Telegram Bot failed to start. Check output log for details."
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        app.output_area.ensureCursorVisible()
        QMessageBox.critical(app, "Error", error_msg)
        app.telegram_process = None
        app.telegram_toggle_button.setText("Telegram Bot Start")
        if hasattr(app, 'timer'):
            app.timer.stop()
            del app.timer

def telegram_bot_stop(app):
    """Stop the running Telegram bot process by sending CTRL_BREAK_EVENT on Windows or SIGTERM elsewhere."""
    logger.info("Initiating Telegram Bot Stop...")
    app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Telegram Bot...")
    app.output_area.ensureCursorVisible()

    if not app.telegram_process or app.telegram_process.poll() is not None:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] No Telegram Bot is running.")
        app.output_area.ensureCursorVisible()
        QMessageBox.information(app, "Info", "No Telegram Bot is running!")
        app.telegram_toggle_button.setText("Telegram Bot Start")
        if hasattr(app, 'timer'):
            app.timer.stop()
            del app.timer
        return

    try:
        # Choose termination signal based on platform
        termination_signal = signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM
        # Send termination signal
        os.kill(app.telegram_process.pid, termination_signal)
        logger.info(f"Sent termination signal {termination_signal} to PID {app.telegram_process.pid}")
        try:
            app.telegram_process.wait(timeout=5)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Telegram Bot stopped successfully.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Telegram Bot stopped successfully!")
        except subprocess.TimeoutExpired:
            logger.warning("Telegram process did not terminate gracefully, killing...")
            app.telegram_process.kill()
            app.telegram_process.wait(timeout=2)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Telegram Bot forcefully stopped.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Telegram Bot forcefully stopped!")
        app.telegram_process = None
        app.telegram_toggle_button.setText("Telegram Bot Start")
        if hasattr(app, 'timer'):
            app.timer.stop()
            del app.timer
    except Exception as e:
        logger.error(f"Error stopping Telegram Bot: {str(e)}")
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error stopping Telegram Bot: {str(e)}")
        app.output_area.ensureCursorVisible()
        QMessageBox.critical(app, "Error", f"Error stopping Telegram Bot: {str(e)}")
        app.telegram_toggle_button.setText("Telegram Bot Start")
        if hasattr(app, 'timer'):
            app.timer.stop()
            del app.timer

def telegram_settings(app):
    """Display and edit Telegram settings from config/settings.py."""
    logger.info("Opening Telegram Settings dialog...")
    settings_dialog = QDialog(app)
    settings_dialog.setWindowTitle("Telegram Settings")
    settings_dialog.setGeometry(100, 100, 600, 300)
    layout = QVBoxLayout()

    def display_settings():
        layout.addWidget(QLabel("Bot Token:"))
        token_label = QLabel(settings.TELEGRAM_BOT_TOKEN)
        token_label.setWordWrap(True)
        layout.addWidget(token_label)

        layout.addWidget(QLabel("Bot Username:"))
        layout.addWidget(QLabel(settings.TELEGRAM_BOT_USERNAME))

        layout.addWidget(QLabel("Agent Aliases:"))
        aliases_label = QLabel(", ".join(settings.TELEGRAM_AGENT_ALIASES))
        aliases_label.setWordWrap(True)
        layout.addWidget(aliases_label)

    display_settings()

    def edit_settings():
        edit_dialog = QDialog(settings_dialog)
        edit_dialog.setWindowTitle("Edit Telegram Settings")
        edit_dialog.setGeometry(100, 100, 600, 250)
        edit_layout = QVBoxLayout()

        # Bot Token
        edit_layout.addWidget(QLabel("Bot Token:"))
        token_entry = QLineEdit()
        token_entry.setText(settings.TELEGRAM_BOT_TOKEN)
        edit_layout.addWidget(token_entry)

        # Bot Username
        edit_layout.addWidget(QLabel("Bot Username:"))
        username_entry = QLineEdit()
        username_entry.setText(settings.TELEGRAM_BOT_USERNAME)
        edit_layout.addWidget(username_entry)

        # Agent Aliases
        edit_layout.addWidget(QLabel("Agent Aliases (comma-separated):"))
        aliases_entry = QLineEdit()
        aliases_entry.setText(", ".join(settings.TELEGRAM_AGENT_ALIASES))
        edit_layout.addWidget(aliases_entry)

        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        edit_layout.addLayout(button_layout)
        edit_layout.addStretch()

        def save_settings():
            new_token = token_entry.text().strip()
            new_username = username_entry.text().strip()
            new_aliases = [alias.strip() for alias in aliases_entry.text().split(",") if alias.strip()]

            if not new_token or not new_username or not new_aliases:
                QMessageBox.warning(edit_dialog, "Warning", "All fields must be filled.")
                return

            try:
                settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "settings.py")
                with open(settings_path, "r") as f:
                    lines = f.readlines()

                # Initialize variables to track the state
                new_lines = []
                in_aliases_block = False
                skip_lines = False

                # Prepare new values
                new_token_line = f'TELEGRAM_BOT_TOKEN = "{new_token}"\n'
                new_username_line = f'TELEGRAM_BOT_USERNAME = "{new_username}"\n'
                new_aliases_lines = ["TELEGRAM_AGENT_ALIASES = [\n"]
                for alias in new_aliases:
                    new_aliases_lines.append(f'    "{alias}",\n')
                new_aliases_lines.append("]\n")

                # Process each line
                for line in lines:
                    stripped_line = line.strip()

                    if stripped_line.startswith("TELEGRAM_BOT_TOKEN"):
                        new_lines.append(new_token_line)
                        continue
                    elif stripped_line.startswith("TELEGRAM_BOT_USERNAME"):
                        new_lines.append(new_username_line)
                        continue
                    elif stripped_line.startswith("TELEGRAM_AGENT_ALIASES"):
                        new_lines.extend(new_aliases_lines)
                        in_aliases_block = True
                        skip_lines = True
                        continue
                    elif in_aliases_block and stripped_line == "]":
                        in_aliases_block = False
                        skip_lines = False
                        continue
                    elif skip_lines:
                        continue
                    else:
                        new_lines.append(line)

                # Write the updated content back to settings.py
                with open(settings_path, "w") as f:
                    f.writelines(new_lines)

                # Reload the settings module
                importlib.reload(settings)

                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Telegram settings updated successfully.")
                app.output_area.ensureCursorVisible()
                QMessageBox.information(edit_dialog, "Success", "Telegram settings updated successfully!")
                edit_dialog.close()
                settings_dialog.close()
            except Exception as e:
                logger.error(f"Error updating Telegram settings: {str(e)}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error updating Telegram settings: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(edit_dialog, "Error", f"Error updating settings: {str(e)}")

        save_button.clicked.connect(save_settings)
        cancel_button.clicked.connect(edit_dialog.close)
        edit_dialog.setLayout(edit_layout)
        edit_dialog.exec()

    edit_button = QPushButton("Edit")
    edit_button.clicked.connect(edit_settings)
    layout.addWidget(edit_button)

    close_button = QPushButton("Close")
    close_button.clicked.connect(settings_dialog.close)
    layout.addWidget(close_button)
    layout.addStretch()

    settings_dialog.setLayout(layout)
    settings_dialog.exec()

def telegram_help():
    """Show Telegram help information (placeholder)."""
    QMessageBox.information(None, "Placeholder", "Opens Telegram README.")