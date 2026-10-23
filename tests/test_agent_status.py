"""Qt-free tests for desktop/agent_status.py — per-transport status
parsed from the agent's own log lines (the exact strings the agent,
its supervisor and the transports print today)."""

from desktop.agent_status import transport_states

TELEGRAM_START = "  CodeHubb Assistant — Telegram transport starting (long polling)"
TELEGRAM_RETRY = (
    "  [telegram] Telegram unreachable (NetworkError: httpx.ConnectError) — "
    "retrying in 30s. The agent stays up; check the network/VPN if this repeats."
)
TELEGRAM_CREDS_RETRY = (
    "  [telegram] Telegram rejected its sign-in (InvalidToken) — that usually "
    "means a bad token or credentials; check them in Settings. "
    "Retrying in 15s anyway, in case it was a glitch."
)


def test_disabled_and_stopped_defaults():
    states = transport_states("", ["telegram"], agent_running=False)
    assert states == {
        "discord": "disabled",
        "telegram": "stopped",
        "whatsapp": "disabled",
    }


def test_enabled_but_agent_down_is_stopped_even_with_old_log_lines():
    states = transport_states(TELEGRAM_START, ["telegram"], agent_running=False)
    assert states["telegram"] == "stopped"


def test_running_with_no_events_yet_is_connecting():
    states = transport_states("", ["discord", "whatsapp"], agent_running=True)
    assert states["discord"] == "connecting"
    assert states["whatsapp"] == "connecting"


def test_telegram_start_line_means_connected():
    states = transport_states(TELEGRAM_START, ["telegram"], agent_running=True)
    assert states["telegram"] == "connected"


def test_telegram_supervisor_retry_after_start_is_retrying():
    log = TELEGRAM_START + "\n" + TELEGRAM_RETRY
    states = transport_states(log, ["telegram"], agent_running=True)
    assert states["telegram"] == "retrying"


def test_telegram_credentials_retry_line_is_retrying():
    log = TELEGRAM_START + "\n" + TELEGRAM_CREDS_RETRY
    states = transport_states(log, ["telegram"], agent_running=True)
    assert states["telegram"] == "retrying"


def test_telegram_recovery_start_after_retry_is_connected():
    log = "\n".join([TELEGRAM_START, TELEGRAM_RETRY, TELEGRAM_START])
    states = transport_states(log, ["telegram"], agent_running=True)
    assert states["telegram"] == "connected"


def test_telegram_stopped_line_wins_over_start():
    log = TELEGRAM_START + "\n  [telegram] transport stopped.\n"
    states = transport_states(log, ["telegram"], agent_running=True)
    assert states["telegram"] == "stopped"


def test_discord_online_then_connection_lost_then_online():
    online = "  CodeHubb Assistant — Zara is online as CodeHubbBot#1234"
    lost = "  Connection lost (OSError: network down). Retrying in 10s..."
    assert transport_states(online, ["discord"], agent_running=True)["discord"] == "connected"
    log = online + "\n" + lost
    assert transport_states(log, ["discord"], agent_running=True)["discord"] == "retrying"
    assert transport_states(log + "\n" + online, ["discord"], agent_running=True)["discord"] == "connected"


def test_whatsapp_bridge_coming_up_then_online_then_sidecar_noise():
    sidecar = "[whatsapp-sidecar] listening on 127.0.0.1:17331"
    online = "  CodeHubb Assistant — WhatsApp transport online as 923001234567@s.whatsapp.net"
    states = transport_states(sidecar, ["whatsapp"], agent_running=True)
    assert states["whatsapp"] == "connecting"
    states = transport_states(sidecar + "\n" + online, ["whatsapp"], agent_running=True)
    assert states["whatsapp"] == "connected"
    # Sidecar chatter after "online" must not drag it back to connecting.
    states = transport_states(
        sidecar + "\n" + online + "\n[whatsapp-sidecar] message received",
        ["whatsapp"], agent_running=True,
    )
    assert states["whatsapp"] == "connected"


def test_whatsapp_sidecar_exit_is_retrying_and_logout_is_stopped():
    exited = "[whatsapp] sidecar exited (code 1); restarting in 4s..."
    states = transport_states(exited, ["whatsapp"], agent_running=True)
    assert states["whatsapp"] == "retrying"
    logged_out = (
        "  [whatsapp] The WhatsApp pairing was logged out (phone removed "
        "the linked device, or the session expired)."
    )
    states = transport_states(logged_out, ["whatsapp"], agent_running=True)
    assert states["whatsapp"] == "stopped"


def test_could_not_start_is_error():
    log = "  [telegram] could not start: RuntimeError: boom"
    states = transport_states(log, ["telegram"], agent_running=True)
    assert states["telegram"] == "error"


def test_all_transports_stopped_line_stops_everything_enabled():
    log = TELEGRAM_START + "\n  All transports have stopped.\n"
    states = transport_states(log, ["telegram", "discord"], agent_running=True)
    assert states["telegram"] == "stopped"
    assert states["discord"] == "stopped"


def test_events_for_disabled_transports_are_ignored():
    states = transport_states(TELEGRAM_START, ["discord"], agent_running=True)
    assert states["telegram"] == "disabled"
    assert states["discord"] == "connecting"
