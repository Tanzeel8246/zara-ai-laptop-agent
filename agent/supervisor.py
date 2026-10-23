"""Transport supervision: a transport that falls over is restarted, forever.

Why this exists (Hotfix 1.0.7, from a live failure on the owner's machine):
his broadband ISP SNI-filters api.telegram.org — the TCP connection opens
but the TLS handshake times out, so the Telegram transport crashed seconds
after starting. Telegram was the only enabled transport, so the whole agent
exited ("All transports have stopped") and the bot simply never replied.

A home laptop's network is not a datacentre: routers reboot, lines drop for
hours during power cuts, an ISP can block a host outright. None of that may
be a permanent death. Each transport is therefore supervised: when run()
raises, it is retried with capped exponential backoff for as long as the
agent runs, and a transport that recovers resumes normal operation with no
agent restart. Crash isolation between transports is unchanged — one
transport retrying never blocks or stops the others.

Failure classes change only the log line, never the will to retry:
  network      unreachable host, timeout, TLS death → "unreachable"
  credentials  the service rejected the sign-in (bad token) → the line says
               so plainly, so the owner fixes the token instead of waiting
               for the network to heal; we still retry (services glitch too)
  fatal        the transport stopped itself via SystemExit (e.g. Discord
               rejecting its token) → same credentials-flavoured line
  unknown      anything else → "crashed", with the exception named

A transport whose run() RETURNS has stopped on purpose (clean shutdown,
or WhatsApp's bridge reporting a logged-out session) and is NOT restarted.
"""

import sys
import time
import traceback

# Seconds between retries for consecutive failures: 5, 15, 30, 60, then the
# cap forever. Short at first (a router reboot heals in seconds), patient
# later (an ISP block can last hours — keep knocking, quietly).
BACKOFF_STEPS = (5, 15, 30, 60)
BACKOFF_CAP = 300  # 5 minutes

# A transport that ran at least this long before failing was basically
# working; its failure starts a fresh backoff streak instead of continuing
# to punish an old one.
HEALTHY_AFTER = 120

_DISPLAY = {"whatsapp": "WhatsApp", "telegram": "Telegram", "discord": "Discord"}

_NETWORK_NAMES = (
    "network", "connecterror", "connecttimeout", "readtimeout", "pooltimeout",
    "writeerror", "readerror", "remoteprotocol", "timedout", "timeouterror",
)
_CREDENTIAL_NAMES = (
    "invalidtoken", "unauthorized", "loginfailure", "privilegedintents",
    "forbidden", "authfailure", "authenticationerror",
)


def _display(transport):
    name = getattr(transport, "name", "transport")
    return _DISPLAY.get(name, str(name).capitalize())


def _chain(exc):
    """The exception plus its causes/contexts (httpx & PTB wrap heavily)."""
    seen, out, current, depth = set(), [], exc, 0
    while current is not None and id(current) not in seen and depth < 6:
        seen.add(id(current))
        out.append(current)
        current = current.__cause__ or current.__context__
        depth += 1
    return out


def classify_failure(exc):
    """Bucket an exception: 'credentials', 'network' or 'unknown'.

    Name-based on purpose: the supervisor is transport-agnostic and must
    not import telegram/discord error classes just to recognise them."""
    for item in _chain(exc):
        name = type(item).__name__.lower()
        if any(hint in name for hint in _CREDENTIAL_NAMES):
            return "credentials"
    for item in _chain(exc):
        name = type(item).__name__.lower()
        if any(hint in name for hint in _NETWORK_NAMES):
            return "network"
        if isinstance(item, (TimeoutError, ConnectionError)):
            return "network"
    return "unknown"


def backoff_delay(failures, steps=BACKOFF_STEPS, cap=BACKOFF_CAP):
    """Delay before the next attempt, given the consecutive-failure count
    (1 = the first failure just happened)."""
    if failures < 1:
        failures = 1
    if failures <= len(steps):
        return steps[failures - 1]
    return cap


def _stderr_log(text):
    print(text, file=sys.stderr)


def supervise_transport(
    transport,
    *,
    sleep=time.sleep,
    now=time.monotonic,
    log=None,
    stop_event=None,
    max_attempts=None,
    steps=BACKOFF_STEPS,
    cap=BACKOFF_CAP,
    healthy_after=HEALTHY_AFTER,
):
    """Run one transport, restarting it after failures with backoff.

    Returns why the loop ended: "stopped" (run() returned — a deliberate
    stop, never restarted), "interrupted" (KeyboardInterrupt),
    "stopped-by-event" (stop_event was set) or "exhausted" (max_attempts
    reached — a test hook; production passes None and retries forever).

    sleep/now/log/stop_event are injectable so tests never really wait.
    When stop_event is given, the backoff wait happens on the event itself
    so shutdown is prompt; otherwise the injected sleep is used.
    """
    log = log or _stderr_log
    display = _display(transport)
    failures = 0
    attempts = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            return "stopped-by-event"
        attempts += 1
        started = now()
        try:
            transport.run()
        except KeyboardInterrupt:
            return "interrupted"
        except SystemExit as exc:
            kind = "fatal"
            detail = f"exit code {exc.code}"
            ran = now() - started
        except Exception as exc:  # noqa: BLE001 - supervision means catching all of it
            kind = classify_failure(exc)
            detail = f"{type(exc).__name__}: {exc}"
            ran = now() - started
            if failures == 0 or ran >= healthy_after:
                # Full traceback once per streak: the first failure is the
                # one a human will debug; the retries stay one line each.
                log(traceback.format_exc())
        else:
            if failures:
                log(f"\n  [{transport.name}] {display} is back and has stopped cleanly.\n")
            else:
                log(f"\n  [{transport.name}] transport stopped.\n")
            return "stopped"

        failures = 1 if ran >= healthy_after else failures + 1
        if max_attempts is not None and attempts >= max_attempts:
            return "exhausted"
        delay = backoff_delay(failures, steps=steps, cap=cap)
        if kind == "network":
            log(
                f"\n  [{transport.name}] {display} unreachable ({detail}) — "
                f"retrying in {delay:g}s. The agent stays up; "
                f"check the network/VPN if this repeats.\n"
            )
        elif kind == "credentials":
            log(
                f"\n  [{transport.name}] {display} rejected its sign-in ({detail}) — "
                f"that usually means a bad token or credentials; check them in "
                f"Settings. Retrying in {delay:g}s anyway, in case it was a glitch.\n"
            )
        elif kind == "fatal":
            log(
                f"\n  [{transport.name}] {display} stopped itself ({detail}) — "
                f"that usually means bad credentials or missing setup; see the "
                f"message above. Retrying in {delay:g}s anyway.\n"
            )
        else:
            log(
                f"\n  [{transport.name}] {display} transport crashed ({detail}) — "
                f"retrying in {delay:g}s.\n"
            )

        if stop_event is not None:
            if stop_event.wait(delay):
                return "stopped-by-event"
        else:
            sleep(delay)
