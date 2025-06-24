from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QComboBox, QCheckBox, QMessageBox, QWidget, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QTextCursor, QFont
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
import logging.handlers
import os
import re
from pathlib import Path
import psutil
import importlib
import torch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
handler = logging.handlers.TimedRotatingFileHandler('agent.log', when='midnight', interval=1, backupCount=7)
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.handlers = [handler]

class RagWorker(QThread):
    update_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.loop = asyncio.new_event_loop()
        self.rag = None
        self.running = True
        self.initialized = False

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.initialize_rag()
            self.loop.run_forever()
        except Exception as e:
            self.error_signal.emit(f"Failed to start RAG worker: {str(e)}")

    def initialize_rag(self):
        if not self.initialized:
            try:
                self.rag = RAGHandler()
                self.initialized = True
                if not self.rag.index or not self.rag.texts:
                    self.update_signal.emit("No RAG data available. Use the buttons below to ingest PDFs or websites.\n")
                else:
                    self.update_signal.emit(f"Loaded {len(self.rag.texts)} RAG entries. Enter a query to search.\n")
            except Exception as e:
                self.error_signal.emit(f"Failed to initialize RAGHandler: {str(e)}")
                self.initialized = False

    def ingest_data(self, source_type, custom_urls=None):
        if not self.rag or not self.isRunning():
            self.error_signal.emit("RAGHandler is not initialized or running.")
            return
        try:
            async def ingest_task():
                try:
                    if source_type == "PDFs":
                        await self.rag.ingest_pdfs()
                    else:
                        async with async_playwright() as p:
                            browser = await p.chromium.launch(headless=True)
                            page = await browser.new_page()
                            for url in custom_urls or []:
                                try:
                                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                                    content = await page.content()
                                    self.rag.store(content, url)
                                    logger.info(f"Studied website: {url}")
                                except Exception as e:
                                    logger.error(f"Error studying website {url}: {str(e)}")
                            await browser.close()
                    self.rag._load_indices()
                    if self.rag.index and self.rag.texts:
                        self.update_signal.emit(f"Successfully ingested {source_type}. {len(self.rag.texts)} entries loaded.\nEnter a query to search.\n")
                    else:
                        self.update_signal.emit(f"No data ingested from {source_type}. Check the source files.\n")
                except Exception as e:
                    self.error_signal.emit(f"Error ingesting {source_type}: {str(e)}")

            asyncio.run_coroutine_threadsafe(ingest_task(), self.loop)
        except Exception as e:
            self.error_signal.emit(f"Error scheduling ingestion: {str(e)}")

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
                self.initialized = True
                self.update_signal.emit("RAG data cleared. Use the buttons above to ingest new data.\n")
                self.update_signal.emit("Success")
            else:
                self.update_signal.emit("No RAG data files found to clear.\n")
        except Exception as e:
            self.error_signal.emit(f"Error clearing RAG data: {str(e)}")

    def stop(self):
        self.running = False
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.quit()
        self.wait()

