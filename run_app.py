#!/usr/bin/env python3
"""CodeHubb Assistant — desktop shell (system tray + setup wizard).

Run:  python run_app.py        (or: python -m desktop)
The headless agent alone is run.py; this is the friendly front door for
buyers: tray icon, first-run wizard, settings, audit log and diagnostics.

Frozen builds (Phase 5): this same executable is also the agent — the
tray relaunches it with `--run-agent` and desktop.app.main() dispatches
that to agent.main.run() in-process, because a bundle has no run.py.
"""

from desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
