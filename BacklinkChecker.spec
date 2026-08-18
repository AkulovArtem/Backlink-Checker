"""
BacklinkChecker — PyInstaller onefile spec.

Before building (Python 3.13):
    pip install -r requirements.txt
    playwright install chromium   (once on the build machine)

Build:
    pyinstaller BacklinkChecker.spec --clean --noconfirm
"""

import os
import playwright
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── Playwright paths ─────────────────────────────────────────
_pw_dir = Path(playwright.__file__).parent
_pw_driver_dir = _pw_dir / "driver"
_pw_node = _pw_driver_dir / "node.exe"
_pw_package = _pw_driver_dir / "package"

if not _pw_node.exists():
    raise SystemExit(f"[ERROR] playwright node.exe not found at {_pw_node}")

# ── Browser paths ───────────────────────────────────────────
# headless=True  → chromium_headless_shell-XXXX  (used by this app)
# headless=False → chromium-XXXX                 (not used, not bundled)
_local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
_pw_browsers = _local_app / "ms-playwright"

_shell_dirs = sorted(_pw_browsers.glob("chromium_headless_shell-*"))
if not _shell_dirs:
    raise SystemExit(
        "\n[ERROR] chromium_headless_shell not found.\n"
        "Run first:  playwright install chromium\n"
    )
_shell_dir = _shell_dirs[-1]

print(f"[spec] playwright    : {_pw_dir}")
print(f"[spec] node.exe      : {_pw_node.stat().st_size // 1024 // 1024} MB")
print(f"[spec] headless shell: {_shell_dir.name}")
print(f"[spec] shell size    : {sum(f.stat().st_size for f in _shell_dir.rglob('*') if f.is_file()) // 1024 // 1024} MB")

# ── Playwright Python submodules + data files (excluding driver binaries) ─────
_pw_hiddenimports = collect_submodules("playwright")
_pw_datas = collect_data_files(
    "playwright",
    excludes=["**/driver/node.exe", "**/driver/package/**"],
)

# ───────────────────────────────────────────────────────────────

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[
        # node.exe as a binary → PyInstaller preserves execute permission
        (str(_pw_node), "playwright/driver"),
    ],
    datas=[
        ("icon.ico", "."),
        # Playwright JS scripts (loaded by node.exe at runtime)
        (str(_pw_package), "playwright/driver/package"),
        # Headless shell (used when headless=True — the only mode this app uses)
        (str(_shell_dir), _shell_dir.name),
        *_pw_datas,
    ],
    hiddenimports=_pw_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Backlink Checker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX corrupts Chromium binaries
    upx_exclude=[],
    runtime_tmpdir="%LOCALAPPDATA%\\BacklinkChecker",  # cache extraction → fast after first run
    console=False,
    icon="icon.ico",
)
