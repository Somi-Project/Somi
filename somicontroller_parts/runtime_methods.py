from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (runtime_methods.py)."""

def open_agentpedia_viewer(self):
    dialog = QDialog(self)
    dialog.setWindowTitle("Agentpedia")
    dialog.resize(920, 560)
    dialog.setStyleSheet(dialog_stylesheet())

    layout = QVBoxLayout(dialog)
    row = QHBoxLayout()

    topics = QListWidget()
    viewer = QTextEdit()
    viewer.setReadOnly(True)

    row.addWidget(topics, 1)
    row.addWidget(viewer, 2)
    layout.addLayout(row)

    refresh_btn = QPushButton("Refresh")
    layout.addWidget(refresh_btn)

    def load_topics():
        topics.clear()
        try:
            out = self.toolbox_runtime.run(
                "research.artifacts",
                {"action": "agentpedia_list_topics", "k": 200},
                {"source": "gui", "approved": True, "user_id": "default_user"},
            )
            rows = list((out or {}).get("topics") or [])
            for item in rows:
                topics.addItem(str(item.get("topic") or "Unknown"))
        except Exception as exc:
            viewer.setPlainText(f"Failed to load Agentpedia topics: {exc}")

    def on_pick():
        it = topics.currentItem()
        if not it:
            return
        topic = it.text().strip()
        try:
            out = self.toolbox_runtime.run(
                "research.artifacts",
                {"action": "agentpedia_topic_page", "topic": topic},
                {"source": "gui", "approved": True, "user_id": "default_user"},
            )
            md = str((out or {}).get("markdown") or "")
            viewer.setPlainText(md or "No topic page available.")
        except Exception as exc:
            viewer.setPlainText(f"Failed to load topic page: {exc}")

    refresh_btn.clicked.connect(load_topics)
    topics.itemSelectionChanged.connect(on_pick)

    load_topics()
    dialog.exec()

def toggle_speech_process(self):
    was_active = bool(self.alex_process and self.alex_process.poll() is None)
    self.refresh_agent_names()
    is_active = bool(speechgui.toggle_speech_runtime(self))
    self.speech_active = is_active
    self.state["speech_status"] = "Listening" if is_active else "Idle"
    self.mic_state_label.setText("Mic: ON" if is_active else "Mic: OFF")
    self.voice_state_label.setText("Voice: STANDBY" if is_active else "Voice: READY")
    self.speech_btn.setText("Stop Speech" if is_active else "Speech Control")
    self.waveform.set_active(is_active)
    if was_active and not is_active:
        self.push_activity("speech", "Speech runtime stopped")
    elif is_active:
        self.push_activity("speech", "Speech runtime listening")
    else:
        self.push_activity("speech", "Speech control opened")
    self.update_top_strip()

def load_agent_names(self):
    try:
        characters = json.loads(PERSONALITY_CONFIG.read_text(encoding="utf-8"))
        agent_keys = list(characters.keys())
        agent_names = [k.replace("Name: ", "") for k in agent_keys]
        return agent_keys, agent_names
    except Exception:
        return [], []

def refresh_agent_names(self):
    self.agent_keys, self.agent_names = self.load_agent_names()
    previous_key = str(getattr(self, "selected_agent_key", "") or "")
    if previous_key not in self.agent_keys:
        self.selected_agent_key = self._default_agent_key()
        if str(self.selected_agent_key or "") and str(self.selected_agent_key) != previous_key:
            try:
                self._persist_selected_agent_key(self.selected_agent_key)
            except Exception:
                pass
    if getattr(self, "persona_combo", None):
        previous = self.persona_combo.currentText()
        self.persona_combo.blockSignals(True)
        self.persona_combo.clear()
        self.persona_combo.addItems(self.agent_names)
        target = self.selected_agent_key.replace("Name: ", "")
        if target in self.agent_names:
            self.persona_combo.setCurrentText(target)
        elif previous in self.agent_names:
            self.persona_combo.setCurrentText(previous)
        self.persona_combo.blockSignals(False)

    if getattr(self, "chat_panel", None) and getattr(self.chat_panel, "name_combo", None):
        combo = self.chat_panel.name_combo
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self.agent_names)
        target = self.selected_agent_key.replace("Name: ", "")
        if target in self.agent_names:
            combo.setCurrentText(target)
        elif current in self.agent_names:
            combo.setCurrentText(current)
        combo.blockSignals(False)

def _default_agent_key(self):
    if self.agent_keys:
        return self.agent_keys[0]
    return "Name: Somi"

def preload_default_agent_and_chat_worker(self):
    self.refresh_agent_names()
    agent_key = str(getattr(self, "selected_agent_key", "") or self._default_agent_key())
    if agent_key not in self.agent_keys:
        agent_key = self._default_agent_key()
    self.preloaded_agent = None
    self.agent_warmup_worker = None
    self.push_activity("core", f"Chat standby ready for {agent_key.replace('Name: ', '')}")
    try:
        if self.chat_panel:
            self.chat_panel.load_history()
    except Exception as exc:
        logger.exception("Failed to prepare chat panel history")
        self.push_activity("core", f"Chat history preload failed: {exc}")

    def _start_chat_worker():
        try:
            use_studies = True
            if getattr(self, "chat_panel", None) is not None:
                use_studies = bool(self.chat_panel.use_studies_check.isChecked())
            self.ensure_chat_worker_running(use_studies=use_studies)
            self.push_activity("core", "Chat worker pre-initialized")
        except Exception as exc:
            logger.exception("Failed to pre-initialize chat worker")
            self.push_activity("core", f"Chat worker preload failed: {exc}")

    QTimer.singleShot(0, _start_chat_worker)
    QTimer.singleShot(700, _start_chat_worker)

def _on_agent_warmed(self, ok: bool, detail: str):
    if ok:
        if self.agent_warmup_worker:
            self.preloaded_agent = self.agent_warmup_worker.agent
        self.push_activity("core", f"Agent warmup ready: {detail}")
        try:
            if self.chat_panel:
                self.chat_panel.load_history()
            self.ensure_chat_worker_running()
            self.push_activity("core", "Chat worker pre-initialized")
        except Exception as exc:
            logger.exception("Failed to pre-initialize chat worker")
            self.push_activity("core", f"Chat worker preload failed: {exc}")
    else:
        self.push_activity("core", f"Agent warmup failed: {detail}")

def toggle_ai_model(self):
    aicoregui.ai_model_start_stop(self)
    self.push_activity("core", "AI model toggled")

def open_chat(self):
    self.toggle_chat_popout(force_popout=True)
    self.push_activity("core", "User opened chat")

def ensure_chat_worker_running(self, use_studies: bool = True):
    from gui.aicoregui import ChatWorker

    if self.chat_worker and self.chat_worker.isRunning():
        if self.chat_worker.is_busy():
            if self.chat_panel:
                self.chat_panel.attach_worker(self.chat_worker)
            return
        try:
            self.chat_worker.update_agent(str(getattr(self, "selected_agent_key", "") or self._default_agent_key()), use_studies)
        except Exception:
            pass
        if self.chat_panel:
            self.chat_panel.attach_worker(self.chat_worker)
        return

    agent_key = str(getattr(self, "selected_agent_key", "") or self._default_agent_key())
    if agent_key not in self.agent_keys:
        agent_key = self._default_agent_key()

    self.chat_worker = ChatWorker(self, agent_key, use_studies, preloaded_agent=self.preloaded_agent)
    self.chat_worker.error_signal.connect(lambda msg: self.push_activity("core", f"Chat worker error: {msg}"))
    self.chat_worker.status_signal.connect(lambda status: self.push_activity("core", f"Chat worker status: {status}"))
    def _handle_chat_worker_status(status):
        normalized = str(status or "").strip().lower()
        if normalized != "ready":
            return
        if self.chat_panel:
            self.chat_panel.on_status("Ready")
        if self._startup_chat_message_sent:
            return
        startup_msg = "Prime chat is ready - how can I help you today?"
        if self.chat_panel:
            self.chat_panel.chat_area.append(f"Somi: {startup_msg}\n")
            self.chat_panel.chat_area.ensureCursorVisible()
        self.push_activity("core", "Chat worker ready")
        self._startup_chat_message_sent = True
    self.chat_worker.status_signal.connect(_handle_chat_worker_status)
    if self.chat_panel and not self._startup_chat_message_sent:
        self.chat_panel.on_status("Warming up chat...")
    self.chat_worker.start()
    if self.chat_panel:
        self.chat_panel.attach_worker(self.chat_worker)

def stop_chat_worker(self):
    if self.chat_panel:
        self.chat_panel.cancel_ocr_if_running()
    had_running_worker = bool(self.chat_worker and self.chat_worker.isRunning())
    if had_running_worker:
        self.chat_worker.stop()
        self.chat_worker.wait(1500)
    self.chat_worker = None
    if self.chat_panel:
        self.chat_panel.detach_worker()
    if had_running_worker:
        self.push_activity("core", "Chat worker stopped")

def toggle_chat_popout(self, force_popout: bool = False):
    if not self.chat_panel:
        return
    if self.chat_is_popped and force_popout:
        if self.chat_popout:
            self.chat_popout.show()
            self.chat_popout.raise_()
            self.chat_popout.activateWindow()
        self.chat_panel.set_popout_state(True, is_maximized=bool(self.chat_popout and self.chat_popout.isMaximized()))
        return
    if not self.chat_is_popped:
        if self.chat_panel.parent() and self.chat_host_layout:
            self.chat_host_layout.removeWidget(self.chat_panel)
        if not self.chat_popout:
            self.chat_popout = ChatPopoutWindow(self, self.chat_panel)
        self.chat_popout.show()
        self.chat_popout.raise_()
        self.chat_popout.activateWindow()
        self.chat_is_popped = True
        self.chat_panel.set_popout_state(True, is_maximized=self.chat_popout.isMaximized())
        return
    self.dock_chat_panel()

def dock_chat_panel(self):
    if self._chat_docking_in_progress:
        return
    self._chat_docking_in_progress = True
    if not self.chat_panel or not self.chat_embed_parent:
        self._chat_docking_in_progress = False
        return
    try:
        if self.chat_popout:
            pop_layout = self.chat_popout.layout()
            if pop_layout:
                pop_layout.removeWidget(self.chat_panel)
            self.chat_popout.deleteLater()
            self.chat_popout = None
        self.chat_embed_parent.addWidget(self.chat_panel)
        self.chat_is_popped = False
        self.chat_panel.set_popout_state(False, False)
    finally:
        self._chat_docking_in_progress = False

def toggle_chat_expand(self):
    if not self.chat_is_popped or not self.chat_popout:
        return
    if self.chat_popout.isMaximized():
        self.chat_popout.showNormal()
    else:
        self.chat_popout.showMaximized()
    self.chat_panel.set_popout_state(True, self.chat_popout.isMaximized())

def open_data_agent(self):
    from gui import dataagentgui

    dialog = dataagentgui.DataAgentWindow(self)
    dialog.exec()
    self.push_activity("module", "User opened data agent")

def run_personality_editor(self):
    try:
        subprocess.Popen([sys.executable, "persona.py"], shell=False)
        self.output_area.append("Personality Editor launched.")
        self.push_activity("module", "Personality editor opened")
    except Exception as exc:
        QMessageBox.critical(self, "Error", f"Failed to launch Personality Editor: {exc}")

def _extract_json_block(self, text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return ""

def fetch_runtime_diagnostics(self):
    report_path = Path("sessions/evals/latest_eval_harness.json")
    cmd = [sys.executable, "-m", "runtime.eval_harness"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=180,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "diagnostics timed out after 180s", "report_path": str(report_path)}
    except Exception as exc:
        return {"ok": False, "error": f"failed to run diagnostics: {type(exc).__name__}: {exc}", "report_path": str(report_path)}

    if proc.returncode != 0:
        stderr = str(proc.stderr or "").strip()
        stdout = str(proc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        return {"ok": False, "error": detail, "report_path": str(report_path)}

    parsed = None
    stdout = str(proc.stdout or "").strip()
    try:
        parsed = json.loads(stdout)
    except Exception:
        block = self._extract_json_block(stdout)
        if block:
            try:
                parsed = json.loads(block)
            except Exception:
                parsed = None

    if parsed is None and report_path.exists():
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            parsed = None

    if not isinstance(parsed, dict):
        return {"ok": False, "error": "diagnostics output was not valid JSON", "report_path": str(report_path)}

    return {
        "ok": True,
        "report": parsed,
        "report_path": str(report_path),
    }

def run_runtime_diagnostics(self):
    if self._runtime_diagnostics_running:
        self.push_activity("diagnostics", "Runtime diagnostics already running")
        return
    self._runtime_diagnostics_running = True
    self.output_area.append("[Diagnostics] Starting runtime diagnostics...")
    self.output_area.ensureCursorVisible()
    self.push_activity("diagnostics", "Running runtime diagnostics")
    self._start_worker("runtime_diagnostics", self.fetch_runtime_diagnostics)

def closeEvent(self, event):
    timer_attrs = [
        "clock_timer",
        "intel_timer",
        "reminder_timer",
        "weather_timer",
        "news_timer",
        "finance_news_timer",
        "developments_timer",
        "output_watch_timer",
        "hb_label_timer",
        "hb_event_timer",
        "hb_diag_timer",
        "stream_meter_timer",
        "hud_target_timer",
        "startup_refresh_timer",
    ]
    for attr in timer_attrs:
        timer = getattr(self, attr, None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    if getattr(self, "intel_anim", None) is not None:
        try:
            self.intel_anim.stop()
        except Exception:
            pass
        callback = getattr(self, "_intel_swap_text_callback", None)
        if callback is not None:
            try:
                self.intel_anim.finished.disconnect(callback)
            except Exception:
                pass
            self._intel_swap_text_callback = None

    if getattr(self, "waveform", None) is not None:
        try:
            self.waveform.set_active(False)
        except Exception:
            pass

    orbit = getattr(self, "stream_orbit", None)
    orbit_timer = getattr(orbit, "_timer", None)
    if orbit_timer is not None:
        try:
            orbit_timer.stop()
        except Exception:
            pass

    overlay = getattr(self, "hud_overlay", None)
    overlay_timer = getattr(overlay, "timer", None)
    if overlay_timer is not None:
        try:
            overlay_timer.stop()
        except Exception:
            pass
    if overlay is not None:
        try:
            overlay.hide()
        except Exception:
            pass

    panel = getattr(self, "chat_panel", None)
    spinner = getattr(panel, "spinner_timer", None)
    if spinner is not None:
        try:
            spinner.stop()
        except Exception:
            pass

    control_room = getattr(self, "control_room_panel", None)
    refresh_timer = getattr(control_room, "refresh_timer", None)
    if refresh_timer is not None:
        try:
            refresh_timer.stop()
        except Exception:
            pass

    for worker in list(getattr(self, "workers", []) or []):
        try:
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(400)
            if worker.isRunning():
                worker.terminate()
                worker.wait(1200)
        except Exception:
            pass
    self.workers = []

    self.heartbeat_service.stop()
    self.stop_chat_worker()
    if self.agent_warmup_worker and self.agent_warmup_worker.isRunning():
        self.agent_warmup_worker.quit()
        self.agent_warmup_worker.wait(1000)
    for process in [self.telegram_process, self.twitter_autotweet_process, self.twitter_autoresponse_process, self.alex_process, self.ai_model_process]:
        if process and process.poll() is None:
            try:
                os.kill(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except Exception:
                process.kill()
    super(SomiAIGUI, self).closeEvent(event)
