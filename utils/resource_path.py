import sys
from pathlib import Path

_APP_SUPPORT_NAME = "Backlink Checker"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bundle_dir() -> Path:
    """Read-only files inside the frozen app, or the project root in dev."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return _project_root()


def _data_dir() -> Path:
    """Writable files: Application Support on a frozen Mac app, otherwise next to the EXE / project."""
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / _APP_SUPPORT_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return _project_root()


def resource_path(relative: str) -> str:
    """Absolute path to a read-only bundled resource (icon, etc.)."""
    return str(_bundle_dir() / relative)


def data_path(filename: str) -> Path:
    """Absolute path for writable persistent files (DB, logs)."""
    return _data_dir() / filename
