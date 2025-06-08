# gui/twittergui.py
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QMessageBox, QCheckBox
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

def twitter_developer_tweet(app):
    """Send a single tweet using the devpost command."""
    dialog = QDialog(app)
    dialog.setWindowTitle("Send Developer Tweet")
    dialog.setGeometry(100, 100, 400, 300)
    layout = QVBoxLayout()
    content_label = QLabel("Tweet Content:")
    layout.addWidget(content_label)
    content_entry = QLineEdit()
    layout.addWidget(content_entry)
    button_layout = QHBoxLayout()
    send_button = QPushButton("Send")
    cancel_button = QPushButton("Cancel")
    button_layout.addWidget(send_button)
    button_layout.addWidget(cancel_button)
    layout.addLayout(button_layout)
    dialog.setLayout(layout)

    def send_tweet():
        content = content_entry.text().strip()
        if not content:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Tweet content cannot be empty.")
            app.output_area.ensureCursorVisible()
            QMessageBox.warning(dialog, "Warning", "Tweet content cannot be empty.")
            return
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Sending Developer Tweet: {content}...")
        app.output_area.ensureCursorVisible()
        cmd = ["python", "somi.py", "devpost"]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            # Run devpost with input piped
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                universal_newlines=True,
                bufsize=1,
                env=env
            )
            stdout, stderr = process.communicate(input=f"{content}\n", timeout=60)
            if process.returncode == 0:
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {stdout.strip()}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Tweet sent successfully.")
                app.output_area.ensureCursorVisible()
                QMessageBox.information(app, "Success", "Tweet sent successfully!")
            else:
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Failed to send tweet: {stderr.strip()}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(app, "Error", f"Failed to send tweet: {stderr.strip()}")
        except subprocess.TimeoutExpired:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Tweet sending timed out.")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", "Tweet sending timed out.")
            process.kill()
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error sending tweet: {str(e)}")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error sending tweet: {str(e)}")
        dialog.close()

    send_button.clicked.connect(send_tweet)
    cancel_button.clicked.connect(dialog.close)
    dialog.exec()

