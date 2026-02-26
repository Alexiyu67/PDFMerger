# PDFJoiner

A cross-platform desktop tool for merging PDFs and images into a single PDF.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## Download

Pre-built binaries — no Python required. Pick your platform:

| Platform | Link                                                                                                 |
|----------|------------------------------------------------------------------------------------------------------|
| **Windows** (10/11, 64-bit) | [⬇ PDFJoiner-Windows.zip](https://github.com/Alexiyu67/PDFMerger/releases/latest/download/PDFJoiner-Windows.zip) |
| **macOS** (Apple Silicon) | [⬇ PDFJoiner-macOS.zip](https://github.com/Alexiyu67/PDFMerger/releases/latest/download/PDFJoiner-macOS.zip) |
| **Linux** (x64, Ubuntu 22.04+) | [⬇ PDFJoiner-Linux.tar.gz](https://github.com/Alexiyu67/PDFMerger/releases/latest/download/PDFJoiner-Linux.tar.gz) |

> **First time on macOS?** After extracting, right-click → Open to bypass Gatekeeper.
>
> **Linux:** Make it executable with `chmod +x PDFJoiner` after extracting.

All releases: [Releases page](https://github.com/Alexiyu67/PDFMerger/releases)

---

## Features

- **Merge PDFs and images** — combine any mix of PDF, JPG, PNG, BMP, and TIFF files
- **Drag and drop** — drop files and folders straight from your file manager
- **Live preview** — scroll through all pages, single file or merged result
- **Reorder** — inline ▲/▼ buttons or drag-and-drop to arrange files
- **Include / exclude** — uncheck files to skip them without removing from the list
- **Page numbers** — configurable position, format, font size, and color
- **Watermark** — diagonal semi-transparent text overlay
- **Text annotations** — click-to-place labels anywhere on the merged preview
- **Dark mode** — follows your OS theme automatically
- **Cross-platform** — Windows, macOS, and Linux

---

## Build from source

Requires Python 3.10+.

```bash
git clone https://github.com/Alexiyu67/PDFJoiner.git
cd PDFJoiner
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

To build a standalone binary:

```bash
pip install pyinstaller
python build.py
# output: dist/PDFJoiner.exe (Windows) or dist/PDFJoiner (macOS/Linux)
```

---

## Keyboard shortcuts

| Action                     | Shortcut   |
|----------------------------|------------|
| Add files / folders        | `Ctrl+O`   |
| Save merged PDF            | `Ctrl+S`   |
| Delete file or annotation  | `Delete`   |
| Clear list                 | `Ctrl+L`   |
| About                      | `F1`       |
| Quit                       | `Ctrl+Q`   |

---

## Architecture

```
main.py              → Entry point
pdfjoiner/
├── __init__.py      → Version
├── model.py         → Data model (FileEntry, ProjectModel, OutputOptions)
├── service.py       → PDF/image rendering and merging (PyMuPDF)
└── view.py          → Qt UI (MainWindow, PreviewPanel, dialogs)
```

## Dependencies

| Package  | Purpose                                    | License |
|----------|--------------------------------------------|---------|
| PySide6  | Qt GUI framework (official Python binding) | LGPL    |
| PyMuPDF  | PDF & image reading, rendering, merging    | AGPL    |

## License

MIT — see [LICENSE](LICENSE).
