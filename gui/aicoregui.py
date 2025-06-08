# gui/aicoregui.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QComboBox, QCheckBox, QMessageBox, QWidget, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer, QEventLoop
import asyncio
import threading
import subprocess
import time
from datetime import datetime
from agents import Agent
from rag import RAGHandler
from config import settings
from playwright.async_api import async_playwright
import logging
import os
import re
from pathlib import Path
import importlib

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', filename='agent.log')
logger = logging.getLogger(__name__)

# Worker thread for asyncio and RAG operations
class RagWorker(QThread):
    update_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.loop = asyncio.new_event_loop()
        self.rag = None
        self.running = True

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.rag = RAGHandler()
            if not self.rag.index or not self.rag.texts:
                self.update_signal.emit("No RAG data available. Use the buttons below to ingest PDFs or websites.\n")
            else:
                self.update_signal.emit(f"Loaded {len(self.rag.texts)} RAG entries. Enter a query to search.\n")
            self.update_signal.emit("RAG initialized.")
            self.loop.run_forever()
        except Exception as e:
            self.error_signal.emit(f"Failed to initialize RAGHandler: {str(e)}")

    def stop(self):
        self.running = False
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.quit()
        self.wait()

    def ingest_data(self, source_type, custom_urls=None):
        if not self.rag or not self.isRunning():
            self.error_signal.emit("RAGHandler is not initialized or running.")
            return
        try:
            if source_type == "PDFs":
                asyncio.run_coroutine_threadsafe(self.rag.ingest_pdfs(), self.loop).result()
            else:
                async def custom_study_websites():
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        page = await browser.new_page()
                        for url in custom_urls:
                            try:
                                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                                content = await page.content()
                                self.rag.store(content, url)
                                logger.info(f"Studied website: {url}")
                            except Exception as e:
                                logger.error(f"Error studying website {url}: {str(e)}")
                        await browser.close()
                asyncio.run_coroutine_threadsafe(custom_study_websites(), self.loop).result()
            self.rag._load_indices()
            if self.rag.index and self.rag.texts:
                self.update_signal.emit(f"Successfully ingested {source_type}. {len(self.rag.texts)} entries loaded.\nEnter a query to search.\n")
            else:
                self.update_signal.emit(f"No data ingested from {source_type}. Check the source files.\n")
        except Exception as e:
            self.error_signal.emit(f"Error ingesting {source_type}: {str(e)}")

    def search_rag(self, query):
        if not self.rag or not self.isRunning():
            self.error_signal.emit("RAGHandler is not initialized or running.")
            return
        try:
            results = self.rag.retrieve(query, k=3)
            if not results:
                self.update_signal.emit("No results found.\n")
            else:
                output = ""
                for result in results:
                    output += f"Source: {result['source']}\nContent: {result['content'][:200]}{'...' if len(result['content']) > 200 else ''}\n---\n"
                self.update_signal.emit(output)
        except Exception as e:
            self.error_signal.emit(f"Error retrieving results: {str(e)}")

    def clear_studies(self):
        if not self.rag or not self.isRunning():
            self.error_signal.emit("RAGHandler is not initialized or running.")
            return
        try:
            storage_path = Path("rag_data")
            vector_file = storage_path / "rag_vectors.faiss"
            text_file = storage_path / "rag_texts.json"
            files_deleted = False
            if vector_file.exists():
                os.remove(vector_file)
                files_deleted = True
            if text_file.exists():
                os.remove(text_file)
                files_deleted = True
            if files_deleted:
                self.rag = RAGHandler()
                self.update_signal.emit("RAG data cleared. Use the buttons above to ingest new data.\n")
                self.update_signal.emit("Success")
            else:
                self.update_signal.emit("No RAG data files found to clear.\n")
        except Exception as e:
            self.error_signal.emit(f"Error clearing RAG data: {str(e)}")

