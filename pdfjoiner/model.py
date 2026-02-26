"""Data model for PDFJoiner — the single source of truth for file list state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

# File extensions we accept
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


def is_supported(path: Path) -> bool:
    """Return True if the file extension is one we can handle."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


@dataclass
class FileEntry:
    """A single file in the merge list."""

    path: Path
    included: bool = True
    page_count: int = 1
    thumbnail: Optional[QPixmap] = field(default=None, repr=False)

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def is_pdf(self) -> bool:
        return self.path.suffix.lower() == ".pdf"

    @property
    def is_image(self) -> bool:
        return self.path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


class ProjectModel(QObject):
    """Manages the ordered list of FileEntry objects.

    All mutations go through public methods which emit signals
    so the view can react. The view never mutates this directly.
    """

    # Emitted whenever the list changes (add, remove, reorder, toggle)
    list_changed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._entries: List[FileEntry] = []

    # ── Accessors ──────────────────────────────────────────────

    @property
    def entries(self) -> List[FileEntry]:
        """Return a shallow copy so callers can't mutate the list directly."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> FileEntry:
        return self._entries[index]

    def included_entries(self) -> List[FileEntry]:
        """Return only entries with included=True, preserving order."""
        return [e for e in self._entries if e.included]

    # ── Add ────────────────────────────────────────────────────

    def add_files(self, paths: List[Path]) -> int:
        """Add files to the end of the list. Returns number actually added.

        Skips unsupported extensions and duplicates (same absolute path).
        """
        existing = {e.path.resolve() for e in self._entries}
        added = 0
        for p in paths:
            p = Path(p)
            if not p.is_file():
                continue
            if not is_supported(p):
                continue
            if p.resolve() in existing:
                continue
            self._entries.append(FileEntry(path=p))
            existing.add(p.resolve())
            added += 1
        if added:
            self.list_changed.emit()
        return added

    def add_folder(self, folder: Path) -> int:
        """Recursively scan a folder for supported files and add them.

        Files are sorted alphabetically within the folder. Returns count added.
        """
        folder = Path(folder)
        if not folder.is_dir():
            return 0
        paths = sorted(
            p for p in folder.rglob("*") if p.is_file() and is_supported(p)
        )
        return self.add_files(paths)

    # ── Remove ─────────────────────────────────────────────────

    def remove(self, indices: List[int]) -> None:
        """Remove entries at the given indices."""
        to_remove = set(indices)
        before = len(self._entries)
        self._entries = [
            e for i, e in enumerate(self._entries) if i not in to_remove
        ]
        if len(self._entries) != before:
            self.list_changed.emit()

    def clear(self) -> None:
        """Remove all entries."""
        if self._entries:
            self._entries.clear()
            self.list_changed.emit()

    # ── Reorder ────────────────────────────────────────────────

    def move(self, old_index: int, new_index: int) -> None:
        """Move an entry from old_index to new_index."""
        if old_index == new_index:
            return
        if not (0 <= old_index < len(self._entries)):
            return
        if not (0 <= new_index < len(self._entries)):
            return
        entry = self._entries.pop(old_index)
        self._entries.insert(new_index, entry)
        self.list_changed.emit()

    def move_up(self, index: int) -> None:
        """Move entry one position earlier in the list."""
        self.move(index, index - 1)

    def move_down(self, index: int) -> None:
        """Move entry one position later in the list."""
        self.move(index, index + 1)

    # ── Include / Exclude ──────────────────────────────────────

    def toggle_included(self, index: int) -> None:
        """Toggle the included flag on the entry at index."""
        if 0 <= index < len(self._entries):
            self._entries[index].included = not self._entries[index].included
            self.list_changed.emit()

    def set_included(self, index: int, included: bool) -> None:
        """Explicitly set the included flag on the entry at index."""
        if 0 <= index < len(self._entries):
            if self._entries[index].included != included:
                self._entries[index].included = included
                self.list_changed.emit()
