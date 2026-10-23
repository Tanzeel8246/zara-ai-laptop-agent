"""Auto-update (Phase 5, Qt-free).

The seller publishes one small JSON feed per release:

    {"version": "1.1.0",
     "url": "https://…/CodeHubbAssistant-Setup-1.1.0.exe",
     "sha256": "<hex of the installer>",
     "notes": "What changed",
     "mandatory": false}

Its URL lives in UPDATE_FEED_URL (config). Blank — the default, and
always true for development builds — means the updater is DISABLED:
check() is a no-op and the tray hides its update items entirely.

Flow: check() fetches + compares against agent.version; download()
streams the installer into .runtime/updates/, verifies the SHA256
(a mismatch discards the file, always) and records the staged update
in the store's meta table; the tray then offers "Restart to update",
which hands the staged file to packaging/apply_update.ps1 and quits.

Fetching and downloading are injectable callables, so tests never touch
the network.
"""

import hashlib
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .bundled_paths import ROOT, app_dir, bundle_dir, is_frozen
from .version import __version__

META_AVAILABLE = "update.available"
META_STAGED = "update.staged"
META_ERROR = "update.error"


class UpdateError(Exception):
    """A check/download problem worth showing the user verbatim."""


# ------------------------------------------------------------- versions ----

def parse_version(text):
    """'1.2.3' / 'v1.2' -> tuple of ints. Junk raises ValueError."""
    text = str(text or "").strip().lstrip("vV")
    core = text.split("-", 1)[0].split("+", 1)[0]
    if not core:
        raise ValueError(f"empty version: {text!r}")
    parts = []
    for piece in core.split("."):
        if not piece.isdigit():
            raise ValueError(f"not a numeric version: {text!r}")
        parts.append(int(piece))
    return tuple(parts)


def compare_versions(a, b):
    """-1 / 0 / 1; missing components count as 0 ('1.2' == '1.2.0')."""
    ta, tb = parse_version(a), parse_version(b)
    width = max(len(ta), len(tb))
    ta += (0,) * (width - len(ta))
    tb += (0,) * (width - len(tb))
    return (ta > tb) - (ta < tb)


def is_newer(remote, current):
    return compare_versions(remote, current) > 0


# ------------------------------------------------------------------ feed ---

@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""
    mandatory: bool = False


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def parse_feed(data):
    """Validate feed JSON (bytes/str/dict) into an UpdateInfo."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise UpdateError(f"Update feed is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("Update feed is not a JSON object.")
    version = str(data.get("version") or "").strip()
    url = str(data.get("url") or "").strip()
    sha256 = str(data.get("sha256") or "").strip()
    if not version:
        raise UpdateError("Update feed has no 'version'.")
    try:
        parse_version(version)
    except ValueError as exc:
        raise UpdateError(f"Update feed version is unusable: {exc}") from exc
    if not url.lower().startswith(("https://", "http://")):
        raise UpdateError("Update feed has no usable download 'url'.")
    if not _SHA256_RE.match(sha256):
        raise UpdateError("Update feed 'sha256' is not a 64-char hex digest.")
    return UpdateInfo(
        version=version,
        url=url,
        sha256=sha256.lower(),
        notes=str(data.get("notes") or ""),
        mandatory=bool(data.get("mandatory", False)),
    )


def _default_fetcher(url):
    request = urllib.request.Request(url, headers={"User-Agent": "CodeHubbAssistant"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _default_downloader(url, dest):
    request = urllib.request.Request(url, headers={"User-Agent": "CodeHubbAssistant"})
    with urllib.request.urlopen(request, timeout=300) as response, open(dest, "wb") as fh:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 512), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(url, version):
    name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or f"update-{version}"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or f"update-{version}"
    return name


def apply_script_path(root=None):
    """packaging/apply_update.ps1 as shipped: next to the app in a frozen
    bundle, in the repo's packaging/ folder in a source checkout."""
    candidates = []
    if root is not None:
        candidates.append(Path(root) / "packaging" / "apply_update.ps1")
    if is_frozen():
        candidates.append(bundle_dir() / "packaging" / "apply_update.ps1")
        candidates.append(app_dir() / "packaging" / "apply_update.ps1")
    candidates.append(ROOT / "packaging" / "apply_update.ps1")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


