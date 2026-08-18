@echo off
chcp 65001 > nul
echo ============================================
echo   Backlink Checker — build
echo ============================================

echo.
echo [1/3] Installing pinned dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )
python -m PyInstaller --version
echo      OK

echo.
echo [2/3] Checking Playwright Chromium...
python -c "
import os, json
from pathlib import Path
pw_base = Path(os.environ.get('LOCALAPPDATA','')) / 'ms-playwright'
dirs = sorted(pw_base.glob('chromium-*'))

import playwright
pkg = Path(playwright.__file__).parent / 'driver' / 'package' / 'browsers.json'
expected = None
if pkg.exists():
    data = json.loads(pkg.read_text())
    for b in data.get('browsers', []):
        if b.get('name') == 'chromium':
            expected = 'chromium-' + str(b.get('revision'))

installed = [d.name for d in dirs]
print('Expected :', expected)
print('Installed:', installed)
if expected and expected not in installed:
    print('MISMATCH — run: python -m playwright install chromium')
    exit(1)
elif not dirs:
    print('NOT FOUND — run: python -m playwright install chromium')
    exit(1)
else:
    print('OK')
" 2>&1
if errorlevel 1 (
    echo.
    echo Chromium version mismatch or not found.
    echo Running: python -m playwright install chromium
    python -m playwright install chromium
    if errorlevel 1 ( echo FAILED & pause & exit /b 1 )
)

echo.
echo [3/3] Building EXE (may take several minutes)...
python -m PyInstaller BacklinkChecker.spec --clean --noconfirm
if errorlevel 1 ( echo BUILD FAILED & pause & exit /b 1 )

echo.
echo ============================================
if exist "dist\Backlink Checker.exe" (
    for %%A in ("dist\Backlink Checker.exe") do echo   Size : %%~zA bytes
    echo   Path : dist\Backlink Checker.exe
    echo   SUCCESS — ready to distribute
) else (
    echo   FAILED: EXE not found in dist\
)
echo ============================================
pause
