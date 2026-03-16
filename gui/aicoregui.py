import asyncio
import json
import subprocess
import time
from concurrent.futures import CancelledError
from datetime import datetime
from agents import Agent
from workshop.toolbox.stacks.research_core.rag_handler import RAGHandler
from config import settings
from playwright.async_api import async_playwright
import logging
import logging.handlers
import os
import re
from pathlib import Path
import psutil
import importlib
try:
    import torch
except Exception:
    torch = None
import sys
import signal
from gui.themes import COLORS, dialog_stylesheet
from gui.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFont,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPixmap,
    QPushButton,
    QTextDocument,
    QTextEdit,
    QThread,
    QTimer,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
    pyqtSignal,
)
from workshop.toolbox.runtime import InternalToolRuntime

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
            storage_path = Path("database") / "rag_data"
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
    response_signal = pyqtSignal(str, str, object)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, app, agent_name, use_studies, parent=None, preloaded_agent=None):
        super().__init__(parent)
        self.app = app
        self.agent_name = agent_name
        self.use_studies = use_studies
        self.loop = asyncio.new_event_loop()
        self.agent = preloaded_agent
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

    def process_prompt(self, prompt, display_prompt=None):
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

            self.status_signal.emit("Routing request...")

            async def _gen():
                self.agent._last_request_source = "gui"
                return await self.agent.generate_response_with_attachments(prompt, user_id="default_user")

            self.pending_future = asyncio.run_coroutine_threadsafe(_gen(), self.loop)

            def _done(fut):
                try:
                    response, attachments = fut.result()
                    attachments = attachments or []
                    shown_prompt = display_prompt if isinstance(display_prompt, str) and display_prompt.strip() else prompt
                    self.response_signal.emit(shown_prompt, (response or "No response received.") + "\n", attachments)
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

    def _to_payload(self) -> dict:
        if isinstance(self.req, dict):
            mode = str(self.req.get("mode") or "general")
            image_paths = list(self.req.get("image_paths") or [])
            schema_id = self.req.get("schema_id")
            options = dict(self.req.get("options") or {})
        else:
            mode = str(getattr(self.req, "mode", "general") or "general")
            image_paths = list(getattr(self.req, "image_paths", []) or [])
            schema_id = getattr(self.req, "schema_id", None)
            options = dict(getattr(self.req, "options", {}) or {})
        return {
            "action": "run",
            "mode": mode,
            "image_paths": image_paths,
            "schema_id": schema_id,
            "options": options,
        }

    def run(self):
        try:
            runtime = InternalToolRuntime()
            payload = self._to_payload()
            result = runtime.run("ocr.extract", payload, {"source": "gui", "approved": True})
            self.result_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(f"OCR failed: {str(e)}")


def ai_chat(app):
    """Legacy wrapper for modules that still open chat as a detached window."""
    app.toggle_chat_popout(force_popout=True)

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

    use_gpu = mode == "GPU (CUDA)" and bool(torch) and torch.cuda.is_available()
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







