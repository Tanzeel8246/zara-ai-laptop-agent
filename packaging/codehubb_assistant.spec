# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — CodeHubb Assistant onedir build (Phase 5).

Entry point is run_app.py (the tray app). The headless agent is the SAME
executable relaunched with --run-agent (desktop.app.main dispatches it to
agent.main.run(); desktop.agent_process.agent_command builds that command
when sys.frozen) — a bundle has no run.py for a child process to run.

Layout this produces (dist/CodeHubbAssistant/):
    CodeHubbAssistant.exe
    _internal/  agent, desktop, sidecar/, .env.example, desktop/assets/,
                packaging/apply_update.ps1, browsers/ (when staged)

The installer (CodeHubbAssistant.iss) ships that whole folder per-user.
Build via packaging/build_windows.ps1, which also stages the Playwright
Chromium into packaging/browsers/ first (PLAYWRIGHT_BROWSERS_PATH).
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.version import __version__  # noqa: E402  single source of truth

try:
    from PyInstaller.utils.hooks import collect_all
except Exception:  # noqa: BLE001 - spec still parses for static checks
    collect_all = None


datas = []
binaries = []
hiddenimports = []


def _collect(package):
    """collect_all for libraries that ship data/submodules PyInstaller's
    static analysis misses. A missing optional package must not fail the
    spec parse, only a real build on Windows resolves them for real."""
    if collect_all is None:
        return
    try:
        d, b, h = collect_all(package)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(h)
    except Exception:  # noqa: BLE001
        pass


for _pkg in ("litellm", "certifi", "playwright", "keyring", "claude_agent_sdk"):
    _collect(_pkg)

hiddenimports += [
    # keyring's Windows backend is discovered by entry point at runtime;
    # name it (and the null backend) so a frozen build can always store
    # secrets.
    "keyring.backends.Windows",
    "keyring.backends.fail",
    "keyring.backends.chainer",
    # GUI essentials (PyInstaller's Qt hooks do the heavy lifting; these
    # are the modules this app imports directly).
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # Transports import lazily per enabled front end — name them all.
    "discord",
    "telegram",
    "websockets",
    # Voice + screen toolkits load lazily inside tool handlers.
    "faster_whisper",
    "mss",
    "pyautogui",
    "pygetwindow",
    "pyperclip",
]

# ---- bundled data files -------------------------------------------------
# WhatsApp sidecar: sources only. node_modules is NOT staged by the spec
# (60 MB) — build_windows.ps1 runs `npm install` inside the BUILT output's
# sidecar folder as a build step, so the installer still ships it ready.
for _name in ("index.js", "package.json", "package-lock.json", "README.md"):
    _src = ROOT / "sidecar" / _name
    if _src.exists():
        datas.append((str(_src), "sidecar"))

_env_example = ROOT / ".env.example"
if _env_example.exists():
    datas.append((str(_env_example), "."))

_assets = ROOT / "desktop" / "assets"
if _assets.is_dir():
    for _png in sorted(_assets.glob("*.png")):
        datas.append((str(_png), "desktop/assets"))

_apply = ROOT / "packaging" / "apply_update.ps1"
if _apply.exists():
    datas.append((str(_apply), "packaging"))

# Playwright Chromium: build_windows.ps1 sets PLAYWRIGHT_BROWSERS_PATH to
# packaging/browsers and runs `playwright install chromium` there; bundle
# whatever it staged as browsers/ (the runtime locates it via
# agent.bundled_paths).
_browsers_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")) \
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else ROOT / "packaging" / "browsers"
if _browsers_root.is_dir():
    for _entry in sorted(_browsers_root.iterdir()):
        if _entry.is_dir():
            datas.append((str(_entry), f"browsers/{_entry.name}"))

excludes = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "matplotlib",
    "IPython",
    "jupyter",
    "torch",
    "tensorflow",
    "pytest",
]

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CodeHubbAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # tray app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CodeHubbAssistant",
)
