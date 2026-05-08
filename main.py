"""
Entry point for Backlink Checker desktop application.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtWidgets import QApplication

# Log file sits next to the script/executable regardless of working directory
_LOG_PATH = Path(__file__).parent / "backlink_checker.log"

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

from db import database as db  # noqa: E402
from gui.app import MainApp  # noqa: E402


def main():
    db.init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("Backlink Checker")

    window = MainApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
