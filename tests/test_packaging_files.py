"""Packaging deliverables (Phase 5) — static guarantees. Inno Setup and
PowerShell cannot execute in this sandbox, so these tests pin the
properties the release depends on; build_windows.ps1 re-checks them on
the Windows build machine."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"


def _read(name):
    path = PACKAGING / name
    assert path.exists(), f"packaging/{name} is missing"
    return path.read_text(encoding="utf-8")


def test_spec_is_valid_python_and_targets_the_tray():
    spec = _read("codehubb_assistant.spec")
    ast.parse(spec)  # syntax must be valid Python
    assert "run_app.py" in spec
    assert 'name="CodeHubbAssistant"' in spec
    assert "console=False" in spec          # windowed tray app
    assert "exclude_binaries=True" in spec  # onedir, not onefile


def test_spec_bundles_the_runtime_data():
    spec = _read("codehubb_assistant.spec")
    for needle in ('"sidecar"', ".env.example", "desktop/assets",
                   "apply_update.ps1", "browsers", "keyring.backends.Windows",
                   "litellm", "certifi", "version_info.txt"):
        assert needle in spec, f"spec is missing {needle}"
    # node_modules is staged by the build script, never as spec data
    assert '"node_modules"' not in spec


def test_inno_installs_per_user_with_shortcuts():
    iss = _read("CodeHubbAssistant.iss")
    assert "{localappdata}" in iss
    assert "PrivilegesRequired=lowest" in iss
    assert "WizardStyle=modern" in iss
    assert 'Name: "desktopicon"' in iss and "Flags: unchecked" in iss
    assert "{group}" in iss                    # Start Menu group
    assert "postinstall" in iss               # launch-after-install option
    assert "CodeHubbAssistant-Setup-{#AppVersion}" in iss
    assert "..\\dist\\CodeHubbAssistant" in iss


def test_apply_update_script_contract():
    ps = _read("apply_update.ps1")
    for needle in ("$Installer", "$WaitPid", "$Relaunch",
                   "Wait-Process", "/VERYSILENT", "Expand-Archive",
                   "Start-Process", "apply-update.log"):
        assert needle in ps, f"apply_update.ps1 is missing {needle}"


def test_build_script_gates_on_version_and_builds_all_stages():
    ps = _read("build_windows.ps1")
    for needle in ("version.py", "AppVersion", "version mismatch",
                   "requirements-gui.txt", "playwright install chromium",
                   "PyInstaller", "codehubb_assistant.spec",
                   "npm install", "ISCC", "CodeHubbAssistant-Setup-"):
        assert needle in ps, f"build_windows.ps1 is missing {needle}"
