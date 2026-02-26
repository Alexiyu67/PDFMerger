"""Main window — UI shell for PDFJoiner."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdfjoiner.model import SUPPORTED_EXTENSIONS, FileEntry, ProjectModel
from pdfjoiner.service import MergeService


def _file_filter() -> str:
    """Build a file dialog filter string from supported extensions."""
    exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
    return f"Supported files ({exts});;PDF files (*.pdf);;Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif);;All files (*)"


class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFJoiner")
        self.setMinimumSize(900, 600)

        # ── Model ──────────────────────────────────────────────
        self._model = ProjectModel(self)
        self._model.list_changed.connect(self._on_list_changed)

        # ── Build UI ───────────────────────────────────────────
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        # Initial state
        self._update_status()

    # ══════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        self._act_add_files = QAction("Add Files", self)
        self._act_add_files.setShortcut(QKeySequence("Ctrl+O"))
        self._act_add_files.setToolTip("Add PDF or image files (Ctrl+O)")
        self._act_add_files.triggered.connect(self._on_add_files)
        tb.addAction(self._act_add_files)

        self._act_add_folder = QAction("Add Folder", self)
        self._act_add_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self._act_add_folder.setToolTip("Add all supported files from a folder (Ctrl+Shift+O)")
        self._act_add_folder.triggered.connect(self._on_add_folder)
        tb.addAction(self._act_add_folder)

        tb.addSeparator()

        self._act_remove = QAction("Remove", self)
        self._act_remove.setShortcut(QKeySequence.StandardKey.Delete)
        self._act_remove.setToolTip("Remove selected files from list")
        self._act_remove.triggered.connect(self._on_remove)
        tb.addAction(self._act_remove)

        tb.addSeparator()

        self._act_move_up = QAction("▲ Up", self)
        self._act_move_up.setShortcut(QKeySequence("Ctrl+Up"))
        self._act_move_up.setToolTip("Move selected file up (Ctrl+Up)")
        self._act_move_up.triggered.connect(self._on_move_up)
        tb.addAction(self._act_move_up)

        self._act_move_down = QAction("▼ Down", self)
        self._act_move_down.setShortcut(QKeySequence("Ctrl+Down"))
        self._act_move_down.setToolTip("Move selected file down (Ctrl+Down)")
        self._act_move_down.triggered.connect(self._on_move_down)
        tb.addAction(self._act_move_down)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # ── Splitter: file list (left) | preview placeholder (right) ──
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self._splitter, stretch=1)

        # Left panel — file list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_label = QLabel("Files to merge:")
        left_layout.addWidget(list_label)

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_list.setAlternatingRowColors(True)
        self._file_list.itemChanged.connect(self._on_item_checked)
        self._file_list.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._file_list)

        self._splitter.addWidget(left)

        # Right panel — preview placeholder (Step 5)
        self._preview_placeholder = QLabel("Select a file to preview")
        self._preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_placeholder.setMinimumWidth(300)
        self._preview_placeholder.setStyleSheet("background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 4px;")
        self._splitter.addWidget(self._preview_placeholder)

        self._splitter.setSizes([400, 500])

        # ── Bottom bar: output name + save ─────────────────────
        bottom = QHBoxLayout()
        root_layout.addLayout(bottom)

        bottom.addWidget(QLabel("Output file:"))

        self._output_name = QLineEdit("merged.pdf")
        self._output_name.setPlaceholderText("merged.pdf")
        self._output_name.setMinimumWidth(250)
        bottom.addWidget(self._output_name, stretch=1)

        self._btn_save = QPushButton("Save Merged PDF")
        self._btn_save.setShortcut(QKeySequence("Ctrl+S"))
        self._btn_save.setToolTip("Merge included files and save (Ctrl+S)")
        self._btn_save.clicked.connect(self._on_save)
        bottom.addWidget(self._btn_save)

    def _build_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

    # ══════════════════════════════════════════════════════════
    # File list synchronisation
    # ══════════════════════════════════════════════════════════

    def _on_list_changed(self) -> None:
        """Rebuild the QListWidget from the model."""
        # Remember current selection
        current_row = self._file_list.currentRow()

        # Block signals while rebuilding to avoid triggering itemChanged
        self._file_list.blockSignals(True)
        self._file_list.clear()

        for entry in self._model.entries:
            item = QListWidgetItem()
            item.setText(self._format_entry(entry))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if entry.included else Qt.CheckState.Unchecked
            )
            # Gray out excluded files
            if not entry.included:
                item.setForeground(QColor(160, 160, 160))
            self._file_list.addItem(item)

        self._file_list.blockSignals(False)

        # Restore selection
        if 0 <= current_row < self._file_list.count():
            self._file_list.setCurrentRow(current_row)
        elif self._file_list.count() > 0:
            self._file_list.setCurrentRow(min(current_row, self._file_list.count() - 1))

        self._update_status()

    def _format_entry(self, entry: FileEntry) -> str:
        """Format display text for a file entry."""
        suffix = entry.path.suffix.upper().lstrip(".")
        if entry.is_pdf:
            pages = MergeService.get_page_count(entry.path)
            return f"{entry.filename}  [{suffix}, {pages} page{'s' if pages != 1 else ''}]"
        return f"{entry.filename}  [{suffix}]"

    def _update_status(self) -> None:
        total = len(self._model)
        included = len(self._model.included_entries())
        if total == 0:
            self._statusbar.showMessage("No files added. Use 'Add Files' or 'Add Folder' to begin.")
        else:
            self._statusbar.showMessage(f"{total} file(s) — {included} included for merge")

    # ══════════════════════════════════════════════════════════
    # Toolbar actions
    # ══════════════════════════════════════════════════════════

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Files", "", _file_filter()
        )
        if paths:
            added = self._model.add_files([Path(p) for p in paths])
            if added == 0:
                self._statusbar.showMessage("No new files added (duplicates or unsupported).", 3000)

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add Folder")
        if folder:
            added = self._model.add_folder(Path(folder))
            if added == 0:
                self._statusbar.showMessage("No supported files found in folder.", 3000)

    def _on_remove(self) -> None:
        indices = sorted(set(idx.row() for idx in self._file_list.selectedIndexes()), reverse=True)
        if indices:
            self._model.remove(indices)

    def _on_move_up(self) -> None:
        row = self._file_list.currentRow()
        if row > 0:
            self._model.move_up(row)
            self._file_list.setCurrentRow(row - 1)

    def _on_move_down(self) -> None:
        row = self._file_list.currentRow()
        if 0 <= row < len(self._model) - 1:
            self._model.move_down(row)
            self._file_list.setCurrentRow(row + 1)

    # ══════════════════════════════════════════════════════════
    # Checkbox handling
    # ══════════════════════════════════════════════════════════

    def _on_item_checked(self, item: QListWidgetItem) -> None:
        """Sync checkbox state back to the model."""
        row = self._file_list.row(item)
        if row < 0 or row >= len(self._model):
            return
        is_checked = item.checkState() == Qt.CheckState.Checked
        self._model.set_included(row, is_checked)

    # ══════════════════════════════════════════════════════════
    # Selection (preview hook for Step 5)
    # ══════════════════════════════════════════════════════════

    def _on_selection_changed(self, row: int) -> None:
        """Called when the user clicks a different row. Preview hook for Step 5."""
        if 0 <= row < len(self._model):
            entry = self._model[row]
            self._preview_placeholder.setText(f"Preview: {entry.filename}\n(coming in Step 5)")
        else:
            self._preview_placeholder.setText("Select a file to preview")

    # ══════════════════════════════════════════════════════════
    # Save / merge
    # ══════════════════════════════════════════════════════════

    def _on_save(self) -> None:
        included = self._model.included_entries()
        if not included:
            QMessageBox.warning(self, "Nothing to merge", "No files are included for merging.")
            return

        # Determine output filename
        name = self._output_name.text().strip()
        if not name:
            name = "merged.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"

        # Ask where to save
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Merged PDF", name, "PDF files (*.pdf)"
        )
        if not path:
            return

        try:
            total = MergeService.merge(self._model.entries, Path(path))
            self._statusbar.showMessage(f"Saved {total} page(s) to {Path(path).name}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Merge failed", str(exc))
