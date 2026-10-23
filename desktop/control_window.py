"""The control window — the app's visible face (Hotfix 1.0.9).

Why this exists: until 1.0.8 the shell was ONLY a tray icon, and the
tray icon usually hides in the Windows notification-area overflow. On
launch nothing appeared anywhere, so the owner concluded three times
in one evening that the app "won't start" — while it was running
invisibly in the tray. A running app must be visible somewhere: this
window opens at launch (after setup), shows the agent and transport
status live, and carries the same actions as the tray menu.

Closing it does NOT quit: the window hides and the assistant keeps
running in the tray (the hint under the status lines says so). Status
is pushed in by the TrayController from the existing plumbing —
desktop/agent_status.py reads the agent's own log; nothing here keeps
a second copy of the state.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop.agent_status import KNOWN_TRANSPORTS, STATE_TEXT, TRANSPORT_DISPLAY

HINT_TEXT = (
    "Closing this window keeps the assistant running in the tray "
    "(the icon near the clock). Use Quit to stop it completely."
)


class ControlWindow(QWidget):
    """Status + the tray's main actions, in a window you can see."""

    def __init__(
        self,
        *,
        product_name="CodeHubb Assistant",
        on_start=None,
        on_stop=None,
        on_settings=None,
        on_view_logs=None,
        on_quit=None,
        parent=None,
    ):
        super().__init__(parent)
        # A real top-level window even though the tray controller owns us.
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self.setWindowTitle(product_name)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        title = QLabel(product_name)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        self.agent_label = QLabel("Agent: —")
        layout.addWidget(self.agent_label)
        self.transport_labels = {}
        for name in KNOWN_TRANSPORTS:
            label = QLabel(f"{TRANSPORT_DISPLAY[name]}: —")
            self.transport_labels[name] = label
            layout.addWidget(label)

        hint = QLabel(HINT_TEXT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self.start_button = QPushButton("Start Agent")
        if on_start is not None:
            self.start_button.clicked.connect(lambda _checked=False: on_start())
        row.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop Agent")
        self.stop_button.setEnabled(False)
        if on_stop is not None:
            self.stop_button.clicked.connect(lambda _checked=False: on_stop())
        row.addWidget(self.stop_button)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.settings_button = QPushButton("Settings…")
        if on_settings is not None:
            self.settings_button.clicked.connect(lambda _checked=False: on_settings())
        row.addWidget(self.settings_button)
        self.logs_button = QPushButton("View Logs")
        if on_view_logs is not None:
            self.logs_button.clicked.connect(lambda _checked=False: on_view_logs())
        row.addWidget(self.logs_button)
        row.addStretch(1)
        self.quit_button = QPushButton("Quit")
        if on_quit is not None:
            self.quit_button.clicked.connect(lambda _checked=False: on_quit())
        row.addWidget(self.quit_button)
        layout.addLayout(row)

    # ------------------------------------------------------------ status

    def update_status(self, snapshot):
        """Apply one status snapshot (built by TrayController from
        desktop.agent_status + the process state)."""
        self.agent_label.setText(snapshot.get("agent_text", "Agent: —"))
        agent_state = snapshot.get("agent_state")
        self.start_button.setEnabled(agent_state != "running")
        self.stop_button.setEnabled(agent_state == "running")
        transports = snapshot.get("transports", {})
        for name, label in self.transport_labels.items():
            state = transports.get(name, "disabled")
            label.setText(
                f"{TRANSPORT_DISPLAY[name]}: {STATE_TEXT.get(state, state)}"
            )

    # ------------------------------------------------------------ window

    def closeEvent(self, event):
        """Closing the window minimizes to the tray — never quits."""
        event.ignore()
        self.hide()
