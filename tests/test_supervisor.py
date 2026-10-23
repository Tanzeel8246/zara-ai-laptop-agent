"""Hotfix 1.0.7: transport supervision.

The owner's ISP SNI-filters api.telegram.org (TLS handshake timeout), which
crashed his only transport seconds after start and took the whole agent
down. These tests pin the replacement behaviour: a crashed transport is
retried with capped exponential backoff, the agent stays alive while every
transport is down, a recovered transport resumes without an agent restart,
and a bad-token failure is logged as a credentials problem — not silently
looped as if it were the network.

All waiting is injected (fake sleep / fake clock / a stop event): the suite
never really sleeps on backoff.
"""

import threading

from agent import supervisor
from agent.supervisor import backoff_delay, classify_failure, supervise_transport


# Exception classes whose NAMES mirror the real libraries' errors — the
# classifier is name-based so it never imports telegram/discord itself.
class NetworkError(Exception):
    pass


class TimedOut(Exception):
    pass


class InvalidToken(Exception):
    pass


class ScriptedTransport:
    """Plays a script of outcomes, one per run() call."""

    name = "telegram"

    def __init__(self, script, clock=None):
        self.script = list(script)
        self.clock = clock
        self.runs = 0

    def run(self):
        self.runs += 1
        action = self.script.pop(0) if self.script else ("return",)
        if action[0] == "advance":      # simulate a long run, then do `inner`
            _, seconds, inner = action
            if self.clock is not None:
                self.clock[0] += seconds
            action = inner
        if action[0] == "raise":
            raise action[1]
        if action[0] == "exit":
            raise SystemExit(action[1])
        return None


class AlwaysDownTransport:
    name = "telegram"

    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1
        raise NetworkError("TLS handshake timed out")


def _rig(transport, **kwargs):
    sleeps, lines = [], []
    kwargs.setdefault("sleep", sleeps.append)
    kwargs.setdefault("log", lines.append)
    return sleeps, lines, kwargs


# ------------------------------------------------------------- backoff math

def test_backoff_sequence_matches_the_documented_steps():
    assert [backoff_delay(n) for n in range(1, 8)] == [5, 15, 30, 60, 300, 300, 300]


# ----------------------------------------------------------- classification

def test_classify_network_by_name_and_builtin():
    assert classify_failure(NetworkError("x")) == "network"
    assert classify_failure(TimedOut("x")) == "network"
    assert classify_failure(ConnectionError("x")) == "network"
    assert classify_failure(TimeoutError("x")) == "network"


def test_classify_credentials_beats_network_wrapping():
    assert classify_failure(InvalidToken("401")) == "credentials"
    try:
        try:
            raise InvalidToken("bad token")
        except InvalidToken as exc:
            raise RuntimeError("startup failed") from exc
    except RuntimeError as wrapped:
        assert classify_failure(wrapped) == "credentials"


def test_classify_wrapped_network_cause():
    try:
        try:
            raise NetworkError("TLS timed out")
        except NetworkError as exc:
            raise RuntimeError("polling died") from exc
    except RuntimeError as wrapped:
        assert classify_failure(wrapped) == "network"


def test_classify_unknown():
    assert classify_failure(ValueError("nope")) == "unknown"


# -------------------------------------------------------------- retry loop

def test_fails_twice_then_recovers_without_restart():
    transport = ScriptedTransport([
        ("raise", NetworkError("TLS handshake timed out")),
        ("raise", NetworkError("TLS handshake timed out")),
        ("return",),
    ])
    sleeps, lines, kwargs = _rig(transport)
    result = supervise_transport(transport, **kwargs)
    assert result == "stopped"
    assert transport.runs == 3
    assert sleeps == [5, 15]                       # the backoff sequence, in order
    text = "\n".join(lines)
    assert "Telegram unreachable" in text
    assert "retrying in 5s" in text and "retrying in 15s" in text


def test_backoff_reaches_the_five_minute_cap():
    transport = ScriptedTransport([("raise", NetworkError("x"))] * 6)
    sleeps, lines, kwargs = _rig(transport, max_attempts=6)
    result = supervise_transport(transport, **kwargs)
    assert result == "exhausted"
    assert transport.runs == 6
    assert sleeps == [5, 15, 30, 60, 300]


def test_invalid_token_is_logged_as_credentials_not_network():
    transport = ScriptedTransport([("raise", InvalidToken("401 Unauthorized"))] * 2)
    sleeps, lines, kwargs = _rig(transport, max_attempts=2)
    result = supervise_transport(transport, **kwargs)
    assert result == "exhausted"
    text = "\n".join(lines)
    assert "rejected its sign-in" in text
    assert "bad token" in text
    assert "unreachable" not in text
    assert sleeps == [5]                            # still retried, with backoff


def test_system_exit_is_retried_with_the_fatal_line():
    transport = ScriptedTransport([("exit", 1), ("return",)])
    sleeps, lines, kwargs = _rig(transport)
    result = supervise_transport(transport, **kwargs)
    assert result == "stopped"
    assert transport.runs == 2
    text = "\n".join(lines)
    assert "stopped itself (exit code 1)" in text
    assert "bad credentials" in text
    assert sleeps == [5]


def test_clean_stop_is_never_restarted():
    transport = ScriptedTransport([("return",)])
    sleeps, lines, kwargs = _rig(transport)
    assert supervise_transport(transport, **kwargs) == "stopped"
    assert transport.runs == 1
    assert sleeps == []


def test_healthy_run_resets_the_backoff_streak():
    clock = [1000.0]
    transport = ScriptedTransport(
        [
            ("raise", NetworkError("x")),
            ("raise", NetworkError("x")),
            # third run lasts 200s (>= HEALTHY_AFTER) before failing
            ("advance", 200, ("raise", NetworkError("x"))),
            ("return",),
        ],
        clock=clock,
    )
    sleeps, lines, kwargs = _rig(transport, now=lambda: clock[0])
    assert supervise_transport(transport, **kwargs) == "stopped"
    assert sleeps == [5, 15, 5]                     # third failure restarts at 5


def test_agent_stays_alive_while_every_transport_is_down():
    """Mirror of main.run()'s wait predicate: while the down transport's
    supervisor thread lives, the agent process must NOT exit."""
    stop = threading.Event()
    down = AlwaysDownTransport()
    outcome = {}

    def run_supervised():
        outcome["result"] = supervise_transport(
            down,
            log=lambda _line: None,
            stop_event=stop,
            steps=(0.05, 0.05),
            cap=0.05,
        )

    thread = threading.Thread(target=run_supervised, daemon=True)
    thread.start()

    clean = ScriptedTransport([("return",)])
    assert supervise_transport(clean, log=lambda _line: None) == "stopped"
    # The clean transport finished; the down one is still being retried —
    # exactly the state in which the old code printed "All transports have
    # stopped" and exited. (Poll briefly: the retry thread needs a moment
    # to reach its second attempt.)
    import time as _time

    deadline = _time.monotonic() + 5
    while down.runs < 2 and _time.monotonic() < deadline:
        _time.sleep(0.01)
    assert thread.is_alive()
    assert down.runs >= 2

    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcome["result"] == "stopped-by-event"


def test_supervisor_module_is_the_one_main_uses():
    import agent.main

    assert agent.main.supervisor is supervisor
