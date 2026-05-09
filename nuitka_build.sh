#!/bin/bash
# Option B: Nuitka build (alternative to PyInstaller / build.bat)
# Requirements:
#   pip install nuitka
#   playwright install chromium

PW_BASE="${LOCALAPPDATA}/ms-playwright"
CHROMIUM_DIR=$(ls -dt "${PW_BASE}"/chromium-* 2>/dev/null | head -1)

if [ -z "$CHROMIUM_DIR" ]; then
    echo "[ERROR] Chromium not found. Run: playwright install chromium"
    exit 1
fi

CHROMIUM_NAME=$(basename "$CHROMIUM_DIR")

python -m nuitka --standalone --onefile \
  --enable-plugin=pyqt6 \
  --include-data-file=./icon.ico=icon.ico \
  --include-data-dir="${CHROMIUM_DIR}"="${CHROMIUM_NAME}" \
  --windows-icon-from-ico=icon.ico \
  --output-filename="Backlink Checker.exe" \
  main.py
