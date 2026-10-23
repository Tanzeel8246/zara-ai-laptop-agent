"""Reusable settings field widgets (PySide6).

Each widget edits one slice of desktop.settings_model.Settings through
load(settings) / apply(settings), so the setup wizard (one widget per page)
and the settings dialog (widgets on tabs) share exactly the same fields,
defaults and behaviour — including where secrets go (the model decides;
widgets only hold text).
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from agent.brain.providers import PROVIDERS, get_provider, model_supports_vision
from desktop import autostart, pairing
from desktop.brain_test import test_brain_connection as probe_brain
from desktop.settings_model import SECRET_FIELDS

_ENV_BY_ATTR = dict(SECRET_FIELDS)
_ATTR_BY_ENV = {env: attr for attr, env in SECRET_FIELDS.items()}


def _secret_line_edit(value=""):
    edit = QLineEdit(value)
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText("stored in your OS keyring — never in .env")
    return edit


class GeneralFields(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Product name (shown in the app and at startup):"))
        self.product_name = QLineEdit()
        layout.addWidget(self.product_name)
        layout.addWidget(QLabel("Your assistant's name — she answers to it; rename her freely:"))
        self.assistant_name = QLineEdit()
        layout.addWidget(self.assistant_name)
        layout.addStretch(1)

    def load(self, settings):
        self.product_name.setText(settings.product_name)
        self.assistant_name.setText(settings.assistant_name)

    def apply(self, settings):
        settings.product_name = self.product_name.text().strip() or "CodeHubb Assistant"
        settings.assistant_name = self.assistant_name.text().strip() or "Zara"
        return []


class BrainFields(QWidget):
    """Brain choice: subscription, auto, or one API provider from the registry."""

    def __init__(self, parent=None, *, completion=None):
        super().__init__(parent)
        self._completion = completion  # injectable LiteLLM probe (tests fake it)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("How should your assistant think?"))
        self.choice = QComboBox()
        self.choice.addItem("Claude subscription — run on your Claude Code login, no API cost", ("subscription", "anthropic"))
        self.choice.addItem("Auto — subscription if no API key, otherwise the API below", ("auto", "anthropic"))
        for provider in PROVIDERS.values():
            self.choice.addItem(f"API — {provider.display_name}", ("api", provider.id))
        layout.addWidget(self.choice)

        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)

        self.key_label = QLabel("API key:")
        self.api_key = _secret_line_edit()
        layout.addWidget(self.key_label)
        layout.addWidget(self.api_key)

        self.base_label = QLabel("Custom endpoint base URL (e.g. https://openrouter.ai/api/v1 or http://localhost:11434/v1):")
        self.custom_base = QLineEdit()
        layout.addWidget(self.base_label)
        layout.addWidget(self.custom_base)

        self.model_label = QLabel("Model:")
        self.model = QLineEdit()
        layout.addWidget(self.model_label)
        layout.addWidget(self.model)
        # Hotfix 1.0.1: a display-style name ("Gemini 3.8 Flash") can never
        # work here — the provider needs the exact model ID. Say so, right
        # under the field, and mirror the ID in the placeholder.
        self.model_hint = QLabel(
            "Exact model ID — leave the prefilled value unless you know the ID you want."
        )
        self.model_hint.setWordWrap(True)
        self.model_hint.setStyleSheet("color: #6B7280;")
        layout.addWidget(self.model_hint)

        self.vision_warning = QLabel("")
        self.vision_warning.setWordWrap(True)
        self.vision_warning.setStyleSheet("color: #B45309; font-weight: bold;")
        layout.addWidget(self.vision_warning)

        row = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._run_test)
        row.addWidget(self.test_button)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        row.addWidget(self.test_result, 1)
        layout.addLayout(row)
        layout.addStretch(1)

        self.choice.currentIndexChanged.connect(self._sync_visibility)
        self.model.textChanged.connect(self._sync_vision_warning)

    # ------------------------------------------------------------ helpers

    def _selection(self):
        return self.choice.currentData()  # (brain_mode, provider_id)

    def _provider(self):
        _mode, provider_id = self._selection()
        return get_provider(provider_id)

    def _sync_visibility(self):
        mode, _pid = self._selection()
        provider = self._provider()
        is_api = mode == "api"
        self.api_key.setVisible(is_api)
        self.key_label.setVisible(is_api)
        if is_api and provider is not None:
            self.key_label.setText(f"API key ({provider.env_key}):")
            self.model.setPlaceholderText(provider.default_model)
            if not self.model.text().strip():
                self.model.setText(provider.default_model)
            self.notes.setText(provider.notes)
        elif mode == "subscription":
            self.notes.setText(
                "Runs on your Claude Code login through the Claude Agent SDK. "
                "The Claude Code CLI must be installed and signed in on this machine."
            )
        else:
            self.notes.setText(
                "Auto: if the Anthropic key below is set it is used; otherwise the "
                "Claude subscription login is used."
            )
            self.api_key.setVisible(True)
            self.key_label.setVisible(True)
            self.key_label.setText("API key (ANTHROPIC_API_KEY, optional in auto mode):")
        is_custom = is_api and provider is not None and provider.id == "custom"
        self.base_label.setVisible(is_custom)
        self.custom_base.setVisible(is_custom)
        self.model_label.setText(
            "Subscription model:" if mode == "subscription" else "Model:"
        )
        self._sync_vision_warning()

    def _sync_vision_warning(self):
        mode, _pid = self._selection()
        provider = self._provider()
        if mode == "api" and provider is not None and not model_supports_vision(provider, self.model.text()):
            self.vision_warning.setText(
                "⚠ This model cannot see images: screenshots will be sent to you, "
                "but the assistant will decide from text output only."
            )
        else:
            self.vision_warning.setText("")

    # ------------------------------------------------------------ load/save

    def load(self, settings):
        target = None
        for index in range(self.choice.count()):
            mode, provider_id = self.choice.itemData(index)
            if settings.brain == "subscription" and mode == "subscription":
                target = index
                break
            if settings.brain == "auto" and mode == "auto":
                target = index
                break
            if settings.brain == "api" and mode == "api" and provider_id == settings.api_provider:
                target = index
                break
        if target is None:
            target = 0
        self.choice.setCurrentIndex(target)
        provider = self._provider()
        if provider is not None:
            attr = _ATTR_BY_ENV.get(provider.env_key)
            self.api_key.setText(getattr(settings, attr, "") if attr else "")
        self.custom_base.setText(settings.custom_api_base)
        mode, _pid = self._selection()
        if mode == "subscription":
            self.model.setText(settings.subscription_model)
        else:
            self.model.setText(settings.provider_model)
        self._sync_visibility()

    def apply(self, settings):
        mode, provider_id = self._selection()
        settings.brain = mode
        if mode == "api":
            settings.api_provider = provider_id
            provider = self._provider()
            # Hotfix 1.0.1: an empty model field falls back to the
            # provider's registry default instead of saving a blank model.
            settings.provider_model = self.model.text().strip() or (
                provider.default_model if provider is not None else ""
            )
            if provider is not None:
                attr = _ATTR_BY_ENV.get(provider.env_key)
                if attr:
                    setattr(settings, attr, self.api_key.text().strip())
            if provider_id == "custom":
                settings.custom_api_base = self.custom_base.text().strip()
        elif mode == "auto":
            settings.api_provider = "anthropic"
            settings.anthropic_key = self.api_key.text().strip()
            provider = self._provider()
            settings.provider_model = (
                self.model.text().strip()
                or settings.provider_model
                or (provider.default_model if provider is not None else "")
            )
        else:  # subscription
            settings.subscription_model = self.model.text().strip() or "opus"
        return []

    # ---------------------------------------------------------------- test

    def _run_test(self):
        from desktop.settings_model import Settings

        snapshot = Settings()
        self.apply(snapshot)
        # apply() only fills the chosen provider's key; copy the rest across
        # so _provider_key() sees a coherent picture.
        ok, message = probe_brain(snapshot, completion=self._completion)
        self.test_result.setText(("✅ " if ok else "❌ ") + message)


class TransportsFields(QWidget):
    """Discord / Telegram / WhatsApp groups, each independently toggleable."""

    def __init__(self, parent=None, *, pairing_factory=None):
        super().__init__(parent)
        self._pairing_factory = pairing_factory or pairing.PairingSession
        self._pairing = None
        layout = QVBoxLayout(self)

        self.discord_group = QGroupBox("Discord")
        self.discord_group.setCheckable(True)
        d_layout = QVBoxLayout(self.discord_group)
        d_layout.addWidget(QLabel("Bot token:"))
        self.discord_token = _secret_line_edit()
        d_layout.addWidget(self.discord_token)
        d_layout.addWidget(QLabel("Allowed Discord user IDs (comma-separated — only these people can command the agent):"))
        self.discord_ids = QLineEdit()
        d_layout.addWidget(self.discord_ids)
        layout.addWidget(self.discord_group)

        self.telegram_group = QGroupBox("Telegram")
        self.telegram_group.setCheckable(True)
        t_layout = QVBoxLayout(self.telegram_group)
        t_layout.addWidget(QLabel("Bot token (from @BotFather):"))
        self.telegram_token = _secret_line_edit()
        t_layout.addWidget(self.telegram_token)
        t_layout.addWidget(QLabel("Allowed Telegram user IDs (comma-separated; message @userinfobot to learn yours):"))
        self.telegram_ids = QLineEdit()
        t_layout.addWidget(self.telegram_ids)
        t_layout.addWidget(QLabel("Proxy (optional):"))
        self.telegram_proxy = _secret_line_edit()
        self.telegram_proxy.setPlaceholderText(
            "socks5://127.0.0.1:1080 or http://127.0.0.1:8080 — leave empty for a direct connection"
        )
        t_layout.addWidget(self.telegram_proxy)
        proxy_hint = QLabel(
            "If Telegram is blocked on your network, route the bot through a local VPN/proxy."
        )
        proxy_hint.setWordWrap(True)
        t_layout.addWidget(proxy_hint)
        layout.addWidget(self.telegram_group)

        self.whatsapp_group = QGroupBox("WhatsApp (unofficial bridge)")
        self.whatsapp_group.setCheckable(True)
        w_layout = QVBoxLayout(self.whatsapp_group)
        warning = QLabel(
            "⚠ Use a DEDICATED secondary number — never your main or business number. "
            "This route uses an unofficial WhatsApp Web bridge and WhatsApp can restrict "
            "the linked number."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("font-weight: bold; color: #B91C1C;")
        w_layout.addWidget(warning)
        w_layout.addWidget(QLabel("Allowed numbers, international format, digits only (e.g. 923001234567):"))
        self.whatsapp_numbers = QLineEdit()
        w_layout.addWidget(self.whatsapp_numbers)

        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("Pairing method:"))
        self.pair_qr_radio = QRadioButton("QR code")
        self.pair_code_radio = QRadioButton("Pairing code")
        self.pair_qr_radio.setChecked(True)
        method_row.addWidget(self.pair_qr_radio)
        method_row.addWidget(self.pair_code_radio)
        method_row.addStretch(1)
        w_layout.addLayout(method_row)
        self.pair_number_label = QLabel(
            "Number of the WhatsApp account you are linking, with country code:"
        )
        w_layout.addWidget(self.pair_number_label)
        self.pair_number = QLineEdit()
        self.pair_number.setPlaceholderText("e.g. 923001234567")
        w_layout.addWidget(self.pair_number)

        pair_row = QHBoxLayout()
        self.pair_button = QPushButton("Start pairing")
        self.pair_button.clicked.connect(self.start_pairing)
        pair_row.addWidget(self.pair_button)
        self.pair_stop_button = QPushButton("Stop")
        self.pair_stop_button.clicked.connect(self.stop_pairing)
        self.pair_stop_button.setEnabled(False)
        pair_row.addWidget(self.pair_stop_button)
        pair_row.addStretch(1)
        w_layout.addLayout(pair_row)
        self.pair_status = QLabel(
            "Pairing links this computer to your WhatsApp once (like WhatsApp Web). "
            "Stop the agent before pairing."
        )
        self.pair_status.setWordWrap(True)
        w_layout.addWidget(self.pair_status)
        self.pair_code_label = QLabel("")
        self.pair_code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pair_code_label.setStyleSheet("font-size: 30px; font-weight: bold;")
        self.pair_code_label.setVisible(False)
        w_layout.addWidget(self.pair_code_label)
        self.pair_code_help = QLabel(
            "On your phone: WhatsApp → Linked devices → Link a device → "
            "“Link with phone number instead” → enter the code shown here. "
            "This asks for the same link a different way — WhatsApp can "
            "still decline it."
        )
        self.pair_code_help.setWordWrap(True)
        w_layout.addWidget(self.pair_code_help)
        self.pair_tips = QLabel(
            "Scanning tips: use the official WhatsApp app → Settings → "
            "Linked devices → Link a device (not the camera). If several "
            "attempts fail, WhatsApp may pause linking for a while — "
            "wait before retrying."
        )
        self.pair_tips.setWordWrap(True)
        w_layout.addWidget(self.pair_tips)
        self.qr_label = QLabel("")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(0)
        w_layout.addWidget(self.qr_label)
        layout.addWidget(self.whatsapp_group)
        layout.addStretch(1)

        self._pair_timer = QTimer(self)
        self._pair_timer.setInterval(800)
        self._pair_timer.timeout.connect(self.poll_pairing)
        self.pair_qr_radio.toggled.connect(self._sync_pairing_method)
        self.pair_code_radio.toggled.connect(self._sync_pairing_method)
        self.pair_number.textChanged.connect(self._sync_pair_button)
        self.whatsapp_numbers.textChanged.connect(self._prefill_pair_number)
        self._sync_pairing_method()

    # ------------------------------------------------------------ load/save

    def load(self, settings):
        self.discord_group.setChecked("discord" in settings.transports)
        self.telegram_group.setChecked("telegram" in settings.transports)
        self.whatsapp_group.setChecked("whatsapp" in settings.transports)
        self.discord_token.setText(settings.discord_token)
        self.discord_ids.setText(settings.discord_allowed_user_ids)
        self.telegram_token.setText(settings.telegram_token)
        self.telegram_ids.setText(settings.telegram_allowed_user_ids)
        self.telegram_proxy.setText(settings.telegram_proxy)
        self.whatsapp_numbers.setText(settings.whatsapp_allowed_numbers)
        self._prefill_pair_number()

    def apply(self, settings):
        transports = []
        if self.discord_group.isChecked():
            transports.append("discord")
        if self.telegram_group.isChecked():
            transports.append("telegram")
        if self.whatsapp_group.isChecked():
            transports.append("whatsapp")
        settings.transports = transports
        settings.discord_token = self.discord_token.text().strip()
        settings.discord_allowed_user_ids = self.discord_ids.text().strip()
        settings.telegram_token = self.telegram_token.text().strip()
        settings.telegram_allowed_user_ids = self.telegram_ids.text().strip()
        settings.telegram_proxy = self.telegram_proxy.text().strip()
        settings.whatsapp_allowed_numbers = self.whatsapp_numbers.text().strip()
        return []

    # -------------------------------------------------------------- pairing

    def _first_allowed_number(self):
        for part in self.whatsapp_numbers.text().split(","):
            digits = pairing.normalize_pairing_number(part)
            if digits:
                return digits
        return ""

    def _prefill_pair_number(self):
        """The pairing number defaults to the first allowed number — the
        account being linked is normally the one allowed to command."""
        if not self.pair_number.text().strip():
            first = self._first_allowed_number()
            if first:
                self.pair_number.setText(first)

    def _sync_pairing_method(self):
        code_mode = self.pair_code_radio.isChecked()
        self.pair_number_label.setVisible(code_mode)
        self.pair_number.setVisible(code_mode)
        self.pair_code_help.setVisible(code_mode)
        self.pair_tips.setVisible(not code_mode)
        if code_mode:
            self._prefill_pair_number()
        self._sync_pair_button()

    def _sync_pair_button(self):
        if self._pairing is not None:
            self.pair_button.setEnabled(False)
            return
        if self.pair_code_radio.isChecked():
            digits = pairing.normalize_pairing_number(self.pair_number.text())
            # Same bar as the sidecar's own sanity check: a real
            # international number is at least 10 digits.
            self.pair_button.setEnabled(len(digits) >= 10)
        else:
            self.pair_button.setEnabled(True)

    def _set_method_controls_enabled(self, enabled):
        self.pair_qr_radio.setEnabled(enabled)
        self.pair_code_radio.setEnabled(enabled)
        self.pair_number.setEnabled(enabled)

    def start_pairing(self):
        if self._pairing is not None:
            return
        self._pairing = self._pairing_factory()
        if self.pair_code_radio.isChecked():
            status = self._pairing.start(
                method="code",
                number=pairing.normalize_pairing_number(
                    self.pair_number.text()
                ),
            )
        else:
            status = self._pairing.start()
        self.pair_button.setEnabled(False)
        self.pair_stop_button.setEnabled(True)
        self._set_method_controls_enabled(False)
        self._pair_timer.start()
        self._show_pairing_status(status)

    def poll_pairing(self):
        if self._pairing is None:
            return
        self._show_pairing_status(self._pairing.poll())

    def _show_pairing_status(self, status):
        if status.detail:
            self.pair_status.setText(status.detail)
        code = getattr(status, "pairing_code", "")
        if code:
            self.pair_code_label.setText(pairing.format_pairing_code(code))
            self.pair_code_label.setVisible(True)
        if status.state == "waiting_qr" and status.qr:
            data = pairing.make_qr_png_bytes(status.qr)
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                # Hotfix 1.0.1: WhatsApp payloads render as very large PNGs;
                # cap what the label shows at 320x320 so the code always
                # fits the page and stays scannable.
                if pixmap.width() > 320 or pixmap.height() > 320:
                    pixmap = pixmap.scaled(
                        320, 320,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                self.qr_label.setPixmap(pixmap)
                self.qr_label.setMinimumHeight(pixmap.height())
        if status.state in ("connected", "logged_out", "error", "stopped"):
            if status.state == "connected":
                self.pair_status.setText("✅ " + (status.detail or "Phone linked — WhatsApp is ready."))
            self._pair_timer.stop()
            self.stop_pairing()

    def stop_pairing(self):
        self._pair_timer.stop()
        if self._pairing is not None:
            try:
                self._pairing.stop()
            except Exception:  # noqa: BLE001 - leaving the page must never crash
                pass
            self._pairing = None
        self.pair_code_label.setText("")
        self.pair_code_label.setVisible(False)
        self.pair_stop_button.setEnabled(False)
        self._set_method_controls_enabled(True)
        self._sync_pair_button()


class BehaviourFields(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._initial_autostart = autostart.is_enabled()
        layout = QVBoxLayout(self)
        self.confirm_risky = QCheckBox("Ask me before risky actions (recommended)")
        layout.addWidget(self.confirm_risky)
        explanation = QLabel(
            "When this is ON, destructive actions — deleting files, shutting down, "
            "editing the registry, force-closing programs — pause and ask for your "
            "approval in the chat first. When it is OFF the assistant acts "
            "immediately, with no questions."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(QLabel("Voice replies:"))
        self.voice_mode = QComboBox()
        self.voice_mode.addItem("Auto — speak when I send a voice note", "auto")
        self.voice_mode.addItem("Always — speak every reply", "always")
        self.voice_mode.addItem("Never — text only", "never")
        layout.addWidget(self.voice_mode)

        self.show_tool_calls = QCheckBox("Show a line for every tool call (debugging — noisy)")
        layout.addWidget(self.show_tool_calls)

        row = QHBoxLayout()
        row.addWidget(QLabel("Max steps per instruction:"))
        self.max_iterations = QSpinBox()
        self.max_iterations.setRange(10, 5000)
        row.addWidget(self.max_iterations)
        row.addStretch(1)
        layout.addLayout(row)

        self.autostart_box = QCheckBox("Start the assistant automatically when I log in to Windows")
        layout.addWidget(self.autostart_box)
        if not autostart.supported():
            self.autostart_box.setEnabled(False)
            note = QLabel("Autostart setup is Windows-only in this build.")
            layout.addWidget(note)
        layout.addStretch(1)

    def load(self, settings):
        self.confirm_risky.setChecked(settings.confirm_risky)
        index = self.voice_mode.findData(settings.voice_replies)
        self.voice_mode.setCurrentIndex(index if index >= 0 else 0)
        self.show_tool_calls.setChecked(settings.show_tool_calls)
        self.max_iterations.setValue(settings.max_iterations)
        self._initial_autostart = autostart.is_enabled(product_name=settings.product_name)
        self.autostart_box.setChecked(self._initial_autostart)

    def apply(self, settings):
        settings.confirm_risky = self.confirm_risky.isChecked()
        settings.voice_replies = self.voice_mode.currentData()
        settings.show_tool_calls = self.show_tool_calls.isChecked()
        settings.max_iterations = self.max_iterations.value()
        messages = []
        wanted = self.autostart_box.isChecked()
        if autostart.supported() and wanted != self._initial_autostart:
            ok, message = autostart.set_enabled(wanted, product_name=settings.product_name)
            messages.append(message)
            if ok:
                self._initial_autostart = wanted
        return messages
