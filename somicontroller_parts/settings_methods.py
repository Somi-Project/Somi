from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (settings_methods.py)."""

def read_gui_settings(self):
    if not GUI_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(GUI_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_gui_settings(self, payload):
    try:
        GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        GUI_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write GUI settings: %s", exc)

def load_gui_theme_preference(self):
    data = self.read_gui_settings()
    set_theme(str(data.get("theme", "cockpit_balanced")))

def _model_profile_options(self):
    defaults = ["low", "medium", "high", "very_high", "ultra"]
    try:
        from config import modelsettings as modelsettings_module

        available = list(getattr(modelsettings_module, "AVAILABLE_MODEL_CAPABILITY_PROFILES", defaults))
        cleaned = [str(x).strip() for x in available if str(x).strip()]
        return cleaned or defaults
    except Exception:
        return defaults

def _normalize_model_profile(self, profile_name):
    raw = str(profile_name or "").strip()
    try:
        from config import modelsettings as modelsettings_module

        return str(modelsettings_module.normalize_model_profile(raw))
    except Exception:
        key = raw.lower()
        aliases = {"very high": "very_high", "very-high": "very_high", "vh": "very_high"}
        key = aliases.get(key, key)
        return key if key in {"low", "medium", "high", "very_high", "ultra"} else "medium"

def _effective_model_profile(self):
    data = self.read_gui_settings()
    preferred = str(data.get("model_capability_profile", "")).strip()
    env_name = str(os.getenv("SOMI_MODEL_PROFILE", "")).strip()
    return self._normalize_model_profile(preferred or env_name or "medium")

def _reload_runtime_model_stack(self):
    try:
        from config import modelsettings as modelsettings_module
        from config import memorysettings as memorysettings_module
        from config import settings as settings_module
        import agents as agents_module
        from gui import aicoregui

        modelsettings_module = importlib.reload(modelsettings_module)
        memorysettings_module = importlib.reload(memorysettings_module)
        settings_module = importlib.reload(settings_module)
        agents_module = importlib.reload(agents_module)

        aicoregui.settings = settings_module
        aicoregui.Agent = agents_module.Agent
        return True
    except Exception as exc:
        logger.exception("Failed to reload runtime model stack")
        self.push_activity("core", f"Model settings reload failed: {exc}")
        return False

def load_gui_model_profile_preference(self):
    profile = self._effective_model_profile()
    os.environ["SOMI_MODEL_PROFILE"] = profile
    self._reload_runtime_model_stack()

def apply_model_profile(self, profile_name):
    profile = self._normalize_model_profile(profile_name)
    data = self.read_gui_settings()
    data["model_capability_profile"] = profile
    self.write_gui_settings(data)
    os.environ["SOMI_MODEL_PROFILE"] = profile
    if not self._reload_runtime_model_stack():
        return False

    use_studies = True
    if self.chat_panel is not None:
        try:
            use_studies = bool(self.chat_panel.use_studies_check.isChecked())
        except Exception:
            use_studies = True

    if self.chat_worker and self.chat_worker.isRunning() and self.chat_worker.is_busy():
        self.chat_worker.cancel_current()
    self.stop_chat_worker()
    self.ensure_chat_worker_running(use_studies=use_studies)
    self.push_activity("module", f"Model profile set to {profile}")
    return True

def _runtime_model_snapshot(self):
    settings_map = self.read_settings()
    try:
        from config import settings as settings_module

        settings_map["DEFAULT_MODEL"] = str(getattr(settings_module, "DEFAULT_MODEL", settings_map.get("DEFAULT_MODEL", "--")))
        settings_map["MEMORY_MODEL"] = str(getattr(settings_module, "MEMORY_MODEL", settings_map.get("MEMORY_MODEL", "--")))
        settings_map["CODING_MODEL"] = str(getattr(settings_module, "CODING_MODEL", settings_map.get("CODING_MODEL", "--")))
        settings_map["DEFAULT_TEMP"] = str(getattr(settings_module, "DEFAULT_TEMP", settings_map.get("DEFAULT_TEMP", "0.4")))
        settings_map["VISION_MODEL"] = str(getattr(settings_module, "VISION_MODEL", settings_map.get("VISION_MODEL", "--")))
        settings_map["CODING_AGENT_PROFILE"] = str(
            getattr(settings_module, "CODING_AGENT_PROFILE", settings_map.get("CODING_AGENT_PROFILE", "coding_worker"))
        )
        settings_map["CODING_WORKSPACE_ROOT"] = str(
            getattr(settings_module, "CODING_WORKSPACE_ROOT", settings_map.get("CODING_WORKSPACE_ROOT", "workshop/tools/workspace/coding_mode"))
        )
        settings_map["CODING_SKILL_DRAFTS_ROOT"] = str(
            getattr(settings_module, "CODING_SKILL_DRAFTS_ROOT", settings_map.get("CODING_SKILL_DRAFTS_ROOT", "skills_local"))
        )
        settings_map["MODEL_CAPABILITY_PROFILE"] = str(
            getattr(settings_module, "ACTIVE_MODEL_CAPABILITY_PROFILE", self._effective_model_profile())
        )
    except Exception:
        settings_map["MODEL_CAPABILITY_PROFILE"] = self._effective_model_profile()
    return settings_map

def open_theme_selector(self):
    dialog = QDialog(self)
    dialog.setWindowTitle("Theme")
    dialog.resize(360, 170)
    dialog.setStyleSheet(dialog_stylesheet())

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Select interface theme:"))
    combo = QComboBox()
    options = list_themes()
    for key, label in options:
        combo.addItem(label, key)

    current = get_theme_name()
    for i, (key, _label) in enumerate(options):
        if key == current:
            combo.setCurrentIndex(i)
            break
    layout.addWidget(combo)

    buttons = QHBoxLayout()
    apply_btn = QPushButton("Apply")
    cancel_btn = QPushButton("Cancel")
    buttons.addWidget(apply_btn)
    buttons.addWidget(cancel_btn)
    layout.addLayout(buttons)

    def apply_theme_change():
        selected = combo.currentData()
        selected_name = str(selected or "default_dark")
        set_theme(selected_name)
        data = self.read_gui_settings()
        data["theme"] = selected_name
        self.write_gui_settings(data)
        self.apply_theme()
        self.push_activity("system", f"Theme changed to {combo.currentText()}")
        dialog.accept()

    apply_btn.clicked.connect(apply_theme_change)
    cancel_btn.clicked.connect(dialog.reject)
    dialog.exec()

def _sub_btn(self, text, callback):
    btn = QPushButton(text)
    btn.clicked.connect(callback)
    return btn

def read_settings(self):
    settings = {
        "DEFAULT_MODEL": "dolphin3",
        "MEMORY_MODEL": "codellama",
        "CODING_MODEL": "stable-code:3b",
        "DEFAULT_TEMP": "0.7",
        "VISION_MODEL": "Gemma3:4b",
        "CODING_AGENT_PROFILE": "coding_worker",
        "CODING_WORKSPACE_ROOT": "workshop/tools/workspace/coding_mode",
        "CODING_SKILL_DRAFTS_ROOT": "skills_local",
    }
    path = Path("config/settings.py")
    if not path.exists():
        return settings
    content = path.read_text(encoding="utf-8")
    for key in settings:
        m = re.search(rf"^{key}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\n#]+))", content, re.MULTILINE)
        if m:
            settings[key] = (m.group(1) or m.group(2) or m.group(3)).strip()
    return settings

def show_model_selections(self):
    try:
        settings = self._runtime_model_snapshot()
        profile = str(settings.get("MODEL_CAPABILITY_PROFILE", self._effective_model_profile()))
        profile_options = self._model_profile_options()
        model_window = QWidget()
        model_window.setWindowTitle("AI Model Selections")
        model_window.setGeometry(100, 100, 460, 380)
        model_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        layout = QVBoxLayout(model_window)
        layout.setSpacing(10)

        label = QLabel("Model Settings")
        layout.addWidget(label)

        profile_row = QWidget()
        profile_layout = QHBoxLayout(profile_row)
        profile_label = QLabel("Capability Profile:")
        profile_label.setFixedWidth(150)
        profile_combo = QComboBox()
        for name in profile_options:
            profile_combo.addItem(name, name)
        current_index = profile_combo.findData(profile)
        if current_index >= 0:
            profile_combo.setCurrentIndex(current_index)
        profile_layout.addWidget(profile_label)
        profile_layout.addWidget(profile_combo)
        layout.addWidget(profile_row)

        note = QLabel("Switching profile reloads model settings and restarts chat worker.")
        note.setWordWrap(True)
        layout.addWidget(note)

        model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "CODING_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
        for key in model_keys:
            value = settings.get(key, "Not set")
            frame = QWidget()
            frame_layout = QHBoxLayout(frame)
            key_label = QLabel(f"{key}:")
            key_label.setFixedWidth(150)
            value_label = QLabel(str(value))
            frame_layout.addWidget(key_label)
            frame_layout.addWidget(value_label)
            frame_layout.addStretch()
            layout.addWidget(frame)

        layout.addWidget(QLabel(f"CODING_AGENT_PROFILE: {settings.get('CODING_AGENT_PROFILE', 'coding_worker')}"))
        layout.addWidget(QLabel(f"CODING_WORKSPACE_ROOT: {settings.get('CODING_WORKSPACE_ROOT', 'workshop/tools/workspace/coding_mode')}"))
        layout.addWidget(QLabel(f"CODING_SKILL_DRAFTS_ROOT: {settings.get('CODING_SKILL_DRAFTS_ROOT', 'skills_local')}"))

        def apply_profile_change():
            selected_profile = str(profile_combo.currentData() or profile_combo.currentText() or "medium")
            ok = self.apply_model_profile(selected_profile)
            if ok:
                QMessageBox.information(model_window, "Success", f"Model profile set to '{selected_profile}'.")
                model_window.close()
                self.show_model_selections()
            else:
                QMessageBox.critical(model_window, "Error", "Failed to apply model profile.")

        apply_button = QPushButton("Apply Profile")
        apply_button.clicked.connect(apply_profile_change)
        layout.addWidget(apply_button)

        diagnostics_button = QPushButton("Run Diagnostics")
        diagnostics_button.clicked.connect(self.run_runtime_diagnostics)
        layout.addWidget(diagnostics_button)

        edit_button = QPushButton("Edit Settings")
        edit_button.clicked.connect(lambda: self.edit_model_settings(settings, model_window))
        layout.addWidget(edit_button)
        model_window.show()
        self.model_settings_window = model_window
        self.push_activity("module", "Opened model settings")
    except Exception as e:
        logger.error(f"Error showing model selections: {str(e)}")
        QMessageBox.critical(self, "Error", f"Failed to show model selections: {str(e)}")

def edit_model_settings(self, current_settings, parent_window):
    try:
        edit_window = QWidget()
        edit_window.setWindowTitle("Edit Model Settings")
        edit_window.setGeometry(120, 120, 440, 360)
        edit_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        layout = QVBoxLayout(edit_window)
        entries = {}
        model_keys = ["DEFAULT_MODEL", "MEMORY_MODEL", "CODING_MODEL", "DEFAULT_TEMP", "VISION_MODEL"]
        for key in model_keys:
            frame = QWidget()
            frame_layout = QHBoxLayout(frame)
            key_label = QLabel(f"{key}:")
            key_label.setFixedWidth(150)
            entry = QLineEdit()
            entry.setText(current_settings.get(key, ""))
            frame_layout.addWidget(key_label)
            frame_layout.addWidget(entry)
            entries[key] = entry
            layout.addWidget(frame)

        def save_settings():
            try:
                new_settings = {key: entry.text().strip() for key, entry in entries.items()}
                temp = float(new_settings["DEFAULT_TEMP"])
                if not 0.0 <= temp <= 1.0:
                    raise ValueError("DEFAULT_TEMP must be between 0.0 and 1.0")

                settings_path = Path("config/settings.py")
                if not settings_path.exists():
                    QMessageBox.critical(edit_window, "Error", "config/settings.py not found.")
                    return

                lines = settings_path.read_text(encoding="utf-8").splitlines(keepends=True)
                new_lines = []
                updated_keys = set()
                for line in lines:
                    stripped = line.strip()
                    replaced = False
                    for key, value in new_settings.items():
                        if stripped.startswith(f"{key} ="):
                            new_line = f"{key} = {value}\n" if key == "DEFAULT_TEMP" else f'{key} = "{value}"\n'
                            new_lines.append(new_line)
                            updated_keys.add(key)
                            replaced = True
                            break
                    if not replaced:
                        new_lines.append(line)

                for key, value in new_settings.items():
                    if key not in updated_keys:
                        new_lines.append(f"{key} = {value}\n" if key == "DEFAULT_TEMP" else f'{key} = "{value}"\n')

                settings_path.write_text("".join(new_lines), encoding="utf-8")
                self.output_area.append("Model settings updated successfully.")
                self.output_area.ensureCursorVisible()
                self.push_activity("module", "Updated model settings")
                QMessageBox.information(edit_window, "Success", "Model settings updated successfully!")
                edit_window.close()
                parent_window.close()
                self.show_model_selections()
            except ValueError as ve:
                QMessageBox.critical(edit_window, "Error", str(ve))
            except Exception as e:
                logger.error(f"Error saving settings: {str(e)}")
                QMessageBox.critical(edit_window, "Error", f"Failed to save settings: {str(e)}")

        save_button = QPushButton("Save")
        save_button.clicked.connect(save_settings)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(edit_window.close)
        layout.addWidget(save_button)
        layout.addWidget(cancel_button)
        edit_window.show()
        self.edit_settings_window = edit_window
    except Exception as e:
        logger.error(f"Error editing model settings: {str(e)}")
        QMessageBox.critical(self, "Error", f"Failed to edit model settings: {str(e)}")

def change_background(self):
    file_name, _ = QFileDialog.getOpenFileName(
        self,
        "Select Background Image",
        "",
        "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)",
    )
    if not file_name:
        return
    if not os.path.exists(file_name):
        QMessageBox.warning(self, "Error", "Selected image file does not exist.")
        return

    self._custom_background_path = file_name
    self.apply_theme()

    self.output_area.append(f"Background changed to {os.path.basename(file_name)}")
    self.output_area.ensureCursorVisible()
    self.push_activity("ui", "Background updated")

def read_help_file(self, filename):
    path = Path("workshop") / "help" / f"{filename}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else f"Help file '{filename}.txt' not found."

def show_help(self, section):
    content = self.read_help_file(section)
    if "not found" in content:
        QMessageBox.warning(self, "Error", content)
        return
    HelpWindow(self, f"Help - {section}", content).exec()
