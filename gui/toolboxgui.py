from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit, QCheckBox, QComboBox

from jobs.engine import JobsEngine
from gui.stepstream import GuiStepSink


class ToolboxPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sink = GuiStepSink()
        self.layout = QVBoxLayout(self)
        self.mode = QComboBox(); self.mode.addItems(["fast", "standard", "quality"])
        self.active = QCheckBox("ACTIVE mode")
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.start = QPushButton("Start Job")
        self.start.clicked.connect(self.start_job)
        for w in [self.mode, self.active, self.start, self.log]: self.layout.addWidget(w)

    def start_job(self):
        out = JobsEngine().run_create_tool("hello_tool", "Returns greeting + system time", self.mode.currentText(), self.active.isChecked(), self.sink)
        self.log.append(str(out))
