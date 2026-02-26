"""Build script — produces a standalone binary via PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Output lands in dist/PDFJoiner/ (directory mode) or dist/PDFJoiner.exe (onefile mode).
"""

import platform
import subprocess
import sys


def main() -> None:
    name = "PDFJoiner"
    entry = "main.py"

    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        "--onefile",
        "--windowed",           # no console window on Windows/macOS
        "--noconfirm",          # overwrite previous build without asking
        "--clean",              # clean cache before building
        "--add-data", "LICENSE:.",
        "--add-data", "README.md:.",
        entry,
    ]

    # macOS: set bundle identifier
    if platform.system() == "Darwin":
        args.extend(["--osx-bundle-identifier", "com.pdfjoiner.app"])

    print(f"Building {name} for {platform.system()}...")
    print(f"Command: {' '.join(args)}\n")

    result = subprocess.run(args)

    if result.returncode == 0:
        print(f"\nBuild successful! Binary is in dist/")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
