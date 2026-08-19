"""
BacklinkChecker — PyInstaller macOS .app spec (Apple Silicon only).

Before building (Python 3.13):
    pip install -r requirements.txt
    python -m playwright install chromium

Build:
    ./build_macos.sh
    # or: pyinstaller BacklinkChecker.macos.spec --clean --noconfirm
"""

import json
import platform
import sys
from pathlib import Path

import playwright
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

from gui.constants import APP_VERSION

if sys.platform != "darwin":
    raise SystemExit("[ERROR] BacklinkChecker.macos.spec is for macOS only")

if platform.machine() != "arm64":
    raise SystemExit("[ERROR] Apple Silicon (arm64) Python is required")

# ── Playwright paths ─────────────────────────────────────────
_pw_dir = Path(playwright.__file__).parent
_pw_driver_dir = _pw_dir / "driver"
_pw_node = _pw_driver_dir / "node"
_pw_package = _pw_driver_dir / "package"

if not _pw_node.exists():
    raise SystemExit(f"[ERROR] playwright node not found at {_pw_node}")

# ── Browser paths ───────────────────────────────────────────
# headless=True  → chromium_headless_shell-XXXX
_pw_browsers = Path.home() / "Library" / "Caches" / "ms-playwright"
_expected_rev = None
_browsers_json = _pw_package / "browsers.json"
if _browsers_json.exists():
    _data = json.loads(_browsers_json.read_text())
    for _browser in _data.get("browsers", []):
        if _browser.get("name") == "chromium-headless-shell":
            _expected_rev = str(_browser.get("revision"))
            break

if _expected_rev:
    _shell_dir = _pw_browsers / f"chromium_headless_shell-{_expected_rev}"
else:
    _shell_dirs = sorted(_pw_browsers.glob("chromium_headless_shell-*"))
    _shell_dir = _shell_dirs[-1] if _shell_dirs else Path()

if not _shell_dir.is_dir():
    raise SystemExit(
        "\n[ERROR] chromium_headless_shell not found.\n"
        "Run first:  python -m playwright install chromium\n"
    )

_shell_bytes = sum(f.stat().st_size for f in _shell_dir.rglob("*") if f.is_file())
print(f"[spec] playwright    : {_pw_dir}")
print(f"[spec] node          : {_pw_node.stat().st_size // 1024 // 1024} MB")
print(f"[spec] headless shell: {_shell_dir.name}")
print(f"[spec] shell size    : {_shell_bytes // 1024 // 1024} MB")

_pw_hiddenimports = collect_submodules("playwright")
_pw_datas = collect_data_files(
    "playwright",
    excludes=["**/driver/node", "**/driver/node.exe", "**/driver/package/**"],
)

# ───────────────────────────────────────────────────────────────

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[
        (str(_pw_node), "playwright/driver"),
    ],
    datas=[
        ("icon.ico", "."),
        ("icon.icns", "."),
        (str(_pw_package), "playwright/driver/package"),
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
    [],
    exclude_binaries=True,
    name="Backlink Checker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="icon.icns",
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Backlink Checker",
)

app = BUNDLE(
    coll,
    name="Backlink Checker.app",
    icon="icon.icns",
    bundle_identifier="ru.artemakulov.backlinkchecker",
    info_plist={
        "CFBundleName": "Backlink Checker",
        "CFBundleDisplayName": "Backlink Checker",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleIdentifier": "ru.artemakulov.backlinkchecker",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
)
