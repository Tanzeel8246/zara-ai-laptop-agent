"""Offscreen GUI tests for the 1.0.9 control window, its tray wiring,
the shell single-instance guard and the console startup lines.

Construction + scripted interaction only — no event loop is run except
short processEvents() spins where a QTimer has to fire.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="GUI dependencies not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_window(**overrides):
    from desktop.control_window import ControlWindow

    calls = []
    kwargs = {
        "product_name": "CodeHubb Assistant",
        "on_start": lambda: calls.append("start"),
        "on_stop": lambda: calls.append("stop"),
        "on_settings": lambda: calls.append("settings"),
        "on_view_logs": lambda: calls.append("logs"),
        "on_quit": lambda: calls.append("quit"),
    }
    kwargs.update(overrides)
    return ControlWindow(**kwargs), calls


def test_window_constructs_with_initial_button_states(qapp):
    window, _calls = _make_window()
    try:
        assert window.windowTitle() == "CodeHubb Assistant"
        # Nothing known yet: Start offered, Stop not.
        assert window.start_button.isEnabled()
        assert not window.stop_button.isEnabled()
        # All three transports get a line, and the tray hint is present.
        assert set(window.transport_labels) == {"discord", "telegram", "whatsapp"}
        texts = [label.text() for label in window.findChildren(type(window.agent_label))]
        assert any("keeps the assistant running in the tray" in t for t in texts)
    finally:
        window.close()


def test_window_update_status_with_retrying_transport(qapp):
    window, _calls = _make_window()
    try:
        window.update_status(
            {
                "agent_text": "Agent: Running (PID 4242)",
                "agent_state": "running",
                "transports": {
                    "discord": "disabled",
                    "telegram": "retrying",
                    "whatsapp": "connected",
                },
            }
        )
        assert window.agent_label.text() == "Agent: Running (PID 4242)"
        assert window.transport_labels["telegram"].text() == "Telegram: Retrying…"
        assert window.transport_labels["whatsapp"].text() == "WhatsApp: Connected"
        assert window.transport_labels["discord"].text() == "Discord: Disabled"
        assert not window.start_button.isEnabled()
        assert window.stop_button.isEnabled()

        window.update_status(
            {"agent_text": "Agent: Stopped", "agent_state": "stopped", "transports": {}}
        )
        assert window.start_button.isEnabled()
        assert not window.stop_button.isEnabled()
    finally:
        window.close()


def test_window_close_minimizes_to_tray_instead_of_quitting(qapp):
    window, _calls = _make_window()
    window.show()
    assert window.isVisible()
    window.close()  # must hide, not destroy
    assert not window.isVisible()
    window.show()  # ... and it can come straight back
    assert window.isVisible()
    window.hide()


def test_window_buttons_fire_their_callbacks(qapp):
    window, calls = _make_window()
    try:
        window.start_button.click()
        window.settings_button.click()
        window.logs_button.click()
        window.quit_button.click()
        assert calls == ["start", "settings", "logs", "quit"]
    finally:
        window.close()


class _FakeAgent:
    """Just the surface TrayController.refresh_status touches."""

    pid = 4242
    exit_code = None

    def __init__(self, log_path):
        self._log_path = log_path

    def poll(self):
        return "running"

    @property
    def state(self):
        return "running"

    def read_log_tail(self, lines=60):
        try:
            return self._log_path.read_text(encoding="utf-8")
        except OSError:
            return ""


def _make_controller(qapp, tmp_path, **kwargs):
    from desktop.app import create_controller

    kwargs.setdefault("auto_open_wizard", False)
    kwargs.setdefault("auto_open_window", False)
    kwargs.setdefault("updater", None)
    return create_controller(qapp, env_path=tmp_path / ".env", **kwargs)


def test_controller_menu_and_double_click_open_the_window(qapp, tmp_path):
    controller = _make_controller(qapp, tmp_path)
    try:
        texts = [a.text() for a in controller.tray.contextMenu().actions()]
        assert any("Open Control Window" in t for t in texts)
        assert not controller.control_window.isVisible()

        from PySide6.QtWidgets import QSystemTrayIcon

        controller._on_tray_click(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert controller.control_window.isVisible()
        # Double-click must NOT have toggled the agent on.
        assert controller.status() != "running"
    finally:
        controller.control_window.hide()
        controller.tray.hide()


def test_controller_pushes_live_status_into_the_window(qapp, tmp_path):
    controller = _make_controller(qapp, tmp_path)
    try:
        log_path = tmp_path / "agent-shell.log"
        log_path.write_text(
            "  CodeHubb Assistant — Telegram transport starting (long polling)\n"
            "  [telegram] Telegram unreachable (NetworkError) — retrying in 30s.\n",
            encoding="utf-8",
        )
        controller.agent = _FakeAgent(log_path)
        controller.settings.transports = ["telegram"]
        controller.show_control_window()
        assert controller.control_window.agent_label.text().startswith(
            "Agent: Running (PID 4242)"
        )
        assert (
            controller.control_window.transport_labels["telegram"].text()
            == "Telegram: Retrying…"
        )
        assert (
            controller.control_window.transport_labels["discord"].text()
            == "Discord: Disabled"
        )
        assert not controller.control_window.start_button.isEnabled()
        assert controller.control_window.stop_button.isEnabled()
    finally:
        controller.control_window.hide()
        controller.tray.hide()


def test_controller_auto_opens_window_on_normal_launch(qapp, tmp_path):
    controller = _make_controller(qapp, tmp_path, auto_open_window=True)
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not controller.control_window.isVisible():
            qapp.processEvents()
            time.sleep(0.02)
        assert controller.control_window.isVisible()
    finally:
        controller.control_window.hide()
        controller.tray.hide()


def test_shell_lock_turns_a_second_launch_away(qapp):
    from desktop.app import acquire_shell_lock

    lock = acquire_shell_lock()
    assert lock is not None
    try:
        assert acquire_shell_lock() is None
    finally:
        lock.unlock()


def test_startup_lines_say_where_the_app_lives():
    from desktop import app as app_module

    assert "control window" in app_module.STARTING_LINE
    assert "system tray" in app_module.STARTING_LINE
    assert "already running" in app_module.ALREADY_RUNNING_LINE
    assert "system tray" in app_module.ALREADY_RUNNING_LINE
