"""Main window — UI shell for PDFJoiner."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QModelIndex, QRect, QSize, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdfjoiner import __version__
from pdfjoiner.model import (
    SUPPORTED_EXTENSIONS,
    FileEntry,
    OutputOptions,
    PageNumberOptions,
    ProjectModel,
    WatermarkOptions,
    is_supported,
)
from pdfjoiner.service import MergeService


def _file_filter() -> str:
    """Build a file dialog filter string from supported extensions."""
    exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
    return (
        f"Supported files ({exts});;"
        f"PDF files (*.pdf);;"
        f"Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif);;"
        f"All files (*)"
    )


def _paths_from_mime(event) -> List[Path]:
    """Extract file/folder paths from a drag-and-drop mime payload."""
    paths: List[Path] = []
    if event.mimeData().hasUrls():
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
    return paths


def _has_acceptable_files(event) -> bool:
    """Return True if the drag payload contains at least one local file/folder."""
    if not event.mimeData().hasUrls():
        return False
    for url in event.mimeData().urls():
        if url.isLocalFile():
            p = Path(url.toLocalFile())
            if p.is_dir() or (p.is_file() and is_supported(p)):
                return True
    return False


# ══════════════════════════════════════════════════════════════
# Drop indicator delegate — paints a visual gap between items
# ══════════════════════════════════════════════════════════════

_GAP_HEIGHT = 36  # pixel height of the insertion gap
_GAP_COLOR = QColor(80, 130, 220, 45)    # subtle blue fill
_GAP_LINE_COLOR = QColor(80, 130, 220)   # blue insertion line
_GAP_LINE_WIDTH = 2


class _DropIndicatorDelegate(QStyledItemDelegate):
    """Custom delegate that inflates one row to create a visual drop gap.

    The owning FileListWidget sets ``gap_index`` to the row *before which*
    the gap should appear.  A value of -1 means no gap.
    """

    def __init__(self, list_widget: "FileListWidget") -> None:
        super().__init__(list_widget)
        self._list = list_widget

    # ── Size ───────────────────────────────────────────────────

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        if self._list.gap_index >= 0 and index.row() == self._list.gap_index:
            size.setHeight(size.height() + _GAP_HEIGHT)
        return size

    # ── Paint ──────────────────────────────────────────────────

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        gap = self._list.gap_index

        if gap >= 0 and index.row() == gap:
            # Draw the gap zone at the top of this item's rect
            gap_rect = QRect(option.rect)
            gap_rect.setHeight(_GAP_HEIGHT)

            painter.fillRect(gap_rect, _GAP_COLOR)

            # Horizontal insertion line centred in the gap
            painter.save()
            pen = QPen(_GAP_LINE_COLOR, _GAP_LINE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            y = gap_rect.center().y()
            painter.drawLine(gap_rect.left() + 6, y, gap_rect.right() - 6, y)

            # Small circles at each end of the line
            painter.setBrush(_GAP_LINE_COLOR)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(gap_rect.left() + 3, y - 3, 6, 6)
            painter.drawEllipse(gap_rect.right() - 9, y - 3, 6, 6)
            painter.restore()

            # Shift the actual item content below the gap
            shifted = QStyleOptionViewItem(option)
            shifted.rect = QRect(option.rect)
            shifted.rect.setTop(option.rect.top() + _GAP_HEIGHT)
            super().paint(painter, shifted, index)
        else:
            super().paint(painter, option, index)


# ══════════════════════════════════════════════════════════════
# File list with drag-and-drop support
# ══════════════════════════════════════════════════════════════


class FileListWidget(QListWidget):
    """QListWidget subclass that supports:

    - Internal drag-and-drop reordering with a visual insertion gap
    - External OS file/folder drops
    """

    row_moved = Signal(int, int)
    files_dropped = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)

        # Disable Qt's built-in drop indicator line — we draw our own
        self.setDropIndicatorShown(False)

        self._drag_start_row: int = -1
        self._gap_index: int = -1  # row before which the gap is shown

        self.setItemDelegate(_DropIndicatorDelegate(self))

    @property
    def gap_index(self) -> int:
        return self._gap_index

    # ── Gap management ─────────────────────────────────────────

    def _set_gap(self, index: int) -> None:
        """Set the visual gap position. -1 to hide."""
        if index == self._gap_index:
            return
        self._gap_index = index
        # Force the list to re-query sizeHint and repaint
        self.scheduleDelayedItemsLayout()

    def _clear_gap(self) -> None:
        self._set_gap(-1)

    def _gap_index_for_pos(self, pos) -> int:
        """Determine which gap index a drag position maps to.

        If the cursor is in the top half of an item → gap before that item.
        If in the bottom half → gap before the next item.
        Past the last item → gap at count() (append).
        """
        item = self.itemAt(pos.toPoint() if hasattr(pos, 'toPoint') else pos)
        if item is None:
            return self.count()

        row = self.row(item)
        rect = self.visualItemRect(item)

        # Account for existing gap height in the hit-test
        if row == self._gap_index:
            item_top = rect.top() + _GAP_HEIGHT
        else:
            item_top = rect.top()

        item_mid = item_top + (rect.height() - (_GAP_HEIGHT if row == self._gap_index else 0)) / 2
        cursor_y = pos.toPoint().y() if hasattr(pos, 'toPoint') else pos.y()

        if cursor_y < item_mid:
            return row
        else:
            return row + 1

    # ── Drag events ────────────────────────────────────────────

    def startDrag(self, supportedActions) -> None:
        self._drag_start_row = self.currentRow()
        super().startDrag(supportedActions)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self:
            event.accept()
        elif _has_acceptable_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self:
            # Internal reorder — show gap
            event.accept()
            target = self._gap_index_for_pos(event.position())

            # Don't show gap at the dragged item's own position
            # (placing it right before or right after itself is a no-op)
            if self._drag_start_row >= 0:
                if target == self._drag_start_row or target == self._drag_start_row + 1:
                    self._clear_gap()
                    return

            self._set_gap(target)

        elif event.mimeData().hasUrls():
            # External file drop — show gap for insertion position
            event.acceptProposedAction()
            target = self._gap_index_for_pos(event.position())
            self._set_gap(target)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._clear_gap()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        target = self._gap_index if self._gap_index >= 0 else self._gap_index_for_pos(event.position())
        self._clear_gap()

        # External drop
        if event.source() is not self and event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            paths = _paths_from_mime(event)
            if paths:
                self.files_dropped.emit(paths)
            return

        # Internal reorder
        if event.source() is self and self._drag_start_row >= 0:
            old_row = self._drag_start_row
            self._drag_start_row = -1

            # Convert "insert before target" to a move-to index
            # If dragging down, the removal of the source shifts indices
            new_row = target if target < old_row else target - 1
            new_row = max(0, min(new_row, self.count() - 1))

            if old_row != new_row:
                event.ignore()
                self.row_moved.emit(old_row, new_row)
                return

        self._drag_start_row = -1
        super().dropEvent(event)


# ══════════════════════════════════════════════════════════════
# Preview panel widget
# ══════════════════════════════════════════════════════════════


class PreviewPanel(QFrame):
    """Right-side panel: single-file preview with page nav, or merged preview."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setStyleSheet(
            "PreviewPanel { background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; }"
        )
        self._current_path: Optional[Path] = None
        self._current_page: int = 0
        self._page_count: int = 0
        self._merged_mode: bool = False
        self._build_ui()
        self._show_placeholder()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self._title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(self._scroll, stretch=1)

        self._page_container = QWidget()
        self._page_layout = QVBoxLayout(self._page_container)
        self._page_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._page_layout.setSpacing(12)
        self._scroll.setWidget(self._page_container)

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
        self._merged_mode = False
        self._current_path = path
        self._current_page = 0
        self._page_count = MergeService.get_page_count(path)
        self._title.setText(path.name)
        self._render_single_page()
        self._update_nav()

    def show_merged(self, entries: List[FileEntry]) -> None:
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
            img_label = QLabel()
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_label.setPixmap(pix)
            self._page_layout.addWidget(img_label)

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
        self._show_placeholder(text)

    # ── Internal ───────────────────────────────────────────────

    def _render_single_page(self) -> None:
        self._clear_pages()
        if self._current_path is None:
            return

        pix = MergeService.render_preview(
            self._current_path, page=self._current_page,
            max_width=self._preview_width(), max_height=800,
        )
        if pix is None:
            err = QLabel("Could not render this file.")
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setStyleSheet("color: #c00; padding: 20px;")
            self._page_layout.addWidget(err)
            return

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setPixmap(pix)
        self._page_layout.addWidget(img_label)

    def _show_placeholder(self, text: str = "Select a file to preview") -> None:
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
        while self._page_layout.count():
            child = self._page_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _preview_width(self) -> int:
        return max(self._scroll.viewport().width() - 20, 200)

    def _update_nav(self) -> None:
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
# Output options dialog
# ══════════════════════════════════════════════════════════════


