"""First-run setup wizard (PySide6 QWizard).

Six pages — Welcome, License, Brain, Transports, Behaviour, Finish.
Settings pages flow through desktop.settings_model.Settings only; the
License page is the exception by design: activation acts immediately
(keyring + license server), so it hosts desktop.license_panel.LicensePanel
bound to agent.licensing, not to the Settings model. Re-runnable at any
time from the tray menu.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from desktop import diagnostics
from desktop.fields import BehaviourFields, BrainFields, GeneralFields, TransportsFields
from desktop.license_panel import LicensePanel
from desktop.settings_model import Settings, transport_problems


def _scroll_area(widget):
    """Wrap a page body in a borderless vertical scroll area (hotfix 1.0.1).

    Wizard pages used to lay their content out directly, so on shorter
    windows the bottom of a page — the WhatsApp QR included — was simply
    cut off with no way to reach it. Every page body now scrolls; the
    page title/subtitle stay native to the wizard, outside the area.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class _FieldsPage(QWizardPage):
    """A wizard page hosting one reusable fields widget, scrollable."""

    fields_factory = None  # set by subclasses

    def __init__(self, title, subtitle=""):
        super().__init__()
        self.setTitle(title)
        if subtitle:
            self.setSubTitle(subtitle)
        self.fields = self.fields_factory()
        self.scroll = _scroll_area(self.fields)
        layout = QVBoxLayout(self)
        layout.addWidget(self.scroll)

    def swap_fields(self, fields):
        """Replace the hosted fields widget (injectable-probe pages)."""
        old = self.fields
        self.fields = fields
        self.scroll.takeWidget()  # detaches `old` from the scroll area
        self.scroll.setWidget(fields)
        old.deleteLater()

    def initializePage(self):
        self.fields.load(self.wizard().settings)

    def validatePage(self):
        messages = self.fields.apply(self.wizard().settings)
        self.wizard().notes.extend(messages)
        return True

    def cleanupPage(self):
        stop = getattr(self.fields, "stop_pairing", None)
        if callable(stop):
            stop()


class WelcomePage(_FieldsPage):
    fields_factory = GeneralFields

    def __init__(self):
        super().__init__(
            "Welcome to CodeHubb Assistant",
            "Your own AI assistant for this computer",
        )
        intro = QLabel(
            "• Chat with it from WhatsApp, Telegram or Discord — it works this computer for you.\n"
            "• It can open apps, manage files, browse the web, take screenshots and speak replies aloud.\n"
            "• You bring your own AI account (a Claude subscription or an API key) — "
            "there is no extra AI bill from us."
        )
        intro.setWordWrap(True)
        self.layout().insertWidget(0, intro)


class LicensePage(QWizardPage):
    """The real license page (Phase 4): hosts the shared LicensePanel."""

    def __init__(self, license_client=None):
        super().__init__()
        self.setTitle("License")
        self.setSubTitle("Your trial, your key, this computer")
        layout = QVBoxLayout(self)
        self.panel = LicensePanel(client=license_client)
        layout.addWidget(_scroll_area(self.panel))

    def initializePage(self):
        self.panel.refresh()


class BrainPage(_FieldsPage):
    fields_factory = BrainFields

    def __init__(self, completion=None):
        super().__init__("Brain", "Pick the AI your assistant thinks with")
        # _FieldsPage built the widget with the default factory; rebuild with
        # the injectable probe when one was supplied.
        if completion is not None:
            self.swap_fields(BrainFields(completion=completion))


class TransportsPage(_FieldsPage):
    def __init__(self, pairing_factory=None):
        super().__init__(
            "Chats & messaging",
            "Enable only the apps you want — each one can be skipped and set up later",
        )
        if pairing_factory is not None:
            self.swap_fields(TransportsFields(pairing_factory=pairing_factory))

    fields_factory = TransportsFields

    def validatePage(self):
        # Hotfix 1.0.4: a switched-on-but-empty chat app used to sail
        # through the wizard and only bounce the user AFTER it finished
        # (the "Setup needed first" dialog). Block here instead, naming
        # the group and the remedy; unchecked groups are ignored.
        messages = self.fields.apply(self.wizard().settings)
        self.wizard().notes.extend(messages)
        problems = transport_problems(self.wizard().settings, require_one=True)
        if problems:
            QMessageBox.warning(self, "Chats & messaging", "\n\n".join(problems))
            return False
        return True


class BehaviourPage(_FieldsPage):
    fields_factory = BehaviourFields

    def __init__(self):
        super().__init__("Behaviour & safety", "How careful should she be?")


class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Ready")
        self.setSubTitle("Review, then start your assistant")
        body = QWidget()
        body_layout = QVBoxLayout(body)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        body_layout.addWidget(self.summary)
        self.start_now = QCheckBox("Start the agent when I finish")
        self.start_now.setChecked(True)
        body_layout.addWidget(self.start_now)
        body_layout.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(_scroll_area(body))

    def initializePage(self):
        wizard = self.wizard()
        # Make sure the diagnostics reflect every page, even ones the user
        # reached with the Back button.
        problems = wizard.settings.validate()
        warnings = wizard.settings.validate_warnings()
        report = diagnostics.build_report(problems=problems, warnings=warnings)
        tail = "\n".join(report.splitlines()[:14])
        self.summary.setText(
            "Setup summary (full diagnostics are available from the tray menu):\n\n" + tail
        )


class SetupWizard(QWizard):
    """Modal wizard bound to one Settings object; saves on Finish."""

    def __init__(self, settings=None, parent=None, *, completion=None,
                 pairing_factory=None, env_path=None, license_client=None):
        super().__init__(parent)
        self.settings = settings or Settings.load(env_path)
        self.env_path = env_path
        self.notes = []
        self.save_result = None
        self.setWindowTitle(f"{self.settings.product_name} — Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.addPage(WelcomePage())
        self.addPage(LicensePage(license_client=license_client))
        self.addPage(BrainPage(completion=completion))
        self.addPage(TransportsPage(pairing_factory=pairing_factory))
        self.addPage(BehaviourPage())
        self.addPage(FinishPage())
        self.resize(680, 560)

    @property
    def start_agent_requested(self):
        page = self.page(5)
        return bool(page and page.start_now.isChecked())

    def accept(self):
        # Apply every fields page (validatePage only ran for visited pages
        # when jumping around), then persist through the model.
        for page_id in self.pageIds():
            page = self.page(page_id)
            fields = getattr(page, "fields", None)
            if fields is not None:
                self.notes.extend(fields.apply(self.settings))
        self.save_result = self.settings.save(self.env_path)
        super().accept()

    def reject(self):
        transports = self.page(3)
        fields = getattr(transports, "fields", None)
        if fields is not None:
            fields.stop_pairing()
        super().reject()
