"""Main window — UI shell for PDFJoiner."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QModelIndex, QPointF, QRect, QRectF, QSize, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetricsF,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
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
    TextAnnotation,
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
# Inline row widget for the file list
# ══════════════════════════════════════════════════════════════

_BTN_STYLE = """
    QPushButton {
        border: none; background: transparent; padding: 2px 5px;
        font-size: 13px;
    }
    QPushButton:hover { background: palette(midlight); border-radius: 3px; }
"""
_BTN_DEL_STYLE = """
    QPushButton {
        border: none; background: transparent; padding: 2px 5px;
        font-size: 13px;
    }
    QPushButton:hover { color: #c00; background: rgba(255,0,0,0.08); border-radius: 3px; }
"""


class FileRowWidget(QWidget):
    """Inline widget for a single row in the file list.

    Layout: [checkbox] [filename + info label ...stretch...] [▲] [▼] [✕]
    """

    include_toggled = Signal(int, bool)
    move_up_clicked = Signal(int)
    move_down_clicked = Signal(int)
    remove_clicked = Signal(int)

    def __init__(self, row: int, entry: "FileEntry", label_text: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._row = row

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(2)

        self._check = QCheckBox()
        self._check.setChecked(entry.included)
        self._check.toggled.connect(lambda checked: self.include_toggled.emit(self._row, checked))
        layout.addWidget(self._check)

        self._label = QLabel(label_text)
        if not entry.included:
            self._label.setEnabled(False)  # uses palette's disabled text color
        layout.addWidget(self._label, stretch=1)

        btn_up = QPushButton("▲")
        btn_up.setFixedSize(24, 22)
        btn_up.setStyleSheet(_BTN_STYLE)
        btn_up.setToolTip("Move up")
        btn_up.clicked.connect(lambda: self.move_up_clicked.emit(self._row))
        layout.addWidget(btn_up)

        btn_down = QPushButton("▼")
        btn_down.setFixedSize(24, 22)
        btn_down.setStyleSheet(_BTN_STYLE)
        btn_down.setToolTip("Move down")
        btn_down.clicked.connect(lambda: self.move_down_clicked.emit(self._row))
        layout.addWidget(btn_down)

        btn_del = QPushButton("✕")
        btn_del.setFixedSize(24, 22)
        btn_del.setStyleSheet(_BTN_DEL_STYLE)
        btn_del.setToolTip("Remove")
        btn_del.clicked.connect(lambda: self.remove_clicked.emit(self._row))
        layout.addWidget(btn_del)


# ══════════════════════════════════════════════════════════════
# Annotation helpers
# ══════════════════════════════════════════════════════════════


class AnnotatedPageWidget(QWidget):
    """Displays a single rendered page with annotation overlays.

    Supports selecting, dragging, editing, and deleting annotations.

    Interactions:
    - Left-click on empty space  → ``clicked`` signal (create new)
    - Left-click on annotation   → select it
    - Drag a selected annotation → move it, then ``annotation_moved``
    - Double-click annotation    → ``annotation_edit_requested``
    - Delete / Backspace key     → ``annotation_delete_requested``
    - Right-click annotation     → context menu (Edit / Delete)
    """

    # Click on empty space → create new annotation
    clicked = Signal(int, float, float)
    # Annotation was dragged to a new position (already mutated)
    annotation_moved = Signal(object)
    # User wants to edit an annotation (double-click or context menu)
    annotation_edit_requested = Signal(object)
    # User wants to delete an annotation (Delete key or context menu)
    annotation_delete_requested = Signal(object)

    _SELECTION_COLOR = QColor(0, 120, 215)  # Windows-style accent blue
    _HIT_PAD = 6.0  # extra pixels around text rect for easier clicking

    def __init__(
        self,
        pixmap: QPixmap,
        page_index: int,
        annotations: List[TextAnnotation],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._page_index = page_index
        self._annotations = annotations
        self.setFixedSize(pixmap.size())
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)

        # Mode
        self._annotate_mode: bool = False

        # Selection / drag state
        self._selected: Optional[TextAnnotation] = None
        self._dragging: bool = False
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0

        # Cached hit-rects (rebuilt every paint)
        self._hit_rects: List[tuple] = []  # [(QRectF, TextAnnotation), ...]

    @property
    def selected(self) -> Optional[TextAnnotation]:
        return self._selected

    @property
    def annotate_mode(self) -> bool:
        return self._annotate_mode

    @annotate_mode.setter
    def annotate_mode(self, on: bool) -> None:
        self._annotate_mode = on
        # Update cursor for current state
        default = Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor
        self.setCursor(QCursor(default))

    def set_selected(self, ann: Optional[TextAnnotation]) -> None:
        if self._selected is not ann:
            self._selected = ann
            self.update()

    def set_annotations(self, annotations: List[TextAnnotation]) -> None:
        self._annotations = annotations
        # Clear selection if it no longer exists
        if self._selected not in annotations:
            self._selected = None
        self.update()

    # ── Geometry helpers ───────────────────────────────────────

    def _ann_rect(self, ann: TextAnnotation) -> QRectF:
        """Compute the bounding rect for an annotation in widget pixels."""
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        x = ann.x_ratio * pw
        y = ann.y_ratio * ph

        scale = ph / 842.0
        font_size = max(8.0, ann.font_size * scale)
        font = QFont("Helvetica", int(font_size))
        fm = QFontMetricsF(font)
        text_rect = fm.boundingRect(ann.text)
        pad = 3.0 + self._HIT_PAD

        return QRectF(
            x - pad,
            y - text_rect.height() - pad,
            text_rect.width() + 2 * pad,
            text_rect.height() + 2 * pad,
        )

    def _hit_test(self, pos: QPointF) -> Optional[TextAnnotation]:
        """Return the top-most annotation under *pos*, or None."""
        # Iterate in reverse so top-drawn (last) annotations are hit first
        for rect, ann in reversed(self._hit_rects):
            if rect.contains(pos):
                return ann
        return None

    # ── Paint ──────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.drawPixmap(0, 0, self._pixmap)

        pw = self._pixmap.width()
        ph = self._pixmap.height()
        self._hit_rects = []

        for ann in self._annotations:
            if not ann.text.strip():
                continue

            x = ann.x_ratio * pw
            y = ann.y_ratio * ph
            scale = ph / 842.0
            font_size = max(8.0, ann.font_size * scale)

            font = QFont("Helvetica", int(font_size))
            painter.setFont(font)
            fm = QFontMetricsF(font)
            text_rect = fm.boundingRect(ann.text)
            pad = 3.0

            bg_rect = QRectF(
                x - pad,
                y - text_rect.height() - pad,
                text_rect.width() + 2 * pad,
                text_rect.height() + 2 * pad,
            )

            r, g, b = ann.color
            is_sel = ann is self._selected

            # Background pill
            bg_alpha = 0.22 if is_sel else 0.12
            bg_color = QColor.fromRgbF(r, g, b, bg_alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(bg_rect, 3, 3)

            # Selection highlight border
            if is_sel:
                sel_pen = QPen(self._SELECTION_COLOR, 2.0, Qt.PenStyle.DashLine)
                painter.setPen(sel_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                hit_rect = bg_rect.adjusted(
                    -self._HIT_PAD, -self._HIT_PAD, self._HIT_PAD, self._HIT_PAD
                )
                painter.drawRoundedRect(hit_rect, 4, 4)

            # Text
            text_color = QColor.fromRgbF(r, g, b)
            painter.setPen(QPen(text_color))
            painter.drawText(QPointF(x, y), ann.text)

            # Marker dot
            painter.setBrush(QBrush(text_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, y), 3, 3)

            # Store hit rect for click testing
            self._hit_rects.append((self._ann_rect(ann), ann))

        painter.end()

    # ── Mouse events ───────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()

        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_test(pos)
            if hit is not None:
                # Select the annotation and prepare for potential drag
                self._selected = hit
                self._dragging = False
                pw = self._pixmap.width()
                ph = self._pixmap.height()
                self._drag_offset_x = pos.x() - hit.x_ratio * pw
                self._drag_offset_y = pos.y() - hit.y_ratio * ph
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                self.update()
            else:
                # Deselect; only create new annotation if annotate mode is on
                self._selected = None
                self.update()
                if self._annotate_mode:
                    pw = self._pixmap.width()
                    ph = self._pixmap.height()
                    if pw > 0 and ph > 0:
                        x_ratio = max(0.0, min(1.0, pos.x() / pw))
                        y_ratio = max(0.0, min(1.0, pos.y() / ph))
                        self.clicked.emit(self._page_index, x_ratio, y_ratio)

        elif event.button() == Qt.MouseButton.RightButton:
            hit = self._hit_test(pos)
            if hit is not None:
                self._selected = hit
                self.update()
                self._show_context_menu(event.globalPosition().toPoint(), hit)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()

        if self._selected is not None and event.buttons() & Qt.MouseButton.LeftButton:
            # Start or continue dragging
            self._dragging = True
            pw = self._pixmap.width()
            ph = self._pixmap.height()
            if pw > 0 and ph > 0:
                new_x = (pos.x() - self._drag_offset_x) / pw
                new_y = (pos.y() - self._drag_offset_y) / ph
                self._selected.x_ratio = max(0.0, min(1.0, new_x))
                self._selected.y_ratio = max(0.0, min(1.0, new_y))
                self.update()
        else:
            # Update cursor based on hover
            hit = self._hit_test(pos)
            if hit is not None:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                default = Qt.CursorShape.CrossCursor if self._annotate_mode else Qt.CursorShape.ArrowCursor
                self.setCursor(QCursor(default))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging and self._selected is not None:
                self._dragging = False
                self.annotation_moved.emit(self._selected)
            # Restore cursor
            hit = self._hit_test(event.position())
            if hit is not None:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                default = Qt.CursorShape.CrossCursor if self._annotate_mode else Qt.CursorShape.ArrowCursor
                self.setCursor(QCursor(default))
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_test(event.position())
            if hit is not None:
                self._selected = hit
                self.update()
                self.annotation_edit_requested.emit(hit)
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._selected is not None and event.key() in (
            Qt.Key.Key_Delete, Qt.Key.Key_Backspace
        ):
            self.annotation_delete_requested.emit(self._selected)
            return
        super().keyPressEvent(event)

    # ── Context menu ───────────────────────────────────────────

    def _show_context_menu(self, global_pos, ann: TextAnnotation) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        act_edit = menu.addAction("Edit Annotation…")
        act_delete = menu.addAction("Delete Annotation")

        chosen = menu.exec(global_pos)
        if chosen is act_edit:
            self.annotation_edit_requested.emit(ann)
        elif chosen is act_delete:
            self.annotation_delete_requested.emit(ann)


class AnnotationDialog(QDialog):
    """Dialog for creating or editing a text annotation."""

    _COLOR_MAP = {
        "Black": (0.0, 0.0, 0.0),
        "Red": (0.8, 0.0, 0.0),
        "Blue": (0.0, 0.0, 0.8),
        "Green": (0.0, 0.5, 0.0),
        "Gray": (0.5, 0.5, 0.5),
    }

    def __init__(
        self,
        page_index: int,
        x_ratio: float,
        y_ratio: float,
        parent: Optional[QWidget] = None,
        *,
        existing: Optional[TextAnnotation] = None,
    ) -> None:
        super().__init__(parent)
        editing = existing is not None
        title = "Edit Annotation" if editing else "Add Annotation"
        self.setWindowTitle(f"{title} — Page {page_index + 1}")
        self.setMinimumWidth(340)

        layout = QFormLayout(self)

        self._text = QLineEdit()
        self._text.setPlaceholderText("Enter annotation text…")
        if editing:
            self._text.setText(existing.text)
        layout.addRow("Text:", self._text)

        self._font_size = QDoubleSpinBox()
        self._font_size.setRange(6.0, 72.0)
        self._font_size.setValue(existing.font_size if editing else 12.0)
        self._font_size.setSuffix(" pt")
        layout.addRow("Font size:", self._font_size)

        self._color = QComboBox()
        self._color.addItems(list(self._COLOR_MAP.keys()))
        if editing:
            # Select the matching color, or default to Black
            for name, rgb in self._COLOR_MAP.items():
                if rgb == existing.color:
                    self._color.setCurrentText(name)
                    break
        layout.addRow("Color:", self._color)

        pos_text = f"({x_ratio:.0%}, {y_ratio:.0%})"
        pos_label = QLabel(pos_text)
        pos_label.setEnabled(False)
        layout.addRow("Position:", pos_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._text.setFocus()
        self._text.selectAll()

    def get_annotation(self, page_index: int, x_ratio: float, y_ratio: float) -> TextAnnotation:
        """Build a TextAnnotation from the dialog state."""
        color_name = self._color.currentText()
        return TextAnnotation(
            page=page_index,
            x_ratio=x_ratio,
            y_ratio=y_ratio,
            text=self._text.text().strip(),
            font_size=self._font_size.value(),
            color=self._COLOR_MAP.get(color_name, (0.0, 0.0, 0.0)),
        )


# ══════════════════════════════════════════════════════════════
# Preview panel widget
# ══════════════════════════════════════════════════════════════


class PreviewPanel(QFrame):
    """Right-side panel: single-file preview with page nav, or merged preview."""

    # Emitted when user clicks on empty space to add annotation
    annotation_requested = Signal(int, float, float)  # page_index, x_ratio, y_ratio
    # Forwarded from AnnotatedPageWidget for annotation management
    annotation_moved = Signal(object)
    annotation_edit_requested = Signal(object)
    annotation_delete_requested = Signal(object)
    # Emitted when user switches between single/merged via the toggle
    mode_changed = Signal(str)  # "single" or "merged"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setStyleSheet(
            "PreviewPanel { background: palette(base); border: 1px solid palette(mid); border-radius: 4px; }"
        )
        self._current_path: Optional[Path] = None
        self._current_page: int = 0
        self._page_count: int = 0
        self._merged_mode: bool = False
        self._annotate_mode: bool = False
        self._page_widgets: List[AnnotatedPageWidget] = []
        self._single_page_widgets: List[QLabel] = []
        self._build_ui()
        self._show_placeholder()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toggle bar: Single / Merged
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)
        layout.addLayout(toggle_row)

        _SEG_LEFT = (
            "QPushButton { border: 1px solid palette(mid); border-right: none;"
            " border-radius: 0; border-top-left-radius: 4px; border-bottom-left-radius: 4px;"
            " padding: 4px 14px; background: palette(button); color: palette(button-text); }"
            "QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }"
        )
        _SEG_RIGHT = (
            "QPushButton { border: 1px solid palette(mid);"
            " border-radius: 0; border-top-right-radius: 4px; border-bottom-right-radius: 4px;"
            " padding: 4px 14px; background: palette(button); color: palette(button-text); }"
            "QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }"
        )

        self._btn_single = QPushButton("Single")
        self._btn_single.setCheckable(True)
        self._btn_single.setChecked(True)
        self._btn_single.setStyleSheet(_SEG_LEFT)
        self._btn_single.clicked.connect(lambda: self._set_preview_mode("single"))
        toggle_row.addWidget(self._btn_single)

        self._btn_merged = QPushButton("Merged")
        self._btn_merged.setCheckable(True)
        self._btn_merged.setStyleSheet(_SEG_RIGHT)
        self._btn_merged.clicked.connect(lambda: self._set_preview_mode("merged"))
        toggle_row.addWidget(self._btn_merged)

        toggle_row.addStretch()

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
        self._btn_single.setChecked(True)
        self._btn_merged.setChecked(False)
        self._current_path = path
        self._current_page = 0
        self._page_count = MergeService.get_page_count(path)
        self._title.setText(path.name)
        self._render_all_pages()
        self._update_nav()

    def show_merged(
        self,
        entries: List[FileEntry],
        options: Optional["OutputOptions"] = None,
    ) -> None:
        self._merged_mode = True
        self._btn_single.setChecked(False)
        self._btn_merged.setChecked(True)
        self._current_path = None

        included = [e for e in entries if e.included]
        if not included:
            self._show_placeholder("No included files to preview.")
            return

        self._title.setText(f"Merged preview — {len(included)} file(s)")
        self._clear_pages()

        pixmaps = MergeService.render_merged_preview(
            entries, max_width=self._preview_width(), max_height=1200,
            options=options,
        )
        if not pixmaps:
            self._show_placeholder("Could not render merged preview.")
            return

        all_annotations = options.annotations if options else []
        self._page_widgets = []

        for i, pix in enumerate(pixmaps):
            page_anns = [a for a in all_annotations if a.page == i]
            page_widget = AnnotatedPageWidget(pix, i, page_anns)
            page_widget.annotate_mode = self._annotate_mode
            page_widget.clicked.connect(self.annotation_requested)
            page_widget.annotation_moved.connect(self.annotation_moved)
            page_widget.annotation_edit_requested.connect(self.annotation_edit_requested)
            page_widget.annotation_delete_requested.connect(self.annotation_delete_requested)
            self._page_layout.addWidget(page_widget)
            self._page_widgets.append(page_widget)

            num_label = QLabel(f"— Page {i + 1} —  (double-click annotation to edit, right-click for menu)")
            num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num_label.setStyleSheet("color: palette(dark); font-size: 11px;")
            self._page_layout.addWidget(num_label)

        self._page_count = len(pixmaps)
        self._current_page = 0
        self._page_label.setText(f"{self._page_count} page(s)")
        self._btn_prev.setVisible(False)
        self._btn_next.setVisible(False)

    def set_annotate_mode(self, on: bool) -> None:
        """Toggle annotation placement mode on/off for all page widgets."""
        self._annotate_mode = on
        for pw in self._page_widgets:
            pw.annotate_mode = on

    def _set_preview_mode(self, mode: str) -> None:
        """Switch the toggle buttons and emit mode_changed."""
        self._btn_single.setChecked(mode == "single")
        self._btn_merged.setChecked(mode == "merged")
        self.mode_changed.emit(mode)

    def show_placeholder(self, text: str = "Select a file to preview") -> None:
        self._show_placeholder(text)

    # ── Internal ───────────────────────────────────────────────

    def _render_all_pages(self) -> None:
        """Render every page of the current single file into the scroll area."""
        self._clear_pages()
        if self._current_path is None:
            return

        pw = self._preview_width()
        for i in range(self._page_count):
            pix = MergeService.render_preview(
                self._current_path, page=i,
                max_width=pw, max_height=1200,
            )
            if pix is None:
                continue

            img_label = QLabel()
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_label.setPixmap(pix)
            self._page_layout.addWidget(img_label)
            self._single_page_widgets.append(img_label)

            if self._page_count > 1:
                num_label = QLabel(f"— Page {i + 1} of {self._page_count} —")
                num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                num_label.setStyleSheet("color: palette(dark); font-size: 11px;")
                self._page_layout.addWidget(num_label)

        if not self._single_page_widgets:
            err = QLabel("Could not render this file.")
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setStyleSheet("color: #c00; padding: 20px;")
            self._page_layout.addWidget(err)

    def _show_placeholder(self, text: str = "Select a file to preview") -> None:
        self._merged_mode = False
        self._current_path = None
        self._current_page = 0
        self._page_count = 0
        self._title.setText("")
        self._clear_pages()

        placeholder = QLabel(text)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: palette(dark); font-size: 14px; padding: 40px;")
        self._page_layout.addWidget(placeholder)

        self._btn_prev.setVisible(False)
        self._btn_next.setVisible(False)
        self._page_label.setText("")

    def update_page_annotations(self, annotations: List[TextAnnotation]) -> None:
        """Refresh annotation overlays on existing page widgets.

        Called after an annotation is added/removed so we don't need to
        re-render the entire merged preview.
        """
        for pw in self._page_widgets:
            page_anns = [a for a in annotations if a.page == pw._page_index]
            pw.set_annotations(page_anns)

    def _clear_pages(self) -> None:
        self._page_widgets = []
        self._single_page_widgets = []
        while self._page_layout.count():
            child = self._page_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _preview_width(self) -> int:
        """Target width for rendering pages.

        Use at least 800px for sharp text, but allow viewport to be
        wider if the panel is stretched.
        """
        return max(self._scroll.viewport().width() - 20, 800)

    def _update_nav(self) -> None:
        if self._merged_mode:
            self._btn_prev.setVisible(False)
            self._btn_next.setVisible(False)
            self._page_label.setText(f"{self._page_count} page(s)")
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

    def _scroll_to_page(self, page: int) -> None:
        """Scroll the viewport so that the given page widget is visible."""
        if 0 <= page < len(self._single_page_widgets):
            self._scroll.ensureWidgetVisible(self._single_page_widgets[page], 0, 20)

    def _go_prev(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._scroll_to_page(self._current_page)
            self._update_nav()

    def _go_next(self) -> None:
        if self._current_page < self._page_count - 1:
            self._current_page += 1
            self._scroll_to_page(self._current_page)
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

        from PySide6.QtWidgets import QMenu, QToolButton

        add_menu = QMenu(self)
        self._act_add_files = add_menu.addAction("Files…")
        self._act_add_files.setToolTip("Add PDF or image files")
        self._act_add_files.triggered.connect(self._on_add_files)
        self._act_add_folder = add_menu.addAction("Folder…")
        self._act_add_folder.setToolTip("Add all supported files from a folder")
        self._act_add_folder.triggered.connect(self._on_add_folder)

        self._act_add = QAction("Add…", self)
        self._act_add.setShortcut(QKeySequence("Ctrl+O"))
        self._act_add.setToolTip("Add PDF/image files or folders (Ctrl+O)")
        self._act_add.setMenu(add_menu)
        # Default click (not the dropdown arrow) opens the file picker
        self._act_add.triggered.connect(self._on_add_files)
        tb.addAction(self._act_add)
        # Make the toolbar button show the dropdown arrow
        btn = tb.widgetForAction(self._act_add)
        if isinstance(btn, QToolButton):
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        tb.addSeparator()

        self._act_clear = QAction("Clear All", self)
        self._act_clear.setShortcut(QKeySequence("Ctrl+L"))
        self._act_clear.setToolTip("Remove all files from list (Ctrl+L)")
        self._act_clear.triggered.connect(self._on_clear)
        tb.addAction(self._act_clear)

        tb.addSeparator()

        self._act_annotate = QAction("✏ Annotate", self)
        self._act_annotate.setCheckable(True)
        self._act_annotate.setToolTip(
            "Toggle annotation mode — click on merged preview pages to place text"
        )
        self._act_annotate.toggled.connect(self._on_annotate_toggled)
        tb.addAction(self._act_annotate)

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
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._file_list.currentRowChanged.connect(self._on_selection_changed)
        self._file_list.row_moved.connect(self._on_drag_reorder)
        self._file_list.files_dropped.connect(self._on_external_drop)
        left_layout.addWidget(self._file_list)

        self._splitter.addWidget(left)

        # Right panel — preview
        self._preview = PreviewPanel()
        self._preview.annotation_requested.connect(self._on_annotation_requested)
        self._preview.annotation_moved.connect(self._on_annotation_moved)
        self._preview.annotation_edit_requested.connect(self._on_annotation_edit)
        self._preview.annotation_delete_requested.connect(self._on_annotation_delete)
        self._preview.mode_changed.connect(self._on_preview_mode_changed)
        self._splitter.addWidget(self._preview)

        self._splitter.setSizes([400, 500])

        # Options bar — page numbers, watermark, annotations
        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 4, 0, 0)
        root_layout.addLayout(options_row)

        self._chk_page_numbers = QCheckBox("Page Numbers")
        self._chk_page_numbers.setToolTip("Add page numbers to the merged PDF")
        self._chk_page_numbers.toggled.connect(self._on_quick_toggle_page_numbers)
        options_row.addWidget(self._chk_page_numbers)

        self._chk_watermark = QCheckBox("Watermark")
        self._chk_watermark.setToolTip("Add watermark text to the merged PDF")
        self._chk_watermark.toggled.connect(self._on_quick_toggle_watermark)
        options_row.addWidget(self._chk_watermark)

        self._btn_settings = QPushButton("Settings…")
        self._btn_settings.setToolTip(
            "Configure page number format, watermark text, and other output options"
        )
        self._btn_settings.clicked.connect(self._on_output_options)
        options_row.addWidget(self._btn_settings)

        options_row.addStretch()

        self._btn_clear_annotations = QPushButton("Clear Annotations")
        self._btn_clear_annotations.setToolTip("Remove all text annotations")
        self._btn_clear_annotations.clicked.connect(self._on_clear_annotations)
        options_row.addWidget(self._btn_clear_annotations)

        # Output bar — filename, preview, save
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 2, 0, 0)
        root_layout.addLayout(output_row)

        output_row.addWidget(QLabel("Output:"))

        self._output_name = QLineEdit("merged.pdf")
        self._output_name.setPlaceholderText("merged.pdf")
        self._output_name.setMinimumWidth(200)
        output_row.addWidget(self._output_name, stretch=1)

        self._btn_save = QPushButton("Save Merged PDF")
        self._btn_save.setShortcut(QKeySequence("Ctrl+S"))
        self._btn_save.setToolTip("Merge included files and save (Ctrl+S)")
        self._btn_save.clicked.connect(self._on_save)
        output_row.addWidget(self._btn_save)

    def _build_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

    # ══════════════════════════════════════════════════════════
    # Global key handling
    # ══════════════════════════════════════════════════════════

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Route Delete/Backspace: annotation delete if one is selected, else file remove."""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # Check if any page widget has a selected annotation
            for pw in self._preview._page_widgets:
                if pw.selected is not None:
                    self._on_annotation_delete(pw.selected)
                    return
            # Otherwise remove the currently selected file
            row = self._file_list.currentRow()
            if row >= 0:
                self._on_row_remove(row)
            return
        super().keyPressEvent(event)

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

        for i, entry in enumerate(self._model.entries):
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 30))
            self._file_list.addItem(item)

            row_widget = FileRowWidget(i, entry, self._format_entry(entry))
            row_widget.include_toggled.connect(self._on_row_include)
            row_widget.move_up_clicked.connect(self._on_row_move_up)
            row_widget.move_down_clicked.connect(self._on_row_move_down)
            row_widget.remove_clicked.connect(self._on_row_remove)
            self._file_list.setItemWidget(item, row_widget)

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
                "No files added. Use 'Add…' or drag and drop files/folders to begin."
            )
        else:
            self._statusbar.showMessage(f"{total} file(s) — {included} included for merge")

    # ══════════════════════════════════════════════════════════
    # Toolbar actions
    # ══════════════════════════════════════════════════════════

    def _on_add_files(self) -> None:
        """Open native file picker for PDFs and images."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Files", "", _file_filter())
        if paths:
            self._add_paths([Path(p) for p in paths])

    def _on_add_folder(self) -> None:
        """Open native folder picker, then scan recursively."""
        folder = QFileDialog.getExistingDirectory(self, "Add Folder")
        if folder:
            self._add_paths([Path(folder)])

    def _add_paths(self, paths: List[Path]) -> None:
        """Route a list of paths to the model — files added directly, folders scanned."""
        total_added = 0
        for p in paths:
            if p.is_dir():
                total_added += self._model.add_folder(p)
            elif p.is_file():
                total_added += self._model.add_files([p])
        if total_added > 0:
            self._statusbar.showMessage(f"Added {total_added} file(s).", 3000)
        elif paths:
            self._statusbar.showMessage("No new files added (duplicates or unsupported).", 3000)

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

    def _on_annotate_toggled(self, checked: bool) -> None:
        """Toggle annotation placement mode."""
        self._preview.set_annotate_mode(checked)
        if checked:
            self._statusbar.showMessage(
                "✏ Annotate mode ON — click on merged preview pages to place text", 3000
            )
        else:
            self._statusbar.showMessage("✏ Annotate mode OFF", 2000)

    # ══════════════════════════════════════════════════════════
    # Drag-and-drop handlers
    # ══════════════════════════════════════════════════════════

    def _on_drag_reorder(self, old_row: int, new_row: int) -> None:
        self._model.move(old_row, new_row)
        self._file_list.setCurrentRow(new_row)

    def _on_external_drop(self, paths: list) -> None:
        self._add_dropped_paths(paths)

    def _add_dropped_paths(self, paths: List[Path]) -> None:
        self._add_paths([Path(p) for p in paths])

    # ══════════════════════════════════════════════════════════
    # Inline row actions
    # ══════════════════════════════════════════════════════════

    def _on_row_include(self, row: int, checked: bool) -> None:
        if 0 <= row < len(self._model):
            self._model.set_included(row, checked)

    def _on_row_move_up(self, row: int) -> None:
        if row > 0:
            self._model.move_up(row)
            self._file_list.setCurrentRow(row - 1)

    def _on_row_move_down(self, row: int) -> None:
        if 0 <= row < len(self._model) - 1:
            self._model.move_down(row)
            self._file_list.setCurrentRow(row + 1)

    def _on_row_remove(self, row: int) -> None:
        if 0 <= row < len(self._model):
            self._model.remove([row])
            if self._file_list.count() == 0:
                self._preview.show_placeholder()

    # ══════════════════════════════════════════════════════════
    # Preview
    # ══════════════════════════════════════════════════════════

    def _on_selection_changed(self, row: int) -> None:
        """When a file is clicked in the list, show its single-page preview."""
        if 0 <= row < len(self._model):
            self._preview.show_file(self._model[row].path)
        else:
            self._preview.show_placeholder()

    def _on_preview_mode_changed(self, mode: str) -> None:
        """Handle the Single/Merged toggle in the preview panel."""
        if mode == "merged":
            self._show_merged_preview()
        else:
            row = self._file_list.currentRow()
            if 0 <= row < len(self._model):
                self._preview.show_file(self._model[row].path)
            else:
                self._preview.show_placeholder()

    def _show_merged_preview(self) -> None:
        """Render and display the merged preview."""
        included = self._model.included_entries()
        if not included:
            self._preview.show_placeholder("No included files to preview.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._statusbar.showMessage("Rendering merged preview…")
            self._preview.show_merged(self._model.entries, options=self._output_options)
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
            saved_annotations = self._output_options.annotations
            self._output_options = dlg.get_options()
            self._output_options.annotations = saved_annotations
            self._sync_option_checkboxes()
            self._statusbar.showMessage("Output options updated.", 3000)

    def _on_quick_toggle_page_numbers(self, checked: bool) -> None:
        """Quick-toggle page numbers from the options bar checkbox."""
        self._output_options.page_numbers.enabled = checked

    def _on_quick_toggle_watermark(self, checked: bool) -> None:
        """Quick-toggle watermark from the options bar checkbox."""
        self._output_options.watermark.enabled = checked

    def _sync_option_checkboxes(self) -> None:
        """Sync the quick-toggle checkboxes with the current output options."""
        self._chk_page_numbers.blockSignals(True)
        self._chk_page_numbers.setChecked(self._output_options.page_numbers.enabled)
        self._chk_page_numbers.blockSignals(False)

        self._chk_watermark.blockSignals(True)
        self._chk_watermark.setChecked(self._output_options.watermark.enabled)
        self._chk_watermark.blockSignals(False)

    # ══════════════════════════════════════════════════════════
    # Annotations
    # ══════════════════════════════════════════════════════════

    def _on_annotation_requested(self, page_index: int, x_ratio: float, y_ratio: float) -> None:
        """Handle click on a page in merged preview — open annotation dialog."""
        dlg = AnnotationDialog(page_index, x_ratio, y_ratio, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        ann = dlg.get_annotation(page_index, x_ratio, y_ratio)
        if not ann.text.strip():
            return

        self._output_options.annotations.append(ann)
        self._preview.update_page_annotations(self._output_options.annotations)
        count = len(self._output_options.annotations)
        self._statusbar.showMessage(
            f"Annotation added on page {page_index + 1}  ({count} total)", 3000
        )

    def _on_annotation_moved(self, ann: TextAnnotation) -> None:
        """Handle annotation dragged to a new position (already mutated)."""
        # The annotation's x_ratio/y_ratio were already updated during the drag.
        # Just confirm in the status bar.
        self._statusbar.showMessage(
            f"Annotation moved on page {ann.page + 1}", 2000
        )

    def _on_annotation_edit(self, ann: TextAnnotation) -> None:
        """Open the edit dialog for an existing annotation."""
        dlg = AnnotationDialog(
            ann.page, ann.x_ratio, ann.y_ratio,
            parent=self, existing=ann,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        updated = dlg.get_annotation(ann.page, ann.x_ratio, ann.y_ratio)
        if not updated.text.strip():
            return

        # Mutate the existing annotation in-place so the same object
        # reference stays valid in the page widget.
        ann.text = updated.text
        ann.font_size = updated.font_size
        ann.color = updated.color

        self._preview.update_page_annotations(self._output_options.annotations)
        self._statusbar.showMessage("Annotation updated.", 3000)

    def _on_annotation_delete(self, ann: TextAnnotation) -> None:
        """Delete a single annotation."""
        if ann in self._output_options.annotations:
            self._output_options.annotations.remove(ann)
            self._preview.update_page_annotations(self._output_options.annotations)
            count = len(self._output_options.annotations)
            self._statusbar.showMessage(
                f"Annotation deleted  ({count} remaining)", 3000
            )

    def _on_clear_annotations(self) -> None:
        """Remove all annotations."""
        count = len(self._output_options.annotations)
        if count == 0:
            self._statusbar.showMessage("No annotations to clear.", 3000)
            return
        reply = QMessageBox.question(
            self, "Clear annotations",
            f"Remove all {count} annotation(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._output_options.annotations.clear()
            self._preview.update_page_annotations([])
            self._statusbar.showMessage("All annotations cleared.", 3000)

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
