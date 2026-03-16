from __future__ import annotations

from gui.qt import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
)


class ToolboxPanel(QWidget):
    def __init__(self, controller=None):
        super().__init__(controller if isinstance(controller, QWidget) else None)
        self.controller = controller
        self.snapshot_builder = getattr(controller, "coding_studio_builder", None)
        self.start_here_service = getattr(controller, "start_here_service", None)
        self.skill_marketplace_service = getattr(controller, "skill_marketplace_service", None)
        self._starter_rows: dict[str, dict] = {}
        self._marketplace_rows: dict[str, dict] = {}
        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("codingHero")
        hero_layout = QVBoxLayout(hero)
        title = QLabel("Toolbox Command Deck")
        title.setObjectName("codingTitle")
        subtitle = QLabel("Launch coding work, inspect the live workspace, and hand precise build tasks back into Somi's coding agent.")
        subtitle.setObjectName("codingSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)

        chip_row = QHBoxLayout()
        self.session_label = QLabel("Session: --")
        self.profile_label = QLabel("Profile: --")
        self.workspace_label = QLabel("Workspace: --")
        self.runtime_label = QLabel("Runtimes: --")
        self.health_label = QLabel("Health: --")
        for label in [self.session_label, self.profile_label, self.workspace_label, self.runtime_label, self.health_label]:
            label.setObjectName("codingChip")
            chip_row.addWidget(label)
        hero_layout.addLayout(chip_row)

        prompt_row = QHBoxLayout()
        self.prompt_entry = QLineEdit()
        self.prompt_entry.setObjectName("codingPromptEntry")
        self.prompt_entry.setPlaceholderText("Describe a coding task, bugfix, scaffold, or file change...")
        self.send_button = QPushButton("Send To Coding Chat")
        self.send_button.setObjectName("codingPromptButton")
        self.open_button = QPushButton("Open Coding Studio")
        self.refresh_button = QPushButton("Refresh")
        prompt_row.addWidget(self.prompt_entry, 1)
        prompt_row.addWidget(self.send_button)
        prompt_row.addWidget(self.open_button)
        hero_layout.addLayout(prompt_row)
        root.addWidget(hero)

        starter_card = QFrame()
        starter_card.setObjectName("card")
        starter_layout = QVBoxLayout(starter_card)
        starter_title = QLabel("Start Here")
        starter_title.setObjectName("codingSectionTitle")
        starter_subtitle = QLabel("Pick a guided recipe, template, or bundle instead of starting from a blank page.")
        starter_subtitle.setObjectName("codingSubtitle")
        starter_subtitle.setWordWrap(True)
        starter_layout.addWidget(starter_title)
        starter_layout.addWidget(starter_subtitle)

        starter_split = QHBoxLayout()
        self.starter_list = QListWidget()
        self.starter_list.setObjectName("codingList")
        self.starter_detail = QTextEdit()
        self.starter_detail.setReadOnly(True)
        self.starter_detail.setObjectName("codingConsole")
        self.starter_detail.setMinimumHeight(150)
        starter_split.addWidget(self.starter_list, 4)
        starter_split.addWidget(self.starter_detail, 6)
        starter_layout.addLayout(starter_split)

        starter_button_row = QHBoxLayout()
        self.use_starter_button = QPushButton("Use Starter Prompt")
        self.open_starter_button = QPushButton("Open Surface")
        for button in [self.use_starter_button, self.open_starter_button]:
            button.setObjectName("codingActionButton")
            starter_button_row.addWidget(button)
        starter_layout.addLayout(starter_button_row)
        root.addWidget(starter_card)

        marketplace_card = QFrame()
        marketplace_card.setObjectName("card")
        marketplace_layout = QVBoxLayout(marketplace_card)
        marketplace_title = QLabel("Skill Marketplace")
        marketplace_title.setObjectName("codingSectionTitle")
        marketplace_subtitle = QLabel("Discover trusted skill packages, inspect compatibility, and recover cleanly with rollback if an update misbehaves.")
        marketplace_subtitle.setObjectName("codingSubtitle")
        marketplace_subtitle.setWordWrap(True)
        marketplace_layout.addWidget(marketplace_title)
        marketplace_layout.addWidget(marketplace_subtitle)

        marketplace_split = QHBoxLayout()
        self.marketplace_list = QListWidget()
        self.marketplace_list.setObjectName("codingList")
        self.marketplace_detail = QTextEdit()
        self.marketplace_detail.setReadOnly(True)
        self.marketplace_detail.setObjectName("codingConsole")
        self.marketplace_detail.setMinimumHeight(150)
        marketplace_split.addWidget(self.marketplace_list, 4)
        marketplace_split.addWidget(self.marketplace_detail, 6)
        marketplace_layout.addLayout(marketplace_split)

        marketplace_button_row = QHBoxLayout()
        self.marketplace_refresh_button = QPushButton("Refresh Market")
        self.marketplace_install_button = QPushButton("Install / Update")
        self.marketplace_disable_button = QPushButton("Disable Skill")
        self.marketplace_rollback_button = QPushButton("Rollback")
        for button in [
            self.marketplace_refresh_button,
            self.marketplace_install_button,
            self.marketplace_disable_button,
            self.marketplace_rollback_button,
        ]:
            button.setObjectName("codingActionButton")
            marketplace_button_row.addWidget(button)
        marketplace_layout.addLayout(marketplace_button_row)
        root.addWidget(marketplace_card)

        summary_card = QFrame()
        summary_card.setObjectName("card")
        summary_layout = QVBoxLayout(summary_card)
        summary_title = QLabel("Session Brief")
        summary_title.setObjectName("codingSectionTitle")
        summary_layout.addWidget(summary_title)
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("codingConsole")
        self.summary.setMinimumHeight(170)
        summary_layout.addWidget(self.summary)
        root.addWidget(summary_card)

        action_card = QFrame()
        action_card.setObjectName("card")
        action_layout = QVBoxLayout(action_card)
        action_title = QLabel("Quick Actions")
        action_title.setObjectName("codingSectionTitle")
        action_layout.addWidget(action_title)
        button_row = QHBoxLayout()
        self.check_button = QPushButton("Run Check")
        self.verify_button = QPushButton("Verify Loop")
        self.bootstrap_button = QPushButton("Bootstrap")
        self.skill_button = QPushButton("Draft Skill")
        self.folder_button = QPushButton("Open Folder")
        for button in [self.refresh_button, self.check_button, self.verify_button, self.bootstrap_button, self.skill_button, self.folder_button]:
            button.setObjectName("codingActionButton")
            button_row.addWidget(button)
        action_layout.addLayout(button_row)
        root.addWidget(action_card)

        streams_card = QFrame()
        streams_card.setObjectName("card")
        streams_layout = QHBoxLayout(streams_card)

        runtime_col = QVBoxLayout()
        runtime_title = QLabel("Runtime Inventory")
        runtime_title.setObjectName("codingSectionTitle")
        self.runtime_list = QListWidget()
        self.runtime_list.setObjectName("codingList")
        runtime_col.addWidget(runtime_title)
        runtime_col.addWidget(self.runtime_list, 1)

        file_col = QVBoxLayout()
        file_title = QLabel("Workspace Files")
        file_title.setObjectName("codingSectionTitle")
        self.files_list = QListWidget()
        self.files_list.setObjectName("codingList")
        file_col.addWidget(file_title)
        file_col.addWidget(self.files_list, 1)

        streams_layout.addLayout(runtime_col, 1)
        streams_layout.addLayout(file_col, 1)
        root.addWidget(streams_card, 1)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_title = QLabel("Action Log")
        log_title.setObjectName("codingSectionTitle")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("codingConsole")
        self.log.setMinimumHeight(140)
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log)
        root.addWidget(log_card)

        self.open_button.clicked.connect(lambda: self._call_controller("open_coding_studio"))
        self.refresh_button.clicked.connect(self.refresh_data)
        self.check_button.clicked.connect(lambda: self._call_controller("run_coding_profile_check"))
        self.verify_button.clicked.connect(lambda: self._call_controller("run_coding_verify_loop"))
        self.bootstrap_button.clicked.connect(lambda: self._call_controller("bootstrap_coding_workspace"))
        self.skill_button.clicked.connect(lambda: self._call_controller("draft_coding_skill"))
        self.folder_button.clicked.connect(lambda: self._call_controller("open_coding_workspace_folder"))
        self.send_button.clicked.connect(self._send_prompt)
        self.prompt_entry.returnPressed.connect(self._send_prompt)
        self.files_list.itemDoubleClicked.connect(self._queue_file_prompt)
        self.starter_list.itemSelectionChanged.connect(self._update_starter_detail)
        self.use_starter_button.clicked.connect(self._use_starter_prompt)
        self.open_starter_button.clicked.connect(self._open_starter_surface)
        self.marketplace_list.itemSelectionChanged.connect(self._update_marketplace_detail)
        self.marketplace_refresh_button.clicked.connect(self._refresh_marketplace)
        self.marketplace_install_button.clicked.connect(self._install_marketplace_package)
        self.marketplace_disable_button.clicked.connect(self._disable_marketplace_skill)
        self.marketplace_rollback_button.clicked.connect(self._rollback_marketplace_skill)

    def _coding_user_id(self) -> str:
        return str(getattr(self.controller, "coding_user_id", "default_user") or "default_user").strip() or "default_user"

    def _call_controller(self, name: str) -> None:
        handler = getattr(self.controller, name, None)
        if not callable(handler):
            self.log.append(f"{name} is unavailable.")
            return
        try:
            result = handler()
            if isinstance(result, dict):
                self.log.append(str(result))
        except Exception as exc:
            self.log.append(f"{name} failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _send_prompt(self) -> None:
        prompt = self.prompt_entry.text().strip()
        if not prompt:
            self.log.append("Enter a coding task first.")
            return
        handler = getattr(self.controller, "send_coding_prompt", None)
        if not callable(handler):
            self.log.append("send_coding_prompt is unavailable.")
            return
        try:
            result = handler(prompt)
            self.log.append(str(result or f"Sent coding prompt: {prompt}"))
            self.prompt_entry.clear()
        except Exception as exc:
            self.log.append(f"send_coding_prompt failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _queue_file_prompt(self, item: QListWidgetItem) -> None:
        relative_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if relative_path:
            self.prompt_entry.setText(f"Inspect {relative_path} and continue the coding task.")

    def _selected_starter(self) -> dict:
        selected = self.starter_list.selectedItems()
        if not selected:
            return {}
        item_id = str(selected[0].data(Qt.ItemDataRole.UserRole) or "")
        return dict(self._starter_rows.get(item_id) or {})

    def _selected_marketplace(self) -> dict:
        selected = self.marketplace_list.selectedItems()
        if not selected:
            return {}
        item_id = str(selected[0].data(Qt.ItemDataRole.UserRole) or "")
        return dict(self._marketplace_rows.get(item_id) or {})

    def _update_starter_detail(self) -> None:
        row = self._selected_starter()
        if not row:
            self.starter_detail.setPlainText("Select a recipe, template, or bundle to see the guided path.")
            return
        lines = [
            f"{row.get('name')}",
            f"Kind: {row.get('kind')}",
            f"Primary surface: {row.get('primary_surface') or ', '.join(list(row.get('best_for') or [])[:2]) or 'chat'}",
            "",
            str(row.get("description") or "").strip(),
        ]
        guide_steps = [str(item) for item in list(row.get("guide_steps") or []) if str(item).strip()]
        if guide_steps:
            lines.append("")
            lines.append("Guide steps:")
            for step in guide_steps[:4]:
                lines.append(f"- {step}")
        quick_actions = [str(item) for item in list(row.get("quick_actions") or []) if str(item).strip()]
        if quick_actions:
            lines.append("")
            lines.append("Quick actions:")
            for action in quick_actions[:4]:
                lines.append(f"- {action}")
        prompt = str(row.get("starter_prompt") or "").strip()
        if prompt:
            lines.append("")
            lines.append("Starter prompt:")
            lines.append(prompt)
        self.starter_detail.setPlainText("\n".join(line for line in lines if line is not None).strip())

    def _use_starter_prompt(self) -> None:
        row = self._selected_starter()
        prompt = str(row.get("starter_prompt") or "").strip()
        if not prompt:
            self.log.append("This starter does not have a suggested prompt yet.")
            return
        self.prompt_entry.setText(prompt)
        self.log.append(f"Loaded starter prompt from {row.get('name')}.")

    def _open_starter_surface(self) -> None:
        row = self._selected_starter()
        surface = str(row.get("primary_surface") or "").strip().lower()
        mapping = {
            "coding_studio": "open_coding_studio",
            "control_room": "open_control_room",
            "chat": "open_chat",
            "gui": "open_chat",
        }
        handler = getattr(self.controller, mapping.get(surface, "open_chat"), None)
        if callable(handler):
            try:
                handler()
                self.log.append(f"Opened {surface or 'chat'} for {row.get('name')}.")
            except Exception as exc:
                self.log.append(f"Failed to open {surface or 'chat'}: {type(exc).__name__}: {exc}")
        else:
            self.log.append(f"No surface handler is available for {surface or 'chat'}.")

    def _update_marketplace_detail(self) -> None:
        row = self._selected_marketplace()
        if not row:
            self.marketplace_detail.setPlainText("Select a skill package to inspect trust, compatibility, bundles, and rollback readiness.")
            return
        compatibility = dict(row.get("compatibility") or {})
        security = dict(row.get("security") or {})
        bundle_rows = [dict(item) for item in list(row.get("bundle_rows") or []) if isinstance(item, dict)]
        lines = [
            f"{row.get('name')}",
            f"Package: {row.get('package_id')}",
            f"Skill key: {row.get('skill_key')}",
            f"Status: {row.get('status')}",
            f"Trust: {row.get('trust_badge')}",
            f"Channel: {row.get('update_channel')}",
            f"Version: {row.get('installed_version') or '--'} -> {row.get('version') or '--'}",
            "",
            str(row.get("description") or "").strip(),
            "",
            f"Compatibility: {'ready' if compatibility.get('ok') else 'blocked'}",
            str(compatibility.get("summary") or "").strip(),
            f"Security: critical={security.get('critical', 0)} warn={security.get('warn', 0)} info={security.get('info', 0)}",
            f"Rollback available: {'yes' if row.get('rollback_available') else 'no'}",
        ]
        if bundle_rows:
            lines.append("")
            lines.append("Bundles:")
            for item in bundle_rows[:4]:
                lines.append(f"- {item.get('bundle_id')}: {item.get('name')}")
        homepage = str(row.get("homepage") or "").strip()
        if homepage:
            lines.append("")
            lines.append(f"Homepage: {homepage}")
        self.marketplace_detail.setPlainText("\n".join(line for line in lines if line is not None).strip())

    def _install_marketplace_package(self) -> None:
        row = self._selected_marketplace()
        if not row:
            self.log.append("Select a marketplace package first.")
            return
        service = self.skill_marketplace_service
        if service is None:
            self.log.append("Skill marketplace service is unavailable.")
            return
        try:
            result = service.install_package(str(row.get("package_id") or ""), actor=self._coding_user_id())
            install = dict(result.get("install") or {})
            self.log.append(f"Installed {row.get('package_id')} -> {install.get('skill_key')}.")
        except Exception as exc:
            self.log.append(f"Marketplace install failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _disable_marketplace_skill(self) -> None:
        row = self._selected_marketplace()
        if not row:
            self.log.append("Select an installed marketplace skill first.")
            return
        service = self.skill_marketplace_service
        if service is None:
            self.log.append("Skill marketplace service is unavailable.")
            return
        skill_key = str(row.get("skill_key") or "").strip()
        if not skill_key:
            self.log.append("This package does not map to a tracked skill key.")
            return
        try:
            state = service.manager.set_enabled(skill_key, False, actor=self._coding_user_id())
            self.log.append(f"Disabled {skill_key}: enabled={state.get('enabled')}.")
        except Exception as exc:
            self.log.append(f"Disable failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _rollback_marketplace_skill(self) -> None:
        row = self._selected_marketplace()
        if not row:
            self.log.append("Select a package with an installed skill first.")
            return
        service = self.skill_marketplace_service
        if service is None:
            self.log.append("Skill marketplace service is unavailable.")
            return
        skill_key = str(row.get("skill_key") or "").strip()
        if not skill_key:
            self.log.append("This package does not map to a tracked skill key.")
            return
        try:
            result = service.rollback_package(skill_key, actor=self._coding_user_id())
            rollback = dict(result.get("rollback") or {})
            self.log.append(f"Rolled back {skill_key} from {rollback.get('restored_from')}.")
        except Exception as exc:
            self.log.append(f"Rollback failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _refresh_start_here(self) -> None:
        self.starter_list.clear()
        self._starter_rows = {}
        if self.start_here_service is None:
            self.starter_detail.setPlainText("Start-here guidance is not configured.")
            return
        snapshot = dict(self.start_here_service.build_snapshot() or {})
        rows = []
        rows.extend(list(snapshot.get("featured_recipes") or []))
        rows.extend(list(snapshot.get("agent_templates") or [])[:3])
        rows.extend(list(snapshot.get("workflow_templates") or [])[:2])
        rows.extend(list(snapshot.get("recommended_bundles") or [])[:3])
        for row in rows:
            item_id = f"{row.get('kind', 'starter')}:{row.get('id', row.get('name', 'starter'))}"
            label = f"{str(row.get('kind') or 'starter').replace('_', ' ').title()} | {row.get('name')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.starter_list.addItem(item)
            self._starter_rows[item_id] = dict(row)
        if self.starter_list.count() > 0:
            self.starter_list.setCurrentRow(0)
        else:
            self.starter_detail.setPlainText("No starter guides are available yet.")

    def _refresh_marketplace(self) -> None:
        self.marketplace_list.clear()
        self._marketplace_rows = {}
        service = self.skill_marketplace_service
        if service is None:
            self.marketplace_detail.setPlainText("Skill marketplace is not configured.")
            return
        persona = str(getattr(self.controller, "selected_agent_key", "") or "").replace("Name: ", "").strip().lower()
        snapshot = dict(service.build_snapshot(persona=persona, force_refresh=True) or {})
        for row in list(snapshot.get("items") or []):
            item_id = str(row.get("package_id") or row.get("skill_key") or "")
            label = f"{row.get('status')} | {row.get('trust_badge')} | {row.get('name')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.marketplace_list.addItem(item)
            self._marketplace_rows[item_id] = dict(row)
        if self.marketplace_list.count() > 0:
            self.marketplace_list.setCurrentRow(0)
        else:
            self.marketplace_detail.setPlainText("No marketplace packages are available yet.")

    def refresh_data(self) -> None:
        if self.snapshot_builder is None:
            self.summary.setPlainText("Coding snapshot builder is not configured.")
            self._refresh_start_here()
            self._refresh_marketplace()
            return
        try:
            snapshot = dict(self.snapshot_builder.build(user_id=self._coding_user_id()) or {})
        except Exception as exc:
            self.summary.setPlainText(f"Failed to load coding toolbox snapshot: {type(exc).__name__}: {exc}")
            self._refresh_start_here()
            self._refresh_marketplace()
            return

        session = dict(snapshot.get("session") or {})
        workspace = dict(snapshot.get("workspace") or {})
        skill_hint = dict(snapshot.get("skill_hint") or {})
        health = dict(snapshot.get("health") or {})
        scorecard = dict(snapshot.get("scorecard") or {})
        benchmark_pack = dict(snapshot.get("benchmark_pack") or {})
        self.session_label.setText(f"Session: {session.get('session_id') or '--'}")
        self.profile_label.setText(f"Profile: {workspace.get('profile_display_name') or workspace.get('profile_key') or '--'}")
        self.workspace_label.setText(f"Workspace: {workspace.get('root_path') or '--'}")
        available_runtimes = [str(row.get("key") or "") for row in list(snapshot.get("runtime_rows") or []) if bool(row.get("available"))]
        self.runtime_label.setText(f"Runtimes: {', '.join(available_runtimes[:4]) if available_runtimes else '--'}")
        self.health_label.setText(f"Health: {health.get('status') or scorecard.get('status') or '--'}")

        lines = [str(session.get("welcome_text") or "").strip()]
        next_actions = [str(x) for x in list(snapshot.get("next_actions") or []) if str(x).strip()]
        if next_actions:
            lines.append("Next actions:")
            for item in next_actions[:3]:
                lines.append(f"- {item}")
        if skill_hint.get("capability"):
            lines.append(f"Skill expansion hint: {skill_hint.get('capability')}")
        markers = [str(dict(row).get("path") or "") for row in list(snapshot.get("workspace_markers") or []) if str(dict(row).get("path") or "").strip()]
        if markers:
            lines.append(f"Workspace markers: {', '.join(markers[:5])}")
        if health.get("summary"):
            lines.append(f"Environment: {health.get('summary')}")
        if scorecard.get("summary"):
            lines.append(f"Verify loop: {scorecard.get('summary')}")
        if benchmark_pack.get("label"):
            lines.append(f"Benchmark pack: {benchmark_pack.get('label')} [{benchmark_pack.get('profile_key') or '--'}]")
        self.summary.setPlainText("\n".join(line for line in lines if line).strip() or "No active coding session yet.")
        self.runtime_list.clear()
        for row in list(snapshot.get("runtime_rows") or []):
            label = str(row.get("label") or row.get("key") or "runtime")
            version = str(row.get("version") or "").strip()
            state = "ready" if bool(row.get("available")) else "missing"
            parts = [label]
            if version:
                parts.append(version)
            parts.append(state)
            self.runtime_list.addItem(QListWidgetItem(" | ".join(parts)))
        if self.runtime_list.count() == 0:
            self.runtime_list.addItem(QListWidgetItem("No runtime inventory is available yet."))

        self.files_list.clear()
        file_rows = list(snapshot.get("workspace_files") or [])
        if file_rows:
            for row in file_rows[:25]:
                item = QListWidgetItem(f"{row.get('path')}  [{row.get('kind')}]")
                item.setData(Qt.ItemDataRole.UserRole, str(row.get("path") or ""))
                self.files_list.addItem(item)
        else:
            for path in list(snapshot.get("recent_files") or [])[:12]:
                item = QListWidgetItem(str(path))
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.files_list.addItem(item)
        if self.files_list.count() == 0:
            self.files_list.addItem(QListWidgetItem("No workspace files to show yet."))
        self._refresh_start_here()
        self._refresh_marketplace()