class ChatWorker(QThread):
    response_signal = pyqtSignal(str, str)
    error_signal = pyqtSignal(str)

    def __init__(self, app, agent_name, use_studies, parent=None):
        super().__init__(parent)
        self.app = app
        self.agent_name = agent_name
        self.use_studies = use_studies
        self.loop = asyncio.new_event_loop()
        self.agent = None
        self.running = False

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            if not self.agent:
                self.agent = Agent(name=self.agent_name, use_studies=self.use_studies)
                self.agent.model = settings.DEFAULT_MODEL
                self.agent.temperature = settings.DEFAULT_TEMP
            self.running = True
            self.loop.run_forever()
        except Exception as e:
            self.error_signal.emit(f"Failed to start chat worker: {str(e)}")

    def update_agent(self, agent_name, use_studies):
        if self.agent_name == agent_name and self.use_studies == use_studies:
            return False
        self.agent_name = agent_name
        self.use_studies = use_studies
        if self.agent:
            del self.agent
        self.agent = Agent(name=self.agent_name, use_studies=self.use_studies)
        self.agent.model = settings.DEFAULT_MODEL
        self.agent.temperature = settings.DEFAULT_TEMP
        return True

    def process_prompt(self, prompt):
        if not self.running or not self.agent:
            self.error_signal.emit("Chat worker not running or agent not initialized.")
            return
        try:
            simple_prompts = ["hi", "hello", "hey"]
            original_use_studies = self.use_studies
            if prompt.lower().strip() in simple_prompts and self.use_studies:
                self.use_studies = False
            future = asyncio.run_coroutine_threadsafe(
                self.agent.generate_response(prompt, user_id="default_user"),
                self.loop
            )
            response = future.result()
            self.use_studies = original_use_studies
            self.response_signal.emit(prompt, response + "\n")
        except Exception as e:
            self.error_signal.emit(f"Error processing prompt: {str(e)}")

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

    layout.addWidget(QLabel("Agent Name:"))
    name_combo = QComboBox()
    name_combo.addItems(app.agent_names)
    if app.agent_names:
        name_combo.setCurrentText(app.agent_names[0])
    layout.addWidget(name_combo)

    use_studies_check = QCheckBox("Use Studies (RAG)")
    use_studies_check.setChecked(True)
    layout.addWidget(use_studies_check)

    layout.addWidget(QLabel("Chat:"))
    chat_area = QTextEdit()
    chat_area.setReadOnly(True)
    chat_area.setFixedHeight(400)
    chat_area.setStyleSheet("font-size: 12pt; color: #ffffff; background-color: #1e1e1e; border: 1px solid #444444;")
    chat_area.setFont(QFont("Arial", 12))
    layout.addWidget(chat_area)

    layout.addWidget(QLabel("Prompt:"))
    prompt_entry = QLineEdit()
    prompt_entry.setFixedWidth(700)
    prompt_entry.setStyleSheet("font-size: 12pt; color: #ffffff; background-color: #2d2d2d; border: 1px solid #444444;")
    prompt_entry.setFont(QFont("Arial", 12))
    layout.addWidget(prompt_entry)

    chat_worker = None
    typing_timer = QTimer()
    typing_timer.setInterval(10)
    dots_timer = QTimer()
    dots_timer.setInterval(500)
    current_response = ""
    response_index = 0
    dot_states = ["..", "...", "...."]
    dot_index = 0

    def type_response():
        nonlocal response_index, current_response
        logger.info(f"Typing response, index: {response_index}, response length: {len(current_response)}")
        if response_index < len(current_response):
            chat_area.moveCursor(QTextCursor.MoveOperation.End)
            chat_area.insertPlainText(current_response[response_index])
            response_index += 1
            chat_area.ensureCursorVisible()
            QApplication.processEvents()
        else:
            typing_timer.stop()
            chat_area.append(current_response[response_index:] + "\n\n")
            response_index = 0
            current_response = ""
            logger.info("Finished typing response")

    def update_dots():
        nonlocal dot_index
        selected_name = name_combo.currentText()
        cursor = chat_area.textCursor()
        prev_state = dot_states[dot_index-1 if dot_index > 0 else len(dot_states)-1]
        if chat_area.toPlainText().endswith(f"{selected_name}: {prev_state}"):
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        chat_area.append(f"{selected_name}: {dot_states[dot_index]}")
        chat_area.ensureCursorVisible()
        dot_index = (dot_index + 1) % len(dot_states)
        logger.info(f"Updated typing indicator: {dot_states[dot_index]}")

    def start_typing(user_input, ai_response, agent_name):
        nonlocal current_response, response_index
        logger.info(f"Starting typing for prompt: {user_input}")
        dots_timer.stop()
        cursor = chat_area.textCursor()
        for state in dot_states:
            if chat_area.toPlainText().endswith(f"{agent_name}: {state}"):
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                break
        typing_timer.stop()
        chat_area.append(f"You: {user_input}\n")
        chat_area.append(f"{agent_name}: ")
        current_response = ai_response if ai_response else "No response received."
        response_index = 0
        typing_timer.start()
        logger.info("Typing animation started")

    def start_chat():
        nonlocal chat_worker
        selected_name = name_combo.currentText()
        agent_key = app.agent_keys[app.agent_names.index(selected_name)] if app.agent_names else ""
        if not app.validate_agent_name(agent_key):
            QMessageBox.critical(chat_window, "Error", f"Invalid agent name: {selected_name}")
            return

        if chat_worker and chat_worker.isRunning():
            chat_worker.stop()
            chat_worker.wait()

        chat_worker = ChatWorker(app, agent_key, use_studies_check.isChecked())
        chat_worker.response_signal.connect(lambda user_input, ai_response: start_typing(user_input, ai_response, selected_name))
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
        logger.info("Chat worker started")

    def apply_agent():
        nonlocal chat_worker
        selected_name = name_combo.currentText()
        agent_key = app.agent_keys[app.agent_names.index(selected_name)] if app.agent_names else ""
        if not app.validate_agent_name(agent_key):
            QMessageBox.critical(chat_window, "Error", f"Invalid agent name: {selected_name}")
            return

        if chat_worker and chat_worker.isRunning():
            if not chat_worker.update_agent(agent_key, use_studies_check.isChecked()):
                chat_area.append(f"Agent unchanged: {selected_name}{' using studies' if use_studies_check.isChecked() else ''}.\n")
                return
            chat_area.clear()
            chat_area.append(f"Chatting with {selected_name}{' using studies' if use_studies_check.isChecked() else ''}.\n")
        else:
            if chat_worker:
                chat_worker.stop()
                chat_worker.wait()
            chat_worker = ChatWorker(app, agent_key, use_studies_check.isChecked())
            chat_worker.response_signal.connect(lambda user_input, ai_response: start_typing(user_input, ai_response, selected_name))
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
        logger.info(f"Agent applied: {selected_name}")

    def show_typing_indicator():
        nonlocal chat_worker, dot_index
        if not chat_worker or not chat_worker.isRunning():
            QMessageBox.warning(chat_window, "Warning", "Please start the chat first.")
            return
        prompt = prompt_entry.text().strip()
        if not prompt:
            QMessageBox.warning(chat_window, "Warning", "Please enter a prompt.")
            return
        selected_name = name_combo.currentText()
        dots_timer.stop()
        cursor = chat_area.textCursor()
        for state in dot_states:
            if chat_area.toPlainText().endswith(f"{selected_name}: {state}"):
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                break
        dot_index = 0
        chat_area.append(f"{selected_name}: {dot_states[dot_index]}")
        chat_area.ensureCursorVisible()
        dots_timer.start()
        chat_worker.process_prompt(prompt)
        prompt_entry.clear()
        logger.info(f"Processing prompt: {prompt}")

    def quit_chat():
        nonlocal chat_worker
        if chat_worker and chat_worker.isRunning():
            chat_worker.stop()
            chat_worker.wait()
        typing_timer.stop()
        dots_timer.stop()
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Chat session ended.\n")
        app.output_area.ensureCursorVisible()
        chat_window.reject()
        app.update()
        logger.info("Chat session ended")

    start_button = QPushButton("Start Chat")
    start_button.clicked.connect(start_chat)
    layout.addWidget(start_button)

    apply_agent_button = QPushButton("Apply Agent")
    apply_agent_button.setEnabled(False)
    apply_agent_button.clicked.connect(apply_agent)
    layout.addWidget(apply_agent_button)

    send_button = QPushButton("Send")
    send_button.setEnabled(False)
    send_button.clicked.connect(show_typing_indicator)
    layout.addWidget(send_button)

    quit_button = QPushButton("Quit")
    quit_button.clicked.connect(quit_chat)
    layout.addWidget(quit_button)

    prompt_entry.returnPressed.connect(show_typing_indicator)
    typing_timer.timeout.connect(type_response)
    dots_timer.timeout.connect(update_dots)

    layout.addStretch()
    chat_window.setLayout(layout)
    chat_window.exec()

