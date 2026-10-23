"""Auto-update (Phase 5): semver compare, feed validation, SHA256-gated
download, staged-state persistence in the store meta, disabled without
a feed URL. Fetchers/downloaders are fakes — no network."""

import hashlib
import json
from pathlib import Path

import pytest

from agent import updater as up
from agent.store import Store

FEED = {
    "version": "1.1.0",
    "url": "https://updates.example.com/CodeHubbAssistant-Setup-1.1.0.exe",
    "notes": "Fixes and polish.",
    "mandatory": False,
}
INSTALLER_BYTES = b"fake-installer-bytes"
FEED["sha256"] = hashlib.sha256(INSTALLER_BYTES).hexdigest()


def _store(tmp_path):
    return Store(tmp_path / "meta.db")


def _updater(tmp_path, feed_url="https://updates.example.com/feed.json", **kw):
    kw.setdefault("store", _store(tmp_path))
    kw.setdefault("updates_dir", tmp_path / "updates")
    kw.setdefault("current_version", "1.0.0")
    return up.Updater(feed_url=feed_url, **kw)


# --------------------------------------------------------------- versions

@pytest.mark.parametrize("a,b,expected", [
    ("1.0.0", "1.0.0", 0),
    ("1.0.1", "1.0.0", 1),
    ("1.0.0", "1.0.1", -1),
    ("1.0", "1.0.0", 0),
    ("2.0", "1.9.9", 1),
    ("v1.2.3", "1.2.3", 0),
    ("1.2.3", "1.2.10", -1),
    ("1.10.0", "1.9.0", 1),
    ("1.2.3-beta", "1.2.3", 0),
])
def test_compare_versions(a, b, expected):
    assert up.compare_versions(a, b) == expected
    assert up.is_newer(a, b) == (expected > 0)


def test_parse_version_rejects_junk():
    for junk in ("", "abc", "1..2", "1.x.0", None):
        with pytest.raises(ValueError):
            up.parse_version(junk)


# ------------------------------------------------------------------- feed

def test_parse_feed_ok():
    info = up.parse_feed(json.dumps(FEED))
    assert info.version == "1.1.0"
    assert info.sha256 == FEED["sha256"]
    assert info.mandatory is False


@pytest.mark.parametrize("bad", [
    "not json at all",
    json.dumps({"version": "1.1.0"}),                                  # no url/sha
    json.dumps({"version": "1.1.0", "url": "https://x/y.exe", "sha256": "short"}),
    json.dumps({"version": "banana", "url": "https://x/y.exe", "sha256": "a" * 64}),
    json.dumps({"version": "1.1.0", "url": "ftp://x/y.exe", "sha256": "a" * 64}),
    json.dumps([1, 2, 3]),
])
def test_parse_feed_rejects_broken(bad):
    with pytest.raises(up.UpdateError):
        up.parse_feed(bad)


# ------------------------------------------------------------------ check

def test_disabled_without_feed_url(tmp_path):
    calls = []
    updater = _updater(tmp_path, feed_url="",
                       fetcher=lambda url: calls.append(url))
    assert updater.enabled is False
    assert updater.check() is None
    assert calls == []  # never even fetches


def test_check_finds_newer(tmp_path):
    updater = _updater(tmp_path, fetcher=lambda url: json.dumps(FEED))
    info = updater.check()
    assert info is not None and info.version == "1.1.0"


def test_check_same_version_is_up_to_date(tmp_path):
    feed = dict(FEED, version="1.0.0")
    feed["sha256"] = FEED["sha256"]
    updater = _updater(tmp_path, fetcher=lambda url: json.dumps(feed))
    assert updater.check() is None


def test_check_unreachable_feed_raises_update_error(tmp_path):
    def fetcher(url):
        raise OSError("no route to host")

    updater = _updater(tmp_path, fetcher=fetcher)
    with pytest.raises(up.UpdateError, match="Could not reach"):
        updater.check()


# --------------------------------------------------------------- download

def _downloader(payload):
    def download(url, dest):
        Path(dest).write_bytes(payload)
    return download


def test_download_stages_verified_update(tmp_path):
    updater = _updater(
        tmp_path,
        fetcher=lambda url: json.dumps(FEED),
        downloader=_downloader(INSTALLER_BYTES),
    )
    staged_path = updater.download()
    assert staged_path.exists()
    assert staged_path.read_bytes() == INSTALLER_BYTES
    staged = updater.staged()
    assert staged["version"] == "1.1.0"
    assert staged["path"] == str(staged_path)
    assert staged["sha256"] == FEED["sha256"]


def test_download_bad_sha_discards_and_reports(tmp_path):
    updater = _updater(
        tmp_path,
        fetcher=lambda url: json.dumps(FEED),
        downloader=_downloader(b"tampered-bytes"),
    )
    with pytest.raises(up.UpdateError, match="integrity check"):
        updater.download()
    assert updater.staged() is None
    assert "integrity check" in (updater.last_error() or "")
    leftovers = list((tmp_path / "updates").glob("*")) if (tmp_path / "updates").exists() else []
    assert leftovers == []


def test_staged_state_persists_across_instances(tmp_path):
    store = _store(tmp_path)
    first = _updater(tmp_path, store=store,
                     fetcher=lambda url: json.dumps(FEED),
                     downloader=_downloader(INSTALLER_BYTES))
    first.download()
    second = _updater(tmp_path, store=store)
    staged = second.staged()
    assert staged is not None and staged["version"] == "1.1.0"
    second.clear_staged()
    assert second.staged() is None


def test_staged_vanishes_when_file_deleted(tmp_path):
    updater = _updater(tmp_path,
                       fetcher=lambda url: json.dumps(FEED),
                       downloader=_downloader(INSTALLER_BYTES))
    path = updater.download()
    path.unlink()
    assert updater.staged() is None


def test_apply_script_path_prefers_existing(tmp_path):
    script = tmp_path / "packaging" / "apply_update.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# stub")
    assert up.apply_script_path(root=tmp_path) == script
