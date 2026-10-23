"""Offscreen GUI smoke tests — construction only, no event loop, no display.

Skipped cleanly when PySide6 is not installed (headless agent installs).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="GUI dependencies not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_tray_controller_constructs(qapp, tmp_path):
    from desktop.app import create_controller

    controller = create_controller(
        qapp, env_path=tmp_path / ".env", auto_open_wizard=False
    )
    try:
        # a fresh tmp .env bootstraps from the example -> not fully configured
        assert controller.status() in ("not_configured", "stopped")
        menu = controller.tray.contextMenu()
        texts = [a.text() for a in menu.actions()]
        assert any("Start Agent" in t for t in texts)
        assert any("Setup Wizard" in t for t in texts)
        assert any("Audit Log" in t for t in texts)
        assert any("Diagnostics" in t for t in texts)
        controller.refresh_status()
    finally:
        controller.tray.hide()


def test_wizard_constructs_with_all_pages(qapp, tmp_path):
    from desktop.settings_model import Settings
    from desktop.wizard import SetupWizard

    wizard = SetupWizard(Settings(), env_path=tmp_path / ".env")
    assert len(wizard.pageIds()) == 6
    titles = [wizard.page(i).title() for i in wizard.pageIds()]
    assert any("Welcome" in t for t in titles)
    assert any("License" in t for t in titles)
    # license page is the honest placeholder
    from PySide6.QtWidgets import QLabel

    license_page = wizard.page(1)

    texts = [label.text() for label in license_page.findChildren(QLabel)]
    assert any("Development build — no license required" in t for t in texts)
    wizard.close()


def test_settings_dialog_and_audit_view_construct(qapp, tmp_path):
    from desktop.audit_view import AuditView
    from desktop.settings_dialog import SettingsDialog
    from desktop.settings_model import Settings

    dialog = SettingsDialog(Settings(), env_path=tmp_path / ".env")
    dialog.close()

    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(
        '{"ts": "t", "brain": "api", "tool": "screenshot", "args": "", "decision": "allowed"}\n',
        encoding="utf-8",
    )
    view = AuditView(audit_path=audit_path)
    assert view.table.rowCount() == 1
    view.filter_edit.setText("screenshot")
    assert view.table.rowCount() == 1
    view.filter_edit.setText("nomatch")
    assert view.table.rowCount() == 0
    view.close()


class _StubMessageBox:
    """Records QMessageBox.warning calls instead of blocking modally."""

    warnings = []

    @staticmethod
    def warning(parent, title, text):
        _StubMessageBox.warnings.append((title, text))


def test_wizard_transports_page_blocks_checked_but_empty(qapp, tmp_path, monkeypatch):
    import desktop.wizard as wizard_module
    from desktop.settings_model import Settings
    from desktop.wizard import SetupWizard

    _StubMessageBox.warnings = []
    monkeypatch.setattr(wizard_module, "QMessageBox", _StubMessageBox)

    wizard = SetupWizard(Settings(), env_path=tmp_path / ".env")
    try:
        page = wizard.page(3)  # Transports
        fields = page.fields
        # The owner's exact case: WhatsApp is the only transport he wants,
        # but Discord (default) + Telegram are ticked with empty fields.
        fields.discord_group.setChecked(True)
        fields.telegram_group.setChecked(True)
        fields.whatsapp_group.setChecked(True)
        fields.whatsapp_numbers.setText("923001234567")
        assert page.validatePage() is False
        shown = "\n".join(text for _title, text in _StubMessageBox.warnings)
        assert "Discord" in shown
        assert "Telegram" in shown
        assert "WhatsApp" not in shown  # complete group is not reported

        # Unticking the empty groups (the offered remedy) unblocks the page.
        _StubMessageBox.warnings = []
        fields.discord_group.setChecked(False)
        fields.telegram_group.setChecked(False)
        assert page.validatePage() is True
        assert _StubMessageBox.warnings == []

        # Nothing ticked at all is also blocked.
        fields.whatsapp_group.setChecked(False)
        assert page.validatePage() is False
        shown = "\n".join(text for _title, text in _StubMessageBox.warnings)
        assert "at least one chat app" in shown
    finally:
        wizard.close()


def test_settings_dialog_save_blocks_checked_but_empty(qapp, tmp_path, monkeypatch):
    import desktop.settings_dialog as dialog_module
    from desktop.settings_dialog import SettingsDialog
    from desktop.settings_model import Settings

    _StubMessageBox.warnings = []
    monkeypatch.setattr(dialog_module, "QMessageBox", _StubMessageBox)

    dialog = SettingsDialog(Settings(), env_path=tmp_path / ".env")
    try:
        fields = dialog.transports_fields
        fields.discord_group.setChecked(False)
        fields.telegram_group.setChecked(True)  # token/IDs left empty
        fields.whatsapp_group.setChecked(False)
        dialog._save()
        assert dialog.save_result is None  # refused before saving
        shown = "\n".join(text for _title, text in _StubMessageBox.warnings)
        assert "Telegram" in shown
    finally:
        dialog.close()


def test_wizard_pairing_panel_with_fake_session(qapp, tmp_path):
    from desktop.fields import TransportsFields
    from desktop.pairing import PairingStatus

    class FakeSession:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self, method="qr", number=""):
            self.started = True
            return PairingStatus("waiting_qr", qr="QRDATA", detail="Scan the QR code")

        def poll(self):
            return PairingStatus("waiting_qr", qr="QRDATA", detail="Scan the QR code")

        def stop(self):
            self.stopped = True

    fake = FakeSession()
    fields = TransportsFields(pairing_factory=lambda: fake)
    fields.start_pairing()
    assert fake.started is True
    assert fields.pair_status.text() == "Scan the QR code"
    assert fields.qr_label.pixmap() is not None
    fields.stop_pairing()
    assert fake.stopped is True


# ------------------------------------------------------- hotfix 1.0.1

def test_wizard_page_bodies_are_scrollable(qapp, tmp_path):
    """Hotfix 1.0.1: every wizard page body lives in a QScrollArea, so a
    short window can no longer cut content off with no way to reach it."""
    from PySide6.QtWidgets import QScrollArea

    from desktop.settings_model import Settings
    from desktop.wizard import SetupWizard

    wizard = SetupWizard(Settings(), env_path=tmp_path / ".env")
    try:
        for page_id in wizard.pageIds():
            page = wizard.page(page_id)
            areas = page.findChildren(QScrollArea)
            assert areas, f"page {page_id} ({page.title()}) has no scroll area"
        # fields pages: the scroll area hosts exactly the fields widget
        for page_id in (0, 2, 3, 4):
            page = wizard.page(page_id)
            assert page.scroll.widget() is page.fields
        # license page: the panel itself is the scrolled widget
        license_page = wizard.page(1)
        assert license_page.findChild(QScrollArea).widget() is license_page.panel
    finally:
        wizard.close()


def test_brain_fields_model_guidance_and_fallback(qapp):
    """Hotfix 1.0.1 (Bug 3): switching provider updates the model field's
    placeholder to the registry default ID, a hint explains the ID must be
    exact, and an empty field falls back to that default on apply (which is
    also the path Test connection takes)."""
    from desktop.fields import BrainFields
    from desktop.settings_model import Settings

    fields = BrainFields()
    assert "Exact model ID" in fields.model_hint.text()

    def select(provider_id):
        for index in range(fields.choice.count()):
            mode, pid = fields.choice.itemData(index)
            if mode == "api" and pid == provider_id:
                fields.choice.setCurrentIndex(index)
                return
        raise AssertionError(f"provider {provider_id} not in combo")

    select("gemini")
    assert fields.model.placeholderText() == "gemini-3.8-flash"
    select("openai")
    assert fields.model.placeholderText() == "gpt-5"

    select("gemini")
    fields.model.setText("")  # owner cleared it — apply must not save blank
    snapshot = Settings()
    fields.apply(snapshot)
    assert snapshot.api_provider == "gemini"
    assert snapshot.provider_model == "gemini-3.8-flash"


def test_qr_label_caps_pixmap_at_320(qapp):
    """Hotfix 1.0.1: a realistic (long) WhatsApp payload renders a huge PNG;
    the label must scale it down to at most 320x320 so it can be scanned."""
    from desktop.fields import TransportsFields
    from desktop.pairing import PairingStatus

    # realistic shape/length of a WhatsApp Web pairing payload
    long_payload = (
        "2@zKx9Qp2LmN4vR8sT1wY6bH3jF5dA7gE0cXuIoPqWrTyUiOpAsDfGhJkLzXcVbNm"
        "QwErTyUiOp1234567890+/=,aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdef"
        "FEDCBA9876543210zyxwvutsrqponmlkjihgfedcba,923001234567,ABCD1234"
    )

    class FakeSession:
        def start(self, method="qr", number=""):
            return PairingStatus("waiting_qr", qr=long_payload, detail="scan")

        def poll(self):
            return PairingStatus("waiting_qr", qr=long_payload, detail="scan")

        def stop(self):
            pass

    fields = TransportsFields(pairing_factory=FakeSession)
    fields.start_pairing()
    pixmap = fields.qr_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() <= 320
    assert pixmap.height() <= 320
    fields.stop_pairing()


# ------------------------------------------------------- hotfix 1.0.6

def test_transports_fields_code_mode_flow(qapp):
    """Pairing-code mode: Start is gated on a >=10 digit number, the
    session receives method+number, and the polled code is displayed
    prominently (grouped 4-4) until pairing stops."""
    from desktop.fields import TransportsFields
    from desktop.pairing import PairingStatus

    class FakeSession:
        def __init__(self):
            self.start_args = None
            self.stopped = False

        def start(self, method="qr", number=""):
            self.start_args = (method, number)
            return PairingStatus("starting", detail="Starting the bridge…")

        def poll(self):
            return PairingStatus(
                "waiting_code", pairing_code="ABCDEFGH",
                detail="Enter the code",
            )

        def stop(self):
            self.stopped = True

    fake = FakeSession()
    fields = TransportsFields(pairing_factory=lambda: fake)
    # QR mode is the default: code widgets hidden, Start always enabled
    assert fields.pair_qr_radio.isChecked()
    assert fields.pair_number.isHidden()
    assert fields.pair_code_label.isHidden()
    assert fields.pair_button.isEnabled()
    # code mode: number appears, Start waits for a real number
    fields.pair_code_radio.setChecked(True)
    assert not fields.pair_number.isHidden()
    assert not fields.pair_button.isEnabled()
    fields.pair_number.setText("12345")
    assert not fields.pair_button.isEnabled()
    fields.pair_number.setText("+92 300-1234567")
    assert fields.pair_button.isEnabled()
    fields.start_pairing()
    assert fake.start_args == ("code", "923001234567")
    assert not fields.pair_button.isEnabled()  # running
    # the next poll brings the code -> prominent display, grouped 4-4
    fields.poll_pairing()
    assert fields.pair_status.text() == "Enter the code"
    assert fields.pair_code_label.text() == "ABCD-EFGH"
    assert not fields.pair_code_label.isHidden()
    fields.stop_pairing()
    assert fake.stopped is True
    assert fields.pair_code_label.text() == ""
    assert fields.pair_code_label.isHidden()


def test_transports_fields_code_number_prefill(qapp):
    """The pairing number is prefilled from the first allowed number and
    stays editable."""
    from desktop.fields import TransportsFields
    from desktop.settings_model import Settings

    fields = TransportsFields()
    settings = Settings()
    settings.whatsapp_allowed_numbers = "923001234567, 923217654321"
    fields.load(settings)
    assert fields.pair_number.text() == "923001234567"
    # typing the allowlist first entry later also fills an empty field
    fields.pair_number.setText("")
    fields.whatsapp_numbers.setText("923339998887")
    assert fields.pair_number.text() == "923339998887"


def test_transports_fields_qr_mode_starts_without_method_args(qapp):
    """QR mode is byte-for-byte the old behaviour: start() with no
    method/number, QR rendered as before."""
    from desktop.fields import TransportsFields
    from desktop.pairing import PairingStatus

    class FakeSession:
        def __init__(self):
            self.start_args = None

        def start(self, *args, **kwargs):
            self.start_args = (args, kwargs)
            return PairingStatus("waiting_qr", qr="QRDATA", detail="scan")

        def poll(self):
            return PairingStatus("waiting_qr", qr="QRDATA", detail="scan")

        def stop(self):
            pass

    fake = FakeSession()
    fields = TransportsFields(pairing_factory=lambda: fake)
    fields.start_pairing()
    assert fake.start_args == ((), {})
    assert fields.qr_label.pixmap() is not None
    fields.stop_pairing()
