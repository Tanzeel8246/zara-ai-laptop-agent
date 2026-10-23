"""Node bootstrap decision matrix (Phase 5): override → system → bundled
→ downloaded → missing, plus the pinned-download hash gate. All probes
are fakes — no real Node, no network."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from desktop import node_bootstrap as nb


def _world(tmp_path, *, system=None, versions=None, files=()):
    """Build injectable probes. `versions` maps path-str -> version output."""
    versions = versions or {}
    existing = {str(p) for p in files}

    def which(name):
        return system

    def runner(path):
        return versions[str(path)]

    def exists(path):
        return str(path) in existing

    return which, runner, exists


def test_whatsapp_disabled_short_circuits(tmp_path):
    resolution = nb.resolve_node(whatsapp_enabled=False)
    assert resolution.source == "disabled"
    assert resolution.path is None


def test_override_wins(tmp_path):
    node = tmp_path / "custom" / "node.exe"
    which, runner, exists = _world(
        tmp_path, system="/usr/bin/node",
        versions={str(node): "v20.11.0", "/usr/bin/node": "v22.0.0"},
        files=[node],
    )
    resolution = nb.resolve_node(override=str(node), which=which, runner=runner, exists=exists)
    assert resolution.source == "override"
    assert resolution.path == str(node)
    assert resolution.version == "20.11.0"


def test_override_missing_file_is_missing(tmp_path):
    which, runner, exists = _world(tmp_path)
    resolution = nb.resolve_node(
        override="/nope/node.exe", which=which, runner=runner, exists=exists)
    assert resolution.source == "missing"
    assert "NODE_BINARY" in resolution.detail


def test_override_too_old_is_missing(tmp_path):
    node = tmp_path / "node.exe"
    which, runner, exists = _world(
        tmp_path, versions={str(node): "v16.20.0"}, files=[node])
    resolution = nb.resolve_node(override=str(node), which=which, runner=runner, exists=exists)
    assert resolution.source == "missing"


def test_system_node(tmp_path):
    which, runner, exists = _world(
        tmp_path, system="/usr/bin/node", versions={"/usr/bin/node": "v22.14.0"})
    resolution = nb.resolve_node(app=tmp_path, data=tmp_path / "d",
                                 which=which, runner=runner, exists=exists)
    assert resolution.source == "system"
    assert resolution.version == "22.14.0"


def test_old_system_node_falls_through_to_bundled(tmp_path):
    bundled = tmp_path / "node" / "node.exe"
    which, runner, exists = _world(
        tmp_path, system="/usr/bin/node",
        versions={"/usr/bin/node": "v14.0.0", str(bundled): "v22.14.0"},
        files=[bundled],
    )
    resolution = nb.resolve_node(app=tmp_path, data=tmp_path / "d",
                                 which=which, runner=runner, exists=exists)
    assert resolution.source == "bundled"
    assert resolution.path == str(bundled)


def test_downloaded_node_used_when_nothing_else(tmp_path):
    downloaded = tmp_path / "d" / f"node-v{nb.NODE_VERSION}-win-x64" / "node.exe"
    which, runner, exists = _world(
        tmp_path, versions={str(downloaded): f"v{nb.NODE_VERSION}"},
        files=[downloaded])
    resolution = nb.resolve_node(app=tmp_path / "app", data=tmp_path / "d",
                                 which=which, runner=runner, exists=exists)
    assert resolution.source == "downloaded"


def test_missing_everywhere(tmp_path):
    which, runner, exists = _world(tmp_path)
    resolution = nb.resolve_node(app=tmp_path, data=tmp_path / "d",
                                 which=which, runner=runner, exists=exists)
    assert resolution.source == "missing"
    assert resolution.path is None


def test_parse_node_version():
    assert nb.parse_node_version("v22.14.0\n") == (22, 14, 0)
    assert nb.parse_node_version("18.0") == (18, 0)
    assert nb.parse_node_version("garbage") is None
    assert nb.parse_node_version("") is None


def _node_zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"node-v{nb.NODE_VERSION}-win-x64/node.exe", b"fake-node-binary")
    return buffer.getvalue()


def test_download_verifies_sha_and_extracts(tmp_path):
    payload = _node_zip_bytes()
    sha = hashlib.sha256(payload).hexdigest()

    def fetcher(url, dest):
        Path(dest).write_bytes(payload)

    out = nb.download_node(tmp_path / "data", fetcher=fetcher, expected_sha256=sha)
    assert (out / "node.exe").read_bytes() == b"fake-node-binary"
    # the archive itself is cleaned up after a successful extract
    assert not (tmp_path / "data" / nb.NODE_WIN_X64_ZIP).exists()


def test_download_rejects_bad_sha_and_discards(tmp_path):
    payload = _node_zip_bytes()

    def fetcher(url, dest):
        Path(dest).write_bytes(payload)

    with pytest.raises(ValueError, match="SHA256"):
        nb.download_node(tmp_path / "data", fetcher=fetcher, expected_sha256="0" * 64)
    assert not (tmp_path / "data" / nb.NODE_WIN_X64_ZIP).exists()
    assert not list((tmp_path / "data").rglob("node.exe"))


def test_ensure_node_downloads_when_missing(tmp_path):
    payload = _node_zip_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    data = tmp_path / "data"

    def fetcher(url, dest):
        Path(dest).write_bytes(payload)

    downloaded_path = data / f"node-v{nb.NODE_VERSION}-win-x64" / "node.exe"

    def runner(path):
        if str(path) == str(downloaded_path):
            return f"v{nb.NODE_VERSION}"
        raise AssertionError("unexpected probe")

    # download_node uses the REAL pinned hash; patch it for this test so
    # the fake archive passes — the hash gate itself is tested above.
    original = nb.NODE_ZIP_SHA256
    nb.NODE_ZIP_SHA256 = sha
    try:
        resolution = nb.ensure_node(
            app=tmp_path / "app", data=data, download=True,
            fetcher=fetcher, which=lambda name: None, runner=runner,
        )
    finally:
        nb.NODE_ZIP_SHA256 = original
    assert resolution.source == "downloaded"
    assert resolution.path == str(downloaded_path)


def test_ensure_node_without_download_stays_missing(tmp_path):
    resolution = nb.ensure_node(
        app=tmp_path, data=tmp_path / "d", download=False,
        which=lambda name: None, runner=lambda p: "v22.0.0",
        exists=lambda p: False,
    )
    assert resolution.source == "missing"


def test_pinned_download_is_the_official_lts():
    assert nb.NODE_DOWNLOAD_URL.startswith("https://nodejs.org/dist/")
    assert nb.NODE_WIN_X64_ZIP in nb.NODE_DOWNLOAD_URL
    assert len(nb.NODE_ZIP_SHA256) == 64
