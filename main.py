"""Entry point for PDFJoiner."""

import sys

from PySide6.QtWidgets import QApplication

from pdfjoiner.model import ProjectModel
from pdfjoiner.view import MainWindow


def _smoke_test() -> None:
    """Quick console check that model + service work. Remove after Step 4."""
    from pathlib import Path
    from pdfjoiner.service import MergeService

    model = ProjectModel()
    model.list_changed.connect(lambda: print(f"  [signal] list_changed → {len(model)} entries"))

    print("── Model smoke test ──")

    project_dir = Path(__file__).parent

    # Scan project root for any PDFs/images
    real = sorted(project_dir.glob("*"))
    added = model.add_files(real)
    print(f"  add_files(project root) → {added} added")
    print(f"  Total entries: {len(model)}")
    print(f"  Included: {len(model.included_entries())}")

    if len(model) > 0:
        model.toggle_included(0)
        print(f"  After toggle(0): included={model[0].included}")
        model.toggle_included(0)

    if len(model) >= 2:
        print(f"  Before move: {[e.filename for e in model.entries]}")
        model.move(0, 1)
        print(f"  After move(0,1): {[e.filename for e in model.entries]}")

    # ── Service smoke test ──
    print("── Service smoke test ──")

    if len(model) > 0:
        entry = model[0]
        pages = MergeService.get_page_count(entry.path)
        print(f"  {entry.filename}: {pages} page(s)")

        thumb = MergeService.render_thumbnail(entry.path)
        print(f"  Thumbnail: {thumb.width()}x{thumb.height()}" if thumb else "  Thumbnail: None")

        preview = MergeService.render_preview(entry.path)
        print(f"  Preview: {preview.width()}x{preview.height()}" if preview else "  Preview: None")
    else:
        print("  (no files found — drop a .pdf or .jpg next to main.py to test)")

    if len(model.included_entries()) >= 2:
        out = project_dir / "_test_merged.pdf"
        total = MergeService.merge(model.entries, out)
        print(f"  Merged {total} pages → {out}")
    else:
        print("  (need 2+ included files to test merge)")

    print("── Smoke test done ──\n")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDFJoiner")
    app.setApplicationVersion("0.1.0")

    _smoke_test()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
