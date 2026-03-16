from __future__ import annotations

from datetime import datetime
from typing import Any

from gui.qt import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
)


class CodingStudioPanel(QWidget):
    def __init__(self, controller, snapshot_builder=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.snapshot_builder = snapshot_builder or getattr(controller, "coding_studio_builder", None)
        self.snapshot: dict[str, Any] = {}
        self._build_ui()
        self.refresh_data()

    def _coding_user_id(self) -> str:
        return str(getattr(self.controller, "coding_user_id", "default_user") or "default_user").strip() or "default_user"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("codingHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setSpacing(8)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Coding Studio")
        title.setObjectName("codingTitle")
        subtitle = QLabel("Local coding workspace for planning, scaffolding, runtime checks, and safe self-expansion.")
        subtitle.setObjectName("codingSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        head.addLayout(title_box, 1)

        self.refresh_button = QPushButton("Refresh")
        self.open_folder_button = QPushButton("Open Folder")
        self.run_check_button = QPushButton("Run Check")
        self.verify_button = QPushButton("Verify Loop")
        self.bootstrap_button = QPushButton("Bootstrap")
        self.draft_skill_button = QPushButton("Draft Skill")
        for button in [
            self.refresh_button,
            self.open_folder_button,
            self.run_check_button,
            self.verify_button,
            self.bootstrap_button,
            self.draft_skill_button,
        ]:
            button.setObjectName("codingActionButton")
            head.addWidget(button)
        hero_layout.addLayout(head)

        chips = QHBoxLayout()
        self.session_chip = QLabel("Session: --")
        self.profile_chip = QLabel("Profile: --")
        self.runtime_chip = QLabel("Runtimes: --")
        self.health_chip = QLabel("Health: --")
        self.workspace_chip = QLabel("Workspace: --")
        self.skill_chip = QLabel("Skill: --")
        self.job_chip = QLabel("Job: --")
        for chip in [self.session_chip, self.profile_chip, self.runtime_chip, self.health_chip, self.workspace_chip, self.skill_chip, self.job_chip]:
            chip.setObjectName("codingChip")
            chips.addWidget(chip)
        hero_layout.addLayout(chips)
        root.addWidget(hero)

        prompt_row = QHBoxLayout()
        self.task_entry = QLineEdit()
        self.task_entry.setObjectName("codingPromptEntry")
        self.task_entry.setPlaceholderText("Describe a coding task, patch, scaffold, or bug to work on...")
        self.send_button = QPushButton("Send To Coding Chat")
        self.send_button.setObjectName("codingPromptButton")
        self.open_chat_button = QPushButton("Open Chat")
        self.open_chat_button.setObjectName("codingActionButton")
        prompt_row.addWidget(self.task_entry, 1)
        prompt_row.addWidget(self.send_button)
        prompt_row.addWidget(self.open_chat_button)
        root.addLayout(prompt_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.welcome_title = QLabel("Welcome State")
        self.welcome_title.setObjectName("codingSectionTitle")
        self.welcome_text = QTextEdit()
        self.welcome_text.setObjectName("codingConsole")
        self.welcome_text.setReadOnly(True)
        left_layout.addWidget(self.welcome_title)
        left_layout.addWidget(self.welcome_text, 3)

        self.next_actions_title = QLabel("Next Actions")
        self.next_actions_title.setObjectName("codingSectionTitle")
        self.next_actions_list = QListWidget()
        self.next_actions_list.setObjectName("codingList")
        left_layout.addWidget(self.next_actions_title)
        left_layout.addWidget(self.next_actions_list, 2)

        self.runtime_title = QLabel("Runtime Inventory")
        self.runtime_title.setObjectName("codingSectionTitle")
        self.runtime_list = QListWidget()
        self.runtime_list.setObjectName("codingList")
        left_layout.addWidget(self.runtime_title)
        left_layout.addWidget(self.runtime_list, 2)

        self.repo_title = QLabel("Repo Focus")
        self.repo_title.setObjectName("codingSectionTitle")
        self.repo_list = QListWidget()
        self.repo_list.setObjectName("codingList")
        left_layout.addWidget(self.repo_title)
        left_layout.addWidget(self.repo_list, 2)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        self.files_title = QLabel("Workspace Files")
        self.files_title.setObjectName("codingSectionTitle")
        self.files_list = QListWidget()
        self.files_list.setObjectName("codingList")
        middle_layout.addWidget(self.files_title)
        middle_layout.addWidget(self.files_list, 3)

        self.commands_title = QLabel("Suggested Commands")
        self.commands_title.setObjectName("codingSectionTitle")
        self.commands_list = QListWidget()
        self.commands_list.setObjectName("codingList")
        middle_layout.addWidget(self.commands_title)
        middle_layout.addWidget(self.commands_list, 2)

        self.starters_title = QLabel("Starter Files")
        self.starters_title.setObjectName("codingSectionTitle")
        self.starter_files_list = QListWidget()
        self.starter_files_list.setObjectName("codingList")
        middle_layout.addWidget(self.starters_title)
        middle_layout.addWidget(self.starter_files_list, 2)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.sessions_title = QLabel("Recent Sessions")
        self.sessions_title.setObjectName("codingSectionTitle")
        self.sessions_list = QListWidget()
        self.sessions_list.setObjectName("codingList")
        right_layout.addWidget(self.sessions_title)
        right_layout.addWidget(self.sessions_list, 2)

        self.health_title = QLabel("Health and Score")
        self.health_title.setObjectName("codingSectionTitle")
        self.health_list = QListWidget()
        self.health_list.setObjectName("codingList")
        right_layout.addWidget(self.health_title)
        right_layout.addWidget(self.health_list, 2)

        self.job_title = QLabel("Job Scorecard")
        self.job_title.setObjectName("codingSectionTitle")
        self.job_list = QListWidget()
        self.job_list.setObjectName("codingList")
        right_layout.addWidget(self.job_title)
        right_layout.addWidget(self.job_list, 2)

        self.log_title = QLabel("Action Log")
        self.log_title.setObjectName("codingSectionTitle")
        self.log = QTextEdit()
        self.log.setObjectName("codingConsole")
        self.log.setReadOnly(True)
        right_layout.addWidget(self.log_title)
        right_layout.addWidget(self.log, 3)

        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 4)
        root.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_data)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.run_check_button.clicked.connect(self._run_check)
        self.verify_button.clicked.connect(self._run_verify)
        self.bootstrap_button.clicked.connect(self._bootstrap)
        self.draft_skill_button.clicked.connect(self._draft_skill)
        self.send_button.clicked.connect(self._send_prompt)
        self.open_chat_button.clicked.connect(self._open_chat)
        self.task_entry.returnPressed.connect(self._send_prompt)
        self.files_list.itemDoubleClicked.connect(self._queue_file_prompt)
        self.commands_list.itemDoubleClicked.connect(self._copy_command_to_prompt)
        self.starter_files_list.itemDoubleClicked.connect(self._queue_file_prompt)

    def append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")

    @staticmethod
    def _runtime_label(row: dict[str, Any]) -> str:
        label = str(row.get("label") or row.get("key") or "runtime")
        version = str(row.get("version") or "").strip()
        state = "ready" if bool(row.get("available")) else "missing"
        path = str(row.get("path") or "").strip()
        bits = [label]
        if version:
            bits.append(version)
        bits.append(state)
        if path:
            bits.append(path)
        return " | ".join(bits)

    def refresh_data(self) -> None:
        if self.snapshot_builder is None:
            self.welcome_text.setPlainText("Coding studio snapshot builder is not configured.")
            return
        try:
            self.snapshot = dict(self.snapshot_builder.build(user_id=self._coding_user_id()) or {})
        except Exception as exc:
            self.welcome_text.setPlainText(f"Failed to refresh coding studio: {type(exc).__name__}: {exc}")
            return

        session = dict(self.snapshot.get("session") or {})
        workspace = dict(self.snapshot.get("workspace") or {})
        runtime_rows = [dict(row) for row in list(self.snapshot.get("runtime_rows") or [])]
        runtimes = [str(row.get("key") or "") for row in runtime_rows if bool(row.get("available")) and str(row.get("key") or "").strip()]
        skill_hint = dict(self.snapshot.get("skill_hint") or {})
        health = dict(self.snapshot.get("health") or {})
        scorecard = dict(self.snapshot.get("scorecard") or {})
        benchmark_pack = dict(self.snapshot.get("benchmark_pack") or {})
        repo_map = dict(self.snapshot.get("repo_map") or {})
        active_job = dict(self.snapshot.get("active_job") or {})
        coding_memory = dict(self.snapshot.get("coding_memory") or {})

        self.session_chip.setText(f"Session: {session.get('session_id') or '--'}")
        self.profile_chip.setText(f"Profile: {workspace.get('profile_display_name') or workspace.get('profile_key') or '--'}")
        self.runtime_chip.setText(f"Runtimes: {', '.join(runtimes[:4]) if runtimes else '--'}")
        self.health_chip.setText(f"Health: {health.get('status') or scorecard.get('status') or '--'}")
        self.workspace_chip.setText(f"Workspace: {workspace.get('root_path') or '--'}")
        self.skill_chip.setText(f"Skill: {skill_hint.get('capability') or '--'}")
        self.job_chip.setText(f"Job: {active_job.get('status') or '--'}")

        welcome_blocks = [str(session.get("welcome_text") or "").strip()]
        if workspace.get("root_path"):
            welcome_blocks.append(f"Workspace root: {workspace.get('root_path')}")
        if workspace.get("run_command"):
            welcome_blocks.append(f"Run command: {workspace.get('run_command')}")
        if workspace.get("test_command"):
            welcome_blocks.append(f"Check command: {workspace.get('test_command')}")
        if health.get("summary"):
            welcome_blocks.append(f"Environment: {health.get('summary')}")
        if scorecard.get("summary"):
            welcome_blocks.append(f"Verify loop: {scorecard.get('summary')}")
        if repo_map.get("summary"):
            welcome_blocks.append(f"Repo map: {repo_map.get('summary')}")
        if coding_memory.get("summary"):
            welcome_blocks.append(f"Context memory: {coding_memory.get('summary')}")
        if benchmark_pack.get("label"):
            welcome_blocks.append(f"Benchmark pack: {benchmark_pack.get('label')} [{benchmark_pack.get('profile_key') or '--'}]")
        self.welcome_text.setPlainText("\n".join(block for block in welcome_blocks if block).strip() or "No active coding session yet.")

        self.next_actions_list.clear()
        for item in list(self.snapshot.get("next_actions") or []):
            self.next_actions_list.addItem(QListWidgetItem(str(item)))
        if self.next_actions_list.count() == 0:
            self.next_actions_list.addItem(QListWidgetItem("Open or start a coding session to populate next actions."))

        self.runtime_list.clear()
        for row in runtime_rows:
            item = QListWidgetItem(self._runtime_label(row))
            item.setData(Qt.ItemDataRole.UserRole, str(row.get("key") or ""))
            self.runtime_list.addItem(item)
        if self.runtime_list.count() == 0:
            self.runtime_list.addItem(QListWidgetItem("No runtime inventory is available yet."))

        existing_repo_items: set[str] = set()
        self.repo_list.clear()
        for item in list(repo_map.get("focus_files") or [])[:10]:
            label = str(item)
            self.repo_list.addItem(QListWidgetItem(label))
            existing_repo_items.add(label)
        for row in list(repo_map.get("hotspot_files") or [])[:4]:
            label = f"{row.get('path')}  [imports={len(list(row.get('imports') or []))}]"
            if label not in existing_repo_items:
                self.repo_list.addItem(QListWidgetItem(label))
        if self.repo_list.count() == 0:
            self.repo_list.addItem(QListWidgetItem("No repo focus has been calculated yet."))

        self.files_list.clear()
        for row in list(self.snapshot.get("workspace_files") or [])[:30]:
            label = f"{row.get('path')}  [{row.get('kind')}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(row.get("path") or ""))
            self.files_list.addItem(item)
        if self.files_list.count() == 0:
            self.files_list.addItem(QListWidgetItem("No workspace files to show yet."))

        self.commands_list.clear()
        for command in list(self.snapshot.get("suggested_commands") or []):
            item = QListWidgetItem(str(command))
            item.setData(Qt.ItemDataRole.UserRole, str(command))
            self.commands_list.addItem(item)
        if self.commands_list.count() == 0:
            self.commands_list.addItem(QListWidgetItem("No suggested commands yet."))

        self.starter_files_list.clear()
        for path in list(self.snapshot.get("starter_files") or []):
            item = QListWidgetItem(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.starter_files_list.addItem(item)
        if self.starter_files_list.count() == 0:
            self.starter_files_list.addItem(QListWidgetItem("No starter file hints yet."))

        self.sessions_list.clear()
        for row in list(self.snapshot.get("recent_sessions") or []):
            self.sessions_list.addItem(
                QListWidgetItem(f"{row.get('title')}  [{row.get('profile')}]  {row.get('status')}  {row.get('updated_at')}")
            )
        if self.sessions_list.count() == 0:
            self.sessions_list.addItem(QListWidgetItem("No prior coding sessions yet."))

        self.health_list.clear()
        if health.get("summary"):
            self.health_list.addItem(QListWidgetItem(f"Environment: {health.get('summary')}"))
        if scorecard.get("summary"):
            self.health_list.addItem(QListWidgetItem(f"Scorecard: {scorecard.get('summary')}"))
        for row in list(health.get("recommendations") or [])[:3]:
            self.health_list.addItem(QListWidgetItem(f"Next: {row}"))
        if benchmark_pack.get("label"):
            self.health_list.addItem(QListWidgetItem(f"Benchmark: {benchmark_pack.get('label')} [{benchmark_pack.get('profile_key')}]"))
        if self.health_list.count() == 0:
            self.health_list.addItem(QListWidgetItem("Health and verification details will appear here."))

        self.job_list.clear()
        job_score = dict(active_job.get("scorecard") or {})
        if active_job.get("job_id"):
            self.job_list.addItem(QListWidgetItem(f"Job: {active_job.get('job_id')} [{active_job.get('status')}]"))
        if job_score.get("summary"):
            self.job_list.addItem(QListWidgetItem(f"Score: {job_score.get('summary')}"))
        for row in list(job_score.get("next_actions") or [])[:3]:
            self.job_list.addItem(QListWidgetItem(f"Next: {row}"))
        if self.job_list.count() == 0:
            self.job_list.addItem(QListWidgetItem("Job loop metrics will appear here once work starts."))

    def _run_action(self, action: str) -> None:
        handler = {
            "run_check": getattr(self.controller, "run_coding_profile_check", None),
            "run_verify": getattr(self.controller, "run_coding_verify_loop", None),
            "bootstrap": getattr(self.controller, "bootstrap_coding_workspace", None),
            "draft_skill": getattr(self.controller, "draft_coding_skill", None),
            "open_folder": getattr(self.controller, "open_coding_workspace_folder", None),
        }.get(action)
        if not callable(handler):
            self.append_log(f"{action} is not available.")
            return
        try:
            result = handler()
            if isinstance(result, dict):
                self.append_log(str(result))
            elif isinstance(result, str) and result:
                self.append_log(result)
        except Exception as exc:
            self.append_log(f"{action} failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _run_check(self) -> None:
        self._run_action("run_check")

    def _run_verify(self) -> None:
        self._run_action("run_verify")

    def _bootstrap(self) -> None:
        self._run_action("bootstrap")

    def _draft_skill(self) -> None:
        self._run_action("draft_skill")

    def _open_folder(self) -> None:
        self._run_action("open_folder")

    def _send_prompt(self) -> None:
        prompt = self.task_entry.text().strip()
        if not prompt:
            return
        handler = getattr(self.controller, "send_coding_prompt", None)
        if not callable(handler):
            self.append_log("send_coding_prompt is not available.")
            return
        try:
            result = handler(prompt)
            self.append_log(str(result or f"Sent coding prompt: {prompt}"))
            self.task_entry.clear()
        except Exception as exc:
            self.append_log(f"send failed: {type(exc).__name__}: {exc}")
        self.refresh_data()

    def _open_chat(self) -> None:
        handler = getattr(self.controller, "open_chat", None)
        if callable(handler):
            handler()
            self.append_log("Opened chat surface.")

    def _queue_file_prompt(self, item: QListWidgetItem) -> None:
        relative_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if relative_path:
            self.task_entry.setText(f"Inspect {relative_path} and continue the coding task.")

    def _copy_command_to_prompt(self, item: QListWidgetItem) -> None:
        command = str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()
        if not command:
            return
        self.task_entry.setText(f"Use this as the next light check if appropriate: {command}")
        QApplication.clipboard().setText(command)


class CodingStudioWindow(QDialog):
    def __init__(self, controller, snapshot_builder=None, parent=None):
        super().__init__(parent or controller)
        self.setWindowTitle("Coding Studio")
        self.resize(1220, 760)
        layout = QVBoxLayout(self)
        self.panel = CodingStudioPanel(controller, snapshot_builder=snapshot_builder, parent=self)
        layout.addWidget(self.panel)

    def refresh_data(self) -> None:
        self.panel.refresh_data()
