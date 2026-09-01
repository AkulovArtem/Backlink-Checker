"""
Entry point for Backlink Checker desktop application.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

# When frozen by PyInstaller, point playwright to the user-level browser install
# so Chromium is found without needing it bundled inside the EXE.
if getattr(sys, "frozen", False) and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    # Chromium is bundled inside the EXE; PyInstaller extracts it to _MEIPASS at runtime.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = getattr(sys, "_MEIPASS")

from utils.resource_path import data_path, resource_path

# Log file sits next to the EXE (frozen) or project root (dev)
_LOG_PATH = data_path("backlink_checker.log")

# Configure logging before importing anything else
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            _LOG_PATH,
            maxBytes=5 * 1024 * 1024,   # 5 MB per file
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

from db import database as db
from gui.app import MainApp


def main():
    db.init_db()

    # Tell Windows to use our EXE icon in the taskbar instead of the generic Python one.
    # Must be set before QApplication is created.
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BacklinkChecker.App")

    app = QApplication(sys.argv)
    app.setApplicationName("Backlink Checker")
    app.setWindowIcon(QIcon(resource_path("icon.ico")))

    window = MainApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
