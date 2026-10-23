"""WhatsApp pairing helper for the setup wizard (Qt-free).

The pragmatic route chosen for Phase 2: the wizard spawns the Baileys
sidecar directly (node sidecar/index.js) with the same environment the
agent's WhatsApp transport uses, then polls the files the sidecar already
maintains — .runtime/whatsapp/qr.txt while pairing, and the auth state's
creds.json once the phone has linked. The wizard renders the QR string with
the `qrcode` package and stops the sidecar when the page is left.

The agent must NOT be running its WhatsApp transport at the same time (both
would fight over one bridge port and one auth state); the wizard page says
so, and pairing is normally done before the agent is ever started.

First run only: if the sidecar's npm packages are missing, the session
installs them itself (`npm install` in sidecar/, via the shared
agent.sidecar_setup helper — the same courtesy the agent's supervisor
performs) and reports state "installing" while it runs. The manual
command is only ever shown when that automation is impossible or fails.

The sidecar's stdout/stderr go to .runtime/whatsapp/pairing.log (never
/dev/null): when the bridge dies, the last lines of that log ride along
in the status detail, so "exit code 1" always arrives with the actual
Node error attached. Diagnostics bundles the same log.

Pairing-code linking (Hotfix 1.0.6): start(method="code", number=...)
passes WA_PAIRING_METHOD/WA_PAIRING_NUMBER/WA_PAIRING_CODE_FILE to the
sidecar, which requests an 8-character code from WhatsApp (typed on the
phone under "Link with phone number instead") and writes it to
pairing-code.txt; poll() merges it into the status as pairing_code. If
the code request fails, the sidecar keeps the QR flow running and poll()
simply reports the QR as before.

Pristine attempts (Hotfix 1.0.6): every wizard pairing spawn first
clears any WhatsApp auth state that is not a COMPLETED pairing (creds
absent, unreadable, or registered != true) — half-finished state left by
failed attempts is a prime suspect in repeated refusals, so each attempt
starts clean. A registered (successfully paired) session is never
touched. One line about the clearing goes to pairing.log.

The Popen factory is injectable for tests.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent import sidecar_setup

ROOT = Path(__file__).resolve().parent.parent
LOGGED_OUT_EXIT = 2

INSTALLING_DETAIL = (
    "Installing WhatsApp bridge packages — first time only, "
    "this can take a couple of minutes…"
)

SESSION_HEADER_PREFIX = "===== pairing session"
LOG_TAIL_COUNT = 6          # bridge lines attached to a "stopped" detail
LOG_LINE_MAX_CHARS = 200    # per line, so the detail stays readable
ADDR_IN_USE_DETAIL = (
    "Another copy of the WhatsApp bridge is already running — probably "
    "left over from an earlier test. End the node.exe process(es) in "
    "Task Manager or restart the PC, then try again."
)
WAITING_CODE_DETAIL = (
    "On your phone: WhatsApp → Linked devices → Link a device → "
    "“Link with phone number instead” → enter the code shown below."
)
AUTH_CLEARED_LOG_LINE = (
    "[pairing] no completed WhatsApp pairing found — cleared any partial "
    "sign-in state so this pairing attempt starts clean"
)


def normalize_pairing_number(text):
    """Digits-only international number: strips +, spaces, dashes and a
    leading 00 international prefix ("+92 300-1234567" → "923001234567")."""
    digits = re.sub(r"\D", "", str(text or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def format_pairing_code(code):
    """Display form of a pairing code: an 8-character code is grouped
    4-4 ("ABCDEFGH" → "ABCD-EFGH", the way WhatsApp shows it); anything
    else is shown exactly as received."""
    code = str(code or "").strip()
    if len(code) == 8:
        return f"{code[:4]}-{code[4:]}"
    return code


def session_log_lines(log_path):
    """The bridge's own lines from the latest pairing session in the log.

    The log is append-only across sessions, each introduced by a header
    line; only the section after the last header belongs to the run that
    just died. Header lines themselves are never included.
    """
    try:
        lines = Path(log_path).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return []
    start = 0
    for i, line in enumerate(lines):
        if line.startswith(SESSION_HEADER_PREFIX):
            start = i + 1
    return [
        line for line in lines[start:]
        if not line.startswith(SESSION_HEADER_PREFIX)
    ]


def log_tail(log_path, count=LOG_TAIL_COUNT):
    """The last `count` non-empty lines of the current session's log."""
    lines = [line.strip() for line in session_log_lines(log_path)]
    lines = [line for line in lines if line]
    return [line[:LOG_LINE_MAX_CHARS] for line in lines[-count:]]


