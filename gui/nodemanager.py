from __future__ import annotations

from gui.qt import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTextEdit, QVBoxLayout, QWidget, Qt


class NodeManagerPanel(QWidget):
    def __init__(self, controller=None, snapshot_builder=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.snapshot_builder = snapshot_builder or getattr(controller, "node_manager_builder", None)
        self.gateway_service = getattr(controller, "gateway_service", None)
        self._node_rows: dict[str, dict] = {}
        self._audit_rows: dict[str, dict] = {}
        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        hero = QFrame()
        hero.setObjectName("card")
        hero_layout = QVBoxLayout(hero)
        title = QLabel("Node Manager")
        title.setObjectName("codingTitle")
        subtitle = QLabel("Manage paired nodes, inspect remote-action audit, and rotate or revoke access without leaving the desktop shell.")
        subtitle.setObjectName("codingSubtitle")
        subtitle.setWordWrap(True)
        self.summary_label = QLabel("Nodes: -- | Audit: -- | Tokens: --")
        self.summary_label.setObjectName("codingChip")
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        hero_layout.addWidget(self.summary_label)
        root.addWidget(hero)

        split = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Nodes"))
        self.nodes_list = QListWidget()
        self.nodes_list.setObjectName("codingList")
        left.addWidget(self.nodes_list, 1)
        buttons = QHBoxLayout()
        self.rotate_button = QPushButton("Rotate Token")
        self.revoke_button = QPushButton("Revoke Node")
        for button in [self.rotate_button, self.revoke_button]:
            button.setObjectName("codingActionButton")
            buttons.addWidget(button)
        left.addLayout(buttons)
        right = QVBoxLayout()
        right.addWidget(QLabel("Remote Audit"))
        self.audit_list = QListWidget()
        self.audit_list.setObjectName("codingList")
        right.addWidget(self.audit_list, 1)
        split.addLayout(left, 1)
        split.addLayout(right, 1)
        root.addLayout(split, 1)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setObjectName("codingConsole")
        root.addWidget(self.detail)

        self.nodes_list.itemSelectionChanged.connect(self._show_node_detail)
        self.audit_list.itemSelectionChanged.connect(self._show_audit_detail)
        self.rotate_button.clicked.connect(self._rotate_selected_node)
        self.revoke_button.clicked.connect(self._revoke_selected_node)

    def _selected_node(self) -> dict:
        selected = self.nodes_list.selectedItems()
        if not selected:
            return {}
        return dict(self._node_rows.get(str(selected[0].data(Qt.ItemDataRole.UserRole) or "")) or {})

    def _show_node_detail(self) -> None:
        row = self._selected_node()
        if not row:
            self.detail.setPlainText("Select a node to inspect trust, scopes, and capability state.")
            return
        lines = [
            f"Node: {row.get('client_label') or row.get('node_id')}",
            f"Type: {row.get('node_type')}",
            f"Status: {row.get('status')}",
            f"Trust: {row.get('trust_level')}",
            f"Platform: {row.get('platform')}",
            f"Capabilities: {', '.join(list(row.get('capabilities') or [])[:8]) or '--'}",
        ]
        self.detail.setPlainText("\n".join(lines))

    def _show_audit_detail(self) -> None:
        selected = self.audit_list.selectedItems()
        if not selected:
            return
        row = dict(self._audit_rows.get(str(selected[0].data(Qt.ItemDataRole.UserRole) or "")) or {})
        self.detail.setPlainText(
            "\n".join(
                [
                    f"Action: {row.get('action')}",
                    f"Outcome: {row.get('outcome')}",
                    f"Reason: {row.get('reason')}",
                    f"Capability: {row.get('capability') or '--'}",
                    f"Path: {row.get('requested_path') or '--'}",
                    f"Created: {row.get('created_at') or '--'}",
                ]
            )
        )

    def _rotate_selected_node(self) -> None:
        row = self._selected_node()
        if self.gateway_service is None or not row:
            return
        result = self.gateway_service.rotate_node_token(str(row.get("node_id") or ""), actor="desktop_ui")
        self.detail.setPlainText(f"Rotated token for {row.get('node_id')}.\nPreview: {result.get('token_preview')}")
        self.refresh_data()

    def _revoke_selected_node(self) -> None:
        row = self._selected_node()
        if self.gateway_service is None or not row:
            return
        self.gateway_service.revoke_node(str(row.get("node_id") or ""), actor="desktop_ui", reason="desktop node manager revoke")
        self.refresh_data()

    def refresh_data(self) -> None:
        if self.snapshot_builder is None:
            self.detail.setPlainText("Node manager snapshot builder is not configured.")
            return
        snapshot = dict(self.snapshot_builder.build() or {})
        summary = dict(snapshot.get("summary") or {})
        self.summary_label.setText(
            f"Nodes: {summary.get('node_count', 0)} | Audit: {summary.get('audit_count', 0)} | Tokens: {summary.get('token_count', 0)}"
        )
        self.nodes_list.clear()
        self.audit_list.clear()
        self._node_rows = {}
        self._audit_rows = {}
        for row in list(snapshot.get("nodes") or []):
            item_id = str(row.get("node_id") or "")
            item = QListWidgetItem(f"{row.get('status')} | {row.get('client_label') or item_id}")
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.nodes_list.addItem(item)
            self._node_rows[item_id] = dict(row)
        for row in list(snapshot.get("audit") or []):
            item_id = str(row.get("audit_id") or "")
            item = QListWidgetItem(f"{row.get('outcome')} | {row.get('action')} | {row.get('reason')}")
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.audit_list.addItem(item)
            self._audit_rows[item_id] = dict(row)
        if self.nodes_list.count() > 0:
            self.nodes_list.setCurrentRow(0)
        elif self.audit_list.count() > 0:
            self.audit_list.setCurrentRow(0)
        else:
            self.detail.setPlainText("No nodes are registered yet.")
