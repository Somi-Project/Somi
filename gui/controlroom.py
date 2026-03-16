from __future__ import annotations

import json

from gui.qt import QApplication, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTextEdit, QTimer, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, Qt


class ControlRoomPanel(QWidget):
    TAB_ORDER = (
        ("config", "Config"),
        ("sessions", "Sessions"),
        ("tasks", "Tasks"),
        ("subagents", "Subagents"),
        ("workflows", "Workflows"),
        ("actions", "Actions"),
        ("artifacts", "Artifacts"),
        ("jobs", "Jobs"),
        ("automations", "Automations"),
        ("channels", "Channels"),
        ("memory", "Memory"),
        ("observability", "Observability"),
        ("errors", "Errors"),
    )

    def __init__(self, controller, snapshot_builder=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.snapshot_builder = snapshot_builder or getattr(controller, "control_room_builder", None)
        self.snapshot: dict = {}
        self._row_details: dict[str, dict[str, str]] = {}
        self._list_widgets: dict[str, QTreeWidget] = {}
        self._detail_widgets: dict[str, QTextEdit] = {}
        self._summary_labels: list[QLabel] = []
        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(7000)
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.refresh_timer.start()
        self.refresh_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Agent Studio / Control Room")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Inspect sessions, tasks, automations, channels, memory, and failures in one place.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("dialogSubtitle")
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        self.last_updated_label = QLabel("Updated: --")
        self.last_updated_label.setObjectName("metricsPill")
        self.refresh_button = QPushButton("Refresh")
        self.copy_button = QPushButton("Copy Snapshot")
        self.refresh_button.clicked.connect(self.refresh_data)
        self.copy_button.clicked.connect(self.copy_snapshot)
        header.addWidget(self.last_updated_label)
        header.addWidget(self.refresh_button)
        header.addWidget(self.copy_button)
        root.addLayout(header)

        summary_row = QHBoxLayout()
        for _ in range(6):
            chip = QLabel("--")
            chip.setObjectName("statusChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setMinimumHeight(38)
            self._summary_labels.append(chip)
            summary_row.addWidget(chip)
        root.addLayout(summary_row)

        self.tabs = QTabWidget()
        self.overview_text = QTextEdit()
        self.overview_text.setReadOnly(True)
        self.overview_text.setObjectName("controlOverview")
        self.tabs.addTab(self.overview_text, "Overview")

        for key, label in self.TAB_ORDER:
            page = QWidget()
            layout = QHBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)

            tree = QTreeWidget()
            tree.setObjectName("controlTree")
            tree.setColumnCount(4)
            tree.setHeaderLabels(["Name", "Status", "Updated", "Summary"])
            tree.itemSelectionChanged.connect(lambda current_key=key: self._update_detail(current_key))
            detail = QTextEdit()
            detail.setObjectName("controlDetail")
            detail.setReadOnly(True)

            layout.addWidget(tree, 5)
            layout.addWidget(detail, 6)
            self._list_widgets[key] = tree
            self._detail_widgets[key] = detail
            self.tabs.addTab(page, label)
        root.addWidget(self.tabs, 1)

    def _active_thread_id(self) -> str:
        panel = getattr(self.controller, "chat_panel", None)
        for attr in ("current_thread_id", "active_thread_id", "thread_id"):
            value = str(getattr(panel, attr, "") or "").strip()
            if value:
                return value
        return ""

    def _select_first_item(self, key: str) -> None:
        tree = self._list_widgets[key]
        if tree.topLevelItemCount() <= 0:
            return
        item = tree.topLevelItem(0)
        if item is not None:
            tree.setCurrentItem(item)

    def _update_detail(self, key: str) -> None:
        tree = self._list_widgets[key]
        detail = self._detail_widgets[key]
        selected = tree.selectedItems()
        if not selected:
            detail.setPlainText("No item selected.")
            return
        item_id = str(selected[0].data(0, Qt.ItemDataRole.UserRole) or "")
        detail.setPlainText(str(self._row_details.get(key, {}).get(item_id) or "No detail available."))

    def _populate_tab(self, key: str, rows: list[dict]) -> None:
        tree = self._list_widgets[key]
        tree.clear()
        self._row_details[key] = {}
        if not rows:
            placeholder = QTreeWidgetItem(["No data yet", "idle", "", "Waiting for this surface to produce state"])
            placeholder.setData(0, Qt.ItemDataRole.UserRole, "placeholder")
            tree.addTopLevelItem(placeholder)
            self._row_details[key]["placeholder"] = "No data is available for this control-room surface yet."
            self._select_first_item(key)
            return

        for row in rows:
            item = QTreeWidgetItem(
                [
                    str(row.get("title") or "Untitled"),
                    str(row.get("status") or ""),
                    str(row.get("updated_at") or ""),
                    str(row.get("subtitle") or ""),
                ]
            )
            item_id = str(row.get("id") or row.get("title") or "row")
            item.setData(0, Qt.ItemDataRole.UserRole, item_id)
            tree.addTopLevelItem(item)
            self._row_details[key][item_id] = str(row.get("detail") or "")
        for col in range(4):
            tree.resizeColumnToContents(col)
        self._select_first_item(key)

    def refresh_data(self):
        if self.snapshot_builder is None:
            self.overview_text.setPlainText("Control-room snapshot builder is not configured.")
            return
        try:
            snapshot = self.snapshot_builder.build(
                user_id="default_user",
                thread_id=self._active_thread_id(),
                agent_name=str(self.controller._selected_agent_name()),
                model_snapshot=dict(self.controller._runtime_model_snapshot()),
            )
        except Exception as exc:
            self.overview_text.setPlainText(f"Failed to refresh control room: {type(exc).__name__}: {exc}")
            return

        self.snapshot = dict(snapshot or {})
        self.last_updated_label.setText(f"Updated: {self.snapshot.get('updated_at', '--')}")
        self.overview_text.setPlainText(str(self.snapshot.get("overview_text") or "No overview available."))

        cards = list(self.snapshot.get("summary_cards") or [])
        for idx, chip in enumerate(self._summary_labels):
            if idx < len(cards):
                card = cards[idx]
                chip.setText(f"{card.get('label', '--')}\n{card.get('value', '--')} | {card.get('hint', '')}")
            else:
                chip.setText("--")

        tabs = dict(self.snapshot.get("tabs") or {})
        for key, _label in self.TAB_ORDER:
            self._populate_tab(key, list(tabs.get(key) or []))

    def copy_snapshot(self):
        payload = json.dumps(self.snapshot or {}, ensure_ascii=False, indent=2, sort_keys=True)
        QApplication.clipboard().setText(payload)
