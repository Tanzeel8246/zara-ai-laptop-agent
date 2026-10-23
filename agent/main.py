"""Composition root: wire transports + brain + session together and run.

Phase 0 split the original monolith into seams:
    agent.transport   how instructions arrive (Discord is the reference one)
    agent.brain       how instructions are reasoned about (API / subscription)
    agent.safety      the shared pipeline every tool call passes through
    agent.session     what happens to one instruction, transport-neutral

Phase 1: several transports can run at once (TRANSPORTS in .env — discord,
telegram, whatsapp). They share ONE brain, ONE safety pipeline and ONE
session manager, and each runs in its own thread so one transport failing
(bad token, missing Node.js, a dropped network) never takes the others down.

Hotfix 1.0.7: each thread is a SUPERVISOR (agent/supervisor.py), not a
one-shot run — a transport that crashes (e.g. the ISP blocking Telegram's
servers outright) is retried with backoff for as long as the agent runs, so
the agent stays alive even with every transport temporarily down and heals
by itself when the network comes back.

This module keeps only startup concerns: single-instance lock, setup
validation, the wait-for-network gate, and construction.
"""

import sys
import threading
import time

from . import netrecover, supervisor
from .config import CONFIG, validate, validate_warnings


def _single_instance():
    """Windows named mutex so only ONE copy ever runs (two would fight over the transports)."""
    global _INSTANCE_GUARD
    try:
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "CodeHubbAssistantSingleton")
        already = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        _INSTANCE_GUARD = handle  # keep the handle alive for the process lifetime
        return not already
    except Exception:  # noqa: BLE001 - non-Windows or ctypes missing: don't block startup
        return True


_INSTANCE_GUARD = None


def _build_transports(session):
    """Construct every enabled transport. One failing to construct is logged
    and skipped — the rest still start."""
    builders = {}
    if "discord" in CONFIG.transports:
        from .transport.discord_transport import DiscordTransport

        builders["discord"] = DiscordTransport
    if "telegram" in CONFIG.transports:
        from .transport.telegram_transport import TelegramTransport

        builders["telegram"] = TelegramTransport
    if "whatsapp" in CONFIG.transports:
        from .transport.whatsapp_transport import WhatsAppTransport

        builders["whatsapp"] = WhatsAppTransport

    transports = []
    for name, builder in builders.items():
        try:
            transports.append(builder(session))
        except Exception as exc:  # noqa: BLE001 - independence between transports
            print(f"\n  [{name}] could not start: {type(exc).__name__}: {exc}\n", file=sys.stderr)
    return transports


def _run_transport(transport):
    # Supervised, not one-shot: a crashed transport is retried with backoff
    # (agent/supervisor.py) instead of taking its thread — and, when it was
    # the only transport, the whole agent — down with it. Only a transport
    # whose run() RETURNS (a deliberate stop) ends this thread.
    supervisor.supervise_transport(transport)


def run():
    # Phase 5: in a frozen bundle, point Playwright at the Chromium build
    # the installer shipped (no-op in a source checkout without one, and
    # never overrides an explicitly set PLAYWRIGHT_BROWSERS_PATH). Must
    # happen before the browser tool lazily imports playwright.
    from .bundled_paths import ensure_playwright_browsers_path

    ensure_playwright_browsers_path()

    if not _single_instance():
        print(f"\n  {CONFIG.product_name} is already running - this extra copy will exit.\n")
        sys.exit(3)  # run.bat treats 3 as 'do not restart'

    problems = validate()
    if problems:
        print("\n  Setup incomplete:\n")
        for item in problems:
            print(f"   - {item}")
        print(f"\n  Edit {CONFIG.runtime_dir.parent / '.env'} and run again.\n")
        sys.exit(1)

    for warning in validate_warnings():
        print(f"\n  Warning: {warning}")

    from .brain import make_brain
    from .scheduler import Scheduler
    from .session import AgentSession

    brain, brain_label = make_brain()
    session = AgentSession(brain, brain_label)

    # Phase 4: report the license state once at startup. On a development
    # build this prints nothing; with enforcement on, an unactivated copy
    # still starts (so /license and the wizard keep working) but the
    # session gate answers every instruction with the activation notice.
    from . import licensing

    license_status = session._license_status()
    if license_status is not None and license_status.state != "development":
        print(f"\n  License: {licensing.status_line(license_status)}")
        if not license_status.allowed:
            print("  Activation mode: instructions will get the activation notice until a key is entered.")
        try:
            session.license_manager.refresh_online()
        except Exception:  # noqa: BLE001 - offline startup is a normal case
            pass

    # Phase 3: the task-queue worker (recovers any tasks a dead process
    # left 'running') and the scheduler thread (due schedules become
    # queued tasks). Both are daemon threads; transports are unaffected.
    session.queue.start()
    scheduler = Scheduler(session.store, session.queue)
    scheduler.start()

    transports = _build_transports(session)
    if not transports:
        print("\n  No transport could start. See the errors above.\n")
        sys.exit(1)

    # Block until online, actively rejoining Wi-Fi rather than just waiting.
    netrecover.wait_until_online()

    threads = []
    for transport in transports:
        thread = threading.Thread(
            target=_run_transport, args=(transport,), name=f"transport-{transport.name}", daemon=True
        )
        thread.start()
        threads.append(thread)

    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        return
    print("\n  All transports have stopped.\n")
    sys.exit(1)


if __name__ == "__main__":
    run()
