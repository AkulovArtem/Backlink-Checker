import sys
from pathlib import Path


def _app_dir() -> Path:
    """EXE folder when frozen (PyInstaller), project root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> str:
    """Absolute path to a read-only bundled resource (icon, etc.)."""
    base = Path(getattr(sys, "_MEIPASS", _app_dir()))
    return str(base / relative)


def data_path(filename: str) -> Path:
    """Absolute path for writable persistent files (DB, logs) — always next to the EXE."""
    return _app_dir() / filename
