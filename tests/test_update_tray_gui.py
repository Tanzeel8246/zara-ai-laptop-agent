"""Tray update wiring (Phase 5), offscreen: update items appear only
when a feed is configured, 'Restart to Update' only while a verified
update is staged, About shows the version, and applying an update hands
the staged installer to apply_update.ps1 and quits."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="GUI dependencies not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeUpdater:
    def __init__(self, enabled=True, staged=None):
        self.enabled = enabled
        self._staged = staged
        self.check_calls = 0

    def check(self):
        self.check_calls += 1
        return None

    def download(self, info=None):
        raise AssertionError("not used here")

    def staged(self):
        return self._staged


def _controller(qapp, tmp_path, updater):
    from desktop.app import create_controller

    return create_controller(
        qapp, env_path=tmp_path / ".env", auto_open_wizard=False, updater=updater
    )


def _menu_texts(controller):
    menu = controller.tray.contextMenu()
    return [a.text() for a in menu.actions()]


def test_no_update_items_when_updater_disabled(qapp, tmp_path):
    controller = _controller(qapp, tmp_path, FakeUpdater(enabled=False))
    try:
        texts = _menu_texts(controller)
        assert not any("Update" in t for t in texts)
        assert controller.update_check_action is None
        assert controller.update_restart_action is None
        # About is always there and names the version (checked via slot text)
        assert any("About" in t for t in texts)
    finally:
        controller.tray.hide()


def test_update_items_when_enabled_nothing_staged(qapp, tmp_path):
    controller = _controller(qapp, tmp_path, FakeUpdater(enabled=True, staged=None))
    try:
        texts = _menu_texts(controller)
        assert any("Check for Updates" in t for t in texts)
        assert controller.update_restart_action is not None
        assert not controller.update_restart_action.isVisible()
    finally:
        controller.tray.hide()


def test_restart_item_appears_when_staged(qapp, tmp_path):
    staged = {"version": "1.1.0", "path": str(tmp_path / "setup.exe")}
    controller = _controller(qapp, tmp_path, FakeUpdater(enabled=True, staged=staged))
    try:
        controller._update_cache = (None, 0.0)
        controller._refresh_update_action()
        assert controller.update_restart_action.isVisible()
        assert "1.1.0" in controller.update_restart_action.text()
    finally:
        controller.tray.hide()


def test_apply_update_launches_script_and_quits(qapp, tmp_path):
    staged = {"version": "1.1.0", "path": str(tmp_path / "setup.exe")}
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        class _P:
            pid = 999

        return _P()

    controller = _controller(qapp, tmp_path, FakeUpdater(enabled=True, staged=staged))
    try:
        controller._update_popen = fake_popen
        quit_calls = []
        controller.quit = lambda: quit_calls.append(True)
        controller.apply_update()
        args = captured["args"]
        assert args[0] == "powershell"
        assert any(a.endswith("apply_update.ps1") for a in args)
        assert str(tmp_path / "setup.exe") in args
        assert str(os.getpid()) in args
        assert quit_calls == [True]
    finally:
        controller.tray.hide()


def test_apply_update_noop_without_staged(qapp, tmp_path):
    captured = {}
    controller = _controller(qapp, tmp_path, FakeUpdater(enabled=True, staged=None))
    try:
        controller._update_popen = lambda *a, **k: captured.setdefault("called", True)
        quit_calls = []
        controller.quit = lambda: quit_calls.append(True)
        controller.apply_update()
        assert "called" not in captured
        assert quit_calls == []
    finally:
        controller.tray.hide()


def test_about_dialog_mentions_version(qapp, tmp_path, monkeypatch):
    from agent.version import __version__
    from desktop import app as desktop_app

    seen = {}

    class _FakeMessageBox:
        @staticmethod
        def about(parent, title, text):
            seen["title"] = title
            seen["text"] = text

    monkeypatch.setattr(desktop_app, "QMessageBox", _FakeMessageBox)
    controller = _controller(qapp, tmp_path, FakeUpdater(enabled=False))
    try:
        controller.show_about()
        assert __version__ in seen["text"]
        assert "About" in seen["title"]
    finally:
        controller.tray.hide()
