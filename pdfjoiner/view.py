"""Main window — UI shell for PDFJoiner."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QColor, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
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


# ══════════════════════════════════════════════════════════════
# Preview panel widget
# ══════════════════════════════════════════════════════════════


class PreviewPanel(QFrame):
    """Right-side panel that shows file previews and merged previews.

    Supports two modes:
    - Single file: shows one page at a time with page navigation for PDFs.
    - Merged preview: shows all pages stacked vertically in a scrollable area.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setStyleSheet("PreviewPanel { background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; }")

        self._current_path: Optional[Path] = None
        self._current_page: int = 0
        self._page_count: int = 0
        self._merged_mode: bool = False

        self._build_ui()
        self._show_placeholder()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Header: title + mode label ─────────────────────────
        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self._title)

        # ── Scroll area for preview image(s) ───────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(self._scroll, stretch=1)

        # Container inside scroll area (holds one or many page labels)
        self._page_container = QWidget()
        self._page_layout = QVBoxLayout(self._page_container)
        self._page_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._page_layout.setSpacing(12)
        self._scroll.setWidget(self._page_container)

        # ── Page navigation bar ────────────────────────────────
        nav = QHBoxLayout()
        layout.addLayout(nav)

        self._btn_prev = QPushButton("◀ Prev")
        self._btn_prev.clicked.connect(self._go_prev)
        nav.addWidget(self._btn_prev)

        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._page_label, stretch=1)

        self._btn_next = QPushButton("Next ▶")
        self._btn_next.clicked.connect(self._go_next)
        nav.addWidget(self._btn_next)

    # ── Public API ─────────────────────────────────────────────

    def show_file(self, path: Path) -> None:
        """Show a single-file preview with page navigation."""
        self._merged_mode = False
        self._current_path = path
        self._current_page = 0
        self._page_count = MergeService.get_page_count(path)
        self._title.setText(path.name)
        self._render_single_page()
        self._update_nav()

    def show_merged(self, entries: List[FileEntry]) -> None:
        """Show a merged preview of all included files, all pages stacked."""
        self._merged_mode = True
        self._current_path = None

        included = [e for e in entries if e.included]
        if not included:
            self._show_placeholder("No included files to preview.")
            return

        self._title.setText(f"Merged preview — {len(included)} file(s)")
        self._clear_pages()

        pixmaps = MergeService.render_merged_preview(
            entries, max_width=self._preview_width(), max_height=800
        )

        if not pixmaps:
            self._show_placeholder("Could not render merged preview.")
            return

        for i, pix in enumerate(pixmaps):
            page_label = QLabel()
            page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            page_label.setPixmap(pix)
            self._page_layout.addWidget(page_label)

            # Page number label
            num_label = QLabel(f"— Page {i + 1} —")
            num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num_label.setStyleSheet("color: #888; font-size: 11px;")
            self._page_layout.addWidget(num_label)

        self._page_count = len(pixmaps)
        self._current_page = 0
        self._page_label.setText(f"{self._page_count} page(s)")
        self._btn_prev.setVisible(False)
        self._btn_next.setVisible(False)

    def show_placeholder(self, text: str = "Select a file to preview") -> None:
        """Public wrapper for the placeholder state."""
        self._show_placeholder(text)

    # ── Internal rendering ─────────────────────────────────────

    def _render_single_page(self) -> None:
        """Render the current page of the current file."""
        self._clear_pages()

        if self._current_path is None:
            return

        pix = MergeService.render_preview(
            self._current_path,
            page=self._current_page,
            max_width=self._preview_width(),
            max_height=800,
        )

        if pix is None:
            err = QLabel("Could not render this file.")
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._page_layout.addWidget(err)
            return

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setPixmap(pix)
        self._page_layout.addWidget(img_label)

    def _show_placeholder(self, text: str = "Select a file to preview") -> None:
        """Reset to placeholder state."""
        self._merged_mode = False
        self._current_path = None
        self._current_page = 0
        self._page_count = 0
        self._title.setText("")
        self._clear_pages()

        placeholder = QLabel(text)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #999; font-size: 14px; padding: 40px;")
        self._page_layout.addWidget(placeholder)

        self._btn_prev.setVisible(False)
        self._btn_next.setVisible(False)
        self._page_label.setText("")

    def _clear_pages(self) -> None:
        """Remove all widgets from the page container."""
        while self._page_layout.count():
            child = self._page_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _preview_width(self) -> int:
        """Available width for rendering, accounting for margins and scrollbar."""
        return max(self._scroll.viewport().width() - 20, 200)

    # ── Page navigation ────────────────────────────────────────

    def _update_nav(self) -> None:
        """Update navigation buttons and page label for single-file mode."""
        if self._merged_mode:
            return

        has_pages = self._page_count > 1
        self._btn_prev.setVisible(has_pages)
        self._btn_next.setVisible(has_pages)
        self._btn_prev.setEnabled(self._current_page > 0)
        self._btn_next.setEnabled(self._current_page < self._page_count - 1)

        if has_pages:
            self._page_label.setText(f"Page {self._current_page + 1} of {self._page_count}")
        elif self._page_count == 1:
            self._page_label.setText("1 page")
        else:
            self._page_label.setText("")

    def _go_prev(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._render_single_page()
            self._update_nav()

    def _go_next(self) -> None:
        if self._current_page < self._page_count - 1:
            self._current_page += 1
            self._render_single_page()
            self._update_nav()


# ══════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════


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

        # ── Splitter: file list (left) | preview (right) ──
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

        # Right panel — preview
        self._preview = PreviewPanel()
        self._splitter.addWidget(self._preview)

        self._splitter.setSizes([400, 500])

        # ── Bottom bar: output name + preview merged + save ────
        bottom = QHBoxLayout()
        root_layout.addLayout(bottom)

        bottom.addWidget(QLabel("Output file:"))

        self._output_name = QLineEdit("merged.pdf")
        self._output_name.setPlaceholderText("merged.pdf")
        self._output_name.setMinimumWidth(250)
        bottom.addWidget(self._output_name, stretch=1)

        self._btn_preview_merged = QPushButton("Preview Merged")
        self._btn_preview_merged.setToolTip("Preview what the merged PDF will look like")
        self._btn_preview_merged.clicked.connect(self._on_preview_merged)
        bottom.addWidget(self._btn_preview_merged)

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
        current_row = self._file_list.currentRow()

        self._file_list.blockSignals(True)
        self._file_list.clear()

        for entry in self._model.entries:
            item = QListWidgetItem()
            item.setText(self._format_entry(entry))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if entry.included else Qt.CheckState.Unchecked
            )
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
            # Reset preview if we removed the previewed file
            if self._file_list.currentRow() < 0:
                self._preview.show_placeholder()

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
    # Preview
    # ══════════════════════════════════════════════════════════

    def _on_selection_changed(self, row: int) -> None:
        """Show preview of the selected file."""
        if 0 <= row < len(self._model):
            entry = self._model[row]
            self._preview.show_file(entry.path)
        else:
            self._preview.show_placeholder()

    def _on_preview_merged(self) -> None:
        """Show a preview of the merged output."""
        included = self._model.included_entries()
        if not included:
            QMessageBox.information(self, "Nothing to preview", "No files are included for merging.")
            return
        self._statusbar.showMessage("Rendering merged preview…")
        self._preview.show_merged(self._model.entries)
        self._statusbar.showMessage(f"Merged preview: {len(included)} file(s)", 3000)

    # ══════════════════════════════════════════════════════════
    # Save / merge
    # ══════════════════════════════════════════════════════════

    def _on_save(self) -> None:
        included = self._model.included_entries()
        if not included:
            QMessageBox.warning(self, "Nothing to merge", "No files are included for merging.")
            return

        name = self._output_name.text().strip()
        if not name:
            name = "merged.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"

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
