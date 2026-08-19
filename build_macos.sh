#!/usr/bin/env bash
# Build an unsigned Apple Silicon DMG for Backlink Checker.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "[ERROR] Apple Silicon Mac required (darwin/arm64)."
  exit 1
fi

PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

VERSION="$("$PYTHON" -c "from gui.constants import APP_VERSION; print(APP_VERSION)")"
APP_NAME="Backlink Checker"
APP_PATH="dist/${APP_NAME}.app"
DMG_NAME="BacklinkChecker-${VERSION}-macos-arm64.dmg"
DMG_PATH="dist/${DMG_NAME}"

echo "============================================"
echo "  Backlink Checker ${VERSION} — macOS arm64"
echo "============================================"

echo
echo "[1/4] Installing pinned dependencies..."
"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" -m PyInstaller --version

echo
echo "[2/4] Checking Playwright Chromium..."
if ! "$PYTHON" - <<'PY'
import json
from pathlib import Path
import playwright

pkg = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
expected = None
if pkg.exists():
    data = json.loads(pkg.read_text())
    for browser in data.get("browsers", []):
        if browser.get("name") == "chromium-headless-shell":
            expected = f"chromium_headless_shell-{browser.get('revision')}"
            break

cache = Path.home() / "Library" / "Caches" / "ms-playwright"
installed = sorted(p.name for p in cache.glob("chromium_headless_shell-*"))
print("Expected :", expected)
print("Installed:", installed)
if expected and expected not in installed:
    raise SystemExit(1)
if not installed:
    raise SystemExit(1)
print("OK")
PY
then
  echo "Installing Chromium via Playwright..."
  "$PYTHON" -m playwright install chromium
fi

if [[ ! -f icon.icns ]]; then
  echo "[ERROR] icon.icns is missing."
  exit 1
fi

echo
echo "[3/4] Building .app (this may take several minutes)..."
"$PYTHON" -m PyInstaller BacklinkChecker.macos.spec --clean --noconfirm
if [[ ! -d "$APP_PATH" ]]; then
  echo "[ERROR] $APP_PATH not found"
  exit 1
fi

# Ad-hoc signature so the local copy launches. Downloaded DMG still needs
# right-click → Open because there is no Apple Developer ID.
codesign --force --deep --sign - "$APP_PATH"

echo
echo "[4/4] Creating DMG..."
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/bc-dmg.XXXXXX")"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

ditto "$APP_PATH" "${STAGE}/${APP_NAME}.app"
ln -s /Applications "${STAGE}/Applications"
cat > "${STAGE}/Как открыть.txt" <<EOF
Backlink Checker ${VERSION} для Apple Silicon (M1 / M2 / M3 / M4)

1. Перетащите Backlink Checker в папку Программы.
2. При первом запуске: правый клик по приложению → Открыть → Открыть.
   macOS спрашивает это, потому что сборка не подписана аккаунтом Apple.

База и лог:
~/Library/Application Support/Backlink Checker/
EOF

rm -f "$DMG_PATH"
hdiutil create \
  -volname "Backlink Checker" \
  -srcfolder "$STAGE" \
  -ov -format UDZO \
  "$DMG_PATH"

echo
echo "============================================"
echo "  App  : $APP_PATH"
du -sh "$APP_PATH"
echo "  DMG  : $DMG_PATH"
ls -lh "$DMG_PATH"
echo "  SUCCESS"
echo "============================================"
