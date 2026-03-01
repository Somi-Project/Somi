from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from executive.engine import ExecutiveEngine

try:
    from executive.life_modeling import list_goal_link_proposals, resolve_goal_link_proposal
except Exception:  # pragma: no cover
    list_goal_link_proposals = None
    resolve_goal_link_proposal = None


def _looks_like_proposal_id(value: str) -> bool:
    txt = str(value or "").strip()
    return txt.startswith("glp_") and len(txt) >= 8


def _parse_date(value: str) -> datetime | None:
    txt = str(value or "").strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt)
    except Exception:
        return None


class ExecutivePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = ExecutiveEngine()
        self._queue_rows: list[dict] = []
        layout = QVBoxLayout(self)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        now = QPushButton("Suggest intent")
        now.clicked.connect(self.suggest)

        refresh = QPushButton("Refresh goal-link queue")
        refresh.clicked.connect(self.refresh_goal_link_queue)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Text:"))
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("Filter by proposal/goal/project...")
        self.filter_text.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_text)

        filter_row.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["pending", "approved", "rejected", "all"])
        self.status_filter.currentTextChanged.connect(lambda _x: self.refresh_goal_link_queue())
        filter_row.addWidget(self.status_filter)

        filter_row.addWidget(QLabel("From (YYYY-MM-DD):"))
        self.date_from = QLineEdit()
        self.date_from.setPlaceholderText("2026-01-01")
        self.date_from.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.date_from)

        filter_row.addWidget(QLabel("To (YYYY-MM-DD):"))
        self.date_to = QLineEdit()
        self.date_to.setPlaceholderText("2026-12-31")
        self.date_to.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.date_to)

        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setHorizontalHeaderLabels(["Proposal", "Goal", "Project", "Status", "Created"])
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setSortingEnabled(True)
        self.queue_table.itemSelectionChanged.connect(self._sync_id_from_selection)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Proposal ID:"))
        self.proposal_id = QLineEdit()
        self.proposal_id.setPlaceholderText("Select a row or enter glp_xxxxx")
        self.proposal_id.textChanged.connect(self._update_action_buttons)
        controls.addWidget(self.proposal_id)

        self.approve_btn = QPushButton("Approve")
        self.approve_btn.clicked.connect(lambda: self.resolve_selected(True))
        self.reject_btn = QPushButton("Reject")
        self.reject_btn.clicked.connect(lambda: self.resolve_selected(False))
        controls.addWidget(self.approve_btn)
        controls.addWidget(self.reject_btn)

        layout.addWidget(now)
        layout.addWidget(refresh)
        layout.addLayout(filter_row)
        layout.addWidget(self.queue_table)
        layout.addLayout(controls)
        layout.addWidget(self.log)

        self._update_action_buttons()

    def suggest(self):
        self.log.append(str(self.engine.tick()))

    def _sync_id_from_selection(self):
        pid = self._selected_proposal_id()
        if pid:
            self.proposal_id.setText(pid)
        self._update_action_buttons()

    def _selected_proposal_id(self) -> str:
        rows = self.queue_table.selectionModel().selectedRows() if self.queue_table.selectionModel() else []
        if not rows:
            return ""
        row = rows[0].row()
        item = self.queue_table.item(row, 0)
        if item is not None:
            return str(item.text() or "").strip()
        return ""

    def _render_queue_rows(self, rows: list[dict]):
        self._queue_rows = list(rows or [])
        self.queue_table.setSortingEnabled(False)
        self.queue_table.setRowCount(len(self._queue_rows))
        for r, row in enumerate(self._queue_rows):
            vals = [
                str(row.get("proposal_id") or ""),
                str(row.get("goal_id") or ""),
                str(row.get("project_id") or ""),
                str(row.get("status") or "pending"),
                str(row.get("created_at") or ""),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.queue_table.setItem(r, c, item)
        self.queue_table.setSortingEnabled(True)
        self.queue_table.resizeColumnsToContents()
        self._apply_filter()

    def _apply_filter(self):
        query = str(self.filter_text.text() if self.filter_text else "").strip().lower()
        from_dt = _parse_date(self.date_from.text() if self.date_from else "")
        to_dt = _parse_date(self.date_to.text() if self.date_to else "")
        for r in range(self.queue_table.rowCount()):
            row_text = " | ".join(str((self.queue_table.item(r, c).text() if self.queue_table.item(r, c) else "")) for c in range(self.queue_table.columnCount())).lower()
            created_txt = str(self.queue_table.item(r, 4).text() if self.queue_table.item(r, 4) else "")
            created = _parse_date(created_txt.split("T")[0] if "T" in created_txt else created_txt)
            hide = False
            if query and query not in row_text:
                hide = True
            if not hide and from_dt and created and created.date() < from_dt.date():
                hide = True
            if not hide and to_dt and created and created.date() > to_dt.date():
                hide = True
            self.queue_table.setRowHidden(r, hide)

    def _update_action_buttons(self):
        pid = self._selected_proposal_id() or self.proposal_id.text().strip()
        enabled = _looks_like_proposal_id(pid)
        self.approve_btn.setEnabled(enabled)
        self.reject_btn.setEnabled(enabled)

    def refresh_goal_link_queue(self):
        if list_goal_link_proposals is None:
            self.log.append("Phase 7 queue unavailable.")
            self._render_queue_rows([])
            self._update_action_buttons()
            return
        st = str(self.status_filter.currentText() if self.status_filter else "pending")
        rows = list_goal_link_proposals(st) or []
        self._render_queue_rows(rows)
        self.log.append(f"Goal-link proposals ({st}): {len(rows)}")
        self._update_action_buttons()

    def resolve_selected(self, approved: bool):
        pid = self._selected_proposal_id() or self.proposal_id.text().strip()
        if not _looks_like_proposal_id(pid):
            self.log.append("Select a valid proposal row or enter a valid proposal id.")
            self._update_action_buttons()
            return
        if resolve_goal_link_proposal is None:
            self.log.append("Phase 7 queue resolver unavailable.")
            return
        ok = bool(resolve_goal_link_proposal(pid, approved=approved))
        self.log.append(f"{'Approved' if approved else 'Rejected'} {pid}: {'ok' if ok else 'not-found'}")
        self.refresh_goal_link_queue()
