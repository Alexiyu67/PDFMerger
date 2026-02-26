# PDFJoiner — User Manual

## Getting started

Launch **PDFJoiner** by running the executable (or `python main.py` from source). You'll see a two-panel interface: the **file list** on the left and the **preview** on the right.

---

## 1. Adding files

There are three ways to add files:

- **Add… button** (toolbar, or `Ctrl+O`) — click it to open a file picker, or click the small ▾ arrow to choose between *Files…* and *Folder…*
- **Drag and drop** — drag files or folders from your file manager directly onto the file list
- **Folder scan** — when you add a folder, PDFJoiner recursively finds all supported files inside it (PDF, JPG, JPEG, PNG, BMP, TIFF)

Files appear in the list in the order they were added. Each row shows the filename, file type, and page count.

---

## 2. Organizing files

Each file row has inline controls:

| Control | Action |
|---------|--------|
| **☑ checkbox** | Include or exclude the file from the merge. Unchecked files are skipped but stay in the list. |
| **▲ / ▼** | Move the file up or down in the merge order. |
| **✕** | Remove the file from the list entirely. |

You can also **drag and drop** rows within the list to reorder them.

**Clear All** (toolbar) removes every file from the list.

---

## 3. Previewing

The right panel has two modes, toggled at the top:

- **Single** — shows all pages of whichever file is selected in the list. Click a file to switch to this mode automatically.
- **Merged** — renders the final combined PDF with all output options applied (page numbers, watermark, annotations).

In both modes you can **scroll** through pages freely. In Single mode, **◀ Prev / Next ▶** buttons also jump between pages.

---

## 4. Output options

The options bar sits between the file list and the save button:

- **☐ Page Numbers** — toggle on to stamp page numbers on every page. Click **Settings…** to configure position (top/bottom, left/center/right), format (`Page 1`, `1 / 5`, etc.), font size, and color.
- **☐ Watermark** — toggle on to overlay diagonal text. In **Settings…** you can set the watermark text, font size, opacity (0–100%), rotation angle, and color.
- **Output filename** — type your desired filename in the text box (`.pdf` is added automatically if omitted).

---

## 5. Text annotations

1. Click the **✏ Annotate** button in the toolbar to enter annotation mode (the cursor changes to a crosshair).
2. Switch to **Merged** preview.
3. Click anywhere on a page — a dialog appears where you enter text, font size, and color.
4. The annotation appears at the clicked position.

### Editing annotations

These actions work regardless of whether Annotate mode is on:

| Action | How |
|--------|-----|
| **Select** | Click an annotation — it gets a blue dashed border. |
| **Move** | Drag a selected annotation to a new position. |
| **Edit** | Double-click an annotation, or right-click → *Edit Annotation…* |
| **Delete** | Select it and press `Delete`, or right-click → *Delete Annotation* |

**Clear Annotations** (in the options bar) removes all annotations at once.

---

## 6. Saving the merged PDF

Click **Save Merged PDF** (or `Ctrl+S`). A save-file dialog opens with your chosen output filename pre-filled. The final PDF includes all included files in list order, with page numbers, watermark, and annotations baked in.

---

## 7. Dark mode

PDFJoiner follows your operating system's theme automatically. No manual toggle is needed — if your OS is set to dark mode, the app will use dark colors throughout.

---

## 8. Keyboard shortcuts

| Action                            | Shortcut   |
|-----------------------------------|------------|
| Add files / folders               | `Ctrl+O`   |
| Save merged PDF                   | `Ctrl+S`   |
| Delete selected file or annotation| `Delete`   |
| Clear all files                   | `Ctrl+L`   |
| About                             | `F1`       |
| Quit                              | `Ctrl+Q`   |

---

## Supported file types

| Type | Extensions |
|------|-----------|
| PDF  | `.pdf` |
| JPEG | `.jpg`, `.jpeg` |
| PNG  | `.png` |
| BMP  | `.bmp` |
| TIFF | `.tif`, `.tiff` |

---

## Troubleshooting

**"Could not render this file"** — the file may be corrupted or password-protected. PDFJoiner cannot open encrypted PDFs.

**macOS: "app is damaged" / won't open** — right-click the app → Open, or run `xattr -cr PDFJoiner` in Terminal.

**Linux: nothing happens on launch** — make sure the binary is executable (`chmod +x PDFJoiner`) and that you have OpenGL libraries installed (`sudo apt install libegl1 libopengl0`).

**Preview looks blurry** — try making the preview panel wider; pages render at the panel width (minimum 800px).
