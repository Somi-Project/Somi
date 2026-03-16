from __future__ import annotations

from gui.qt import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QTextEdit, QVBoxLayout, QWidget, Qt


class ResearchStudioPanel(QWidget):
    def __init__(self, controller=None, snapshot_builder=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.snapshot_builder = snapshot_builder or getattr(controller, "research_studio_builder", None)
        self._job_rows: dict[str, dict] = {}
        self._export_rows: dict[str, dict] = {}
        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        hero = QFrame()
        hero.setObjectName("card")
        hero_layout = QVBoxLayout(hero)
        title = QLabel("Research Studio")
        title.setObjectName("codingTitle")
        subtitle = QLabel("Track long-running research, inspect evidence exports, and keep premium outputs close to the operator loop.")
        subtitle.setObjectName("codingSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        self.summary_label = QLabel("Active: -- | Jobs: -- | Exports: --")
        self.summary_label.setObjectName("codingChip")
        hero_layout.addWidget(self.summary_label)
        root.addWidget(hero)

        split = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Research Jobs"))
        self.jobs_list = QListWidget()
        self.jobs_list.setObjectName("codingList")
        left.addWidget(self.jobs_list, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Exports"))
        self.exports_list = QListWidget()
        self.exports_list.setObjectName("codingList")
        right.addWidget(self.exports_list, 1)
        split.addLayout(left, 1)
        split.addLayout(right, 1)
        root.addLayout(split, 1)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setObjectName("codingConsole")
        root.addWidget(self.detail)

        self.jobs_list.itemSelectionChanged.connect(self._show_job_detail)
        self.exports_list.itemSelectionChanged.connect(self._show_export_detail)

    def _coding_user_id(self) -> str:
        return str(getattr(self.controller, "coding_user_id", "default_user") or "default_user").strip() or "default_user"

    def _show_job_detail(self) -> None:
        selected = self.jobs_list.selectedItems()
        if not selected:
            return
        item_id = str(selected[0].data(Qt.ItemDataRole.UserRole) or "")
        row = dict(self._job_rows.get(item_id) or {})
        lines = [
            f"Job: {row.get('job_id') or '--'}",
            f"Status: {row.get('status') or '--'}",
            f"Query: {row.get('query') or '--'}",
            f"Updated: {row.get('updated_at') or row.get('created_at') or '--'}",
        ]
        coverage = dict(row.get("coverage") or {})
        if coverage:
            lines.append(f"Coverage: sources={coverage.get('source_count', 0)} contradictions={coverage.get('contradiction_count', 0)}")
        self.detail.setPlainText("\n".join(lines))

    def _show_export_detail(self) -> None:
        selected = self.exports_list.selectedItems()
        if not selected:
            return
        item_id = str(selected[0].data(Qt.ItemDataRole.UserRole) or "")
        row = dict(self._export_rows.get(item_id) or {})
        self.detail.setPlainText(f"{row.get('name')}\n{row.get('path')}\nKind: {row.get('kind')}")

    def refresh_data(self) -> None:
        if self.snapshot_builder is None:
            self.detail.setPlainText("Research studio snapshot builder is not configured.")
            return
        snapshot = dict(self.snapshot_builder.build(user_id=self._coding_user_id()) or {})
        summary = dict(snapshot.get("summary") or {})
        self.summary_label.setText(
            f"Active: {summary.get('active_job_id') or '--'} | Jobs: {summary.get('job_count', 0)} | Exports: {summary.get('export_count', 0)}"
        )
        self.jobs_list.clear()
        self.exports_list.clear()
        self._job_rows = {}
        self._export_rows = {}
        for row in list(snapshot.get("jobs") or []):
            item_id = str(row.get("job_id") or "")
            item = QListWidgetItem(f"{row.get('status') or '--'} | {row.get('query') or item_id}")
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.jobs_list.addItem(item)
            self._job_rows[item_id] = dict(row)
        for row in list(snapshot.get("exports") or []):
            item_id = str(row.get("path") or "")
            item = QListWidgetItem(f"{row.get('kind')} | {row.get('name')}")
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.exports_list.addItem(item)
            self._export_rows[item_id] = dict(row)
        if self.jobs_list.count() > 0:
            self.jobs_list.setCurrentRow(0)
        elif self.exports_list.count() > 0:
            self.exports_list.setCurrentRow(0)
        else:
            self.detail.setPlainText("No research jobs or exports are available yet.")
