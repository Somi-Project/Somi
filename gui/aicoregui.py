from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QComboBox, QCheckBox, QMessageBox, QWidget, QFileDialog, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
import asyncio
import json
import subprocess
import time
from concurrent.futures import CancelledError
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
import sys
import signal
from gui.themes import COLORS, dialog_stylesheet
from handlers.ocr.contracts import OcrRequest
from handlers.ocr.pipeline import run_ocr

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
handler = logging.handlers.TimedRotatingFileHandler('agent.log', when='midnight', interval=1, backupCount=7)
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.handlers = [handler]



def _themed_text_style(font_pt: int = 12) -> str:
    return (
        f"font-size: {font_pt}pt; color: {COLORS['text']}; "
        f"background-color: {COLORS['bg_surface']}; border: 1px solid {COLORS['border']};"
    )


def _themed_input_style(font_pt: int = 12) -> str:
    return (
        f"font-size: {font_pt}pt; color: {COLORS['text']}; "
        f"background-color: {COLORS['bg_input']}; border: 1px solid {COLORS['border']};"
    )

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
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except RuntimeError:
            pass
        self.quit()
        self.wait()

class ChatWorker(QThread):
    response_signal = pyqtSignal(str, str)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, app, agent_name, use_studies, parent=None):
        super().__init__(parent)
        self.app = app
        self.agent_name = agent_name
        self.use_studies = use_studies
        self.loop = asyncio.new_event_loop()
        self.agent = None
        self.running = False
        self.pending_future = None

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
            if self.pending_future and not self.pending_future.done():
                self.error_signal.emit("A response is already generating. Please wait or stop it first.")
                return

            simple_prompts = ["hi", "hello", "hey"]
            original_use_studies = bool(getattr(self.agent, "use_studies", self.use_studies))
            if prompt.lower().strip() in simple_prompts and self.use_studies:
                self.agent.use_studies = False
            else:
                self.agent.use_studies = self.use_studies

            self.status_signal.emit("Routing request…")

            async def _gen():
                return await self.agent.generate_response(prompt, user_id="default_user")

            self.pending_future = asyncio.run_coroutine_threadsafe(_gen(), self.loop)

            def _done(fut):
                try:
                    response = fut.result()
                    self.response_signal.emit(prompt, (response or "No response received.") + "\n")
                    self.status_signal.emit("Done")
                except CancelledError:
                    self.status_signal.emit("Stopped")
                except Exception as exc:
                    self.error_signal.emit(f"Error processing prompt: {str(exc)}")
                    self.status_signal.emit("Idle")
                finally:
                    try:
                        self.agent.use_studies = original_use_studies
                    except Exception:
                        pass
                    self.pending_future = None

            self.pending_future.add_done_callback(_done)
        except Exception as e:
            self.error_signal.emit(f"Error processing prompt: {str(e)}")

    def cancel_current(self):
        if self.pending_future and not self.pending_future.done():
            self.pending_future.cancel()
            self.pending_future = None
            self.status_signal.emit("Stopped")

    def is_busy(self) -> bool:
        return bool(self.pending_future and not self.pending_future.done())

    def stop(self):
        self.running = False
        self.cancel_current()
        if self.agent:
            del self.agent
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except RuntimeError:
            pass
        self.quit()
        self.wait()


class OcrWorker(QThread):
    result_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, req, parent=None):
        super().__init__(parent)
        self.req = req

    def run(self):
        try:
            result = run_ocr(self.req)
            self.result_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(f"OCR failed: {str(e)}")


