"""WhatsApp sidecar package setup — locating npm and installing the
bridge's Node packages on first use (shared, Qt-free).

The Baileys sidecar (sidecar/index.js) needs its npm packages installed
once (`npm install` inside sidecar/) before it can run. A buyer should
never be told to open a terminal and do that by hand, so BOTH places
that start the sidecar — the agent's WhatsApp transport supervisor
(agent/transport/whatsapp_transport.py) and the setup wizard's pairing
helper (desktop/pairing.py) — install the packages automatically via
this module when they are missing. The manual command survives only as
the fallback text when automation is impossible (no npm found) or the
install itself fails.

This module lives on the agent side on purpose: the agent must never
import desktop/, while desktop/ already depends on agent/.

Every process launch is injectable (popen / runner / which / exists)
so the whole flow is unit-tested without a real Node or network.
"""

import shutil
import subprocess
import sys
from pathlib import Path

TAIL_CHARS = 800          # how much npm output an error message keeps
INSTALL_TIMEOUT = 600     # seconds; a first install on a slow link is big


def packages_installed(sidecar_dir):
    """True once `npm install` has populated the sidecar's node_modules."""
    return (Path(sidecar_dir) / "node_modules").exists()


def resolve_npm(node=None, *, which=None, exists=None):
    """Find the npm executable for a resolved node binary.

    npm ships beside node — on Windows it is `npm.cmd` in the same
    folder as node.exe (both the system installer and the official
    portable zip lay it out that way) — so the node's own folder is
    checked first; PATH is the fallback. Returns a path string or None.
    """
    exists = exists or (lambda p: Path(p).exists())
    if node:
        parent = Path(node).parent
        for name in ("npm.cmd", "npm", "npm.exe"):
            candidate = parent / name
            if exists(candidate):
                return str(candidate)
    return (which or shutil.which)("npm")


def install_command(npm):
    """The exact command the manual instructions name: plain npm install."""
    return [str(npm), "install"]


def output_tail(text, chars=TAIL_CHARS):
    """The last `chars` characters of a process output, trimmed."""
    text = (text or "").strip()
    return text[-chars:] if len(text) > chars else text


def manual_install_hint(sidecar_dir):
    """The fallback sentence for when automation cannot do it."""
    return (
        "Run `npm install` once inside the sidecar folder "
        f"({sidecar_dir}), then retry."
    )


def spawn_install(npm, sidecar_dir, popen=None):
    """Start `npm install` without blocking; output is piped so the
    caller can collect a tail if it fails. Used by the wizard's pairing
    session, which polls the process like it polls the sidecar itself."""
    kwargs = {
        "cwd": str(sidecar_dir),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return (popen or subprocess.Popen)(install_command(npm), **kwargs)


def install_packages(sidecar_dir, node=None, *, npm=None, runner=None,
                     timeout=INSTALL_TIMEOUT):
    """Run `npm install` to completion (blocking). Returns (ok, detail).

    ok is True only when npm exited 0 AND node_modules now exists.
    detail is a one-line success note, or the tail of npm's output for
    logs/error messages. Used by the agent's supervisor (via
    asyncio.to_thread, so the event loop never blocks on it).
    """
    sidecar_dir = Path(sidecar_dir)
    npm = npm or resolve_npm(node)
    if not npm:
        return False, "npm was not found beside Node or on PATH."
    runner = runner or subprocess.run
    try:
        proc = runner(
            install_command(npm),
            cwd=str(sidecar_dir),
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - report, never crash the caller
        return False, f"npm install could not run: {exc}"
    if proc.returncode == 0 and packages_installed(sidecar_dir):
        return True, "WhatsApp bridge packages installed."
    tail = output_tail((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return False, tail or f"npm install exited with code {proc.returncode}."
