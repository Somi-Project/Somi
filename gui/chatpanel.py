from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QTextDocument
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import settings
from gui.aicoregui import OcrWorker, _themed_input_style, _themed_text_style
from handlers.ocr.contracts import OcrRequest


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
        self.sessions_dir = Path("sessions/chat")
        self.sessions_index_path = self.sessions_dir / "index.json"
        self.max_sessions = 20
        self.current_session_id = ""
        self.history_path = self.sessions_dir / "default_user.jsonl"
        self.max_history_lines_to_load = 200
        self.history_loaded = False
        self.sessions = []

        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_index = 0
        self.spinner_state = "Stopped"
        self.spinner_timer = QTimer(self)
        self.spinner_timer.setInterval(90)
        self.spinner_timer.timeout.connect(self._tick_spinner)

        self._build_ui()
        self._init_sessions()
        self._set_connected_state(False)
        self.set_popout_state(False, False)

    def _build_ui(self):
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Chat"))
        header.addStretch(1)
        self.btn_popout = QPushButton("↗")
        self.btn_expand = QPushButton("⛶")
        self.btn_stop_chat = QPushButton("Stop Chat")
        self.btn_stop_gen = QPushButton("Stop Generating")
        for btn in [self.btn_popout, self.btn_expand, self.btn_stop_chat, self.btn_stop_gen]:
            btn.setAutoDefault(False)
            btn.setDefault(False)
            header.addWidget(btn)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Agent:"))
        self.name_combo = QComboBox()
        self.name_combo.addItems(getattr(self.app, "agent_names", []))
        current = self.app._selected_agent_name()
        if current in getattr(self.app, "agent_names", []):
            self.name_combo.setCurrentText(current)
        controls.addWidget(self.name_combo)
        self.use_studies_check = QCheckBox("Use Studies (RAG)")
        self.use_studies_check.setChecked(True)
        controls.addWidget(self.use_studies_check)
        self.apply_agent_button = QPushButton("Apply Agent")
        controls.addWidget(self.apply_agent_button)
        root.addLayout(controls)

        sessions_row = QHBoxLayout()
        sessions_row.addWidget(QLabel("Chats:"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(280)
        sessions_row.addWidget(self.session_combo, 1)
        self.new_session_button = QPushButton("+ New Chat")
        sessions_row.addWidget(self.new_session_button)
        root.addLayout(sessions_row)

        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setStyleSheet(_themed_text_style(11))
        self.chat_area.setFont(QFont("Arial", 11))
        root.addWidget(self.chat_area, 1)

        prompt_row = QHBoxLayout()
        self.prompt_entry = QLineEdit()
        self.prompt_entry.setStyleSheet(_themed_input_style(11))
        self.prompt_entry.setFont(QFont("Arial", 11))
        self.send_button = QPushButton("Send")
        prompt_row.addWidget(self.prompt_entry, 1)
        prompt_row.addWidget(self.send_button)
        root.addLayout(prompt_row)

        image_row = QHBoxLayout()
        self.image_label = QLabel("Image: none")
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

        self.status_label = QLabel("Status: Stopped")
        root.addWidget(self.status_label)

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
        self.new_session_button.clicked.connect(self.start_new_session)
        self.session_combo.currentIndexChanged.connect(self._on_session_changed)

    def _set_connected_state(self, connected: bool):
        self.connected = connected
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
        self.status_label.setText("Status: Idle" if connected else "Status: Stopped")

    def _session_file_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def _load_sessions_index(self):
        if not self.sessions_index_path.exists():
            return []
        try:
            data = json.loads(self.sessions_index_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("id")]
        except Exception:
            pass
        return []

    def _normalize_sessions(self):
        normalized = []
        for sess in self.sessions:
            sid = str(sess.get("id", "")).strip()
            if not sid:
                continue
            path = self._session_file_for(sid)
            if not path.exists():
                continue
            normalized.append({
                "id": sid,
                "title": str(sess.get("title") or f"Session {sid}"),
                "updated_at": str(sess.get("updated_at") or datetime.now().isoformat()),
            })
        self.sessions = normalized

    def _save_sessions_index(self):
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            self.sessions_index_path.write_text(json.dumps(self.sessions, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _prune_sessions(self):
        if len(self.sessions) <= self.max_sessions:
            return
        self.sessions.sort(key=lambda s: str(s.get("updated_at", "")))
        while len(self.sessions) > self.max_sessions:
            oldest = self.sessions.pop(0)
            try:
                self._session_file_for(str(oldest.get("id", ""))).unlink(missing_ok=True)
            except Exception:
                pass

    def _refresh_session_combo(self):
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.sessions.sort(key=lambda s: str(s.get("updated_at", "")), reverse=True)
        for sess in self.sessions:
            self.session_combo.addItem(str(sess.get("title", sess.get("id", "session"))), str(sess.get("id", "")))
        idx = self.session_combo.findData(self.current_session_id)
        if idx >= 0:
            self.session_combo.setCurrentIndex(idx)
        self.session_combo.blockSignals(False)

    def _create_session(self, title: str | None = None) -> str:
        sid = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        record = {
            "id": sid,
            "title": title or f"Chat {datetime.now().strftime('%b %d %H:%M')}",
            "updated_at": datetime.now().isoformat(),
        }
        self.sessions.append(record)
        try:
            self._session_file_for(sid).touch(exist_ok=True)
        except Exception:
            pass
        self._prune_sessions()
        self._save_sessions_index()
        return sid

    def _touch_session(self, session_id: str):
        for sess in self.sessions:
            if str(sess.get("id")) == str(session_id):
                sess["updated_at"] = datetime.now().isoformat()
                break
        self._save_sessions_index()

    def _init_sessions(self):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.sessions = self._load_sessions_index()
        before_count = len(self.sessions)
        self._normalize_sessions()
        if len(self.sessions) != before_count:
            self._save_sessions_index()
        if not self.sessions:
            first = self._create_session("Current Session")
            self.current_session_id = first
            self.history_path = self._session_file_for(first)
        else:
            self.sessions.sort(key=lambda s: str(s.get("updated_at", "")), reverse=True)
            self.current_session_id = str(self.sessions[0]["id"])
            self.history_path = self._session_file_for(self.current_session_id)
        self._refresh_session_combo()

    def start_new_session(self):
        sid = self._create_session()
        self.current_session_id = sid
        self.history_path = self._session_file_for(sid)
        self.history_loaded = False
        self._refresh_session_combo()
        self.load_history(force=True)

    def _on_session_changed(self, index: int):
        if index < 0:
            return
        sid = str(self.session_combo.itemData(index) or "")
        if not sid or sid == self.current_session_id:
            return
        self.current_session_id = sid
        self.history_path = self._session_file_for(sid)
        self.history_loaded = False
        self.load_history(force=True)

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
        self.btn_popout.setText("↙" if is_popped_out else "↗")
        self.btn_expand.setEnabled(is_popped_out)
        self.btn_expand.setText("🗗" if is_maximized else "⛶")

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
            "session_id": self.current_session_id,
        }
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._touch_session(self.current_session_id)
            self._refresh_session_combo()
        except Exception:
            pass

    def on_send(self):
        prompt = self.prompt_entry.text().strip()
        if not prompt:
            return
        if not self.worker or not self.worker.isRunning():
            self.app.ensure_chat_worker_running(use_studies=self.use_studies_check.isChecked())
            if not self.worker or not self.worker.isRunning():
                self.on_error("Chat worker is not available.")
                return
        else:
            self.worker.use_studies = self.use_studies_check.isChecked()
            try:
                if self.worker.is_busy():
                    self.on_status("Busy — stop current response first")
                    return
            except Exception:
                pass
        self.on_status("Thinking…")
        self.prompt_entry.setEnabled(False)
        self.send_button.setEnabled(False)
        self.btn_stop_gen.setEnabled(True)
        if self.selected_image_path:
            self.pending_ocr_prompt = prompt
            self.run_ocr_from_ui(prompt)
        else:
            self.worker.process_prompt(prompt)
        self.prompt_entry.clear()

    def on_response(self, user_input, ai_response, attachments):
        selected_name = self.name_combo.currentText() or self.app._selected_agent_name()
        self.chat_area.append(f"You: {user_input}\n")
        self.chat_area.append(f"{selected_name}: {str(ai_response).strip()}\n")
        for att in attachments or []:
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
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)

    def _tick_spinner(self):
        frame = self.spinner_frames[self.spinner_index]
        self.spinner_index = (self.spinner_index + 1) % len(self.spinner_frames)
        self.status_label.setText(f"Status: {frame} {self.spinner_state}")

    def on_status(self, text):
        self.spinner_state = text
        if text in {"Idle", "Done", "Stopped"}:
            self.spinner_timer.stop()
            self.status_label.setText(f"Status: {text}")
        else:
            if not self.spinner_timer.isActive():
                self.spinner_timer.start()

    def on_error(self, msg):
        self.ocr_worker = None
        self.pending_ocr_prompt = ""
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
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)

    def _on_popout_clicked(self):
        if getattr(self.app, "chat_is_popped", False):
            self.dock_requested.emit()
        else:
            self.popout_requested.emit()

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
            self.image_label.setText(f"Image: {path}")

    def clear_image(self):
        self.selected_image_path = ""
        self.image_label.setText("Image: none")

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
        body = result.structured_text if result.structured_text else result.raw_text
        user_text = self.pending_ocr_prompt.strip() if self.pending_ocr_prompt.strip() else "[image + prompt]"
        self.chat_area.append(f"You: {user_text}\n")
        self.chat_area.append(f"{selected_name}: {body}\n")
        if result.exports.get("excel_path"):
            self.chat_area.append(f"Excel saved: {result.exports['excel_path']}\n")
        agent_key = str(getattr(self.app, "selected_agent_key", ""))
        self.append_history("user", user_text, agent_key, [{"type": "image", "path": self.selected_image_path}])
        self.append_history("assistant", str(body), agent_key)
        self.prompt_entry.setEnabled(True)
        self.send_button.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
        self.on_status("Done")
        self.ocr_worker = None
        self.pending_ocr_prompt = ""

    def run_ocr_from_ui(self, prompt):
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.on_status("Busy — OCR already running")
            return
        mode = "auto"
        lower = (prompt or "").lower()
        struct_triggers = [t.lower() for t in (getattr(settings, "REGISTRY_TRIGGERS", []) + getattr(settings, "OCR_TRIGGERS", []) + getattr(settings, "STRUCTURED_OCR_TRIGGERS", []))]
        general_triggers = [t.lower() for t in getattr(settings, "GENERAL_OCR_TRIGGERS", ["ocr"])]
        if any(t in lower for t in struct_triggers):
            mode = "structured"
        elif any(t in lower for t in general_triggers):
            mode = "general"
        req = OcrRequest(image_paths=[self.selected_image_path], prompt=prompt, mode=mode, source="gui")
        self.ocr_worker = OcrWorker(req)
        self.ocr_worker.result_signal.connect(self.handle_ocr_result)
        self.ocr_worker.error_signal.connect(self.on_error)
        self.ocr_worker.start()
