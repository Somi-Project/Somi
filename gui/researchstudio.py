from __future__ import annotations

from gui.qt import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTextEdit, QTimer, QVBoxLayout, QWidget, Qt
from gui.researchstudio_data import ResearchStudioSnapshotBuilder


class ResearchStudioPanel(QWidget):
    def __init__(self, controller=None, snapshot_builder=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.snapshot_builder = snapshot_builder or getattr(controller, "research_studio_builder", None) or ResearchStudioSnapshotBuilder()
        self._job_rows: dict[str, dict] = {}
        self._export_rows: dict[str, dict] = {}
        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        hero = QFrame()
        hero.setObjectName("card")
        hero_layout = QVBoxLayout(hero)
        title_row = QHBoxLayout()
        title = QLabel("Research Studio")
        title.setObjectName("codingTitle")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("codingActionButton")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.refresh_button)
        subtitle = QLabel("Track long-running research, inspect evidence exports, and keep premium outputs close to the operator loop.")
        subtitle.setObjectName("codingSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addLayout(title_row)
        hero_layout.addWidget(subtitle)
        self.summary_label = QLabel("Active: -- | Jobs: -- | Exports: --")
        self.summary_label.setObjectName("codingChip")
        hero_layout.addWidget(self.summary_label)
        chip_row = QHBoxLayout()
        self.progress_chip = QLabel("Coverage: --")
        self.progress_chip.setObjectName("codingChip")
        self.memory_chip = QLabel("Memory: --")
        self.memory_chip.setObjectName("codingChip")
        self.graph_chip = QLabel("Graphs: 0")
        self.graph_chip.setObjectName("codingChip")
        chip_row.addWidget(self.progress_chip)
        chip_row.addWidget(self.memory_chip)
        chip_row.addWidget(self.graph_chip)
        hero_layout.addLayout(chip_row)
        self.active_detail_label = QLabel("No active research job right now.")
        self.active_detail_label.setObjectName("codingSubtitle")
        self.active_detail_label.setWordWrap(True)
        self.active_memory_label = QLabel("Recent browse pulse will appear here when there is no active long-running job.")
        self.active_memory_label.setObjectName("codingSubtitle")
        self.active_memory_label.setWordWrap(True)
        self.subagent_label = QLabel("Subagents: --")
        self.subagent_label.setObjectName("codingSubtitle")
        self.subagent_label.setWordWrap(True)
        hero_layout.addWidget(self.active_detail_label)
        hero_layout.addWidget(self.active_memory_label)
        hero_layout.addWidget(self.subagent_label)
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
        self.refresh_button.clicked.connect(self.refresh_data)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.refresh_timer.start(8000)

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
        progress = dict(row.get("progress") or {})
        coverage = dict(row.get("coverage") or {})
        if progress:
            lines.append(f"Progress: {progress.get('summary') or '--'}")
        if coverage:
            lines.append(f"Coverage: sources={coverage.get('source_count', 0)} contradictions={coverage.get('contradiction_count', 0)}")
        memory = dict(row.get("memory") or {})
        if memory:
            lines.append(f"Memory: {memory.get('summary') or '--'}")
        subagents = [dict(item) for item in list(row.get("subagents") or []) if isinstance(item, dict)]
        if subagents:
            lines.append("Subagents:")
            lines.extend(
                f"- {item.get('id') or '--'} | {item.get('status') or '--'} | {item.get('summary') or '--'}"
                for item in subagents[:6]
            )
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
            f"Active: {summary.get('active_job_id') or '--'} | Jobs: {summary.get('job_count', 0)} | Exports: {summary.get('export_count', 0)} | Graphs: {summary.get('graph_count', 0)}"
        )
        active_job = dict(snapshot.get("active_job") or {})
        progress_summary = str(summary.get("active_progress_summary") or "").strip()
        memory_summary = str(summary.get("active_memory_summary") or "").strip()
        subagent_summary = str(summary.get("active_subagent_summary") or "").strip()
        self.progress_chip.setText(f"Coverage: {progress_summary or '--'}")
        self.memory_chip.setText(f"Memory: {memory_summary or '--'}")
        self.graph_chip.setText(f"Graphs: {summary.get('graph_count', 0)}")
        if active_job:
            active_query = str(summary.get("active_query") or active_job.get("query") or "--").strip() or "--"
            active_status = str(summary.get("active_status") or active_job.get("status") or "--").strip() or "--"
            self.active_detail_label.setText(f"Active job `{active_status}`: {active_query}")
            self.active_memory_label.setText(memory_summary or "Memory summary is still warming up for this job.")
            self.subagent_label.setText(f"Subagents: {subagent_summary or '--'}")
        else:
            pulse = dict(getattr(self.controller, "state", {}).get("research_pulse") or {})
            pulse_query = str(pulse.get("query") or "").strip()
            if pulse_query:
                timeline = [str(item).strip() for item in list(pulse.get("timeline") or []) if str(item).strip()]
                sources = [str(item).strip() for item in list(pulse.get("source_preview") or []) if str(item).strip()]
                self.active_detail_label.setText(
                    f"Latest browse pulse: {str(pulse.get('mode') or 'browse').upper()} | {pulse_query}"
                )
                memory_line = str(pulse.get("summary") or "Somi condensed the latest browse pass into the premium pulse.")
                if sources:
                    memory_line = f"{memory_line} Sources: {' | '.join(sources[:2])}"
                self.active_memory_label.setText(memory_line)
                trace = [str(item).strip() for item in list(pulse.get("trace") or []) if str(item).strip()]
                trace_line = " | ".join(trace[:2]) if trace else str(pulse.get("progress_headline") or "--")
                if timeline:
                    trace_line = f"{trace_line} | Timeline: {' | '.join(timeline[:2])}"
                self.subagent_label.setText(f"Trace: {trace_line}")
            else:
                self.active_detail_label.setText("No active research job right now.")
                self.active_memory_label.setText("Recent browse pulse will appear here when there is no active long-running job.")
                self.subagent_label.setText("Subagents: --")
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