def twitter_autotweet_toggle(app):
    """Toggle the Twitter Autotweet process."""
    logger.info("Initiating Twitter Autotweet Toggle...")
    
    if app.twitter_autotweet_process and app.twitter_autotweet_process.poll() is None:
        # Stop the process
        logger.info("Stopping Twitter Autotweet...")
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Twitter Autotweet...")
        app.output_area.ensureCursorVisible()

        if not app.twitter_autotweet_process:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] No Twitter Autotweet is running.")
            app.output_area.ensureCursorVisible()
            app.twitter_autotweet_toggle_button.setText("Twitter Autotweet Start")
            return

        try:
            termination_signal = signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM
            os.kill(app.twitter_autotweet_process.pid, termination_signal)
            logger.info(f"Sent termination signal {termination_signal} to PID {app.twitter_autotweet_process.pid}")
            app.twitter_autotweet_process.wait(timeout=5)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Twitter Autotweet stopped successfully.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Twitter Autotweet stopped successfully!")
        except subprocess.TimeoutExpired:
            logger.warning("Twitter Autotweet process did not terminate gracefully, killing...")
            app.twitter_autotweet_process.kill()
            app.twitter_autotweet_process.wait(timeout=2)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Twitter Autotweet forcefully stopped.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Twitter Autotweet forcefully stopped!")
        except Exception as e:
            logger.error(f"Error stopping Twitter Autotweet: {str(e)}")
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error stopping Twitter Autotweet: {str(e)}")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error stopping Twitter Autotweet: {str(e)}")
        app.twitter_autotweet_process = None
        app.twitter_autotweet_toggle_button.setText("Twitter Autotweet Start")
        if hasattr(app, 'twitter_autotweet_timer'):
            app.twitter_autotweet_timer.stop()
            del app.twitter_autotweet_timer
    else:
        # Start the process
        dialog = QDialog(app)
        dialog.setWindowTitle("Select Twitter Autotweet Agent")
        dialog.setGeometry(100, 100, 400, 250)
        layout = QVBoxLayout()
        label = QLabel("Agent Name:")
        layout.addWidget(label)
        name_combo = QComboBox()
        name_combo.addItems(app.agent_names)
        name_combo.setCurrentText(app.agent_names[0])
        layout.addWidget(name_combo)
        use_studies_check = QCheckBox("Use Studies (RAG)")
        use_studies_check.setChecked(False)
        layout.addWidget(use_studies_check)
        button_layout = QHBoxLayout()
        start_button = QPushButton("Start")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(start_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        dialog.setLayout(layout)

        def start_autotweet():
            selected_name = name_combo.currentText()
            agent_key = app.agent_keys[app.agent_names.index(selected_name)]
            if not app.validate_agent_name(agent_key):
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid agent name: {selected_name}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(dialog, "Error", f"Invalid agent name: {selected_name}")
                dialog.close()
                return
            use_studies = use_studies_check.isChecked()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Twitter Autotweet with {selected_name} {'using studies' if use_studies else ''}...")
            app.output_area.ensureCursorVisible()
            cmd = ["python", "somi.py", "aiautopost", "--name", agent_key] + (["--use-studies"] if use_studies else [])
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            try:
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                app.twitter_autotweet_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                    bufsize=1,
                    env=env,
                    creationflags=creationflags
                )
                logger.info(f"Started Twitter Autotweet process with PID {app.twitter_autotweet_process.pid}")
                app.stderr_queue = queue.Queue()
                threading.Thread(target=read_stderr, args=(app.twitter_autotweet_process, app.stderr_queue), daemon=True).start()
                app.twitter_autotweet_timer = QTimer(app)
                app.twitter_autotweet_timer.timeout.connect(lambda: check_stderr_queue(app, app.stderr_queue))
                app.twitter_autotweet_timer.start(100)
                QTimer.singleShot(1000, lambda: check_process_status(app, selected_name, 'Twitter Autotweet'))
                app.twitter_autotweet_toggle_button.setText("Twitter Autotweet Stop")
            except Exception as e:
                logger.error(f"Unexpected error starting Twitter Autotweet: {str(e)}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(app, "Error", f"Unexpected error: {str(e)}")
                app.twitter_autotweet_process = None
                app.twitter_autotweet_toggle_button.setText("Twitter Autotweet Start")
            dialog.close()

        start_button.clicked.connect(start_autotweet)
        cancel_button.clicked.connect(dialog.close)
        dialog.exec()

def twitter_autoresponse_toggle(app):
    """Toggle the Twitter Autoresponse process."""
    logger.info("Initiating Twitter Autoresponse Toggle...")
    
    if app.twitter_autoresponse_process and app.twitter_autoresponse_process.poll() is None:
        # Stop the process
        logger.info("Stopping Twitter Autoresponse...")
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Twitter Autoresponse...")
        app.output_area.ensureCursorVisible()

        if not app.twitter_autoresponse_process:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] No Twitter Autoresponse is running.")
            app.output_area.ensureCursorVisible()
            app.twitter_autoresponse_toggle_button.setText("Twitter Autoresponse Start")
            return

        try:
            termination_signal = signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM
            os.kill(app.twitter_autoresponse_process.pid, termination_signal)
            logger.info(f"Sent termination signal {termination_signal} to PID {app.twitter_autoresponse_process.pid}")
            app.twitter_autoresponse_process.wait(timeout=5)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Twitter Autoresponse stopped successfully.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Twitter Autoresponse stopped successfully!")
        except subprocess.TimeoutExpired:
            logger.warning("Twitter Autoresponse process did not terminate gracefully, killing...")
            app.twitter_autoresponse_process.kill()
            app.twitter_autoresponse_process.wait(timeout=2)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Twitter Autoresponse forcefully stopped.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Twitter Autoresponse forcefully stopped!")
        except Exception as e:
            logger.error(f"Error stopping Twitter Autoresponse: {str(e)}")
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error stopping Twitter Autoresponse: {str(e)}")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error stopping Twitter Autoresponse: {str(e)}")
        app.twitter_autoresponse_process = None
        app.twitter_autoresponse_toggle_button.setText("Twitter Autoresponse Start")
        if hasattr(app, 'twitter_autoresponse_timer'):
            app.twitter_autoresponse_timer.stop()
            del app.twitter_autoresponse_timer
    else:
        # Start the process
        dialog = QDialog(app)
        dialog.setWindowTitle("Select Twitter Autoresponse Agent")
        dialog.setGeometry(100, 100, 400, 250)
        layout = QVBoxLayout()
        label = QLabel("Agent Name:")
        layout.addWidget(label)
        name_combo = QComboBox()
        name_combo.addItems(app.agent_names)
        name_combo.setCurrentText(app.agent_names[0])
        layout.addWidget(name_combo)
        use_studies_check = QCheckBox("Use Studies (RAG)")
        use_studies_check.setChecked(False)
        layout.addWidget(use_studies_check)
        limit_label = QLabel("Mentions Limit:")
        layout.addWidget(limit_label)
        limit_entry = QLineEdit("2")
        layout.addWidget(limit_entry)
        button_layout = QHBoxLayout()
        start_button = QPushButton("Start")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(start_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        dialog.setLayout(layout)

        def start_autoresponse():
            selected_name = name_combo.currentText()
            agent_key = app.agent_keys[app.agent_names.index(selected_name)]
            if not app.validate_agent_name(agent_key):
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid agent name: {selected_name}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(dialog, "Error", f"Invalid agent name: {selected_name}")
                dialog.close()
                return
            try:
                limit = int(limit_entry.text().strip())
                if limit <= 0:
                    raise ValueError("Limit must be positive.")
            except ValueError as e:
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid limit: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(dialog, "Error", f"Invalid limit: {str(e)}")
                return
            use_studies = use_studies_check.isChecked()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Twitter Autoresponse with {selected_name} {'using studies' if use_studies else ''}, limit {limit}...")
            app.output_area.ensureCursorVisible()
            cmd = ["python", "somi.py", "aiautoreply", "--name", agent_key, "--limit", str(limit)] + (["--use-studies"] if use_studies else [])
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            try:
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                app.twitter_autoresponse_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                    bufsize=1,
                    env=env,
                    creationflags=creationflags
                )
                logger.info(f"Started Twitter Autoresponse process with PID {app.twitter_autoresponse_process.pid}")
                app.stderr_queue = queue.Queue()
                threading.Thread(target=read_stderr, args=(app.twitter_autoresponse_process, app.stderr_queue), daemon=True).start()
                app.twitter_autoresponse_timer = QTimer(app)
                app.twitter_autoresponse_timer.timeout.connect(lambda: check_stderr_queue(app, app.stderr_queue))
                app.twitter_autoresponse_timer.start(100)
                QTimer.singleShot(1000, lambda: check_process_status(app, selected_name, 'Twitter Autoresponse'))
                app.twitter_autoresponse_toggle_button.setText("Twitter Autoresponse Stop")
            except Exception as e:
                logger.error(f"Unexpected error starting Twitter Autoresponse: {str(e)}")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(app, "Error", f"Unexpected error: {str(e)}")
                app.twitter_autoresponse_process = None
                app.twitter_autoresponse_toggle_button.setText("Twitter Autoresponse Start")
            dialog.close()

        start_button.clicked.connect(start_autoresponse)
        cancel_button.clicked.connect(dialog.close)
        dialog.exec()

