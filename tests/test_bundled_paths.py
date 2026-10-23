"""Bundled-path resolution (Phase 5): where the frozen app finds the
Playwright browsers the installer shipped — and never overriding an
explicit PLAYWRIGHT_BROWSERS_PATH."""

from agent import bundled_paths as bp


def test_explicit_env_always_wins(tmp_path):
    env = {"PLAYWRIGHT_BROWSERS_PATH": "/somewhere/else"}
    result = bp.ensure_playwright_browsers_path(env, root=tmp_path)
    assert result == "/somewhere/else"
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/somewhere/else"


def test_dev_layout_packaging_browsers(tmp_path):
    staged = tmp_path / "packaging" / "browsers"
    staged.mkdir(parents=True)
    env = {}
    result = bp.ensure_playwright_browsers_path(env, root=tmp_path)
    assert result == str(staged)
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(staged)


def test_dev_layout_root_browsers_wins_over_packaging(tmp_path):
    (tmp_path / "packaging" / "browsers").mkdir(parents=True)
    root_browsers = tmp_path / "browsers"
    root_browsers.mkdir()
    env = {}
    assert bp.ensure_playwright_browsers_path(env, root=tmp_path) == str(root_browsers)


def test_frozen_layout_exe_dir(tmp_path):
    app = tmp_path / "app"
    (app / "browsers").mkdir(parents=True)
    exe = app / "CodeHubbAssistant.exe"
    exe.write_text("")
    env = {}
    result = bp.ensure_playwright_browsers_path(
        env, frozen=True, exe=exe, meipass=tmp_path / "_internal", root=tmp_path / "repo"
    )
    assert result == str(app / "browsers")


def test_frozen_layout_meipass_fallback(tmp_path):
    internal = tmp_path / "_internal"
    (internal / "browsers").mkdir(parents=True)
    app = tmp_path / "app"
    app.mkdir()
    env = {}
    result = bp.ensure_playwright_browsers_path(
        env, frozen=True, exe=app / "CodeHubbAssistant.exe",
        meipass=internal, root=tmp_path / "repo",
    )
    assert result == str(internal / "browsers")


def test_nothing_bundled_returns_none_and_leaves_env(tmp_path):
    env = {}
    assert bp.ensure_playwright_browsers_path(env, root=tmp_path) is None
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env


def test_app_and_bundle_dirs():
    import sys

    assert bp.app_dir(frozen=False, root="/repo") == bp.Path("/repo")
    assert bp.bundle_dir(frozen=False, root="/repo") == bp.Path("/repo")
    frozen_app = bp.app_dir(frozen=True, exe="/apps/ca/CodeHubbAssistant.exe")
    assert str(frozen_app).endswith("ca")
    assert bp.is_frozen() == bool(getattr(sys, "frozen", False))
