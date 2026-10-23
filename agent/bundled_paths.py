"""Paths that differ between a source checkout and a frozen bundle (Phase 5).

PyInstaller (onedir) puts the executable in the app folder and the bundled
data files under it (in `_internal` on PyInstaller 6). Two things must find
their way there at runtime:

  - the Playwright Chromium build that packaging/ bundles as `browsers/`
    (Playwright only looks where PLAYWRIGHT_BROWSERS_PATH points, so the
    entry points call ensure_playwright_browsers_path() BEFORE anything
    imports playwright — the browser tool imports it lazily, first use);
  - the install/app directory, for the Node bootstrap's bundled node.

Everything here is Qt-free and injectable so the layout logic is unit
tested without ever freezing anything.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def bundle_dir(frozen=None, meipass=None, exe=None, root=None):
    """Where bundled data files live: sys._MEIPASS when frozen, else root."""
    if frozen is None:
        frozen = is_frozen()
    if not frozen:
        return Path(root) if root else ROOT
    if meipass is not None:
        return Path(meipass)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return app_dir(exe=exe, root=root)


def app_dir(frozen=None, exe=None, root=None):
    """The install/app folder: the executable's folder when frozen, else
    the repository root."""
    if frozen is None:
        frozen = is_frozen()
    if frozen:
        return Path(exe).resolve().parent if exe else Path(sys.executable).resolve().parent
    return Path(root) if root else ROOT


def browsers_dir_candidates(frozen=None, meipass=None, exe=None, root=None):
    """Directories that may hold the bundled Playwright browsers, in the
    order they should win. packaging/browsers is the build-time staging
    dir (build_windows.ps1 points PLAYWRIGHT_BROWSERS_PATH there and the
    spec bundles its contents as `browsers/`)."""
    frozen = is_frozen() if frozen is None else frozen
    root = Path(root) if root else ROOT
    out = []
    if frozen:
        out.append(app_dir(frozen=True, exe=exe, root=root) / "browsers")
        out.append(bundle_dir(frozen=True, meipass=meipass, exe=exe, root=root) / "browsers")
    out.append(root / "browsers")
    out.append(root / "packaging" / "browsers")
    return out


def find_browsers_dir(**layout):
    for candidate in browsers_dir_candidates(**layout):
        if candidate.is_dir():
            return candidate
    return None


def ensure_playwright_browsers_path(env=None, **layout):
    """Point PLAYWRIGHT_BROWSERS_PATH at the bundled browsers, if any.

    An explicitly configured environment variable always wins and is
    never overridden. Returns the effective value (or None when no
    bundled browsers exist — Playwright then uses its default cache,
    e.g. after a manual `playwright install chromium`).
    """
    env = os.environ if env is None else env
    existing = env.get("PLAYWRIGHT_BROWSERS_PATH")
    if existing:
        return existing
    found = find_browsers_dir(**layout)
    if found is None:
        return None
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(found)
    return str(found)
