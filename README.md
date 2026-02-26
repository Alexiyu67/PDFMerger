# PDFJoiner

A cross-platform desktop tool for merging PDFs and images into a single PDF.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

## Features

- **Add files** — PDFs and images (JPG, JPEG, PNG, BMP, TIFF)
- **Add folders** — recursively scan for supported files
- **Preview** — view individual files with page navigation for multi-page PDFs
- **Preview merged** — see what the final combined PDF will look like
- **Reorder** — drag-and-drop or keyboard shortcuts to arrange files
- **Include/exclude** — uncheck files to exclude them without removing from the list
- **Drag and drop** — drop files and folders from your OS file manager
- **Page numbers** — configurable position, format, font size, and color
- **Watermark** — diagonal semi-transparent text with adjustable opacity and angle
- **Text annotations** — click anywhere on the merged preview to place text labels
- **Name the output** — choose a custom filename for the merged PDF
- **Cross-platform** — runs on Windows, macOS, and Linux

## Installation

### From source

Requires Python 3.10 or later.

```bash
git clone https://github.com/youruser/PDFJoiner.git
cd PDFJoiner
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

### Standalone binary

Pre-built binaries are available on the [Releases](https://github.com/youruser/PDFJoiner/releases) page, or you can build your own:

```bash
pip install pyinstaller
python build.py
```

The output binary will be in the `dist/` folder.

## Keyboard shortcuts

| Action               | Shortcut         |
|----------------------|------------------|
| Add files/folders    | `Ctrl+O`         |
| Delete (file or ann.)| `Delete`         |
| Move up              | `Ctrl+Up`        |
| Move down            | `Ctrl+Down`      |
| Save merged          | `Ctrl+S`         |
| Clear list           | `Ctrl+L`         |
| About                | `F1`             |
| Quit                 | `Ctrl+Q`         |

## Architecture

```
main.py          → Entry point
pdfjoiner/
├── __init__.py  → Version
├── model.py     → Data model (FileEntry, ProjectModel, OutputOptions, TextAnnotation)
├── service.py   → PDF/image rendering and merging (PyMuPDF)
└── view.py      → Qt UI (MainWindow, PreviewPanel, AnnotatedPageWidget, FileListWidget)
```

**Model–View–Service** separation: the model holds state and emits signals, the view reacts and delegates to stateless service functions. No circular dependencies.

## Dependencies

| Package  | Purpose                                    | License  |
|----------|--------------------------------------------|----------|
| PySide6  | Qt GUI framework (official Python binding)  | LGPL     |
| PyMuPDF  | PDF & image reading, rendering, merging     | AGPL     |

## Supported file types

PDF, JPG, JPEG, PNG, BMP, TIFF, TIF

## License

MIT — see [LICENSE](LICENSE).
