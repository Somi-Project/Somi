from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit

from executive.engine import ExecutiveEngine


class ExecutivePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = ExecutiveEngine()
        layout = QVBoxLayout(self)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        now = QPushButton("Suggest intent")
        now.clicked.connect(self.suggest)
        layout.addWidget(now); layout.addWidget(self.log)

    def suggest(self):
        self.log.append(str(self.engine.tick()))
