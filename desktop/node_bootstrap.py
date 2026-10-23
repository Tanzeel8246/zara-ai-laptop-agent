"""Node.js resolution for the WhatsApp sidecar (Qt-free, Phase 5).

The Baileys sidecar needs Node.js 18+, but a buyer should never be told
"install Node first": the installer build aims to just work. Resolution
order, first hit wins:

  1. override  — NODE_BINARY in config (explicit path, escape hatch)
  2. system    — `node` on PATH with version >= 18
  3. bundled   — a portable Node shipped in the app folder (node/node.exe)
  4. downloaded— an official Node LTS previously fetched into the app
                 data dir by ensure_node()
  5. missing   — nothing found; ensure_node() can download on request

The download is pinned to one official LTS build and verified against
its published SHA256 (nodejs.org/dist/<ver>/SHASUMS256.txt) before a
single file is extracted; a hash mismatch discards the archive.

All probing is injectable (which/runner/fetcher/exists) so the whole
decision matrix is unit-tested without a real Node or network.
"""

import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from agent.bundled_paths import ROOT, app_dir, is_frozen

MIN_NODE_MAJOR = 18

# Pinned official LTS. SHA256 from https://nodejs.org/dist/v22.14.0/SHASUMS256.txt
# (entry: node-v22.14.0-win-x64.zip) — re-verify both together when bumping.
NODE_VERSION = "22.14.0"
NODE_WIN_X64_ZIP = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_DOWNLOAD_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_WIN_X64_ZIP}"
NODE_ZIP_SHA256 = "55b639295920b219bb2acbcfa00f90393a2789095b7323f79475c9f34795f217"


@dataclass
class NodeResolution:
    source: str                 # override | system | bundled | downloaded | missing | disabled
    path: str | None = None     # the node executable to spawn
    version: str | None = None  # e.g. "22.14.0", when probed
    detail: str = ""            # human-readable note for logs/diagnostics


# ------------------------------------------------------------------ probing

def parse_node_version(text):
    """'v22.14.0\\n' -> (22, 14, 0); unparsable -> None."""
    text = (text or "").strip().lstrip("v")
    parts = text.split(".")
    try:
        return tuple(int(p) for p in parts[:3])
    except (TypeError, ValueError):
        return None


def _default_runner(path):
    out = subprocess.run(
        [str(path), "--version"], capture_output=True, text=True, timeout=15
    )
    return out.stdout


def probe_version(path, runner=None):
    """Dotted version string of a node binary, or None when unusable."""
    runner = runner or _default_runner
    try:
        parsed = parse_node_version(runner(path))
    except Exception:  # noqa: BLE001 - a broken binary is just "not usable"
        return None
    if parsed is None:
        return None
    return ".".join(str(n) for n in parsed)


def _version_ok(version):
    parsed = parse_node_version(version)
    return parsed is not None and parsed[0] >= MIN_NODE_MAJOR


# ------------------------------------------------------------------- layout

def default_app_dir():
    return app_dir(frozen=is_frozen())


def default_data_dir(app=None):
    """Where a downloaded Node lives: inside .runtime with the app's other
    state, so a per-user install keeps everything under one folder."""
    app = Path(app) if app else default_app_dir()
    return app / ".runtime" / "node"


def bundled_candidates(app):
    app = Path(app)
    return [app / "node" / "node.exe", app / "node" / "node", app / "node" / "bin" / "node"]


def downloaded_candidates(data):
    data = Path(data)
    return [
        data / f"node-v{NODE_VERSION}-win-x64" / "node.exe",
        data / "node" / "node.exe",
        data / "node" / "node",
        data / "node" / "bin" / "node",
    ]


# ----------------------------------------------------------------- resolver

def resolve_node(
    *,
    whatsapp_enabled=True,
    override=None,
    app=None,
    data=None,
    which=None,
    runner=None,
    exists=None,
):
    """Decide which node binary the sidecar should use. Pure decision
    logic: every probe is injectable, nothing here downloads anything."""
    exists = exists or (lambda p: Path(p).exists())
    if not whatsapp_enabled:
        return NodeResolution("disabled", detail="WhatsApp transport is not enabled.")

    if override:
        if exists(override):
            version = probe_version(override, runner)
            if _version_ok(version):
                return NodeResolution("override", str(override), version,
                                      "NODE_BINARY override from config.")
            return NodeResolution("missing", detail=(
                f"NODE_BINARY points at {override} but it is not a working "
                f"Node {MIN_NODE_MAJOR}+ binary."))
        return NodeResolution("missing", detail=(
            f"NODE_BINARY is set to {override} but that file does not exist."))

    which = which or shutil.which
    system = which("node")
    if system:
        version = probe_version(system, runner)
        if _version_ok(version):
            return NodeResolution("system", str(system), version, "Node.js on PATH.")
        # an ancient system Node must not shadow a good bundled one

    app = Path(app) if app else default_app_dir()
    for candidate in bundled_candidates(app):
        if exists(candidate):
            version = probe_version(candidate, runner)
            if _version_ok(version):
                return NodeResolution("bundled", str(candidate), version,
                                      "Portable Node bundled with the app.")

    data = Path(data) if data else default_data_dir(app)
    for candidate in downloaded_candidates(data):
        if exists(candidate):
            version = probe_version(candidate, runner)
            if _version_ok(version):
                return NodeResolution("downloaded", str(candidate), version,
                                      "Node downloaded by the app earlier.")
    return NodeResolution("missing", detail=(
        f"No Node.js {MIN_NODE_MAJOR}+ found (system, bundled or downloaded)."))


# ----------------------------------------------------------------- download

def _default_fetcher(url, dest):
    request = urllib.request.Request(url, headers={"User-Agent": "CodeHubbAssistant"})
    with urllib.request.urlopen(request, timeout=120) as response, open(dest, "wb") as fh:
        shutil.copyfileobj(response, fh)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 512), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_node(data=None, *, fetcher=None, url=None, expected_sha256=None):
    """Download the pinned Node LTS zip into the data dir, verify its
    SHA256, and extract it. Returns the extraction directory. Raises
    ValueError on a hash mismatch (archive deleted, nothing extracted).

    url/expected_sha256 default to the module constants AT CALL TIME so
    tests can pin a fake archive against its real digest."""
    url = url or NODE_DOWNLOAD_URL
    expected_sha256 = expected_sha256 or NODE_ZIP_SHA256
    data = Path(data) if data else default_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    archive = data / NODE_WIN_X64_ZIP
    (fetcher or _default_fetcher)(url, archive)
    actual = sha256_of(archive)
    if actual.lower() != expected_sha256.lower():
        archive.unlink(missing_ok=True)
        raise ValueError(
            f"Downloaded Node archive failed its SHA256 check "
            f"(expected {expected_sha256}, got {actual}); it was discarded.")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(data)
    archive.unlink(missing_ok=True)
    return data / f"node-v{NODE_VERSION}-win-x64"


def ensure_node(*, fetcher=None, download=False, **resolve_kwargs):
    """Resolve node; when missing AND download=True, fetch the pinned LTS
    first and resolve again. Returns the final NodeResolution."""
    resolution = resolve_node(**resolve_kwargs)
    if resolution.source != "missing" or not download:
        return resolution
    data = resolve_kwargs.get("data")
    download_node(data, fetcher=fetcher)
    again = resolve_node(**resolve_kwargs)
    if again.source == "missing":
        return NodeResolution("missing", detail=(
            "Node was downloaded but the extracted binary did not run."))
    return again


if __name__ == "__main__":  # manual inspection: python -m desktop.node_bootstrap
    print(resolve_node())
    sys.exit(0)