def log_mentions_addr_in_use(log_path):
    text = "\n".join(session_log_lines(log_path)).lower()
    return "eaddrinuse" in text or "address already in use" in text


def stopped_detail(log_path, rc):
    """The "bridge stopped" message, with the bridge's own last words.

    The plain stopped line comes first (an address-in-use failure leads
    with its plain-language remedy instead), then the tail of the log —
    the real Node error, never a bare exit code.
    """
    parts = []
    if log_mentions_addr_in_use(log_path):
        parts.append(ADDR_IN_USE_DETAIL)
    parts.append(f"The WhatsApp bridge stopped (exit code {rc}).")
    tail = log_tail(log_path)
    if tail:
        parts.append("\n".join(tail))
    return "\n".join(parts)


@dataclass
class PairingStatus:
    state: str          # starting | installing | waiting_qr | waiting_code | connected | logged_out | error | stopped
    qr: str = ""        # the QR payload while state == waiting_qr
    detail: str = ""
    pairing_code: str = ""  # the raw code from the sidecar while state == waiting_code


class PairingSession:
    def __init__(self, root=None, port=17331, popen=None, node=None,
                 npm=None, npm_resolver=None):
        self.root = Path(root) if root else ROOT
        self.wa_dir = self.root / ".runtime" / "whatsapp"
        self.auth_dir = self.wa_dir / "auth"
        self.qr_file = self.wa_dir / "qr.txt"
        self.code_file = self.wa_dir / "pairing-code.txt"
        self.log_file = self.wa_dir / "pairing.log"
        self.port = port
        self._pairing_method = "qr"   # or "code" — set by start()
        self._pairing_number = ""     # digits only — set by start()
        self._popen = popen or subprocess.Popen
        self._node = node  # None = resolve in start()
        self._npm = npm    # None = resolve beside node in start()
        self._npm_resolver = npm_resolver or sidecar_setup.resolve_npm
        self._proc = None
        self._install_proc = None
        self._node_resolved = None
        self._log_handle = None
        self._error = ""

    def start(self, method="qr", number=""):
        """Spawn the sidecar for pairing. Returns the first status.

        method="code" + number=<the account's own number, international>
        selects pairing-code linking; anything else is the QR flow,
        exactly as before. The agent's supervisor never calls this — it
        spawns its sidecar itself, without the pairing env, so agent
        runs are unaffected.
        """
        if self._install_proc is not None and self._install_proc.poll() is None:
            return self.poll()
        if self._proc is not None and self._proc.poll() is None:
            return self.poll()
        self._pairing_method = (
            "code" if str(method or "").strip().lower() == "code" else "qr"
        )
        self._pairing_number = (
            normalize_pairing_number(number)
            if self._pairing_method == "code"
            else ""
        )
        self._error = ""
        node = self._node
        if node is None:
            # Phase 5: shared Node resolution (system 18+ / bundled portable
            # / downloaded LTS / NODE_BINARY override) — same decision the
            # agent's WhatsApp transport makes.
            from .node_bootstrap import resolve_node

            try:
                from agent.config import CONFIG

                override = CONFIG.node_binary or None
            except Exception:  # noqa: BLE001 - pairing must not die on config
                override = None
            resolution = resolve_node(whatsapp_enabled=True, override=override)
            node = resolution.path
            if not node:
                self._error = (
                    "Node.js 18+ was not found. " + resolution.detail
                    + " Install Node.js, or let the installed app download it, "
                    "and come back to this page."
                )
                return PairingStatus("error", detail=self._error)
        self._node_resolved = node
        sidecar_dir = self.root / "sidecar"
        if not sidecar_setup.packages_installed(sidecar_dir):
            # First run: install the bridge packages ourselves — the
            # owner must never be sent to a terminal for this.
            npm = self._npm or self._npm_resolver(node)
            if not npm:
                self._error = (
                    "The WhatsApp bridge packages are not installed yet, and "
                    "npm was not found to install them automatically. "
                    + sidecar_setup.manual_install_hint(sidecar_dir)
                )
                return PairingStatus("error", detail=self._error)
            self._install_proc = sidecar_setup.spawn_install(
                npm, sidecar_dir, popen=self._popen
            )
            return PairingStatus("installing", detail=INSTALLING_DETAIL)
        self._spawn_sidecar(node)
        return self.poll()

    def _open_log(self):
        """Open pairing.log for appending and stamp a session header.

        Returns the handle (kept open for the sidecar's lifetime), or
        None when the log cannot be opened — the spawn then falls back
        to DEVNULL rather than failing the pairing outright.
        """
        self._close_log()
        try:
            self.wa_dir.mkdir(parents=True, exist_ok=True)
            handle = open(self.log_file, "ab")
            stamp = datetime.now().isoformat(timespec="seconds")
            header = (
                f"\n{SESSION_HEADER_PREFIX} {stamp} (port {self.port}) =====\n"
            )
            handle.write(header.encode("utf-8"))
            handle.flush()
        except OSError:
            return None
        self._log_handle = handle
        return handle

    def _close_log(self):
        handle, self._log_handle = self._log_handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def _auth_registered(self):
        """True ONLY when creds.json proves a completed pairing.

        Baileys' multi-file auth state writes creds.json early (keys,
        noise material) and flips "registered" to true only when the
        phone has actually linked — so presence alone is not proof.
        Anything missing, unreadable or not-exactly-true is "not a
        completed pairing".
        """
        try:
            data = json.loads(
                (self.auth_dir / "creds.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        return isinstance(data, dict) and data.get("registered") is True

    def _clear_stale_auth(self, log_handle):
        """Clear a partial (never-completed) sign-in state, if present.

        Runs before every wizard pairing spawn so each attempt starts
        pristine — stale partial auth is a prime suspect when WhatsApp
        keeps refusing links. HARD RULE: a registered session (a phone
        really is linked) is left exactly as-is; the registration check
        above is the only gate and it runs before anything is deleted.
        """
        if self._auth_registered():
            return
        if self.auth_dir.is_dir():
            for entry in self.auth_dir.iterdir():
                try:
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                except OSError:
                    pass
        if log_handle is not None:
            try:
                log_handle.write(
                    (AUTH_CLEARED_LOG_LINE + "\n").encode("utf-8")
                )
                log_handle.flush()
            except OSError:
                pass

    def _spawn_sidecar(self, node):
        sidecar_dir = self.root / "sidecar"
        self.wa_dir.mkdir(parents=True, exist_ok=True)
        # A stale QR (or pairing code) from an earlier run must never be
        # shown as fresh.
        try:
            self.qr_file.unlink()
        except OSError:
            pass
        try:
            self.code_file.unlink()
        except OSError:
            pass
        env = dict(
            os.environ,
            WA_BRIDGE_PORT=str(self.port),
            WA_AUTH_DIR=str(self.auth_dir),
            WA_MEDIA_DIR=str(self.wa_dir / "media"),
            WA_QR_FILE=str(self.qr_file),
            WA_PAIRING_METHOD=self._pairing_method,
            WA_PAIRING_NUMBER=self._pairing_number,
            WA_PAIRING_CODE_FILE=str(self.code_file),
        )
        # The sidecar's output IS the diagnosis when it dies — until
        # 1.0.2 it went to DEVNULL and a crash surfaced as a bare
        # "exit code 1" with the real Node error thrown away.
        log_handle = self._open_log()
        # Pristine start (1.0.6): clear any never-completed sign-in
        # state BEFORE the bridge reads it; a completed pairing is
        # never touched (see _clear_stale_auth).
        self._clear_stale_auth(log_handle)
        kwargs = {"cwd": str(self.root), "env": env}
        if log_handle is not None:
            kwargs["stdout"] = log_handle
            kwargs["stderr"] = subprocess.STDOUT
        else:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = self._popen([node, str(sidecar_dir / "index.js")], **kwargs)
        return self.poll()

    def poll(self):
        if self._install_proc is not None:
            return self._poll_install()
        if self._error and self._proc is None:
            return PairingStatus("error", detail=self._error)
        if self._proc is None:
            return PairingStatus("stopped", detail="Pairing has not been started.")
        rc = self._proc.poll()
        if rc is not None:
            self._close_log()
            if rc == LOGGED_OUT_EXIT:
                return PairingStatus(
                    "logged_out",
                    detail="WhatsApp logged this device out. Start pairing again to get a fresh QR.",
                )
            if rc == 0:
                return PairingStatus(
                    "stopped",
                    detail="The WhatsApp bridge stopped (exit code 0).",
                )
            return PairingStatus(
                "stopped", detail=stopped_detail(self.log_file, rc)
            )
        if (self.auth_dir / "creds.json").exists():
            return PairingStatus("connected", detail="Phone linked — WhatsApp is ready.")
        if self._pairing_method == "code":
            code = self._read_pairing_code()
            if code:
                return PairingStatus(
                    "waiting_code", pairing_code=code,
                    detail=WAITING_CODE_DETAIL,
                )
            # No code (yet, or the request failed): fall through to the
            # QR status below — the sidecar keeps the QR flow running as
            # the fallback, and the wizard shows it.
        if self.qr_file.exists():
            try:
                qr = self.qr_file.read_text(encoding="utf-8").strip()
            except OSError:
                qr = ""
            if qr:
                return PairingStatus(
                    "waiting_qr", qr=qr,
                    detail="On your phone: WhatsApp → Settings → Linked devices → Link a device.",
                )
        return PairingStatus("starting", detail="Starting the WhatsApp bridge…")

    def _read_pairing_code(self):
        """The code the sidecar wrote, or "" — the spawn unlinked any
        stale file, so whatever is here belongs to this attempt."""
        try:
            return self.code_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _poll_install(self):
        """Advance the first-run package install started by start()."""
        proc = self._install_proc
        rc = proc.poll()
        if rc is None:
            return PairingStatus("installing", detail=INSTALLING_DETAIL)
        tail = ""
        try:
            out, _ = proc.communicate()
            tail = sidecar_setup.output_tail(out or "")
        except Exception:  # noqa: BLE001 - a lost tail must not break pairing
            tail = ""
        self._install_proc = None
        sidecar_dir = self.root / "sidecar"
        if rc == 0 and sidecar_setup.packages_installed(sidecar_dir):
            self._spawn_sidecar(self._node_resolved)
            return self.poll()
        self._error = (
            "Installing the WhatsApp bridge packages failed."
            + (f"\n{tail}" if tail else "")
            + "\n" + sidecar_setup.manual_install_hint(sidecar_dir)
        )
        return PairingStatus("error", detail=self._error)

    @staticmethod
    def _terminate(proc):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop(self):
        self._terminate(self._install_proc)
        self._install_proc = None
        self._terminate(self._proc)
        self._proc = None
        self._close_log()


def make_qr_png_bytes(qr_text, box_size=8, border=2):
    """Render a QR payload to PNG bytes (used by the wizard's image label)."""
    import io

    import qrcode

    img = qrcode.make(qr_text, box_size=box_size, border=border)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
