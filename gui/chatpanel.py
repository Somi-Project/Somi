from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from config import settings
from gui.aicoregui import OcrWorker
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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPixmap,
    QPushButton,
    QTextDocument,
    QTextEdit,
    QTimer,
    QUrl,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

try:
    from runtime.ollama_options import build_ollama_chat_options
except Exception:
    def build_ollama_chat_options(**_kwargs):
        return {}


def _research_mode_label(mode: str) -> str:
    mapping = {
        "quick": "Quick browse",
        "quick_web": "Quick browse",
        "deep": "Deep browse",
        "deep_browse": "Deep browse",
        "github": "GitHub browse",
        "direct_url": "Direct page read",
        "official": "Official-source browse",
        "official_direct": "Official-source browse",
    }
    return mapping.get(str(mode or "").strip().lower(), "Browse")


def _render_research_capsule(report) -> str:
    payload = dict(report or {}) if isinstance(report, dict) else {}
    mode_label = _research_mode_label(str(payload.get("mode") or ""))
    trust_level = str(payload.get("trust_level") or "").strip().lower()
    try:
        sources_count = max(0, int(payload.get("sources_count") or 0))
    except Exception:
        sources_count = 0
    try:
        limitations_count = max(0, int(payload.get("limitations_count") or 0))
    except Exception:
        limitations_count = 0
    headline = " ".join(str(payload.get("progress_headline") or "").split()).strip()
    if not headline:
        trace = [str(item).strip() for item in list(payload.get("trace") or []) if str(item).strip()]
        headline = trace[0] if trace else " ".join(str(payload.get("execution_summary") or "").split()).strip()
    headline = re.sub(r"^\d+\.\s*", "", headline)
    parts = [mode_label]
    if sources_count:
        parts.append(f"{sources_count} source{'s' if sources_count != 1 else ''}")
    if trust_level:
        parts.append(f"trust {trust_level.upper()}")
    if headline:
        parts.append(headline[:128])
    if limitations_count:
        parts.append(f"{limitations_count} caution{'s' if limitations_count != 1 else ''}")
    return " | ".join([part for part in parts if part])


