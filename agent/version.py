"""Product version — the single source of truth (Phase 5).

Everything that needs the product version reads it from here:
agent/__init__ re-exports it, the config carries it, diagnostics prints
it, the tray's About box shows it, and the packaging files
(packaging/CodeHubbAssistant.iss, packaging/version_info.txt) are kept
in step by tests/test_version.py and by packaging/build_windows.ps1,
which refuses to build when they disagree.
"""

__version__ = "1.0.8"
