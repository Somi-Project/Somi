from PyQt6.QtWidgets import QDialog, QVBoxLayout


class ChatPopoutWindow(QDialog):
    def __init__(self, app, chat_panel):
        super().__init__(app)
        self.app = app
        self.chat_panel = chat_panel
        self.setWindowTitle("SOMI — Chat")
        self.resize(860, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(chat_panel)

    def closeEvent(self, event):
        self.app.dock_chat_panel()
        event.accept()