def study_material(app):
    logger.info("Opening Study Material subwindow...")
    study_window = QDialog(app)
    study_window.setWindowTitle("Study Material (RAG)")
    study_window.setGeometry(100, 100, 800, 600)
    layout = QVBoxLayout()

    layout.addWidget(QLabel("Query:"))
    query_entry = QLineEdit()
    query_entry.setFixedWidth(700)
    query_entry.setStyleSheet("font-size: 12pt; color: #ffffff; background-color: #2d2d2d; border: 1px solid #444444;")
    query_entry.setFont(QFont("Arial", 12))
    layout.addWidget(query_entry)

    buttons_frame = QWidget()
    buttons_layout = QHBoxLayout()
    buttons_frame.setLayout(buttons_layout)
    layout.addWidget(buttons_frame)

    layout.addWidget(QLabel("Results:"))
    results_area = QTextEdit()
    results_area.setReadOnly(True)
    results_area.setFixedHeight(200)
    results_area.setStyleSheet("font-size: 12pt; color: #ffffff; background-color: #1e1e1e; border: 1px solid #444444;")
    results_area.setFont(QFont("Arial", 12))
    layout.addWidget(results_area)

    rag_worker = RagWorker(app)
    rag_worker.update_signal.connect(lambda msg: [
        results_area.append(msg),
        results_area.ensureCursorVisible(),
        search_button.setEnabled(bool("Loaded" in msg or "Success" in msg)),
        ingest_pdfs_button.setEnabled(True),
        ingest_websites_button.setEnabled(True),
        clear_studies_button.setEnabled(True)
    ])
    rag_worker.error_signal.connect(lambda msg: [
        results_area.append(f"Error: {msg}\n"),
        results_area.ensureCursorVisible(),
        QMessageBox.critical(study_window, "Error", msg),
        ingest_pdfs_button.setEnabled(True),
        ingest_websites_button.setEnabled(True),
        clear_studies_button.setEnabled(True)
    ])
    rag_worker.start()

    app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Study session started.\n")
    app.output_area.ensureCursorVisible()

    def update_settings_websites(new_websites):
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
        ingest_pdfs_button.setEnabled(False)
        ingest_websites_button.setEnabled(False)
        search_button.setEnabled(False)
        clear_studies_button.setEnabled(False)
        websites_window = QDialog(study_window)
        websites_window.setWindowTitle("Enter Websites to Ingest")
        websites_window.setGeometry(100, 100, 600, 600)
        w_layout = QVBoxLayout()

        url_entries = []
        for i in range(10):
            w_layout.addWidget(QLabel(f"Website {i+1}:"))
            entry = QLineEdit()
            entry.setFixedWidth(500)
            entry.setStyleSheet("font-size: 12pt; color: #ffffff; background-color: #2d2d2d; border: 1px solid #444444;")
            entry.setFont(QFont("Arial", 12))
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
        ingest_pdfs_button.setEnabled(False)
        ingest_websites_button.setEnabled(False)
        search_button.setEnabled(False)
        clear_studies_button.setEnabled(False)
        rag_worker.ingest_data(source_type)

    def search_rag():
        if not rag_worker.isRunning():
            rag_worker.error_signal.emit("RAGHandler is not running.")
            return
        query = query_entry.text().strip()
        if not query:
            QMessageBox.warning(study_window, "Warning", "Please enter a query.")
            return
        ingest_pdfs_button.setEnabled(False)
        ingest_websites_button.setEnabled(False)
        search_button.setEnabled(False)
        clear_studies_button.setEnabled(False)
        rag_worker.search_rag(query)

    def clear_studies():
        if not rag_worker.isRunning():
            rag_worker.error_signal.emit("RAGHandler is not running.")
            return
        ingest_pdfs_button.setEnabled(False)
        ingest_websites_button.setEnabled(False)
        search_button.setEnabled(False)
        clear_studies_button.setEnabled(False)
        rag_worker.clear_studies()

    def quit_study():
        if rag_worker.isRunning():
            rag_worker.stop()
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Study session ended.\n")
        app.output_area.ensureCursorVisible()
        study_window.reject()
        app.update()

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

    query_entry.returnPressed.connect(search_rag)

    layout.addStretch()
    study_window.setLayout(layout)
    study_window.exec()

