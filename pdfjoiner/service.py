"""Stateless service for rendering previews and merging PDFs/images.

Uses PyMuPDF (fitz) which handles both PDF pages and images uniformly —
an image is simply opened as a single-page document.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
from PySide6.QtGui import QImage, QPixmap

from pdfjoiner.model import FileEntry, OutputOptions, PageNumberOptions, WatermarkOptions


def _open_document(path: Path) -> fitz.Document:
    """Open a file as a fitz Document."""
    return fitz.open(str(path))


def _page_to_pixmap(
    page: fitz.Page,
    max_width: int = 400,
    max_height: int = 600,
) -> QPixmap:
    """Render a fitz Page to a QPixmap, scaled to fit within max dimensions."""
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return QPixmap()

    zoom_x = max_width / rect.width
    zoom_y = max_height / rect.height
    zoom = min(zoom_x, zoom_y, 2.0)

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def _rotation_matrix(degrees: float) -> fitz.Matrix:
    """Build a proper rotation Matrix from an angle in degrees.

    fitz.Matrix(n) with one arg is a *scaling* matrix, not rotation.
    We must build the 2-D rotation manually.
    """
    rad = math.radians(degrees)
    c = math.cos(rad)
    s = math.sin(rad)
    return fitz.Matrix(c, s, -s, c, 0, 0)


# ══════════════════════════════════════════════════════════════
# Build merged document (shared by merge + preview)
# ══════════════════════════════════════════════════════════════


def _build_merged_doc(
    entries: List[FileEntry],
) -> Tuple[fitz.Document, List[str]]:
    """Assemble included entries into a single fitz.Document in memory.

    Returns (document, list_of_skipped_descriptions).
    Caller is responsible for closing the document.
    """
    skipped: List[str] = []
    output_doc = fitz.open()

    for entry in entries:
        if not entry.included:
            continue
        try:
            src = _open_document(entry.path)
            if entry.is_pdf:
                output_doc.insert_pdf(src)
            else:
                img_pdf = fitz.open()
                img_page = img_pdf.new_page(
                    width=src[0].rect.width,
                    height=src[0].rect.height,
                )
                img_page.insert_image(img_page.rect, filename=str(entry.path))
                output_doc.insert_pdf(img_pdf)
                img_pdf.close()
            src.close()
        except Exception as exc:
            skipped.append(f"{entry.filename}: {exc}")

    return output_doc, skipped


def _flush_doc(doc: fitz.Document) -> fitz.Document:
    """Save a document to bytes and reopen it.

    PyMuPDF sometimes needs a save/reload cycle for newly inserted
    content (text overlays) to become visible to get_pixmap().
    """
    pdf_bytes = doc.tobytes()
    doc.close()
    return fitz.open("pdf", pdf_bytes)


# ══════════════════════════════════════════════════════════════
# Post-merge page stamping
# ══════════════════════════════════════════════════════════════

_REF_PAGE_HEIGHT = 842.0


def _scale_for_page(page: fitz.Page) -> float:
    return page.rect.height / _REF_PAGE_HEIGHT


def _apply_page_numbers(doc: fitz.Document, opts: PageNumberOptions) -> None:
    """Stamp page numbers onto every page using Shape objects.

    Shape.finish() supports fill_opacity and ensures text is committed
    to the page content stream reliably.
    """
    if not opts.enabled:
        return

    total = doc.page_count

    for i in range(total):
        page = doc[i]
        number = opts.start + i
        text = opts.format.replace("{n}", str(number)).replace("{total}", str(total))

        rect = page.rect
        scale = _scale_for_page(page)
        font_size = opts.font_size * scale
        margin = opts.margin * scale

        text_width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)

        pos = opts.position
        if "bottom" in pos:
            y = rect.height - margin
        else:
            y = margin + font_size

        if "left" in pos:
            x = margin
        elif "right" in pos:
            x = rect.width - margin - text_width
        else:
            x = (rect.width - text_width) / 2

        x = max(2, min(x, rect.width - text_width - 2))
        y = max(font_size + 2, min(y, rect.height - 2))

        shape = page.new_shape()
        shape.insert_text(
            fitz.Point(x, y),
            text,
            fontname="helv",
            fontsize=font_size,
            color=opts.color,
        )
        shape.finish()
        shape.commit(overlay=True)


def _apply_watermark(doc: fitz.Document, opts: WatermarkOptions) -> None:
    """Stamp diagonal watermark text onto every page.

    Uses Shape objects which support fill_opacity for transparency and
    morph for rotation.  A proper rotation matrix is built from the angle.
    """
    if not opts.enabled or not opts.text.strip():
        return

    rot = _rotation_matrix(opts.angle)

    for i in range(doc.page_count):
        page = doc[i]
        rect = page.rect
        scale = _scale_for_page(page)
        font_size = opts.font_size * scale

        text_width = fitz.get_text_length(opts.text, fontname="helv", fontsize=font_size)

        center = fitz.Point(rect.width / 2, rect.height / 2)

        # Position text so its visual center aligns with the page center
        text_start = fitz.Point(
            center.x - text_width / 2,
            center.y + font_size / 3,
        )

        shape = page.new_shape()
        shape.insert_text(
            text_start,
            opts.text,
            fontname="helv",
            fontsize=font_size,
            color=opts.color,
            morph=(center, rot),
        )
        shape.finish(fill_opacity=opts.opacity)
        shape.commit(overlay=True)


def _apply_output_options(doc: fitz.Document, options: OutputOptions) -> List[str]:
    """Apply all output options to a merged document."""
    warnings: List[str] = []

    try:
        _apply_watermark(doc, options.watermark)
    except Exception as exc:
        warnings.append(f"Watermark: {exc}")

    try:
        _apply_page_numbers(doc, options.page_numbers)
    except Exception as exc:
        warnings.append(f"Page numbers: {exc}")

    return warnings


# ══════════════════════════════════════════════════════════════
# Result dataclass
# ══════════════════════════════════════════════════════════════


@dataclass
class MergeResult:
    """Result returned by MergeService.merge()."""

    page_count: int = 0
    skipped: List[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return len(self.skipped) > 0


# ══════════════════════════════════════════════════════════════
# Public service
# ══════════════════════════════════════════════════════════════


class MergeService:
    """Stateless helpers for preview rendering and PDF merging."""

    @staticmethod
    def get_page_count(path: Path) -> int:
        try:
            with _open_document(path) as doc:
                return doc.page_count
        except Exception:
            return 1

    @staticmethod
    def can_open(path: Path) -> bool:
        try:
            with _open_document(path) as doc:
                _ = doc.page_count
            return True
        except Exception:
            return False

    @staticmethod
    def render_preview(
        path: Path,
        page: int = 0,
        max_width: int = 400,
        max_height: int = 600,
    ) -> Optional[QPixmap]:
        try:
            with _open_document(path) as doc:
                page_index = min(page, doc.page_count - 1)
                return _page_to_pixmap(doc[page_index], max_width, max_height)
        except Exception:
            return None

    @staticmethod
    def render_thumbnail(path: Path, size: int = 64) -> Optional[QPixmap]:
        try:
            with _open_document(path) as doc:
                return _page_to_pixmap(doc[0], max_width=size, max_height=size)
        except Exception:
            return None

    @staticmethod
    def render_merged_preview(
        entries: List[FileEntry],
        max_width: int = 400,
        max_height: int = 600,
        options: Optional[OutputOptions] = None,
    ) -> List[QPixmap]:
        """Render every page of the would-be merged document.

        If options are provided, page numbers and watermark are stamped
        onto the in-memory document, then it is flushed (saved to bytes
        and reopened) so get_pixmap() sees the changes.
        """
        doc, _ = _build_merged_doc(entries)

        if options is not None:
            _apply_output_options(doc, options)
            # Flush: save to bytes and reopen so overlays are rendered
            doc = _flush_doc(doc)

        pixmaps: List[QPixmap] = []
        for page in doc:
            pixmaps.append(_page_to_pixmap(page, max_width, max_height))

        doc.close()
        return pixmaps

    @staticmethod
    def merge(
        entries: List[FileEntry],
        output: Path,
        options: Optional[OutputOptions] = None,
    ) -> MergeResult:
        """Merge included entries into a single PDF and save to disk."""
        included = [e for e in entries if e.included]
        if not included:
            raise ValueError("No files selected for merging.")

        result = MergeResult()
        output_doc, skipped = _build_merged_doc(entries)
        result.skipped.extend(skipped)

        if output_doc.page_count == 0:
            output_doc.close()
            raise ValueError(
                "All files failed to process. No output generated.\n\n"
                + "\n".join(result.skipped)
            )

        if options is not None:
            warnings = _apply_output_options(output_doc, options)
            result.skipped.extend(warnings)

        result.page_count = output_doc.page_count
        output_doc.save(str(output))
        output_doc.close()
        return result