class OutputOptionsDialog(QDialog):
    """Dialog for configuring page numbers and watermark before saving."""

    def __init__(self, options: OutputOptions, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Output Options")
        self.setMinimumWidth(480)
        self._options = options
        self._build_ui()
        self._load_from_options()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Page Numbers tab ───────────────────────────────────
        pn_tab = QWidget()
        pn_layout = QVBoxLayout(pn_tab)

        self._pn_enabled = QCheckBox("Add page numbers")
        pn_layout.addWidget(self._pn_enabled)

        self._pn_group = QGroupBox()
        self._pn_group.setFlat(True)
        pn_form = QFormLayout(self._pn_group)

        self._pn_position = QComboBox()
        self._pn_position.addItems([
            "Bottom Center", "Bottom Left", "Bottom Right",
            "Top Center", "Top Left", "Top Right",
        ])
        pn_form.addRow("Position:", self._pn_position)

        self._pn_format = QComboBox()
        self._pn_format.setEditable(True)
        self._pn_format.addItems([
            "{n} / {total}",
            "Page {n} of {total}",
            "{n}",
            "Page {n}",
            "- {n} -",
        ])
        pn_form.addRow("Format:", self._pn_format)

        self._pn_start = QSpinBox()
        self._pn_start.setRange(0, 9999)
        self._pn_start.setValue(1)
        pn_form.addRow("Start at:", self._pn_start)

        self._pn_font_size = QDoubleSpinBox()
        self._pn_font_size.setRange(4.0, 72.0)
        self._pn_font_size.setValue(10.0)
        self._pn_font_size.setSuffix(" pt")
        pn_form.addRow("Font size:", self._pn_font_size)

        self._pn_margin = QDoubleSpinBox()
        self._pn_margin.setRange(10.0, 200.0)
        self._pn_margin.setValue(36.0)
        self._pn_margin.setSuffix(" pt")
        pn_form.addRow("Margin:", self._pn_margin)

        pn_layout.addWidget(self._pn_group)
        pn_layout.addStretch()
        tabs.addTab(pn_tab, "Page Numbers")

        # Wire enable/disable
        self._pn_enabled.toggled.connect(self._pn_group.setEnabled)

        # ── Watermark tab ──────────────────────────────────────
        wm_tab = QWidget()
        wm_layout = QVBoxLayout(wm_tab)

        self._wm_enabled = QCheckBox("Add watermark")
        wm_layout.addWidget(self._wm_enabled)

        self._wm_group = QGroupBox()
        self._wm_group.setFlat(True)
        wm_form = QFormLayout(self._wm_group)

        self._wm_text = QLineEdit()
        self._wm_text.setPlaceholderText("DRAFT")
        wm_form.addRow("Text:", self._wm_text)

        self._wm_font_size = QDoubleSpinBox()
        self._wm_font_size.setRange(8.0, 200.0)
        self._wm_font_size.setValue(60.0)
        self._wm_font_size.setSuffix(" pt")
        wm_form.addRow("Font size:", self._wm_font_size)

        self._wm_angle = QDoubleSpinBox()
        self._wm_angle.setRange(-180.0, 180.0)
        self._wm_angle.setValue(45.0)
        self._wm_angle.setSuffix("°")
        wm_form.addRow("Angle:", self._wm_angle)

        # Opacity with slider + label
        opacity_row = QHBoxLayout()
        self._wm_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._wm_opacity_slider.setRange(1, 100)
        self._wm_opacity_slider.setValue(15)
        self._wm_opacity_label = QLabel("15%")
        self._wm_opacity_label.setMinimumWidth(40)
        self._wm_opacity_slider.valueChanged.connect(
            lambda v: self._wm_opacity_label.setText(f"{v}%")
        )
        opacity_row.addWidget(self._wm_opacity_slider, stretch=1)
        opacity_row.addWidget(self._wm_opacity_label)
        wm_form.addRow("Opacity:", opacity_row)

        self._wm_color = QComboBox()
        self._wm_color.addItems(["Gray", "Red", "Blue", "Green", "Black"])
        wm_form.addRow("Color:", self._wm_color)

        wm_layout.addWidget(self._wm_group)
        wm_layout.addStretch()
        tabs.addTab(wm_tab, "Watermark")

        # Wire enable/disable
        self._wm_enabled.toggled.connect(self._wm_group.setEnabled)

        # ── Dialog buttons ─────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Position mapping ───────────────────────────────────────

    _POSITION_MAP = [
        "bottom-center", "bottom-left", "bottom-right",
        "top-center", "top-left", "top-right",
    ]

    _COLOR_MAP = {
        "Gray": (0.5, 0.5, 0.5),
        "Red": (0.8, 0.1, 0.1),
        "Blue": (0.1, 0.1, 0.8),
        "Green": (0.1, 0.6, 0.1),
        "Black": (0.0, 0.0, 0.0),
    }

    # ── Load / save ────────────────────────────────────────────

    def _load_from_options(self) -> None:
        """Populate UI from the options dataclass."""
        pn = self._options.page_numbers
        self._pn_enabled.setChecked(pn.enabled)
        self._pn_group.setEnabled(pn.enabled)
        idx = self._POSITION_MAP.index(pn.position) if pn.position in self._POSITION_MAP else 0
        self._pn_position.setCurrentIndex(idx)
        self._pn_format.setCurrentText(pn.format)
        self._pn_start.setValue(pn.start)
        self._pn_font_size.setValue(pn.font_size)
        self._pn_margin.setValue(pn.margin)

        wm = self._options.watermark
        self._wm_enabled.setChecked(wm.enabled)
        self._wm_group.setEnabled(wm.enabled)
        self._wm_text.setText(wm.text)
        self._wm_font_size.setValue(wm.font_size)
        self._wm_angle.setValue(wm.angle)
        self._wm_opacity_slider.setValue(int(wm.opacity * 100))
        # Find color name
        color_name = "Gray"
        for name, rgb in self._COLOR_MAP.items():
            if rgb == wm.color:
                color_name = name
                break
        self._wm_color.setCurrentText(color_name)

    def get_options(self) -> OutputOptions:
        """Read the UI state into an OutputOptions dataclass."""
        pn = PageNumberOptions(
            enabled=self._pn_enabled.isChecked(),
            position=self._POSITION_MAP[self._pn_position.currentIndex()],
            format=self._pn_format.currentText(),
            start=self._pn_start.value(),
            font_size=self._pn_font_size.value(),
            margin=self._pn_margin.value(),
        )

        color_rgb = self._COLOR_MAP.get(self._wm_color.currentText(), (0.5, 0.5, 0.5))
        wm = WatermarkOptions(
            enabled=self._wm_enabled.isChecked(),
            text=self._wm_text.text() or "DRAFT",
            font_size=self._wm_font_size.value(),
            angle=self._wm_angle.value(),
            opacity=self._wm_opacity_slider.value() / 100.0,
            color=color_rgb,
        )

        return OutputOptions(page_numbers=pn, watermark=wm)


# ══════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════


class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFJoiner")
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        self._model = ProjectModel(self)
        self._model.list_changed.connect(self._on_list_changed)

        # Persistent output options — remembered across saves within a session
        self._output_options = OutputOptions()

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
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

        self._act_clear = QAction("Clear All", self)
        self._act_clear.setShortcut(QKeySequence("Ctrl+L"))
        self._act_clear.setToolTip("Remove all files from list (Ctrl+L)")
        self._act_clear.triggered.connect(self._on_clear)
        tb.addAction(self._act_clear)

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

        tb.addSeparator()

        self._act_about = QAction("About", self)
        self._act_about.setShortcut(QKeySequence("F1"))
        self._act_about.setToolTip("About PDFJoiner (F1)")
        self._act_about.triggered.connect(self._on_about)
        tb.addAction(self._act_about)

        # Quit shortcut (no toolbar button — just the keyboard shortcut)
        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        self.addAction(act_quit)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self._splitter, stretch=1)

        # Left panel — file list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_label = QLabel("Files to merge:")
        left_layout.addWidget(list_label)

        self._file_list = FileListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_list.setAlternatingRowColors(True)
        self._file_list.itemChanged.connect(self._on_item_checked)
        self._file_list.currentRowChanged.connect(self._on_selection_changed)
        self._file_list.row_moved.connect(self._on_drag_reorder)
        self._file_list.files_dropped.connect(self._on_external_drop)
        left_layout.addWidget(self._file_list)

        self._splitter.addWidget(left)

        # Right panel — preview
        self._preview = PreviewPanel()
        self._splitter.addWidget(self._preview)

        self._splitter.setSizes([400, 500])

        # Bottom bar
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

        self._btn_options = QPushButton("Options…")
        self._btn_options.setToolTip("Configure page numbers, watermark, and other output options")
        self._btn_options.clicked.connect(self._on_output_options)
        bottom.addWidget(self._btn_options)

        self._btn_save = QPushButton("Save Merged PDF")
        self._btn_save.setShortcut(QKeySequence("Ctrl+S"))
        self._btn_save.setToolTip("Merge included files and save (Ctrl+S)")
        self._btn_save.clicked.connect(self._on_save)
        bottom.addWidget(self._btn_save)

    def _build_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

    # ══════════════════════════════════════════════════════════
    # OS drag-and-drop on main window
    # ══════════════════════════════════════════════════════════

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _has_acceptable_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _paths_from_mime(event)
        if paths:
            event.acceptProposedAction()
            self._add_dropped_paths(paths)

    # ══════════════════════════════════════════════════════════
    # File list sync
    # ══════════════════════════════════════════════════════════

    def _on_list_changed(self) -> None:
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

        if 0 <= current_row < self._file_list.count():
            self._file_list.setCurrentRow(current_row)
        elif self._file_list.count() > 0:
            self._file_list.setCurrentRow(min(current_row, self._file_list.count() - 1))

        self._update_status()

    def _format_entry(self, entry: FileEntry) -> str:
        suffix = entry.path.suffix.upper().lstrip(".")
        if entry.is_pdf:
            pages = MergeService.get_page_count(entry.path)
            return f"{entry.filename}  [{suffix}, {pages} page{'s' if pages != 1 else ''}]"
        return f"{entry.filename}  [{suffix}]"

    def _update_status(self) -> None:
        total = len(self._model)
        included = len(self._model.included_entries())
        if total == 0:
            self._statusbar.showMessage(
                "No files added. Use 'Add Files', 'Add Folder', or drag and drop to begin."
            )
        else:
            self._statusbar.showMessage(f"{total} file(s) — {included} included for merge")

    # ══════════════════════════════════════════════════════════
    # Toolbar actions
    # ══════════════════════════════════════════════════════════

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Files", "", _file_filter())
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
            if self._file_list.currentRow() < 0:
                self._preview.show_placeholder()

    def _on_clear(self) -> None:
        if len(self._model) == 0:
            return
        reply = QMessageBox.question(
            self, "Clear all files",
            f"Remove all {len(self._model)} file(s) from the list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._model.clear()
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
    # Drag-and-drop handlers
    # ══════════════════════════════════════════════════════════

    def _on_drag_reorder(self, old_row: int, new_row: int) -> None:
        self._model.move(old_row, new_row)
        self._file_list.setCurrentRow(new_row)

    def _on_external_drop(self, paths: list) -> None:
        self._add_dropped_paths(paths)

    def _add_dropped_paths(self, paths: List[Path]) -> None:
        total_added = 0
        for p in paths:
            p = Path(p)
            if p.is_dir():
                total_added += self._model.add_folder(p)
            elif p.is_file():
                total_added += self._model.add_files([p])
        if total_added > 0:
            self._statusbar.showMessage(f"Added {total_added} file(s) via drag and drop.", 3000)
        elif paths:
            self._statusbar.showMessage("No supported files found in dropped items.", 3000)

    # ══════════════════════════════════════════════════════════
    # Checkbox
    # ══════════════════════════════════════════════════════════

    def _on_item_checked(self, item: QListWidgetItem) -> None:
        row = self._file_list.row(item)
        if row < 0 or row >= len(self._model):
            return
        is_checked = item.checkState() == Qt.CheckState.Checked
        self._model.set_included(row, is_checked)

    # ══════════════════════════════════════════════════════════
    # Preview
    # ══════════════════════════════════════════════════════════

    def _on_selection_changed(self, row: int) -> None:
        if 0 <= row < len(self._model):
            self._preview.show_file(self._model[row].path)
        else:
            self._preview.show_placeholder()

    def _on_preview_merged(self) -> None:
        included = self._model.included_entries()
        if not included:
            QMessageBox.information(self, "Nothing to preview", "No files are included for merging.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._statusbar.showMessage("Rendering merged preview…")
            self._preview.show_merged(self._model.entries)
            self._statusbar.showMessage(f"Merged preview: {len(included)} file(s)", 3000)
        finally:
            QApplication.restoreOverrideCursor()

    # ══════════════════════════════════════════════════════════
    # Output options
    # ══════════════════════════════════════════════════════════

    def _on_output_options(self) -> None:
        """Open the output options dialog."""
        dlg = OutputOptionsDialog(self._output_options, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._output_options = dlg.get_options()
            self._statusbar.showMessage("Output options updated.", 3000)

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

        path, _ = QFileDialog.getSaveFileName(self, "Save Merged PDF", name, "PDF files (*.pdf)")
        if not path:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = MergeService.merge(
                self._model.entries, Path(path), options=self._output_options
            )
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Merge failed", str(exc))
            return
        QApplication.restoreOverrideCursor()

        msg = f"Saved {result.page_count} page(s) to {Path(path).name}"
        if result.has_warnings:
            msg += f"  ({len(result.skipped)} file(s) skipped)"
            details = "The following files could not be processed:\n\n" + "\n".join(result.skipped)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Merge completed with warnings")
            box.setText(msg)
            box.setDetailedText(details)
            box.exec()
        else:
            self._statusbar.showMessage(msg, 5000)

    # ══════════════════════════════════════════════════════════
    # About
    # ══════════════════════════════════════════════════════════

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About PDFJoiner",
            f"<h3>PDFJoiner v{__version__}</h3>"
            f"<p>A cross-platform tool for joining PDFs and images into a single PDF.</p>"
            f"<p>Built with PySide6 (Qt) and PyMuPDF.</p>"
            f"<p>License: MIT</p>"
            f"<p><a href='https://github.com/youruser/PDFJoiner'>GitHub</a></p>",
        )