def ai_model_start_stop(app, mode="CPU (Default)"):
    def is_ollama_running():
        try:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'].lower() == 'ollama':
                    return True
        except Exception:
            pass
        return False

    use_gpu = mode == "GPU (CUDA)" and torch.cuda.is_available()
    mode_info = "GPU (CUDA)" if use_gpu else "CPU"
    logger.info(f"Starting Ollama with mode: {mode}, use_gpu: {use_gpu}, mode_info: {mode_info}")

    if not is_ollama_running() and (not hasattr(app, 'ollama_process') or app.ollama_process is None):
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Ollama with model {settings.DEFAULT_MODEL} on {mode_info}...\n")
        app.output_area.ensureCursorVisible()
        app.update()

        try:
            env = os.environ.copy()
            if use_gpu:
                env["CUDA_VISIBLE_DEVICES"] = "0"
                logger.info("Set CUDA_VISIBLE_DEVICES=0 in subprocess environment")
                app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Environment CUDA_VISIBLE_DEVICES: {env.get('CUDA_VISIBLE_DEVICES', 'Not set')}\n")
            else:
                if "CUDA_VISIBLE_DEVICES" in env:
                    del env["CUDA_VISIBLE_DEVICES"]
                logger.info("Cleared CUDA_VISIBLE_DEVICES in subprocess environment")

            if os.name == 'nt':
                cmd = f'start "ollama" cmd /k ollama run {settings.DEFAULT_MODEL}'
                app.ollama_process = subprocess.Popen(cmd, shell=True, env=env)
            else:
                cmd = ["ollama", "run", settings.DEFAULT_MODEL]
                app.ollama_process = subprocess.Popen(cmd, shell=False, env=env)
            app.ai_model_start_button.setText("AI Model Stop")
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ollama started with model {settings.DEFAULT_MODEL} on {mode_info}.\n")
            app.output_area.ensureCursorVisible()
            app.ai_model_start_button.setEnabled(True)
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error starting Ollama: {str(e)}\n")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error starting Ollama: {str(e)}", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setText("AI Model Start")
            app.ai_model_start_button.setEnabled(True)
            app.ollama_process = None
    else:
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Ollama...\n")
        app.output_area.ensureCursorVisible()
        app.update()

        try:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Please close the 'ollama' command window to stop Ollama.\n")
            app.output_area.ensureCursorVisible()
            QMessageBox.information(app, "Info", "Please manually close the 'ollama' command window to stop Ollama.", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setText("AI Model Start")
            app.ollama_process = None
            app.ai_model_start_button.setEnabled(True)
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error prompting to stop Ollama: {str(e)}\n")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Error prompting to stop Ollama: {str(e)}", QMessageBox.StandardButton.Ok)
            app.ai_model_start_button.setEnabled(True)
            app.ollama_process = None

    app.update()

def ai_guide():
    QMessageBox.information(None, "AI Guide", "This is a placeholder for the AI Guide.")