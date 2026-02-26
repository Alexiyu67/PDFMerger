"""Stateless service for rendering previews and merging PDFs/images.

Uses PyMuPDF (fitz) which handles both PDF pages and images uniformly —
an image is simply opened as a single-page document.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from PySide6.QtGui import QImage, QPixmap

from pdfjoiner.model import FileEntry, OutputOptions, PageNumberOptions, WatermarkOptions


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
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return QPixmap()

    zoom_x = max_width / rect.width
    zoom_y = max_height / rect.height
    zoom = min(zoom_x, zoom_y, 2.0)  # cap at 2x to avoid huge renders

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    # Convert fitz Pixmap → QImage → QPixmap
    qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


# ── Post-merge page stamping ──────────────────────────────────

# A standard A4 page is ~595 × 842 points. User-facing font sizes and
# margins are authored for this reference size and scaled proportionally
# for pages of different dimensions (e.g. high-res images).
_REF_PAGE_HEIGHT = 842.0


def _scale_for_page(page: fitz.Page) -> float:
    """Return a multiplier that scales reference-size values to this page."""
    return page.rect.height / _REF_PAGE_HEIGHT


def _apply_page_numbers(doc: fitz.Document, opts: PageNumberOptions) -> None:
    """Stamp page numbers onto every page of the document.

    Font size and margin are scaled relative to each page's height so
    numbers are legible regardless of whether the page is A4, Letter,
    or a high-resolution image.
    """
    if not opts.enabled:
        return

    total = doc.page_count
    font = fitz.Font("helv")

    for i, page in enumerate(doc):
        number = opts.start + i
        text = opts.format.replace("{n}", str(number)).replace("{total}", str(total))

        rect = page.rect
        scale = _scale_for_page(page)
        font_size = opts.font_size * scale
        margin = opts.margin * scale

        # Vertical position
        pos = opts.position
        if "bottom" in pos:
            y = rect.height - margin
        else:  # top
            y = margin + font_size

        # Horizontal position
        text_width = font.text_length(text, fontsize=font_size)

        if "left" in pos:
            x = margin
        elif "right" in pos:
            x = rect.width - margin - text_width
        else:  # center
            x = (rect.width - text_width) / 2

        # Clamp so text never lands outside the page
        x = max(0, min(x, rect.width - text_width))
        y = max(font_size, min(y, rect.height))

        tw = fitz.TextWriter(page.rect)
        tw.append((x, y), text, font=font, fontsize=font_size)
        tw.write_text(page, color=opts.color)


def _apply_watermark(doc: fitz.Document, opts: WatermarkOptions) -> None:
    """Stamp diagonal watermark text onto every page of the document.

    Font size is scaled relative to each page's height so the watermark
    is proportionally sized on every page.
    """
    if not opts.enabled or not opts.text.strip():
        return

    font = fitz.Font("helv")
    angle_rad = math.radians(opts.angle)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    for page in doc:
        rect = page.rect
        scale = _scale_for_page(page)
        font_size = opts.font_size * scale

        center_x = rect.width / 2
        center_y = rect.height / 2

        text_width = font.text_length(opts.text, fontsize=font_size)

        # Build transform: place text at origin, then rotate + translate to center
        mat = (
            fitz.Matrix(1, 0, 0, 1, center_x, center_y)
            * fitz.Matrix(cos_a, sin_a, -sin_a, cos_a, 0, 0)
            * fitz.Matrix(1, 0, 0, 1, -text_width / 2, font_size / 3)
        )

        tw = fitz.TextWriter(page.rect, opacity=opts.opacity)
        tw.append((0, 0), opts.text, font=font, fontsize=font_size)
        tw.write_text(page, morph=(fitz.Point(0, 0), mat), color=opts.color)


# ── Result dataclass ───────────────────────────────────────────


@dataclass
class MergeResult:
    """Result returned by MergeService.merge()."""

    page_count: int = 0
    skipped: List[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return len(self.skipped) > 0


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

    # ── Validate ───────────────────────────────────────────────

    @staticmethod
    def can_open(path: Path) -> bool:
        """Return True if the file can be opened by PyMuPDF."""
        try:
            with _open_document(path) as doc:
                _ = doc.page_count
            return True
        except Exception:
            return False

    # ── Single-file preview ────────────────────────────────────

    @staticmethod
    def render_preview(
        path: Path,
        page: int = 0,
        max_width: int = 400,
        max_height: int = 600,
    ) -> Optional[QPixmap]:
        """Render a single page/image to a QPixmap.

        Returns QPixmap or None if the file can't be rendered.
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
                return _page_to_pixmap(doc[0], max_width=size, max_height=size)
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
    def merge(
        entries: List[FileEntry],
        output: Path,
        options: Optional[OutputOptions] = None,
    ) -> MergeResult:
        """Merge included entries into a single PDF.

        PDFs are inserted page-by-page. Images are inserted as full pages
        sized to their native dimensions. Output options (page numbers,
        watermark) are applied after assembly.

        Args:
            entries: The full file list (only included=True are used).
            output: Destination path for the merged PDF.
            options: Optional output settings for page numbers / watermark.

        Returns:
            MergeResult with page count and list of skipped filenames.

        Raises:
            ValueError: If no included entries to merge.
            OSError: If the output path is not writable.
        """
        included = [e for e in entries if e.included]
        if not included:
            raise ValueError("No files selected for merging.")

        result = MergeResult()
        output_doc = fitz.open()  # new empty PDF

        for entry in included:
            try:
                src = _open_document(entry.path)
                if entry.is_pdf:
                    output_doc.insert_pdf(src)
                else:
                    # Image: convert to a single-page PDF, then insert
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
                result.skipped.append(f"{entry.filename}: {exc}")
                continue

        if output_doc.page_count == 0:
            output_doc.close()
            raise ValueError(
                "All files failed to process. No output generated.\n\n"
                + "\n".join(result.skipped)
            )

        # ── Apply output options ───────────────────────────────
        if options is not None:
            try:
                _apply_watermark(output_doc, options.watermark)
            except Exception as exc:
                result.skipped.append(f"Watermark: {exc}")

            try:
                _apply_page_numbers(output_doc, options.page_numbers)
            except Exception as exc:
                result.skipped.append(f"Page numbers: {exc}")

        result.page_count = output_doc.page_count
        output_doc.save(str(output))
        output_doc.close()
        return result
