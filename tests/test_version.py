"""Version discipline (Phase 5): agent/version.py is the single source of
truth; the Inno script, the exe version resource and config must agree."""

import re
from pathlib import Path

from agent.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_semver_shaped():
    parts = __version__.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts)


def test_config_carries_the_version():
    from agent.config import CONFIG

    assert CONFIG.version == __version__


def test_inno_script_version_matches():
    iss = (ROOT / "packaging" / "CodeHubbAssistant.iss").read_text(encoding="utf-8")
    match = re.search(r'#define\s+AppVersion\s+"([^"]+)"', iss)
    assert match, "Inno script must #define AppVersion"
    assert match.group(1) == __version__


def test_version_info_matches():
    text = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    numbers = tuple(int(p) for p in __version__.split("."))
    filevers = numbers + (0,) * (4 - len(numbers))
    assert f"filevers={filevers}" in text
    assert f"'{__version__}'" in text  # FileVersion / ProductVersion strings


def test_diagnostics_reports_the_version():
    from types import SimpleNamespace

    from desktop import diagnostics

    report = diagnostics.build_report(
        problems=[], warnings=[], transports=[],
        node_present=True, sidecar_ready=True, keyring_ok=True,
        audit_lines=[], shell_log_lines=[],
        license_info=SimpleNamespace(
            state="development", plan=None, buyer_email=None,
            days_left=None, machines_limit=None, machines_used=None,
        ),
    )
    assert f"Product version : {__version__}" in report
