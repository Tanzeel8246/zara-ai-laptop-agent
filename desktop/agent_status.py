"""Per-transport status, read from the agent's own log (Qt-free).

The agent process and the desktop shell are separate processes; the one
channel the agent already reports its life through is its stdout/stderr,
which the shell captures into .runtime/agent-shell.log (see
desktop/agent_process.AgentProcess). This module reads that same log —
no parallel state file, no second source of truth — and reduces each
transport's most recent state line to one status word for the control
window:

    connected    the transport's own "online / starting" line, with no
                 failure line after it
    connecting   enabled and the agent is running, but no state line
                 for this transport has been seen yet (or the WhatsApp
                 bridge is still coming up)
    retrying     the 1.0.7 supervisor (or Discord's own loop) reported a
                 failure and is waiting to try again
    stopped      the transport stopped, or the agent is not running
    error        the transport could not even be constructed
    disabled     not enabled in Settings

Two readings worth documenting:

* Telegram prints "transport starting (long polling)" immediately
  before run_polling(), which raises within seconds when it cannot
  connect — and the supervisor then prints the retry line. A starting
  line with no failure line after it therefore means the transport IS
  polling, so it maps to "connected" (the brief window before a failure
  surfaces shows the same word; the retry line corrects it at once).
* WhatsApp sidecar output lines ("[whatsapp-sidecar] …") keep flowing
  while connected, so they only ever move a transport INTO
  "connecting", never out of "connected".
"""

KNOWN_TRANSPORTS = ("discord", "telegram", "whatsapp")

TRANSPORT_DISPLAY = {
    "discord": "Discord",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
}

STATE_TEXT = {
    "connected": "Connected",
    "connecting": "Connecting…",
    "retrying": "Retrying…",
    "stopped": "Stopped",
    "error": "Error — see View Logs",
    "disabled": "Disabled",
}


def transport_states(log_text, enabled, *, agent_running):
    """Latest state per known transport, from the agent log tail.

    ``enabled`` is the Settings transport list; ``agent_running`` is the
    shell's process state. Returns a state word for EVERY known
    transport (see the module docstring)."""
    enabled = {name for name in (enabled or []) if name in KNOWN_TRANSPORTS}
    states = {}
    for name in KNOWN_TRANSPORTS:
        if name not in enabled:
            states[name] = "disabled"
        elif not agent_running:
            states[name] = "stopped"
        else:
            states[name] = "connecting"
    if not agent_running:
        return states
    for line in (log_text or "").splitlines():
        _apply_line(line, states, enabled)
    return states


def _apply_line(line, states, enabled):
    if "All transports have stopped." in line:
        for name in enabled:
            states[name] = "stopped"
        return
    lowered = line.lower()
    for name in KNOWN_TRANSPORTS:
        if name not in enabled:
            continue
        if f"[{name}]" in line:
            # Supervisor + transport-tagged lines (agent/supervisor.py
            # and the transports' own [name] prints).
            if "could not start" in line:
                states[name] = "error"
            elif "retrying in" in lowered:
                states[name] = "retrying"
            elif "transport stopped" in line or "has stopped cleanly" in line:
                states[name] = "stopped"
            elif name == "whatsapp":
                if "sidecar exited" in line:
                    states[name] = "retrying"
                elif "logged out" in line or "transport is disabled" in lowered:
                    states[name] = "stopped"
                elif "installing the whatsapp bridge packages" in lowered:
                    states[name] = "connecting"
        if name == "telegram":
            if "Telegram transport starting (long polling)" in line:
                states[name] = "connected"  # see module docstring
        elif name == "discord":
            if " is online as " in line:
                states[name] = "connected"
            elif (
                "Connection lost (" in line
                or "Discord rejected the token" in line
                or "Discord needs the MESSAGE CONTENT INTENT" in line
            ):
                states[name] = "retrying"
        elif name == "whatsapp":
            if "WhatsApp transport online as" in line:
                states[name] = "connected"
            elif (
                line.lstrip().startswith("[whatsapp-sidecar]")
                and states[name] != "connected"
            ):
                states[name] = "connecting"
