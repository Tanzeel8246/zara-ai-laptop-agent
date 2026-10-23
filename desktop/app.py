"""Tray application — the desktop shell around the headless agent.

Lives in the system tray AND, since Hotfix 1.0.9, in a control window
(desktop/control_window.py) that opens at launch: status at a glance,
start/stop the agent subprocess, open the setup wizard, settings, the
audit log and diagnostics. First run (no .env yet, or configuration
problems) opens the wizard automatically; the control window follows
when it completes. Closing the control window minimizes to the tray;
quitting the shell stops the agent.
"""

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from desktop import diagnostics, icons
from desktop.agent_process import AgentProcess
from desktop.agent_status import transport_states
from desktop.audit_view import AuditView
from desktop.control_window import ControlWindow
from desktop.settings_dialog import SettingsDialog
from desktop.settings_model import Settings
from desktop.wizard import SetupWizard


class DiagnosticsDialog(QDialog):
    """The support bundle: read it, copy it, or save it as a .txt file."""

    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Diagnostics — send this with a problem report")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(report)
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        copy_button = QPushButton("Copy to clipboard")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.text.toPlainText())
        )
        row.addWidget(copy_button)
        save_button = QPushButton("Save as .txt…")
        save_button.clicked.connect(self._save)
        row.addWidget(save_button)
        row.addStretch(1)
        layout.addLayout(row)

    def _save(self):
        from PySide6.QtWidgets import QFileDialog

        path, _chosen = QFileDialog.getSaveFileName(
            self, "Save diagnostics", "codehubb-assistant-diagnostics.txt", "Text files (*.txt)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.text.toPlainText())


class AgentLogDialog(QDialog):
    """The agent's own log tail (.runtime/agent-shell.log) — the same
    file the control window reads its transport states from."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent log — latest lines")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(
            text or "(the agent log is empty — the agent has not run yet)"
        )
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        row.addWidget(close_button)
        layout.addLayout(row)


class _UpdateThread(QThread):
    """Runs one updater operation (check/download) off the UI thread."""

    done = Signal(object, object)  # (result, error_text)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn(), None)
        except Exception as exc:  # noqa: BLE001 - shown to the user verbatim
            self.done.emit(None, str(exc))


def _default_updater():
    try:
        from agent.updater import get_updater

        return get_updater()
    except Exception:  # noqa: BLE001 - updates must never break the tray
        return None


class TrayController(QWidget):
    """Owns the tray icon, the agent process and every window it opens."""

    def __init__(self, app, *, env_path=None, auto_open_wizard=True,
                 auto_open_window=True, updater="default", update_popen=None):
        super().__init__()
        self.app = app
        self.env_path = env_path
        self.auto_open_window = auto_open_window
        self.updater = _default_updater() if updater == "default" else updater
        self._update_popen = update_popen or subprocess.Popen
        self._update_thread = None
        icons.ensure_icons()
        self.agent = AgentProcess()
        self._last_exit_code = None
        self._error_latched = False
        self.settings = self._load_settings()

        self.tray = QSystemTrayIcon(self._icon_for("stopped"), self)
        self.tray.setToolTip(self.settings.product_name or "CodeHubb Assistant")
        menu = QMenu()
        self.status_action = QAction("Status: …", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()
        self.control_action = QAction("Open Control Window", menu)
        self.control_action.triggered.connect(self.show_control_window)
        menu.addAction(self.control_action)
        menu.addSeparator()
        self.start_action = QAction("Start Agent", menu)
        self.start_action.triggered.connect(self.start_agent)
        menu.addAction(self.start_action)
        self.stop_action = QAction("Stop Agent", menu)
        self.stop_action.triggered.connect(self.stop_agent)
        menu.addAction(self.stop_action)
        menu.addSeparator()
        wizard_action = QAction("Setup Wizard…", menu)
        wizard_action.triggered.connect(self.open_wizard)
        menu.addAction(wizard_action)
        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)
        audit_action = QAction("Audit Log…", menu)
        audit_action.triggered.connect(self.open_audit)
        menu.addAction(audit_action)
        diag_action = QAction("Run Diagnostics", menu)
        diag_action.triggered.connect(self.open_diagnostics)
        menu.addAction(diag_action)
        # Phase 5: auto-update items exist ONLY when an update feed is
        # configured (release builds). Development builds — no feed URL —
        # show nothing at all, and the Restart item stays hidden until an
        # update has actually been downloaded + verified (staged).
        self.update_check_action = None
        self.update_restart_action = None
        if self.updater is not None and self.updater.enabled:
            self.update_check_action = QAction("Check for Updates", menu)
            self.update_check_action.triggered.connect(self.check_for_updates)
            menu.addAction(self.update_check_action)
            self.update_restart_action = QAction("Restart to Update", menu)
            self.update_restart_action.triggered.connect(self.apply_update)
            self.update_restart_action.setVisible(False)
            menu.addAction(self.update_restart_action)
        about_action = QAction("About…", menu)
        about_action.triggered.connect(self.show_about)
        menu.addAction(about_action)
        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_click)
        self.tray.show()

        # Hotfix 1.0.9: the visible face of the app. Until now the shell
        # was only a tray icon — usually hidden in the notification-area
        # overflow — so a launch looked like nothing had happened.
        self.control_window = ControlWindow(
            product_name=self.settings.product_name or "CodeHubb Assistant",
            on_start=self.start_agent,
            on_stop=self.stop_agent,
            on_settings=self.open_settings,
            on_view_logs=self.open_agent_log,
            on_quit=self.quit,
            parent=self,
        )

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start()
        self.refresh_status()

        if auto_open_wizard and self._needs_setup():
            QTimer.singleShot(300, self.open_wizard)
        elif self.auto_open_window:
            # Normal launch: be visible. (First run shows the wizard
            # instead; open_wizard shows this window when it completes.)
            QTimer.singleShot(300, self.show_control_window)

    # ------------------------------------------------------------- state

    def _load_settings(self):
        try:
            return Settings.load(self.env_path)
        except Exception:  # noqa: BLE001 - shell must still open on a broken .env
            return Settings()

    def _needs_setup(self):
        return self.settings.fresh_install or bool(self.settings.validate())

    def _problems(self):
        try:
            return self.settings.validate()
        except Exception:  # noqa: BLE001
            return ["configuration could not be read"]

    def status(self):
        if self.agent.state == "running":
            return "running"
        if self._error_latched:
            return "error"
        if self._problems():
            return "not_configured"
        return "stopped"

    def refresh_status(self):
        previous = self.agent.state
        self.agent.poll()
        if previous == "running" and self.agent.state == "stopped":
            self._last_exit_code = self.agent.exit_code
            # exit 0 = clean shutdown, 3 = another instance already running;
            # anything else is a crash worth surfacing.
            self._error_latched = self._last_exit_code not in (0, 3, None)
        state = self.status()
        label = {
            "running": f"Running (PID {self.agent.pid})",
            "stopped": "Stopped",
            "not_configured": "Not configured — open the Setup Wizard",
            "error": f"Error — agent exited with code {self._last_exit_code}",
        }[state]
        name = self.settings.assistant_name or "Assistant"
        suffix = self._license_suffix()
        if suffix:
            label = f"{label} · {suffix}"
        self.status_action.setText(f"{name}: {label}")
        self.tray.setIcon(self._icon_for(state))
        self.start_action.setEnabled(state != "running")
        self.stop_action.setEnabled(state == "running")
        self._refresh_update_action()
        self._push_window_status(state, label)

    def _push_window_status(self, state, label):
        """Feed the control window from the same state the tray shows.

        Transport states are parsed from the agent's own log tail
        (desktop.agent_status) — the shell's existing channel — and
        only while the window is open, so a hidden window costs the
        once-a-second refresh nothing."""
        if not self.control_window.isVisible():
            return
        states = transport_states(
            self.agent.read_log_tail(400),
            self.settings.transports,
            agent_running=(state == "running"),
        )
        self.control_window.update_status(
            {
                "agent_text": f"Agent: {label}",
                "agent_state": state,
                "transports": states,
            }
        )

    _license_cache = ("", 0.0)

    def _license_suffix(self):
        """'Trial (9 days left)' / 'Activation required' — release builds
        only; development builds append nothing. Cached: the tray refreshes
        every second, license state does not change that fast."""
        import time

        text, stamp = self._license_cache
        if time.monotonic() - stamp < 30:
            return text
        text = ""
        try:
            from agent import licensing

            if licensing.enforcement_enabled():
                status = licensing.get_manager().status()
                text = licensing.status_line(status)
                if status.state in ("trial_expired", "expired", "revoked", "invalid"):
                    text = "Activation required"
        except Exception:  # noqa: BLE001 - the tray must never die on this
            text = ""
        self._license_cache = (text, time.monotonic())
        return text

    _update_cache = (None, 0.0)

    def _refresh_update_action(self):
        """Show 'Restart to Update' only while a verified update is staged.
        Cached like the license suffix: the tray refreshes every second,
        the staged state does not change that fast."""
        if self.update_restart_action is None:
            return
        import time

        staged, stamp = self._update_cache
        if time.monotonic() - stamp >= 30:
            try:
                staged = self.updater.staged() if self.updater else None
            except Exception:  # noqa: BLE001 - never break the tray on this
                staged = None
            self._update_cache = (staged, time.monotonic())
        self.update_restart_action.setVisible(bool(staged))
        if staged:
            self.update_restart_action.setText(
                f"Restart to Update (v{staged.get('version', '?')})"
            )

    def _icon_for(self, state):
        filename = {
            "running": "icon.png",
            "error": "icon-error.png",
        }.get(state, "icon-stopped.png")
        return QIcon(str(icons.ASSETS_DIR / filename))

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # 1.0.9: double-click opens the control window (it carries
            # Start/Stop itself) instead of silently toggling the agent.
            self.show_control_window()

    def show_control_window(self):
        self.control_window.show()
        self.control_window.raise_()
        self.control_window.activateWindow()
        self.refresh_status()

    def open_agent_log(self):
        AgentLogDialog(self.agent.read_log_tail(200), self).exec()

    # ----------------------------------------------------------- actions

    def start_agent(self):
        problems = self._problems()
        if problems:
            QMessageBox.information(
                self, "Setup needed first",
                "The assistant is not fully configured yet:\n\n"
                + "\n".join(f"• {p}" for p in problems)
                + "\n\nOpening the setup wizard…",
            )
            self.open_wizard()
            return
        self._error_latched = False
        self.agent.start()
        self.refresh_status()

    def stop_agent(self):
        self.agent.stop()
        self._error_latched = False
        self.refresh_status()

    def open_wizard(self):
        wizard = SetupWizard(self._load_settings(), self, env_path=self.env_path)
        if wizard.exec():
            self.settings = self._load_settings()
            warnings = wizard.save_result.warnings if wizard.save_result else []
            if warnings:
                QMessageBox.warning(self, "Saved with notes", "\n".join(warnings))
            if wizard.start_agent_requested:
                self.start_agent()
            self.refresh_status()
            # Setup is done — from here the control window is the face
            # of the app (1.0.9), so the user lands somewhere visible.
            self.show_control_window()

    def open_settings(self):
        dialog = SettingsDialog(self._load_settings(), self, env_path=self.env_path)
        if dialog.exec():
            self.settings = self._load_settings()
            self.refresh_status()

    def open_audit(self):
        view = AuditView(self)
        view.exec()

    # ------------------------------------------------------- updates (P5)

    def show_about(self):
        from agent.version import __version__

        name = self.settings.product_name or "CodeHubb Assistant"
        QMessageBox.about(
            self, f"About {name}",
            f"{name}\nVersion {__version__}\n\n"
            f"Your assistant's name: {self.settings.assistant_name or 'Assistant'}\n"
            "Control your Windows laptop from your phone — Discord, "
            "Telegram or WhatsApp.",
        )

    def check_for_updates(self):
        if self.updater is None or not self.updater.enabled:
            return
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        if self.update_check_action is not None:
            self.update_check_action.setEnabled(False)
        thread = _UpdateThread(self.updater.check, self)
        thread.done.connect(self._on_update_check_done)
        self._update_thread = thread
        thread.start()

    def _on_update_check_done(self, info, error):
        if self.update_check_action is not None:
            self.update_check_action.setEnabled(True)
        name = self.settings.product_name or "CodeHubb Assistant"
        if error:
            QMessageBox.warning(self, "Updates", f"Update check failed:\n\n{error}")
            return
        if info is None:
            from agent.version import __version__

            QMessageBox.information(
                self, "Updates",
                f"{name} is up to date (version {__version__}).",
            )
            return
        notes = f"\n\n{info.notes}" if info.notes else ""
        answer = QMessageBox.question(
            self, "Update available",
            f"{name} v{info.version} is available.{notes}\n\n"
            "Download it now? It installs when you choose "
            "'Restart to Update' from this menu.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            thread = _UpdateThread(lambda: self.updater.download(info), self)
            thread.done.connect(self._on_update_download_done)
            self._update_thread = thread
            thread.start()

    def _on_update_download_done(self, path, error):
        if error:
            QMessageBox.warning(self, "Updates", f"Update download failed:\n\n{error}")
            return
        self._update_cache = (None, 0.0)  # force the staged re-check
        self._refresh_update_action()
        answer = QMessageBox.question(
            self, "Update ready",
            "The update was downloaded and verified. Restart now to install it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.apply_update()

    def apply_update(self):
        """Hand the staged installer to packaging/apply_update.ps1 (it
        waits for THIS process to exit, installs silently, relaunches)
        and quit. No-op when nothing is staged."""
        if self.updater is None:
            return
        try:
            staged = self.updater.staged()
        except Exception:  # noqa: BLE001
            staged = None
        if not staged:
            return
        from agent.updater import apply_script_path

        script = apply_script_path()
        relaunch = sys.executable
        args = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script),
            "-Installer", str(staged["path"]),
            "-WaitPid", str(os.getpid()),
            "-Relaunch", str(relaunch),
        ]
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        try:
            self._update_popen(args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - keep the app alive then
            QMessageBox.warning(
                self, "Updates", f"Could not start the updater:\n\n{exc}"
            )
            return
        self.quit()

    def open_diagnostics(self):
        problems = self._problems()
        warnings = []
        try:
            warnings = self.settings.validate_warnings()
        except Exception:  # noqa: BLE001
            warnings = []
        report = diagnostics.build_report(problems=problems, warnings=warnings)
        DiagnosticsDialog(report, self).exec()

    def quit(self):
        if self.agent.state == "running":
            self.agent.stop()
        self.tray.hide()
        self.app.quit()


def create_controller(app=None, **kwargs):
    """Build the tray controller (used by main() and by the smoke tests)."""
    app = app or QApplication.instance() or QApplication(sys.argv)
    return TrayController(app, **kwargs)


# Printed by main() before the event loop (Hotfix 1.0.9). Until now a
# launch printed nothing at all: run from a console, the window came
# back instantly or sat silent and the app "wasn't starting" — while it
# sat in the tray. A launch must announce itself.
STARTING_LINE = (
    "CodeHubb Assistant is starting — a control window will open; "
    "the assistant also lives in the system tray (near the clock)."
)
ALREADY_RUNNING_LINE = (
    "CodeHubb Assistant is already running — "
    "check the system tray / control window."
)
SHELL_LOCK_FILE = "codehubb-assistant-shell.lock"


def acquire_shell_lock():
    """Become the one desktop shell on this machine, or return None.

    A QLockFile in the per-user temp dir is shared by every copy of the
    app (installed build and source folders alike), so a second launch
    is turned away instead of spawning a twin tray icon. A lock left by
    a crashed shell names a dead PID, is recognised as stale and is
    taken over — it can never lock the owner out."""
    lock = QLockFile(str(Path(QDir.tempPath()) / SHELL_LOCK_FILE))
    return lock if lock.tryLock(100) else None


def _run_agent_mode():
    """Frozen-bundle dispatch (Phase 5): `--run-agent` runs the headless
    agent in-process. In the installer build there is no run.py file for
    AgentProcess to launch — the app exe relaunches ITSELF with this flag
    (desktop.agent_process.agent_command), so argv is where the child
    decides it is the agent, not the tray."""
    from agent.main import run as agent_run

    try:
        agent_run()
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--run-agent" in argv:
        return _run_agent_mode()
    print(STARTING_LINE, flush=True)
    app = QApplication(argv)
    app.setApplicationName("CodeHubb Assistant")
    app.setQuitOnLastWindowClosed(False)
    lock = acquire_shell_lock()
    if lock is None:
        print(ALREADY_RUNNING_LINE, flush=True)
        return 0
    controller = create_controller(app)
    _ = controller  # kept alive by its tray icon parent chain + app reference below
    app._tray_controller = controller
    app._shell_lock = lock  # held for the process lifetime
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
