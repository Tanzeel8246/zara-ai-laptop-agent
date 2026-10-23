"""Composition root: wire transport + brain + session together and run.

Phase 0 split the original monolith into seams:
    agent.transport   how instructions arrive (Discord is the reference one)
    agent.brain       how instructions are reasoned about (API / subscription)
    agent.safety      the shared pipeline every tool call passes through
    agent.session     what happens to one instruction, transport-neutral

This module keeps only startup concerns: single-instance lock, setup
validation, the wait-for-network gate, and construction.
"""

import sys

from . import netrecover
from .config import CONFIG, validate, validate_warnings


def _single_instance():
    """Windows named mutex so only ONE copy ever runs (two would fight over the transport)."""
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


def run():
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
    from .session import AgentSession
    from .transport.discord_transport import DiscordTransport

    brain, brain_label = make_brain()
    session = AgentSession(brain, brain_label)
    transport = DiscordTransport(session)

    # Block until online, actively rejoining Wi-Fi rather than just waiting.
    netrecover.wait_until_online()
    transport.run()


if __name__ == "__main__":
    run()
