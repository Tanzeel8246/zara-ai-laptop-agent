"""Qt-free tests for the shared transport-completeness check (hotfix 1.0.4).

The wizard used to save a switched-on-but-empty chat app without a word;
the agent then refused to start and the app bounced the user with a
"Setup needed first" dialog. transport_problems() is the single check
the wizard page, the settings dialog and Settings.validate() now share.
"""

from desktop.settings_model import Settings, transport_problems


def _settings(**overrides):
    settings = Settings()
    settings.transports = []
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_no_transports_is_a_problem_only_when_one_is_required():
    settings = _settings()
    assert transport_problems(settings, require_one=True) == [
        "Turn on at least one chat app, or the assistant will have "
        "no way to reach you."
    ]
    # validate() semantics: zero transports is not, by itself, a problem.
    assert transport_problems(settings) == []


def test_discord_checked_and_empty_names_both_missing_fields():
    settings = _settings(transports=["discord"])
    problems = transport_problems(settings, require_one=True)
    assert len(problems) == 1
    assert "Discord" in problems[0]
    assert "bot token" in problems[0]
    assert "allowed user ID" in problems[0]
    assert "untick Discord" in problems[0]


def test_discord_missing_only_token():
    settings = _settings(
        transports=["discord"], discord_allowed_user_ids="12345"
    )
    problems = transport_problems(settings)
    assert len(problems) == 1
    assert "Discord" in problems[0]
    assert "bot token" in problems[0]


def test_discord_missing_only_ids():
    settings = _settings(transports=["discord"], discord_token="tok")
    problems = transport_problems(settings)
    assert len(problems) == 1
    assert "Discord" in problems[0]
    assert "allowed user ID" in problems[0]


def test_discord_complete_is_clean():
    settings = _settings(
        transports=["discord"],
        discord_token="tok",
        discord_allowed_user_ids="12345",
    )
    assert transport_problems(settings, require_one=True) == []


def test_telegram_checked_and_empty():
    settings = _settings(transports=["telegram"])
    problems = transport_problems(settings, require_one=True)
    assert len(problems) == 1
    assert "Telegram" in problems[0]
    assert "bot token" in problems[0]
    assert "untick Telegram" in problems[0]


def test_telegram_complete_is_clean():
    settings = _settings(
        transports=["telegram"],
        telegram_token="tok",
        telegram_allowed_user_ids="67890",
    )
    assert transport_problems(settings, require_one=True) == []


def test_whatsapp_checked_without_number():
    settings = _settings(transports=["whatsapp"])
    problems = transport_problems(settings, require_one=True)
    assert len(problems) == 1
    assert "WhatsApp" in problems[0]
    assert "allowed number" in problems[0]


def test_whatsapp_with_number_is_clean():
    settings = _settings(
        transports=["whatsapp"], whatsapp_allowed_numbers="923001234567"
    )
    assert transport_problems(settings, require_one=True) == []


def test_unchecked_empty_groups_are_ignored():
    # Discord/Telegram left unticked with empty fields: not a problem as
    # long as one complete transport is on (the owner's exact 1.0.3 case
    # was the reverse — ticked groups with empty fields).
    settings = _settings(
        transports=["whatsapp"], whatsapp_allowed_numbers="923001234567"
    )
    assert transport_problems(settings, require_one=True) == []


def test_only_the_incomplete_checked_group_is_reported():
    settings = _settings(
        transports=["discord", "telegram"],
        discord_token="tok",
        discord_allowed_user_ids="12345",
    )
    problems = transport_problems(settings, require_one=True)
    assert len(problems) == 1
    assert "Telegram" in problems[0]


def test_validate_reports_transport_problems_with_the_same_wording():
    settings = _settings(transports=["telegram"])
    problems = settings.validate()
    assert any(
        p.startswith("Telegram is switched on") for p in problems
    ), problems