def ai_chat(app):
    logger.info("Opening AI Chat subwindow...")
    chat_window = QDialog(app)
    chat_window.setWindowTitle("AI Chat")
    chat_window.setGeometry(100, 100, 800, 600)
    chat_window.setStyleSheet(dialog_stylesheet())
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
    chat_area.setStyleSheet(_themed_text_style(12))
    chat_area.setFont(QFont("Arial", 12))
    layout.addWidget(chat_area)

    status_label = QLabel("Status: Connecting…")
    layout.addWidget(status_label)

    layout.addWidget(QLabel("Prompt:"))
    prompt_entry = QLineEdit()
    prompt_entry.setFixedWidth(700)
    prompt_entry.setStyleSheet(_themed_input_style(12))
    prompt_entry.setFont(QFont("Arial", 12))
    layout.addWidget(prompt_entry)

    selected_image_path = ""
    ocr_worker = None
    image_label = QLabel("Image: none")
    layout.addWidget(image_label)
    image_buttons = QWidget()
    image_buttons_layout = QHBoxLayout()
    image_buttons.setLayout(image_buttons_layout)
    upload_image_button = QPushButton("Upload Image")
    clear_image_button = QPushButton("Clear Image")
    upload_image_button.setAutoDefault(False)
    upload_image_button.setDefault(False)
    clear_image_button.setAutoDefault(False)
    clear_image_button.setDefault(False)
    image_buttons_layout.addWidget(upload_image_button)
    image_buttons_layout.addWidget(clear_image_button)
    layout.addWidget(image_buttons)

    chat_worker = None
    using_app_chat_worker = False
    spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_index = 0
    spinner_state = "Idle"
    spinner_timer = QTimer()
    spinner_timer.setInterval(90)

    def _attach_worker_signals(worker):
        try:
            worker.response_signal.disconnect(on_response)
        except Exception:
            pass
        try:
            worker.status_signal.disconnect(set_status)
        except Exception:
            pass
        try:
            worker.error_signal.disconnect(on_worker_error)
        except Exception:
            pass
        worker.response_signal.connect(on_response)
        worker.status_signal.connect(set_status)
        worker.error_signal.connect(on_worker_error)

    def _detach_worker_signals(worker):
        try:
            worker.response_signal.disconnect(on_response)
        except Exception:
            pass
        try:
            worker.status_signal.disconnect(set_status)
        except Exception:
            pass
        try:
            worker.error_signal.disconnect(on_worker_error)
        except Exception:
            pass

    def on_response(user_input, ai_response):
        selected_name = name_combo.currentText()
        chat_area.append(f"You: {user_input}\n")
        chat_area.append(f"{selected_name}: {ai_response.strip()}\n")
        chat_area.ensureCursorVisible()
        prompt_entry.setEnabled(True)
        send_button.setEnabled(True)
        stop_button.setEnabled(False)

    def tick_spinner():
        nonlocal spinner_index
        frame = spinner_frames[spinner_index]
        spinner_index = (spinner_index + 1) % len(spinner_frames)
        status_label.setText(f"Status: {frame} {spinner_state}")

    def set_status(text):
        nonlocal spinner_state
        spinner_state = text
        if text in {"Idle", "Done", "Stopped"}:
            spinner_timer.stop()
            status_label.setText(f"Status: {text}")
        else:
            if not spinner_timer.isActive():
                spinner_timer.start()

    def on_worker_error(msg):
        chat_area.append(f"Error: {msg}\n")
        chat_area.ensureCursorVisible()
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Chat Error: {msg}\n")
        app.output_area.ensureCursorVisible()
        set_status("Idle")
        prompt_entry.setEnabled(True)
        send_button.setEnabled(True)
        stop_button.setEnabled(False)
        QMessageBox.critical(chat_window, "Error", msg)

    def start_chat():
        nonlocal chat_worker, using_app_chat_worker
        selected_name = name_combo.currentText()
        if not app.agent_names:
            QMessageBox.critical(chat_window, "Error", "No agents loaded. Check personalC.json.")
            set_status("Idle")
            send_button.setEnabled(False)
            prompt_entry.setEnabled(False)
            apply_agent_button.setEnabled(False)
            stop_button.setEnabled(False)
            return
        try:
            agent_key = app.agent_keys[app.agent_names.index(selected_name)]
        except ValueError:
            QMessageBox.critical(chat_window, "Error", f"Agent '{selected_name}' not found.")
            set_status("Idle")
            send_button.setEnabled(False)
            prompt_entry.setEnabled(False)
            apply_agent_button.setEnabled(False)
            stop_button.setEnabled(False)
            return

        if chat_worker and chat_worker.isRunning() and not using_app_chat_worker:
            chat_worker.stop()
            chat_worker.wait()
        if ocr_worker and ocr_worker.isRunning():
            ocr_worker.requestInterruption()
            ocr_worker.wait(100)

        existing_worker = getattr(app, "chat_worker", None)
        if existing_worker and existing_worker.isRunning():
            chat_worker = existing_worker
            using_app_chat_worker = True
            _attach_worker_signals(chat_worker)
            chat_worker.update_agent(agent_key, use_studies_check.isChecked())
        else:
            chat_worker = ChatWorker(app, agent_key, use_studies_check.isChecked())
            using_app_chat_worker = False
            _attach_worker_signals(chat_worker)
            chat_worker.start()
            app.chat_worker = chat_worker
        chat_area.append(f"Connected to {selected_name}. You can start chatting now.\n")
        set_status("Idle")
        send_button.setEnabled(True)
        prompt_entry.setEnabled(True)
        apply_agent_button.setEnabled(True)
        stop_button.setEnabled(False)

    def apply_agent():
        nonlocal chat_worker, using_app_chat_worker
        selected_name = name_combo.currentText()
        if not app.agent_names:
            return
        try:
            agent_key = app.agent_keys[app.agent_names.index(selected_name)]
        except ValueError:
            return

        if chat_worker and chat_worker.isRunning():
            if chat_worker.is_busy():
                set_status("Busy — stop current response before switching agent")
                return
            if not chat_worker.update_agent(agent_key, use_studies_check.isChecked()):
                chat_area.append(f"Agent unchanged: {selected_name}{' using studies' if use_studies_check.isChecked() else ''}.\n")
                return
            chat_area.clear()
            chat_area.append(f"Switched to {selected_name}{' using studies' if use_studies_check.isChecked() else ''}.\n")
        else:
            if chat_worker:
                if not using_app_chat_worker:
                    chat_worker.stop()
                    chat_worker.wait()
            chat_worker = ChatWorker(app, agent_key, use_studies_check.isChecked())
            using_app_chat_worker = False
            _attach_worker_signals(chat_worker)
            chat_worker.start()
            app.chat_worker = chat_worker
            chat_area.clear()
            chat_area.append(f"Now chatting with {selected_name}{' using studies' if use_studies_check.isChecked() else ''}.\n")

    def choose_image():
        nonlocal selected_image_path
        path, _ = QFileDialog.getOpenFileName(chat_window, "Select image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            selected_image_path = path
            image_label.setText(f"Image: {path}")

    def clear_image():
        nonlocal selected_image_path
        selected_image_path = ""
        image_label.setText("Image: none")

    def open_ocr_settings():
        folder = QFileDialog.getExistingDirectory(chat_window, "Select OCR export folder")
        if folder:
            os.makedirs("config", exist_ok=True)
            Path("config/storage.json").write_text('{"excel_output_folder": ' + json.dumps(folder) + '}', encoding="utf-8")
            set_status("OCR settings saved")

    def open_schema_editor():
        schema_path = Path("config/extraction_schemas/default.json")
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        if not schema_path.exists():
            schema_path.write_text('{"schema_id":"default","version":"1.0","fields":[],"output_columns":[],"example":{}}', encoding="utf-8")
        txt, ok = QInputDialog.getMultiLineText(chat_window, "OCR Schema Editor", "Edit default schema JSON:", schema_path.read_text(encoding="utf-8"))
        if ok:
            try:
                json.loads(txt)
                schema_path.write_text(txt, encoding="utf-8")
                set_status("Schema saved")
            except Exception as exc:
                QMessageBox.critical(chat_window, "Error", f"Invalid JSON: {exc}")

    def handle_ocr_result(result):
        nonlocal ocr_worker
        selected_name = name_combo.currentText()
        body = result.structured_text if result.structured_text else result.raw_text
        chat_area.append("You: [image + prompt]\n")
        chat_area.append(f"{selected_name}: {body}\n")
        if result.exports.get("excel_path"):
            chat_area.append(f"Excel saved: {result.exports['excel_path']}\n")
        prompt_entry.setEnabled(True)
        send_button.setEnabled(True)
        stop_button.setEnabled(False)
        set_status("Done")
        ocr_worker = None

    def run_ocr_from_ui(prompt):
        nonlocal ocr_worker, selected_image_path
        mode = "auto"
        lower = (prompt or "").lower()
        struct_triggers = [t.lower() for t in (getattr(settings, "REGISTRY_TRIGGERS", []) + getattr(settings, "OCR_TRIGGERS", []) + getattr(settings, "STRUCTURED_OCR_TRIGGERS", []))]
        general_triggers = [t.lower() for t in getattr(settings, "GENERAL_OCR_TRIGGERS", ["ocr"])]
        if any(t in lower for t in struct_triggers):
            mode = "structured"
        elif any(t in lower for t in general_triggers):
            mode = "general"
        req = OcrRequest(image_paths=[selected_image_path], prompt=prompt, mode=mode, source="gui")
        ocr_worker = OcrWorker(req)
        ocr_worker.result_signal.connect(handle_ocr_result)
        ocr_worker.error_signal.connect(on_worker_error)
        ocr_worker.start()

    def show_typing_indicator():
        nonlocal chat_worker
        if not chat_worker or not chat_worker.isRunning():
            set_status("Connecting — please wait")
            return
        prompt = prompt_entry.text().strip()
        if not prompt:
            QMessageBox.warning(chat_window, "Warning", "Please enter a prompt.")
            return
        set_status("Thinking…")
        prompt_entry.setEnabled(False)
        send_button.setEnabled(False)
        stop_button.setEnabled(True)
        if selected_image_path:
            run_ocr_from_ui(prompt)
        else:
            chat_worker.process_prompt(prompt)
        prompt_entry.clear()

    def stop_generation():
        nonlocal chat_worker, ocr_worker
        if chat_worker and chat_worker.isRunning():
            chat_worker.cancel_current()
        if ocr_worker and ocr_worker.isRunning():
            ocr_worker.requestInterruption()
            ocr_worker.wait(50)
        prompt_entry.setEnabled(True)
        send_button.setEnabled(True)
        stop_button.setEnabled(False)

    def quit_chat():
        nonlocal chat_worker, ocr_worker, using_app_chat_worker
        if chat_worker and chat_worker.isRunning() and not using_app_chat_worker:
            chat_worker.stop()
            chat_worker.wait()
        if chat_worker and using_app_chat_worker:
            _detach_worker_signals(chat_worker)
        if ocr_worker and ocr_worker.isRunning():
            ocr_worker.requestInterruption()
            ocr_worker.wait(100)
        spinner_timer.stop()
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Chat session ended.\n")
        app.output_area.ensureCursorVisible()
        chat_window.reject()

    apply_agent_button = QPushButton("Apply Agent")
    apply_agent_button.setAutoDefault(False)
    apply_agent_button.setDefault(False)
    apply_agent_button.setEnabled(False)
    apply_agent_button.clicked.connect(apply_agent)
    layout.addWidget(apply_agent_button)

    send_button = QPushButton("Send")
    send_button.setAutoDefault(False)
    send_button.setDefault(False)
    send_button.setEnabled(False)
    send_button.clicked.connect(show_typing_indicator)
    layout.addWidget(send_button)

    stop_button = QPushButton("Stop Generating")
    stop_button.setAutoDefault(False)
    stop_button.setDefault(False)
    stop_button.setEnabled(False)
    stop_button.clicked.connect(stop_generation)
    layout.addWidget(stop_button)

    ocr_settings_button = QPushButton("OCR Settings")
    ocr_settings_button.setAutoDefault(False)
    ocr_settings_button.setDefault(False)
    ocr_settings_button.clicked.connect(open_ocr_settings)
    layout.addWidget(ocr_settings_button)

    schema_editor_button = QPushButton("OCR Schema Editor")
    schema_editor_button.setAutoDefault(False)
    schema_editor_button.setDefault(False)
    schema_editor_button.clicked.connect(open_schema_editor)
    layout.addWidget(schema_editor_button)

    quit_button = QPushButton("Quit")
    quit_button.setAutoDefault(False)
    quit_button.setDefault(False)
    quit_button.clicked.connect(quit_chat)
    layout.addWidget(quit_button)

    upload_image_button.clicked.connect(choose_image)
    clear_image_button.clicked.connect(clear_image)
    prompt_entry.returnPressed.connect(show_typing_indicator)
    spinner_timer.timeout.connect(tick_spinner)

    # Auto-start chat session for smoother UX.
    start_chat()

    layout.addStretch()
    chat_window.setLayout(layout)
    chat_window.exec()

def study_material(app):
    logger.info("Opening Study Material subwindow...")
    study_window = QDialog(app)
    study_window.setWindowTitle("Study Material (RAG)")
    study_window.setGeometry(100, 100, 800, 600)
    study_window.setStyleSheet(dialog_stylesheet())
    layout = QVBoxLayout()

    layout.addWidget(QLabel("Query:"))
    query_entry = QLineEdit()
    query_entry.setFixedWidth(700)
    query_entry.setStyleSheet(_themed_input_style(12))
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
    results_area.setStyleSheet(_themed_text_style(12))
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
        websites_window.setStyleSheet(dialog_stylesheet())
        w_layout = QVBoxLayout()

        url_entries = []
        for i in range(10):
            w_layout.addWidget(QLabel(f"Website {i+1}:"))
            entry = QLineEdit()
            entry.setFixedWidth(500)
            entry.setStyleSheet(_themed_input_style(12))
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
    """One-click Ollama control: Start + load model / Stop + free RAM"""
    
    # Only trust our own process handle
    ollama_running = (
        hasattr(app, 'ollama_process') and
        app.ollama_process is not None and
        app.ollama_process.poll() is None
    )

    use_gpu = mode == "GPU (CUDA)" and torch.cuda.is_available()
    mode_info = "GPU (CUDA)" if use_gpu else "CPU"

    if ollama_running:
        # === STOP OLLAMA + FREE RAM ===
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping Ollama and freeing memory...")
        app.output_area.ensureCursorVisible()

        try:
            if sys.platform == 'win32':
                app.ollama_process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                app.ollama_process.terminate()
            app.ollama_process.wait(timeout=8)
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ollama stopped — model unloaded, RAM/VRAM freed.")
        except subprocess.TimeoutExpired:
            app.ollama_process.kill()
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ollama forcefully stopped — memory freed.")
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error stopping Ollama: {e}")
        finally:
            app.ollama_process = None

        # Update main button
        for btn in app.findChildren(QPushButton):
            if btn.text() in ["Stop Ollama", "Stop Agent Running"]:
                btn.setText("Initiate Agent")
                break

    else:
        # === START OLLAMA + LOAD MODEL ===
        app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Ollama with {settings.DEFAULT_MODEL} on {mode_info}...")
        app.output_area.ensureCursorVisible()

        env = os.environ.copy()
        if use_gpu:
            env["CUDA_VISIBLE_DEVICES"] = "0"

        cmd = ["ollama", "run", settings.DEFAULT_MODEL]

        try:
            if sys.platform == 'win32':
                app.ollama_process = subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,  # Opens visible terminal
                    env=env
                )
            else:
                app.ollama_process = subprocess.Popen(cmd, env=env)

            # Update button
            for btn in app.findChildren(QPushButton):
                if btn.text() == "Initiate Agent":
                    btn.setText("Stop Ollama")
                    break

            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Success! {settings.DEFAULT_MODEL} is now loaded and ready.")
            app.output_area.append(f"   → You can now chat, use RAG, voice, etc.")
            app.output_area.ensureCursorVisible()

        except FileNotFoundError:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: Ollama not found!")
            app.output_area.append("   → Please install Ollama from https://ollama.com")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Ollama Not Found", "Ollama is not installed or not in PATH.\nDownload: https://ollama.com")
        except Exception as e:
            app.output_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] Failed to start Ollama: {e}")
            app.output_area.ensureCursorVisible()
            QMessageBox.critical(app, "Error", f"Could not start Ollama:\n{e}")
            app.ollama_process = None

def ai_guide():
    QMessageBox.information(None, "AI Guide", "This is a placeholder for the AI Guide.")