def twitter_settings(app):
    """Display and edit Twitter settings."""
    logger.info("Opening Twitter Settings dialog...")
    settings_dialog = QDialog(app)
    settings_dialog.setWindowTitle("Twitter Settings")
    settings_dialog.setGeometry(100, 100, 600, 400)
    layout = QVBoxLayout()

    def display_settings():
        layout.addWidget(QLabel("Username:"))
        layout.addWidget(QLabel(settings.TWITTER_USERNAME))
        layout.addWidget(QLabel("Password:"))
        password_label = QLabel("********" if settings.TWITTER_PASSWORD else "Not set")
        layout.addWidget(password_label)
        layout.addWidget(QLabel("API Key:"))
        layout.addWidget(QLabel(settings.TWITTER_API))
        layout.addWidget(QLabel("Auto Post Interval (minutes):"))
        layout.addWidget(QLabel(str(settings.AUTO_POST_INTERVAL_MINUTES)))
        layout.addWidget(QLabel("Auto Reply Interval (minutes):"))
        layout.addWidget(QLabel(str(settings.AUTO_REPLY_INTERVAL_MINUTES)))

    display_settings()

    def edit_settings():
        edit_dialog = QDialog(settings_dialog)
        edit_dialog.setWindowTitle("Edit Twitter Settings")
        edit_dialog.setGeometry(100, 100, 600, 400)
        edit_layout = QVBoxLayout()
        edit_layout.addWidget(QLabel("Username:"))
        username_entry = QLineEdit(settings.TWITTER_USERNAME)
        edit_layout.addWidget(username_entry)
        edit_layout.addWidget(QLabel("Password:"))
        password_entry = QLineEdit(settings.TWITTER_PASSWORD)
        password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        edit_layout.addWidget(password_entry)
        edit_layout.addWidget(QLabel("API Key:"))
        api_entry = QLineEdit(settings.TWITTER_API)
        edit_layout.addWidget(api_entry)
        edit_layout.addWidget(QLabel("Auto Post Interval (minutes):"))
        post_interval_entry = QLineEdit(str(settings.AUTO_POST_INTERVAL_MINUTES))
        edit_layout.addWidget(post_interval_entry)
        edit_layout.addWidget(QLabel("Auto Reply Interval (minutes):"))
        reply_interval_entry = QLineEdit(str(settings.AUTO_REPLY_INTERVAL_MINUTES))
        edit_layout.addWidget(reply_interval_entry)
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        edit_layout.addLayout(button_layout)
        edit_dialog.setLayout(edit_layout)

        def save_settings():
            new_username = username_entry.text().strip()
            new_password = password_entry.text().strip()
            new_api = api_entry.text().strip()
            try:
                new_post_interval = int(post_interval_entry.text().strip())
                new_reply_interval = int(reply_interval_entry.text().strip())
                if new_post_interval <= 0 or new_reply_interval <= 0:
                    raise ValueError("Intervals must be positive.")
            except ValueError as e:
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid interval: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(edit_dialog, "Error", f"Invalid interval: {str(e)}")
                return
            if not new_username or not new_api:
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Username and API key must be filled.")
                app.output_area.ensureCursorVisible()
                QMessageBox.warning(edit_dialog, "Warning", "Username and API key must be filled.")
                return
            try:
                settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "settings.py")
                with open(settings_path, "r") as f:
                    lines = f.readlines()
                new_lines = []
                for line in lines:
                    if line.strip().startswith("TWITTER_USERNAME"):
                        new_lines.append(f'TWITTER_USERNAME = "{new_username}"\n')
                    elif line.strip().startswith("TWITTER_PASSWORD"):
                        new_lines.append(f'TWITTER_PASSWORD = "{new_password}"\n')
                    elif line.strip().startswith("TWITTER_API"):
                        new_lines.append(f'TWITTER_API = "{new_api}"\n')
                    elif line.strip().startswith("AUTO_POST_INTERVAL_MINUTES"):
                        new_lines.append(f'AUTO_POST_INTERVAL_MINUTES = {new_post_interval}\n')
                    elif line.strip().startswith("AUTO_REPLY_INTERVAL_MINUTES"):
                        new_lines.append(f'AUTO_REPLY_INTERVAL_MINUTES = {new_reply_interval}\n')
                    else:
                        new_lines.append(line)
                with open(settings_path, "w") as f:
                    f.writelines(new_lines)
                importlib.reload(settings)
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Twitter settings updated successfully.")
                app.output_area.ensureCursorVisible()
                QMessageBox.information(edit_dialog, "Success", "Twitter settings updated successfully!")
                edit_dialog.close()
                settings_dialog.close()
            except Exception as e:
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error updating Twitter settings: {str(e)}")
                app.output_area.ensureCursorVisible()
                QMessageBox.critical(edit_dialog, "Error", f"Error updating Twitter settings: {str(e)}")

        save_button.clicked.connect(save_settings)
        cancel_button.clicked.connect(edit_dialog.close)
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