# ---------------------------------------------------------------- updater --

class Updater:
    def __init__(self, feed_url=None, current_version=None, store=None,
                 updates_dir=None, fetcher=None, downloader=None):
        if feed_url is None:
            from .config import CONFIG

            feed_url = CONFIG.update_feed_url
        self.feed_url = (feed_url or "").strip()
        self.current_version = current_version or __version__
        self._store = store
        if updates_dir is None:
            from .config import CONFIG

            updates_dir = CONFIG.runtime_dir / "updates"
        self.updates_dir = Path(updates_dir)
        self._fetcher = fetcher or _default_fetcher
        self._downloader = downloader or _default_downloader

    # -- state ----------------------------------------------------------

    @property
    def enabled(self):
        return bool(self.feed_url)

    @property
    def store(self):
        if self._store is None:
            from .store import get_store

            self._store = get_store()
        return self._store

    # -- check ------------------------------------------------------------

    def check(self):
        """Fetch the feed. Returns UpdateInfo when a NEWER version exists,
        None when up to date (or disabled). Raises UpdateError on a broken
        feed / unreachable server."""
        if not self.enabled:
            return None
        try:
            raw = self._fetcher(self.feed_url)
        except UpdateError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a user message
            raise UpdateError(f"Could not reach the update feed: {exc}") from exc
        info = parse_feed(raw)
        if is_newer(info.version, self.current_version):
            self.store.set_meta(META_AVAILABLE, json.dumps(info.__dict__))
            return info
        self.store.delete_meta(META_AVAILABLE)
        return None

    # -- download -----------------------------------------------------------

    def download(self, info=None):
        """Download + SHA256-verify the installer; stage it for the tray's
        'Restart to update'. Returns the staged file's Path."""
        if info is None:
            info = self.check()
        if info is None:
            raise UpdateError("No update is available to download.")
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        dest = self.updates_dir / _safe_filename(info.url, info.version)
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            self._downloader(info.url, part)
        except Exception as exc:  # noqa: BLE001
            part.unlink(missing_ok=True)
            self.store.set_meta(META_ERROR, f"download failed: {exc}")
            raise UpdateError(f"Update download failed: {exc}") from exc
        actual = sha256_of(part)
        if actual != info.sha256:
            part.unlink(missing_ok=True)
            message = (
                f"Downloaded update failed its integrity check "
                f"(expected sha256 {info.sha256}, got {actual}); it was discarded."
            )
            self.store.set_meta(META_ERROR, message)
            raise UpdateError(message)
        part.replace(dest)
        staged = {
            "version": info.version,
            "path": str(dest),
            "sha256": info.sha256,
            "notes": info.notes,
            "mandatory": info.mandatory,
            "staged_at": time.time(),
        }
        self.store.set_meta(META_STAGED, json.dumps(staged))
        self.store.delete_meta(META_ERROR)
        return dest

    # -- staged state -------------------------------------------------------

    def staged(self):
        raw = self.store.get_meta(META_STAGED)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if not data.get("path") or not Path(data["path"]).exists():
            return None
        return data

    def last_error(self):
        return self.store.get_meta(META_ERROR)

    def clear_staged(self):
        raw = self.store.get_meta(META_STAGED)
        if raw:
            try:
                path = Path(json.loads(raw).get("path") or "")
                path.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
        self.store.delete_meta(META_STAGED)
        self.store.delete_meta(META_AVAILABLE)


def get_updater():
    """An Updater wired to the live config + default store."""
    return Updater()
