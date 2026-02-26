"""Entry point for PDFJoiner."""

import sys

from PySide6.QtWidgets import QApplication

from pdfjoiner.model import ProjectModel
from pdfjoiner.view import MainWindow


def _smoke_test_model() -> None:
    """Quick console check that the model works. Remove after Step 2."""
    from pathlib import Path

    model = ProjectModel()
    model.list_changed.connect(lambda: print(f"  [signal] list_changed → {len(model)} entries"))

    print("── Model smoke test ──")

    # Try adding the project directory itself (will find .py files → skipped, but tests the path)
    project_dir = Path(__file__).parent
    added = model.add_folder(project_dir / "pdfjoiner")
    print(f"  add_folder('pdfjoiner/') → {added} files added (expect 0, no PDFs/images)")

    # Simulate with fake paths — won't add because files don't exist, which is correct
    fake = [Path("fake_report.pdf"), Path("fake_photo.jpg")]
    added = model.add_files(fake)
    print(f"  add_files(fake paths) → {added} added (expect 0, files don't exist)")

    # Test with real files if any PDFs/images happen to exist next to main.py
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

    print("── Smoke test done ──\n")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDFJoiner")
    app.setApplicationVersion("0.1.0")

    _smoke_test_model()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
