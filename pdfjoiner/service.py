"""Stateless service for rendering previews and merging PDFs/images.

Uses PyMuPDF (fitz) which handles both PDF pages and images uniformly —
an image is simply opened as a single-page document.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPixmap

from pdfjoiner.model import FileEntry


def _open_document(path: Path) -> fitz.Document:
    """Open a file as a fitz Document.

    PDFs open natively. Images are opened via fitz which wraps them
    as single-page documents, giving us a uniform API.
    """
    return fitz.open(str(path))


def _page_to_pixmap(
    page: fitz.Page,
    max_width: int = 400,
    max_height: int = 600,
) -> QPixmap:
    """Render a fitz Page to a QPixmap, scaled to fit within max dimensions."""
    # Calculate zoom to fit within bounds while preserving aspect ratio
    rect = page.rect
    zoom_x = max_width / rect.width if rect.width > 0 else 1.0
    zoom_y = max_height / rect.height if rect.height > 0 else 1.0
    zoom = min(zoom_x, zoom_y, 2.0)  # cap at 2x to avoid huge renders

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    # Convert fitz Pixmap → QImage → QPixmap
    qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


class MergeService:
    """Stateless helpers for preview rendering and PDF merging."""

    # ── Page count ─────────────────────────────────────────────

    @staticmethod
    def get_page_count(path: Path) -> int:
        """Return the number of pages in a PDF, or 1 for an image."""
        try:
            with _open_document(path) as doc:
                return doc.page_count
        except Exception:
            return 1

    # ── Single-file preview ────────────────────────────────────

    @staticmethod
    def render_preview(
        path: Path,
        page: int = 0,
        max_width: int = 400,
        max_height: int = 600,
    ) -> Optional[QPixmap]:
        """Render a single page/image to a QPixmap.

        Args:
            path: File to render.
            page: Page index (0-based). Ignored for images.
            max_width: Maximum pixel width of the result.
            max_height: Maximum pixel height of the result.

        Returns:
            QPixmap or None if the file can't be rendered.
        """
        try:
            with _open_document(path) as doc:
                page_index = min(page, doc.page_count - 1)
                return _page_to_pixmap(doc[page_index], max_width, max_height)
        except Exception:
            return None

    # ── Thumbnail (small, cached on FileEntry) ─────────────────

    @staticmethod
    def render_thumbnail(path: Path, size: int = 64) -> Optional[QPixmap]:
        """Render a small square-ish thumbnail for the file list."""
        try:
            with _open_document(path) as doc:
                pix = _page_to_pixmap(doc[0], max_width=size, max_height=size)
                return pix
        except Exception:
            return None

    # ── Merged preview ─────────────────────────────────────────

    @staticmethod
    def render_merged_preview(
        entries: List[FileEntry],
        max_width: int = 400,
        max_height: int = 600,
    ) -> List[QPixmap]:
        """Render every page of the would-be merged document.

        Returns a list of QPixmaps, one per output page.
        """
        pixmaps: List[QPixmap] = []
        for entry in entries:
            if not entry.included:
                continue
            try:
                with _open_document(entry.path) as doc:
                    for page in doc:
                        pixmaps.append(_page_to_pixmap(page, max_width, max_height))
            except Exception:
                continue
        return pixmaps

    # ── Merge to PDF ───────────────────────────────────────────

    @staticmethod
    def merge(entries: List[FileEntry], output: Path) -> int:
        """Merge included entries into a single PDF.

        PDFs are inserted page-by-page. Images are inserted as full pages
        sized to their native dimensions.

        Args:
            entries: The full file list (only included=True are used).
            output: Destination path for the merged PDF.

        Returns:
            Total page count of the output PDF.

        Raises:
            ValueError: If no included entries to merge.
            OSError: If the output path is not writable.
        """
        included = [e for e in entries if e.included]
        if not included:
            raise ValueError("No files selected for merging.")

        output_doc = fitz.open()  # new empty PDF

        for entry in included:
            try:
                src = _open_document(entry.path)
                if entry.is_pdf:
                    output_doc.insert_pdf(src)
                else:
                    # Image: convert to a single-page PDF, then insert
                    img_pdf = fitz.open()  # temp single-page PDF
                    img_page = img_pdf.new_page(
                        width=src[0].rect.width,
                        height=src[0].rect.height,
                    )
                    img_page.insert_image(img_page.rect, filename=str(entry.path))
                    output_doc.insert_pdf(img_pdf)
                    img_pdf.close()
                src.close()
            except Exception as exc:
                # Skip files that fail — don't abort the whole merge
                print(f"Warning: skipping {entry.filename}: {exc}")
                continue

        total = output_doc.page_count
        output_doc.save(str(output))
        output_doc.close()
        return total
