# Packaging — CodeHubb Assistant release build (Phase 5)

Everything here turns the source tree into the installer a buyer runs.
**The build machine is Windows** (PyInstaller cannot cross-compile);
`build_windows.ps1` is the one-command entry:

```powershell
.\packaging\build_windows.ps1            # full build incl. installer
.\packaging\build_windows.ps1 -SkipInno  # onedir app only (dist\CodeHubbAssistant)
```

## What the pieces do

| File | Role |
|---|---|
| `codehubb_assistant.spec` | PyInstaller onedir spec. Entry `run_app.py` (tray); the agent is the same exe relaunched with `--run-agent`. Bundles the sidecar sources, `.env.example`, tray assets, `apply_update.ps1`, and the staged Playwright `browsers/`. |
| `CodeHubbAssistant.iss` | Inno Setup: per-user install to `{localappdata}\Programs\CodeHubb Assistant`, Start Menu group, optional desktop shortcut, modern wizard, post-install launch. `#define AppVersion` must match `agent/version.py`. |
| `version_info.txt` | Windows version resource for the exe; must match `agent/version.py` too. |
| `build_windows.ps1` | Version-consistency gate → venv + deps → Chromium staging → PyInstaller → `npm install` in the built sidecar → ISCC compile (or prints the manual step). |
| `apply_update.ps1` | Ships inside the install. The tray launches it detached on "Restart to Update": waits for the app PID to exit, runs the staged installer `/VERYSILENT` (or expands a `.zip` update), relaunches the app, logs to `apply_update.log`. |

## Version discipline

`agent/version.py` is the single source of truth. The Inno `#define`,
this folder's `version_info.txt` and the exe metadata must all agree:
`tests/test_version.py` enforces it in CI and `build_windows.ps1`
re-checks before building. To release: bump `agent/version.py`, the
`.iss` define and `version_info.txt` together.

## Node.js for the WhatsApp sidecar

The installer does not force a system Node install. At runtime
`desktop/node_bootstrap.py` resolves, in order: `NODE_BINARY` override →
system Node 18+ → a portable Node in `<app>\node\node.exe` (drop one in
before compiling to ship it) → a Node the app previously downloaded →
otherwise the app can download the pinned official LTS
(v22.14.0, SHA256-verified against nodejs.org's published sums).

## Auto-update feed

Release builds set `UPDATE_FEED_URL` (see `.env.example`) to a static
JSON the seller hosts: `{version, url, sha256, notes, mandatory?}`.
Without it the updater is disabled and the tray shows no update items.