class ChatPanel(QWidget):
    popout_requested = pyqtSignal()
    dock_requested = pyqtSignal()
    expand_requested = pyqtSignal()
    restore_requested = pyqtSignal()
    stop_chat_requested = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.worker = None
        self.connected = False
        self.selected_image_path = ""
        self.ocr_worker = None
        self.pending_ocr_prompt = ""

        self.chat_storage_dir = Path("sessions/chat")
        self.chat_archive_dir = self.chat_storage_dir / "archives"
        self.threads_index_path = self.chat_archive_dir / "threads_index.json"
        self.history_path = self.chat_storage_dir / "default_user.jsonl"
        self.max_history_lines_to_load = 200
        self.history_loaded = False
        self.resume_context_once = ""
        self.pending_send_prompt = ""
        self.pending_send_attempts = 0
        self.pending_send_timer = QTimer(self)
        self.pending_send_timer.setSingleShot(True)
        self.pending_send_timer.timeout.connect(self._flush_pending_prompt)

        self.spinner_frames = ["|", "/", "-", "\\"]
        self.spinner_index = 0
        self.spinner_state = "Stopped"
        self.spinner_timer = QTimer(self)
        self.spinner_timer.setInterval(90)
        self.spinner_timer.timeout.connect(self._tick_spinner)

        self.chat_storage_dir.mkdir(parents=True, exist_ok=True)
        self.chat_archive_dir.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._set_connected_state(False)
        self.set_popout_state(False, False)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Prime Chat")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.btn_new_chat = QPushButton("New Chat")
        self.btn_old_chats = QPushButton("History")
        self.btn_coding = QPushButton("Coding")
        self.btn_popout = QPushButton("Pop Out")
        self.btn_expand = QPushButton("Expand")
        self.btn_stop_chat = QPushButton("Stop Chat")
        self.btn_stop_gen = QPushButton("Stop Gen")
        for btn in [
            self.btn_new_chat,
            self.btn_old_chats,
            self.btn_coding,
            self.btn_popout,
            self.btn_expand,
            self.btn_stop_chat,
            self.btn_stop_gen,
        ]:
            btn.setObjectName("chatHeaderButton")
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setMinimumHeight(26)
            btn.setMaximumHeight(30)
            header.addWidget(btn)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Agent:"))
        self.name_combo = QComboBox()
        self.name_combo.addItems(getattr(self.app, "agent_names", []))
        self.name_combo.setObjectName("chatAgentCombo")
        current = self.app._selected_agent_name()
        if current in getattr(self.app, "agent_names", []):
            self.name_combo.setCurrentText(current)
        controls.addWidget(self.name_combo)
        self.use_studies_check = QCheckBox("Use Studies (RAG)")
        self.use_studies_check.setObjectName("chatToggle")
        self.use_studies_check.setChecked(True)
        controls.addWidget(self.use_studies_check)
        self.apply_agent_button = QPushButton("Apply Agent")
        self.apply_agent_button.setObjectName("chatHeaderButton")
        controls.addWidget(self.apply_agent_button)
        root.addLayout(controls)

        self.chat_area = QTextEdit()
        self.chat_area.setObjectName("chatTranscript")
        self.chat_area.setReadOnly(True)
        self.chat_area.setStyleSheet("")
        self.chat_area.setFont(QFont("Arial", 11))
        self.chat_area.setMinimumHeight(300)
        root.addWidget(self.chat_area, 1)

        prompt_row = QHBoxLayout()
        self.prompt_entry = QLineEdit()
        self.prompt_entry.setObjectName("chatPromptEntry")
        self.prompt_entry.setPlaceholderText("Ask anything, route a task, or hand Somi a problem to solve...")
        self.prompt_entry.setClearButtonEnabled(True)
        self.prompt_entry.setStyleSheet("")
        self.prompt_entry.setFont(QFont("Arial", 11))
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("chatSendButton")
        self.prompt_entry.setMinimumHeight(42)
        self.send_button.setMinimumHeight(42)
        prompt_row.addWidget(self.prompt_entry, 1)
        prompt_row.addWidget(self.send_button)
        root.addLayout(prompt_row)

        image_row = QHBoxLayout()
        self.image_label = QLabel("Vision input: none")
        self.image_label.setObjectName("chatMetaLabel")
        self.upload_image_button = QPushButton("Upload Image")
        self.clear_image_button = QPushButton("Clear Image")
        self.ocr_settings_button = QPushButton("OCR Settings")
        self.schema_editor_button = QPushButton("Schema Editor")
        image_row.addWidget(self.image_label, 1)
        image_row.addWidget(self.upload_image_button)
        image_row.addWidget(self.clear_image_button)
        image_row.addWidget(self.ocr_settings_button)
        image_row.addWidget(self.schema_editor_button)
        root.addLayout(image_row)

        self.status_label = QLabel("Status: Standby")
        self.status_label.setObjectName("chatStatusPill")
        root.addWidget(self.status_label)

        for btn in [
            self.send_button,
            self.upload_image_button,
            self.clear_image_button,
            self.ocr_settings_button,
            self.schema_editor_button,
            self.apply_agent_button,
        ]:
            btn.setAutoDefault(False)
            btn.setDefault(False)

        self.btn_new_chat.clicked.connect(self.start_new_chat)
        self.btn_old_chats.clicked.connect(self.open_old_chats)
        self.btn_coding.clicked.connect(self.app.open_coding_studio)
        self.btn_popout.clicked.connect(self._on_popout_clicked)
        self.btn_expand.clicked.connect(self._on_expand_clicked)
        self.btn_stop_gen.clicked.connect(self.stop_generating)
        self.btn_stop_chat.clicked.connect(self.stop_chat_requested.emit)
        self.send_button.clicked.connect(self.on_send)
        self.prompt_entry.returnPressed.connect(self.on_send)
        self.upload_image_button.clicked.connect(self.choose_image)
        self.clear_image_button.clicked.connect(self.clear_image)
        self.ocr_settings_button.clicked.connect(self.open_ocr_settings)
        self.schema_editor_button.clicked.connect(self.open_schema_editor)
        self.apply_agent_button.clicked.connect(self._apply_agent)

    def _set_connected_state(self, connected: bool):
        self.connected = connected
        # Keep prompt/send available even when disconnected so users can send to auto-restart worker.
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
        self.status_label.setText("Status: Ready" if connected else "Status: Standby")

    def _apply_agent(self):
        selected = self.name_combo.currentText()
        if selected in getattr(self.app, "agent_names", []):
            idx = self.app.agent_names.index(selected)
            if 0 <= idx < len(getattr(self.app, "agent_keys", [])):
                self.app.selected_agent_key = self.app.agent_keys[idx]
                if getattr(self.app, "persona_combo", None):
                    self.app.persona_combo.setCurrentText(selected)
                if hasattr(self.app, "_persist_selected_agent_key"):
                    self.app._persist_selected_agent_key(self.app.selected_agent_key)
        current = getattr(self.app, "chat_worker", None)
        desired_studies = self.use_studies_check.isChecked()
        if current and current.isRunning():
            same_agent = str(getattr(current, "agent_name", "")) == str(getattr(self.app, "selected_agent_key", ""))
            same_studies = bool(getattr(current, "use_studies", True)) == bool(desired_studies)
            if same_agent and same_studies:
                self.app.ensure_chat_worker_running(use_studies=desired_studies)
                return
        self.app.stop_chat_worker()
        self.app.ensure_chat_worker_running(use_studies=desired_studies)

    def attach_worker(self, worker):
        self.detach_worker()
        self.worker = worker
        active_name = self.app._selected_agent_name()
        if active_name in [self.name_combo.itemText(i) for i in range(self.name_combo.count())]:
            self.name_combo.setCurrentText(active_name)
        self.use_studies_check.setChecked(bool(getattr(worker, "use_studies", True)))
        try:
            worker.response_signal.connect(self.on_response)
            worker.status_signal.connect(self.on_status)
            worker.error_signal.connect(self.on_error)
        except Exception:
            pass
        self._set_connected_state(True)
        if self.pending_send_prompt and not self.pending_send_timer.isActive():
            self.pending_send_timer.start(120)

    def detach_worker(self):
        if self.worker:
            try:
                self.worker.response_signal.disconnect(self.on_response)
            except Exception:
                pass
            try:
                self.worker.status_signal.disconnect(self.on_status)
            except Exception:
                pass
            try:
                self.worker.error_signal.disconnect(self.on_error)
            except Exception:
                pass
        self.worker = None
        self._set_connected_state(False)

    def set_popout_state(self, is_popped_out: bool, is_maximized: bool):
        self.btn_popout.setText("Dock" if is_popped_out else "Pop Out")
        self.btn_expand.setEnabled(is_popped_out)
        self.btn_expand.setText("Restore" if is_maximized else "Expand")

    def load_history(self, force: bool = False):
        if self.history_loaded and not force:
            return
        self.chat_area.clear()
        if not self.history_path.exists():
            self.history_loaded = True
            return
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()[-self.max_history_lines_to_load :]
            for line in lines:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                role = str(item.get("role", "system"))
                text = str(item.get("text", ""))
                if role == "system" and text.strip() in {
                    "Chat worker online - how can I help you today?",
                    "Prime chat is ready - how can I help you today?",
                }:
                    continue
                prefix = "You" if role == "user" else "Somi" if role == "assistant" else "System"
                self.chat_area.append(f"{prefix}: {text}\n")
            self.history_loaded = True
        except Exception as exc:
            self.chat_area.append(f"System: Failed to load history: {exc}\n")

    def append_history(self, role, text, agent_key, attachments=None):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "text": text,
            "agent_key": agent_key,
            "attachments": attachments or [],
        }
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def on_send(self):
        prompt = self.prompt_entry.text().strip()
        if not prompt:
            return
        if not self._worker_ready():
            self.app.ensure_chat_worker_running(use_studies=self.use_studies_check.isChecked())
            if not self._worker_ready():
                self._queue_pending_prompt(prompt)
                return
        self._dispatch_prompt(prompt)

    def _worker_ready(self) -> bool:
        worker = self.worker
        return bool(
            worker
            and worker.isRunning()
            and getattr(worker, "running", False)
            and getattr(worker, "agent", None) is not None
        )

    def _queue_pending_prompt(self, prompt: str) -> None:
        self.pending_send_prompt = str(prompt)
        self.pending_send_attempts = 0
        self.prompt_entry.clear()
        self.prompt_entry.setEnabled(False)
        self.send_button.setEnabled(False)
        self.btn_stop_gen.setEnabled(False)
        self.on_status("Starting chat worker...")
        if not self.pending_send_timer.isActive():
            self.pending_send_timer.start(120)

    def _flush_pending_prompt(self) -> None:
        prompt = str(self.pending_send_prompt or "").strip()
        if not prompt:
            return
        if self._worker_ready():
            self.pending_send_prompt = ""
            self.pending_send_attempts = 0
            self._dispatch_prompt(prompt)
            return
        self.pending_send_attempts += 1
        self.app.ensure_chat_worker_running(use_studies=self.use_studies_check.isChecked())
        if self.pending_send_attempts in {20, 50, 90}:
            self.on_status("Still warming chat engine...")
        if self.pending_send_attempts >= 180:
            self.pending_send_prompt = ""
            self.pending_send_attempts = 0
            self.prompt_entry.setEnabled(True)
            self.send_button.setEnabled(True)
            self.on_error("Chat worker took too long to initialize. Check the model stack and try again.")
            return
        if not self.pending_send_timer.isActive():
            self.pending_send_timer.start(120)

    def _dispatch_prompt(self, prompt: str) -> None:
        if not self.worker:
            self.on_error("Chat worker is not available.")
            return
        self.worker.use_studies = self.use_studies_check.isChecked()
        try:
            if self.worker.is_busy():
                self.on_status("Busy - stop current response first")
                return
        except Exception:
            pass
        self.on_status("Thinking...")
        self.prompt_entry.setEnabled(False)
        self.send_button.setEnabled(False)
        self.btn_stop_gen.setEnabled(True)

        effective_prompt = prompt
        if self.resume_context_once:
            effective_prompt = (
                "Resume context from a previously loaded conversation:\n"
                f"{self.resume_context_once}\n\n"
                f"Continue naturally with this user message:\n{prompt}"
            )
            self.resume_context_once = ""

        if self.selected_image_path:
            self.pending_ocr_prompt = prompt
            self.run_ocr_from_ui(prompt)
        else:
            self.worker.process_prompt(effective_prompt, display_prompt=prompt)
        self.prompt_entry.clear()

    def on_response(self, user_input, ai_response, attachments):
        selected_name = self.name_combo.currentText() or self.app._selected_agent_name()
        research_report = {}
        visible_attachments = []
        for att in attachments or []:
            if str(att.get("type", "")).lower() == "research_report":
                research_report = dict(att.get("payload") or {})
                continue
            visible_attachments.append(att)
        self.chat_area.append(f"You: {user_input}\n")
        self.chat_area.append(f"{selected_name}: {str(ai_response).strip()}\n")
        if research_report:
            if hasattr(self.app, "update_research_pulse"):
                try:
                    self.app.update_research_pulse(research_report, announce=True)
                except Exception:
                    pass
            capsule = _render_research_capsule(research_report)
            if capsule:
                self.chat_area.append(f"Research note: {capsule}\n")
        for att in visible_attachments:
            if str(att.get("type", "")).lower() == "image":
                img_path = str(att.get("path", ""))
                if os.path.exists(img_path):
                    self.chat_area.append(f"[{att.get('title') or 'Image'}] {img_path}\n")
                    pix = QPixmap(img_path)
                    if not pix.isNull():
                        img_url = QUrl.fromLocalFile(img_path)
                        self.chat_area.document().addResource(QTextDocument.ResourceType.ImageResource, img_url, pix)
                        self.chat_area.textCursor().insertImage(img_url.toString())
                        self.chat_area.append("\n")
        agent_key = str(getattr(self.app, "selected_agent_key", ""))
        self.append_history("user", user_input, agent_key)
        self.append_history("assistant", str(ai_response).strip(), agent_key, attachments)
        self.chat_area.ensureCursorVisible()
        self.pending_send_timer.stop()
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
    def _tick_spinner(self):
        frame = self.spinner_frames[self.spinner_index]
        self.spinner_index = (self.spinner_index + 1) % len(self.spinner_frames)
        self.status_label.setText(f"Status: {frame} {self.spinner_state}")

    def on_status(self, text):
        self.spinner_state = text
        if text in {"Idle", "Done", "Stopped", "Ready"}:
            self.spinner_timer.stop()
            self.status_label.setText(f"Status: {text}")
        else:
            if not self.spinner_timer.isActive():
                self.spinner_timer.start()

    def on_error(self, msg):
        had_ocr_context = bool(self.ocr_worker is not None or self.pending_ocr_prompt)
        self.ocr_worker = None
        self.pending_ocr_prompt = ""
        self.pending_send_prompt = ""
        self.pending_send_attempts = 0
        self.pending_send_timer.stop()
        if had_ocr_context and bool(getattr(settings, "OCR_AUTO_CLEAR_IMAGE", True)):
            self.clear_image()
        self.chat_area.append(f"Error: {msg}\n")
        self.chat_area.ensureCursorVisible()
        self.on_status("Idle")
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)

    def cancel_ocr_if_running(self):
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.requestInterruption()
            self.ocr_worker.wait(50)
        self.ocr_worker = None
        self.pending_ocr_prompt = ""

    def stop_generating(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel_current()
        self.cancel_ocr_if_running()
        self.pending_send_prompt = ""
        self.pending_send_attempts = 0
        self.pending_send_timer.stop()
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)

    def _on_popout_clicked(self):
        is_popped = bool(getattr(self.app, "chat_is_popped", False))
        if is_popped:
            self.app.dock_chat_panel()
        else:
            self.app.toggle_chat_popout(force_popout=True)

    def _on_expand_clicked(self):
        pop = getattr(self.app, "chat_popout", None)
        if pop and pop.isMaximized():
            self.restore_requested.emit()
        else:
            self.expand_requested.emit()

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.selected_image_path = path
            self.image_label.setText(f"Vision input: {path}")

    def clear_image(self):
        self.selected_image_path = ""
        self.image_label.setText("Vision input: none")

    def _is_unknown_response(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return True
        lower = value.lower()
        low_signal_markers = [
            "not readable",
            "cannot be read",
            "can't be read",
            "cannot be conducted",
            "no analysis",
            "unable to analyze",
            "unable to analyse",
            "cannot determine",
            "insufficient detail",
        ]
        if any(marker in lower for marker in low_signal_markers):
            return True
        normalized = re.sub(r"[^A-Za-z\[\]]", "", value).upper()
        if normalized in {"UNK", "[UNK]", "UNKNOWN", "NA", "N/A"}:
            return True
        words = value.split()
        if not words:
            return True
        unk_like = 0
        for word in words:
            token = re.sub(r"[^A-Za-z\[\]]", "", word).upper()
            if token in {"UNK", "[UNK]", "UNKNOWN"}:
                unk_like += 1
        return (unk_like / max(1, len(words))) >= 0.7

    def open_ocr_settings(self):
        folder = QFileDialog.getExistingDirectory(self, "Select OCR export folder")
        if folder:
            os.makedirs("config", exist_ok=True)
            Path("config/storage.json").write_text('{"excel_output_folder": ' + json.dumps(folder) + '}', encoding="utf-8")
            self.on_status("OCR settings saved")

    def open_schema_editor(self):
        schema_path = Path("config/extraction_schemas/default.json")
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        if not schema_path.exists():
            schema_path.write_text('{"schema_id":"default","version":"1.0","fields":[],"output_columns":[],"example":{}}', encoding="utf-8")
        txt, ok = QInputDialog.getMultiLineText(self, "OCR Schema Editor", "Edit default schema JSON:", schema_path.read_text(encoding="utf-8"))
        if ok:
            try:
                json.loads(txt)
                schema_path.write_text(txt, encoding="utf-8")
                self.on_status("Schema saved")
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Invalid JSON: {exc}")

    def handle_ocr_result(self, result):
        selected_name = self.name_combo.currentText() or self.app._selected_agent_name()
        payload = dict(result or {}) if isinstance(result, dict) else {}

        if not bool(payload.get("ok", True)):
            err = str(payload.get("error") or "OCR request failed.")
            self.on_error(err)
            return

        provenance = dict(payload.get("provenance") or {})
        exports = dict(payload.get("exports") or {})
        mode = str(provenance.get("mode", "")).lower()
        raw_text = str(payload.get("raw_text") or "")
        structured_text = str(payload.get("structured_text") or "")
        body = (structured_text if mode == "structured" else raw_text) or raw_text or structured_text or ""
        body = str(body).strip()

        if self._is_unknown_response(body):
            if mode == "vision":
                body = (
                    "I couldn't confidently interpret this image. "
                    "Try a clearer image/crop, or ask for OCR explicitly if you need text extraction."
                )
            else:
                body = (
                    "I couldn't confidently extract readable text from this image. "
                    "Try a clearer image/crop or run OCR again with a more specific prompt."
                )

        user_text = self.pending_ocr_prompt.strip() if self.pending_ocr_prompt.strip() else "[image + prompt]"
        image_path = self.selected_image_path

        self.chat_area.append(f"You: {user_text}\n")
        self.chat_area.append(f"{selected_name}: {body}\n")
        if exports.get("excel_path"):
            self.chat_area.append(f"Excel saved: {exports['excel_path']}\n")

        agent_key = str(getattr(self.app, "selected_agent_key", ""))
        attachments = [{"type": "image", "path": image_path}] if image_path else []
        self.append_history("user", user_text, agent_key, attachments)
        self.append_history("assistant", str(body), agent_key)

        if bool(getattr(settings, "OCR_AUTO_CLEAR_IMAGE", True)):
            self.clear_image()

        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
        self.on_status("Done")
        self.ocr_worker = None
        self.pending_ocr_prompt = ""

    def run_ocr_from_ui(self, prompt):
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.on_status("Busy - OCR already running")
            self.prompt_entry.setEnabled(True)
            self.send_button.setEnabled(True)
            self.btn_stop_gen.setEnabled(True)
            self.pending_ocr_prompt = ""
            return

        mode = "auto"
        lower = (prompt or "").lower()
        struct_triggers = [
            t.lower()
            for t in (
                getattr(settings, "REGISTRY_TRIGGERS", [])
                + getattr(settings, "STRUCTURED_OCR_TRIGGERS", [])
            )
        ]
        general_triggers = [t.lower() for t in getattr(settings, "GENERAL_OCR_TRIGGERS", ["ocr"])]
        analysis_triggers = [t.lower() for t in getattr(settings, "IMAGE_ANALYSIS_TRIGGERS", [])]

        if any(t in lower for t in struct_triggers):
            mode = "structured"
        elif any(t in lower for t in general_triggers):
            mode = "general"
        elif any(t in lower for t in analysis_triggers):
            mode = "vision"
        else:
            mode = "vision"

        req = {
            "image_paths": [self.selected_image_path],
            "mode": mode,
            "options": {"prompt": prompt, "source": "gui"},
        }
        self.ocr_worker = OcrWorker(req)
        self.ocr_worker.result_signal.connect(self.handle_ocr_result)
        self.ocr_worker.error_signal.connect(self.on_error)
        self.ocr_worker.start()
    def _read_history_entries(self, path: Path | None = None) -> list[dict]:
        p = path or self.history_path
        if not p.exists():
            return []
        rows = []
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _load_threads_index(self) -> list[dict]:
        if not self.threads_index_path.exists():
            return []
        try:
            data = json.loads(self.threads_index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_threads_index(self, rows: list[dict]) -> None:
        try:
            self.chat_archive_dir.mkdir(parents=True, exist_ok=True)
            self.threads_index_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _slugify(self, text: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9\s_-]", "", str(text or "").strip())
        value = re.sub(r"\s+", "-", value).strip("-_")
        return value[:56] or "chat"

    def _ollama_chat(self, system_prompt: str, user_prompt: str, *, timeout: float = 8.0) -> str:
        model = str(getattr(settings, "INSTRUCT_MODEL", "") or getattr(settings, "DEFAULT_MODEL", ""))
        if not model:
            return ""
        opts = build_ollama_chat_options(
            model=model,
            role="instruct",
            temperature=0.15,
            think=False,
            extra={"num_predict": 140},
        )
        keep_alive = opts.pop("keep_alive", None) if isinstance(opts, dict) else None
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": opts if isinstance(opts, dict) else {},
        }
        if keep_alive is not None:
            try:
                payload["keep_alive"] = f"{int(keep_alive)}s"
            except Exception:
                pass

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw)
            return str(parsed.get("message", {}).get("content", "") or "").strip()
        except Exception:
            return ""

    def _build_resume_context(self, entries: list[dict], summary_hint: str = "") -> str:
        turns = [e for e in entries if str(e.get("role", "")).lower() in {"user", "assistant"}]
        tail = turns[-6:]
        recent_lines = []
        for item in tail:
            role = "User" if str(item.get("role", "")).lower() == "user" else "Assistant"
            txt = str(item.get("text", "")).strip().replace("\n", " ")
            recent_lines.append(f"- {role}: {txt[:280]}")
        summary = str(summary_hint or "").strip() or "Conversation loaded from archive."
        return f"Summary: {summary}\nRecent turns:\n" + ("\n".join(recent_lines) if recent_lines else "- (none)")

    def _suggest_thread_title(self, first_query: str) -> str:
        seed = str(first_query or "").strip()
        if not seed:
            return "Archived Chat"
        sys_prompt = "Generate a concise chat title (3-7 words). Return title only, no quotes."
        raw = self._ollama_chat(sys_prompt, seed, timeout=6.0)
        title = re.sub(r"[\r\n]+", " ", raw).strip(" .:-_\"'")
        if not title:
            title = " ".join(seed.split()[:7]).strip()
        return title[:72] or "Archived Chat"

    def _summarize_thread(self, entries: list[dict]) -> str:
        turns = [e for e in entries if str(e.get("role", "")).lower() in {"user", "assistant"}]
        if not turns:
            return "No usable turns captured."
        excerpt = []
        for item in turns[-12:]:
            role = "User" if str(item.get("role", "")).lower() == "user" else "Assistant"
            txt = str(item.get("text", "")).strip().replace("\n", " ")
            excerpt.append(f"{role}: {txt[:260]}")
        transcript = "\n".join(excerpt)
        sys_prompt = (
            "Summarize this chat for continuation context in 4-6 bullet-like lines. "
            "Include goals, constraints, decisions, and unresolved asks."
        )
        summary = self._ollama_chat(sys_prompt, transcript, timeout=7.0)
        if summary:
            return summary[:1400]

        first_user = next((str(x.get("text", "")).strip() for x in turns if str(x.get("role", "")).lower() == "user"), "")
        last_user = next((str(x.get("text", "")).strip() for x in reversed(turns) if str(x.get("role", "")).lower() == "user"), "")
        last_assistant = next((str(x.get("text", "")).strip() for x in reversed(turns) if str(x.get("role", "")).lower() == "assistant"), "")
        bits = [
            f"Initial ask: {first_user[:240]}" if first_user else "",
            f"Latest user focus: {last_user[:240]}" if last_user else "",
            f"Latest assistant output: {last_assistant[:240]}" if last_assistant else "",
        ]
        return "\n".join([b for b in bits if b]) or "Conversation summary unavailable."

    def _render_thread_markdown(self, title: str, summary: str, entries: list[dict]) -> str:
        out = [f"# {title}", "", "## Summary", "", summary.strip(), "", "## Transcript", ""]
        for item in entries:
            role_raw = str(item.get("role", "system")).lower()
            role = "You" if role_raw == "user" else "Somi" if role_raw == "assistant" else "System"
            ts = str(item.get("timestamp", "")).strip()
            text = str(item.get("text", "")).strip()
            out.append(f"### {role}" + (f" ({ts})" if ts else ""))
            out.append("")
            out.append(text if text else "(empty)")
            out.append("")
        return "\n".join(out).strip() + "\n"

    def archive_current_chat(self) -> dict | None:
        entries = self._read_history_entries(self.history_path)
        turns = [e for e in entries if str(e.get("role", "")).lower() in {"user", "assistant"}]
        if not turns:
            return None

        first_query = next((str(e.get("text", "")).strip() for e in turns if str(e.get("role", "")).lower() == "user"), "")
        title = self._suggest_thread_title(first_query)
        summary = self._summarize_thread(turns)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = self._slugify(title)
        thread_id = f"{stamp}_{slug}"
        jsonl_path = self.chat_archive_dir / f"{thread_id}.jsonl"
        md_path = self.chat_archive_dir / f"{thread_id}.md"

        json_lines = [json.dumps(e, ensure_ascii=False) for e in entries]
        jsonl_path.write_text(("\n".join(json_lines) + "\n") if json_lines else "", encoding="utf-8")
        md_path.write_text(self._render_thread_markdown(title, summary, entries), encoding="utf-8")

        meta = {
            "id": thread_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "first_query": first_query[:240],
            "summary": summary[:1800],
            "jsonl_path": str(jsonl_path),
            "markdown_path": str(md_path),
        }
        index = self._load_threads_index()
        index = [x for x in index if str(x.get("id", "")) != thread_id]
        index.insert(0, meta)
        self._save_threads_index(index)
        return meta

    def start_new_chat(self):
        try:
            if self.worker and self.worker.isRunning() and self.worker.is_busy():
                self.on_status("Busy - stop current response first")
                return
        except Exception:
            pass

        archived = self.archive_current_chat()
        self.cancel_ocr_if_running()
        self.app.stop_chat_worker()
        self.resume_context_once = ""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text("", encoding="utf-8")
        self.history_loaded = False
        self.chat_area.clear()

        if archived:
            self.chat_area.append(f"System: Archived chat as '{archived.get('title', 'Untitled')}'.\n")
        if hasattr(self.app, "push_activity"):
            self.app.push_activity("chat", "Started new chat")

        if hasattr(self.app, "_startup_chat_message_sent"):
            self.app._startup_chat_message_sent = False
        self.app.ensure_chat_worker_running(use_studies=self.use_studies_check.isChecked())
        self.on_status("Idle")

    def _load_archived_chat(self, meta: dict):
        jsonl_path = Path(str(meta.get("jsonl_path", "")).strip())
        if not jsonl_path.exists():
            QMessageBox.warning(self, "Missing Archive", f"Archive file not found:\n{jsonl_path}")
            return
        entries = self._read_history_entries(jsonl_path)
        if not entries:
            QMessageBox.information(self, "Empty Archive", "Selected archive has no usable transcript.")
            return

        self.app.stop_chat_worker()
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
        self.history_path.write_text(serialized + ("\n" if serialized else ""), encoding="utf-8")
        self.history_loaded = False
        self.load_history(force=True)
        self.resume_context_once = self._build_resume_context(entries, summary_hint=str(meta.get("summary", "")))
        self.app.ensure_chat_worker_running(use_studies=self.use_studies_check.isChecked())
        self.chat_area.append("System: Archive loaded. Next prompt will use compact resume context.\n")
        self.chat_area.ensureCursorVisible()
        if hasattr(self.app, "push_activity"):
            self.app.push_activity("chat", f"Loaded archived chat: {meta.get('title', 'Untitled')}")

    def open_old_chats(self):
        threads = self._load_threads_index()
        if not threads:
            QMessageBox.information(self, "Old Chats", "No archived chats found yet.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Old Chats")
        dialog.resize(760, 460)
        root = QVBoxLayout(dialog)

        row = QHBoxLayout()
        list_widget = QListWidget()
        preview = QTextEdit()
        preview.setReadOnly(True)
        row.addWidget(list_widget, 2)
        row.addWidget(preview, 3)
        root.addLayout(row)

        for item in threads:
            title = str(item.get("title", "Untitled"))
            created = str(item.get("created_at", ""))[:19].replace("T", " ")
            list_widget.addItem(QListWidgetItem(f"{title}  [{created}]"))

        def refresh_preview():
            idx = list_widget.currentRow()
            if idx < 0 or idx >= len(threads):
                preview.setPlainText("")
                return
            meta = threads[idx]
            summary = str(meta.get("summary", "")).strip() or "No summary."
            first = str(meta.get("first_query", "")).strip()
            preview.setPlainText(
                f"Title: {meta.get('title', 'Untitled')}\n"
                f"Created: {meta.get('created_at', '--')}\n"
                f"First query: {first}\n\n"
                f"Summary:\n{summary}\n"
            )

        buttons = QHBoxLayout()
        load_btn = QPushButton("Load Chat")
        cancel_btn = QPushButton("Cancel")
        buttons.addWidget(load_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

        list_widget.currentRowChanged.connect(lambda _row: refresh_preview())
        cancel_btn.clicked.connect(dialog.reject)

        def load_selected():
            idx = list_widget.currentRow()
            if idx < 0 or idx >= len(threads):
                QMessageBox.information(dialog, "Old Chats", "Select a chat to load.")
                return
            self._load_archived_chat(threads[idx])
            dialog.accept()

        load_btn.clicked.connect(load_selected)

        if list_widget.count():
            list_widget.setCurrentRow(0)
            refresh_preview()

        dialog.exec()











