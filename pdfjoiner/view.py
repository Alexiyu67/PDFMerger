"""Main window — UI shell for PDFJoiner."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QLabel


class MainWindow(QMainWindow):
    """Application main window. Expanded in later steps."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFJoiner")
        self.setMinimumSize(900, 600)

        # Placeholder — replaced with real layout in Step 4
        placeholder = QLabel("PDFJoiner — ready for Step 2+", self)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(placeholder)
