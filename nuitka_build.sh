#!/bin/bash
python -m nuitka --standalone --onefile \
  --enable-plugin=pyqt6 \
  --include-data-dir=./assets=assets \
  --windows-icon-from-ico=assets/icon.ico \
  --output-filename=BacklinkChecker.exe \
  main.py