def twitter_login(app):
    """Generate and save Twitter cookies using gencookies command."""
    logger.info("Initiating Twitter Login...")
    app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Generating Twitter cookies...")
    app.output_area.ensureCursorVisible()
    cmd = ["python", "somi.py", "gencookies"]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True,
            bufsize=1,
            env=env
        )
        stdout, stderr = process.communicate(timeout=60)
        if process.returncode == 0:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {stdout.strip()}")
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Cookies generated and saved successfully.")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Cookies generated and saved successfully!")
        else:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Failed to generate cookies: {stderr.strip()}")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Failed to generate cookies: {stderr.strip()}")
    except subprocess.TimeoutExpired:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Cookie generation timed out.")
        app.output_area.ensureCursorVisible()
        QMessageBox.critical(app, "Error", "Cookie generation timed out.")
        process.kill()
    except Exception as e:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error generating cookies: {str(e)}")
        app.output_area.ensureCursorVisible()
        QMessageBox.critical(app, "Error", f"Error generating cookies: {str(e)}")

def twitter_help():
    """Show Twitter help information (placeholder)."""
    QMessageBox.information(None, "Placeholder", "Opens Twitter README.")

def read_stderr(process, q):
    """Read stderr lines and put them into the queue."""
    while True:
        line = process.stderr.readline()
        if line:
            q.put(line.strip())
        else:
            break

def check_stderr_queue(app, q):
    """Check the stderr queue and update output_area."""
    try:
        while not q.empty():
            line = q.get_nowait()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Twitter stderr: {line}")
            app.output_area.ensureCursorVisible()
    except queue.Empty:
        pass

def check_process_status(app, selected_name, process_name):
    """Check if the process is still running after startup."""
    process_attr = f'{process_name.lower().replace(" ", "_")}_process'
    process = getattr(app, process_attr)
    if process and process.poll() is None:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {process_name} started successfully with {selected_name}.")
        app.output_area.ensureCursorVisible()
        QMessageBox.information(app, "Success", f"{process_name} started successfully with {selected_name}!")
    else:
        error_msg = f"{process_name} failed to start. Check output log for details."
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        app.output_area.ensureCursorVisible()
        QMessageBox.critical(app, "Error", error_msg)
        setattr(app, process_attr, None)
        getattr(app, f'{process_name.lower().replace(" ", "_")}_toggle_button').setText(f"{process_name} Start")
        timer_attr = f'{process_name.lower().replace(" ", "_")}_timer'
        if hasattr(app, timer_attr):
            getattr(app, timer_attr).stop()
            delattr(app, timer_attr)