# Background Chat Worker
class ChatWorker(QThread):
    response_signal = pyqtSignal(str, str)  # (user_input, ai_response)
    error_signal = pyqtSignal(str)

    def __init__(self, app, agent_name, use_studies, parent=None):
        super().__init__(parent)
        self.app = app
        self.agent_name = agent_name
        self.use_studies = use_studies
        self.loop = asyncio.new_event_loop()
        self.agent = None
        self.running = False
        self.last_save_time = time.time()
        self.save_interval = 300  # Save every 5 minutes (300 seconds)

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.agent = Agent(
                name=self.agent_name,
                use_studies=self.use_studies
            )
            self.agent.model = settings.DEFAULT_MODEL
            self.agent.temperature = settings.DEFAULT_TEMP
            self.response_signal.emit("", f"Chat session started with {self.agent_name}.\n")
            self.running = True
            self.loop.run_forever()
        except Exception as e:
            self.error_signal.emit(f"Failed to start chat worker: {str(e)}")

    def process_prompt(self, prompt):
        if not self.running or not self.agent:
            self.error_signal.emit("Chat worker not running or agent not initialized.")
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.agent.generate_response(prompt, user_id="default_user"),
                self.loop
            )
            response = future.result()
            self.response_signal.emit(prompt, response + "\n\n")
            # Check if it's time to save
            current_time = time.time()
            if current_time - self.last_save_time >= self.save_interval:
                self._save_and_cleanup()
                self.last_save_time = current_time
        except Exception as e:
            self.error_signal.emit(f"Error processing prompt: {str(e)}")

    def _save_and_cleanup(self):
        if self.agent:
            try:
                del self.agent
                self.agent = Agent(
                    name=self.agent_name,
                    use_studies=self.use_studies
                )
                self.agent.model = settings.DEFAULT_MODEL
                self.agent.temperature = settings.DEFAULT_TEMP
                logger.info(f"Saved and reinitialized agent at {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                self.error_signal.emit(f"Error during save/cleanup: {str(e)}")

    def stop(self):
        self.running = False
        if self.agent:
            del self.agent
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.quit()
        self.wait()

def ai_chat(app):
    logger.info("Opening AI Chat subwindow...")
    chat_window = QDialog(app)
    chat_window.setWindowTitle("AI Chat")
    chat_window.setGeometry(100, 100, 800, 600)
    layout = QVBoxLayout()

    # Agent Name Selection
    layout.addWidget(QLabel("Agent Name:"))
    name_combo = QComboBox()
    name_combo.addItems(app.agent_names)
    name_combo.setCurrentText(app.agent_names[0])  # Default to first display name
    layout.addWidget(name_combo)

    # Use Studies Checkbox
    use_studies_check = QCheckBox("Use Studies (RAG)")
    use_studies_check.setChecked(True)  # Default checked
    layout.addWidget(use_studies_check)

    # Chat Display Area
    layout.addWidget(QLabel("Chat:"))
    chat_area = QTextEdit()
    chat_area.setReadOnly(True)
    chat_area.setFixedHeight(200)  # Approximate height for 12 lines
    layout.addWidget(chat_area)

    # Prompt Entry
    layout.addWidget(QLabel("Prompt:"))
    prompt_entry = QLineEdit()
    prompt_entry.setFixedWidth(700)
    layout.addWidget(prompt_entry)

    # Chat Worker
    chat_worker = None

    def start_chat():
        nonlocal chat_worker
        selected_name = name_combo.currentText()
        agent_key = app.agent_keys[app.agent_names.index(selected_name)]
        if not app.validate_agent_name(agent_key):
            QMessageBox.critical(chat_window, "Error", f"Invalid agent name: {selected_name}")
            return

        if chat_worker and chat_worker.isRunning():
            chat_worker.stop()
            chat_worker.wait()

        chat_worker = ChatWorker(app, agent_key, use_studies_check.isChecked())
        chat_worker.response_signal.connect(lambda user_input, ai_response: [
            chat_area.append(f"You: {user_input}\n"),
            chat_area.append(f"{selected_name}: {ai_response}"),
            chat_area.ensureCursorVisible()
        ])
        chat_worker.error_signal.connect(lambda msg: [
            chat_area.append(f"Error: {msg}\n"),
            chat_area.ensureCursorVisible(),
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {msg}\n"),
            app.output_area.ensureCursorVisible(),
            QMessageBox.critical(chat_window, "Error", msg)
        ])
        chat_worker.start()
        send_button.setEnabled(True)
        prompt_entry.setEnabled(True)
        apply_agent_button.setEnabled(True)

    def apply_agent():
        nonlocal chat_worker
        selected_name = name_combo.currentText()
        agent_key = app.agent_keys[app.agent_names.index(selected_name)]
        if not app.validate_agent_name(agent_key):
            QMessageBox.critical(chat_window, "Error", f"Invalid agent name: {selected_name}")
            return

        if chat_worker and chat_worker.isRunning():
            chat_worker.stop()
            chat_worker.wait()
        chat_worker = ChatWorker(app, agent_key, use_studies_check.isChecked())
        chat_worker.response_signal.connect(lambda user_input, ai_response: [
            chat_area.append(f"You: {user_input}\n"),
            chat_area.append(f"{selected_name}: {ai_response}"),
            chat_area.ensureCursorVisible()
        ])
        chat_worker.error_signal.connect(lambda msg: [
            chat_area.append(f"Error: {msg}\n"),
            chat_area.ensureCursorVisible(),
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {msg}\n"),
            app.output_area.ensureCursorVisible(),
            QMessageBox.critical(chat_window, "Error", msg)
        ])
        chat_worker.start()
        chat_area.clear()
        chat_area.append(f"Chatting with {selected_name}{' using studies' if use_studies_check.isChecked() else ''}.\n")

    def send_prompt():
        if not chat_worker or not chat_worker.isRunning():
            QMessageBox.warning(chat_window, "Warning", "Please start the chat first.")
            return
        prompt = prompt_entry.text().strip()
        if not prompt:
            QMessageBox.warning(chat_window, "Warning", "Please enter a prompt.")
            return
        chat_worker.process_prompt(prompt)
        prompt_entry.clear()

    def quit_chat():
        nonlocal chat_worker
        if chat_worker and chat_worker.isRunning():
            chat_worker.stop()
            chat_worker.wait()
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Chat session ended.\n")
        app.output_area.ensureCursorVisible()
        chat_window.reject()
        app.update()

    # Buttons
    start_button = QPushButton("Start Chat")
    start_button.clicked.connect(start_chat)
    layout.addWidget(start_button)

    apply_agent_button = QPushButton("Apply Agent")
    apply_agent_button.setEnabled(False)
    apply_agent_button.clicked.connect(apply_agent)
    layout.addWidget(apply_agent_button)

    send_button = QPushButton("Send")
    send_button.setEnabled(False)
    send_button.clicked.connect(send_prompt)
    layout.addWidget(send_button)

    quit_button = QPushButton("Quit")
    quit_button.clicked.connect(quit_chat)
    layout.addWidget(quit_button)

    # Bind Enter key to send_prompt
    prompt_entry.returnPressed.connect(send_prompt)

    layout.addStretch()
    chat_window.setLayout(layout)
    chat_window.exec()

def study_material(app):
    logger.info("Opening Study Material subwindow...")
    study_window = QDialog(app)
    study_window.setWindowTitle("Study Material (RAG)")
    study_window.setGeometry(100, 100, 800, 600)
    layout = QVBoxLayout()

    # Query Entry
    layout.addWidget(QLabel("Query:"))
    query_entry = QLineEdit()
    query_entry.setFixedWidth(700)
    layout.addWidget(query_entry)

    # Buttons Frame
    buttons_frame = QWidget()
    buttons_layout = QHBoxLayout()
    buttons_frame.setLayout(buttons_layout)
    layout.addWidget(buttons_frame)

    # Results Area
    layout.addWidget(QLabel("Results:"))
    results_area = QTextEdit()
    results_area.setReadOnly(True)
    results_area.setFixedHeight(200)  # Approximate height for 12 lines
    layout.addWidget(results_area)

    # Initialize RagWorker
    rag_worker = RagWorker(app)
    rag_worker.update_signal.connect(lambda msg: [
        results_area.append(msg),
        results_area.ensureCursorVisible(),
        search_button.setEnabled(bool("Loaded" in msg or "Success" in msg))
    ])
    rag_worker.error_signal.connect(lambda msg: [
        results_area.append(f"Error: {msg}\n"),
        results_area.ensureCursorVisible(),
        QMessageBox.critical(study_window, "Error", msg) if "Error" in msg else None,
        study_window.reject() if "Failed" in msg else None
    ])
    rag_worker.start()

    app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Study session started.\n")
    app.output_area.ensureCursorVisible()

    def update_settings_websites(new_websites):
        """Update RAG_WEBSITES in config/settings.py and reload the module."""
        try:
            new_websites = list(dict.fromkeys(new_websites))
            settings_path = "config/settings.py"
            with open(settings_path, "r") as f:
                lines = f.readlines()

            new_lines = []
            in_rag_websites = False
            for line in lines:
                if line.strip().startswith("RAG_WEBSITES ="):
                    in_rag_websites = True
                    if not new_websites:
                        new_lines.append("RAG_WEBSITES = []\n")
                    else:
                        new_lines.append("RAG_WEBSITES = [\n")
                        for url in new_websites:
                            new_lines.append(f'    "{url}",\n')
                        new_lines[-1] = new_lines[-1].rstrip(",\n") + "\n"
                        new_lines.append("]\n")
                    continue
                if in_rag_websites:
                    if line.strip() == "]":
                        in_rag_websites = False
                    continue
                new_lines.append(line)

            with open(settings_path, "w") as f:
                f.writelines(new_lines)

            importlib.reload(settings)
            rag_worker.ingest_data("Websites", new_websites)
        except Exception as e:
            logger.error(f"Error updating settings.py: {str(e)}")
            rag_worker.error_signal.emit(f"Error updating settings.py: {str(e)}")

    def ingest_websites():
        websites_window = QDialog(study_window)
        websites_window.setWindowTitle("Enter Websites to Ingest")
        websites_window.setGeometry(100, 100, 600, 600)
        w_layout = QVBoxLayout()

        url_entries = []
        for i in range(10):
            w_layout.addWidget(QLabel(f"Website {i+1}:"))
            entry = QLineEdit()
            entry.setFixedWidth(500)
            w_layout.addWidget(entry)
            url_entries.append(entry)

        def submit_urls():
            new_urls = []
            for entry in url_entries:
                url = entry.text().strip()
                if url:
                    if not re.match(r"^https?://", url):
                        url = f"https://{url}"
                    new_urls.append(url)

            if not new_urls:
                QMessageBox.warning(websites_window, "Warning", "Please enter at least one website URL.")
                return

            update_settings_websites(new_urls)
            websites_window.accept()

        def cancel():
            websites_window.reject()

        submit_button = QPushButton("Submit")
        submit_button.clicked.connect(submit_urls)
        w_layout.addWidget(submit_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(cancel)
        w_layout.addWidget(cancel_button)

        w_layout.addStretch()
        websites_window.setLayout(w_layout)
        websites_window.exec()

    def ingest_data(source_type):
        if not rag_worker.isRunning():
            rag_worker.error_signal.emit("RAGHandler is not running.")
            return
        rag_worker.ingest_data(source_type)

    def search_rag():
        if not rag_worker.isRunning():
            rag_worker.error_signal.emit("RAGHandler is not running.")
            return
        query = query_entry.text().strip()
        if not query:
            QMessageBox.warning(study_window, "Warning", "Please enter a query.")
            return
        rag_worker.search_rag(query)

    def clear_studies():
        if not rag_worker.isRunning():
            rag_worker.error_signal.emit("RAGHandler is not running.")
            return
        rag_worker.clear_studies()

    def quit_study():
        if rag_worker.isRunning():
            rag_worker.stop()
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Study session ended.\n")
        app.output_area.ensureCursorVisible()
        study_window.reject()
        app.update()

    # Buttons
    ingest_pdfs_button = QPushButton("Ingest PDFs")
    ingest_pdfs_button.clicked.connect(lambda: ingest_data("PDFs"))
    buttons_layout.addWidget(ingest_pdfs_button)

    ingest_websites_button = QPushButton("Ingest Websites")
    ingest_websites_button.clicked.connect(ingest_websites)
    buttons_layout.addWidget(ingest_websites_button)

    search_button = QPushButton("Search")
    search_button.setEnabled(False)
    search_button.clicked.connect(search_rag)
    buttons_layout.addWidget(search_button)

    clear_studies_button = QPushButton("Clear Studies")
    clear_studies_button.clicked.connect(clear_studies)
    buttons_layout.addWidget(clear_studies_button)

    quit_button = QPushButton("Quit")
    quit_button.clicked.connect(quit_study)
    buttons_layout.addWidget(quit_button)

    # Bind Enter key to search_rag
    query_entry.returnPressed.connect(search_rag)

    layout.addStretch()
    study_window.setLayout(layout)
    study_window.exec()

def ai_model_start_stop(app):
    if not hasattr(app, 'ollama_process') or app.ollama_process is None:
        # Start Ollama with a visible command window
        app.ai_model_start_button.setEnabled(False)
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Ollama with model {settings.DEFAULT_MODEL}...\n")
        app.output_area.ensureCursorVisible()
        app.update()

        try:
            # Run ollama with a visible command window titled "ollama"
            if os.name == 'nt':  # Windows
                cmd = f'start "ollama" cmd /k ollama run {settings.DEFAULT_MODEL}'
                app.ollama_process = subprocess.Popen(cmd, shell=True)
            else:  # Unix-like systems (Linux, macOS)
                cmd = ["ollama", "run", settings.DEFAULT_MODEL]
                app.ollama_process = subprocess.Popen(cmd, shell=False)
            app.ai_model_start_button.setText("AI Model Stop")  # Update button text
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ollama started with model {settings.DEFAULT_MODEL}.\n")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Success", "Ollama running! A command window titled 'ollama' should be visible.", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setEnabled(True)
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error starting Ollama: {str(e)}\n")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error starting Ollama: {str(e)}", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setText("AI Model Start")  # Revert on failure
            app.ai_model_start_button.setEnabled(True)
            app.ollama_process = None
    else:
        # Prompt user to manually close the Ollama window
        app.ai_model_start_button.setEnabled(False)
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Please close the 'ollama' command window to stop Ollama.\n")
        app.output_area.ensureCursorVisible()
        app.update()

        try:
            QMessageBox.information(app, "Info", "Please manually close the 'ollama' command window to stop Ollama.", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setText("AI Model Start")  # Update button text
            app.ollama_process = None
            app.ai_model_start_button.setEnabled(True)
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error prompting to stop Ollama: {str(e)}\n")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error prompting to stop Ollama: {str(e)}", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setEnabled(True)
            app.ollama_process = None

    app.update()