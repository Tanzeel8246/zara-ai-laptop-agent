"""Hotfix 1.0.7: the optional Telegram proxy.

Some ISPs block api.telegram.org (the connection opens, the TLS handshake
times out). The proxy setting routes the bot through a local VPN/proxy. It
is secret-class (a proxy URL can embed credentials): keyring storage like
the bot token, and logs only ever show scheme + host.

Everything is faked at the builder boundary — no network, no real token.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from agent.secrets import SECRET_KEYS  # noqa: E402
from agent.transport.telegram_transport import build_application, mask_proxy_url  # noqa: E402


# ------------------------------------------------------------- log masking

def test_mask_strips_credentials_path_and_query():
    assert mask_proxy_url("socks5://user:secretpass@127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert mask_proxy_url("http://proxy.local:8080/some/path?token=abc") == "http://proxy.local:8080"
    assert mask_proxy_url("socks5://proxy.local") == "socks5://proxy.local"


def test_mask_degrades_safely_on_garbage():
    assert mask_proxy_url("not a url") == "(proxy set)"
    assert mask_proxy_url("") == "(proxy set)"


# ------------------------------------------------------- builder boundary

class FakeBuilder:
    def __init__(self):
        self.calls = []

    def token(self, value):
        self.calls.append(("token", value))
        return self

    def concurrent_updates(self, value):
        # Hotfix 1.0.10: build_application always enables concurrent
        # update handling (PTB's serial default starves confirm taps).
        self.calls.append(("concurrent_updates", value))
        return self

    def proxy(self, value):
        self.calls.append(("proxy", value))
        return self

    def get_updates_proxy(self, value):
        self.calls.append(("get_updates_proxy", value))
        return self

    def build(self):
        return ("APP", self.calls)


class FakeApplication:
    builder_instance = None

    @classmethod
    def builder(cls):
        return cls.builder_instance


@pytest.fixture
def fake_ptb(monkeypatch):
    import telegram.ext

    builder = FakeBuilder()
    FakeApplication.builder_instance = builder
    monkeypatch.setattr(telegram.ext, "Application", FakeApplication)
    return builder


def test_builder_receives_proxy_on_both_paths_when_set(fake_ptb):
    app, calls = build_application("TOKEN", "socks5://127.0.0.1:1080")
    assert app == "APP"
    assert ("token", "TOKEN") in calls
    # PTB keeps a SEPARATE request for get_updates; both must be proxied.
    assert ("proxy", "socks5://127.0.0.1:1080") in calls
    assert ("get_updates_proxy", "socks5://127.0.0.1:1080") in calls


def test_builder_gets_no_proxy_calls_when_unset(fake_ptb):
    for blank in ("", "   ", None):
        fake_ptb.calls.clear()
        build_application("TOKEN", blank)
        kinds = [kind for kind, _ in fake_ptb.calls]
        assert "proxy" not in kinds and "get_updates_proxy" not in kinds
        assert ("token", "TOKEN") in fake_ptb.calls


# ------------------------------------------------------- secret plumbing

def test_proxy_is_a_registered_secret_key():
    assert "TELEGRAM_PROXY" in SECRET_KEYS


def test_config_exposes_telegram_proxy():
    from agent.config import CONFIG

    assert isinstance(CONFIG.telegram_proxy, str)


# ------------------------------------------------------ settings round-trip

class FakeKeyring:
    def __init__(self):
        self.store = {}
        self.deleted = []

    def get(self, name):
        return self.store.get(name, "")

    def set(self, name, value):
        self.store[name] = value
        return True

    def delete(self, name):
        self.deleted.append(name)
        self.store.pop(name, None)
        return True


@pytest.fixture
def env_home(tmp_path):
    (tmp_path / ".env.example").write_text(
        "PRODUCT_NAME=CodeHubb Assistant\nCONFIRM_RISKY=false\n", encoding="utf-8"
    )
    return tmp_path


def _with_root(tmp_path, fn):
    import desktop.settings_model as sm

    original = sm.ROOT
    sm.ROOT = tmp_path
    try:
        return fn()
    finally:
        sm.ROOT = original


def test_proxy_round_trips_through_the_keyring_never_the_env(env_home):
    from desktop.settings_model import Settings

    keyring = FakeKeyring()
    env_path = env_home / ".env"
    settings = Settings(transports=["telegram"], telegram_proxy="socks5://127.0.0.1:1080")
    _with_root(env_home, lambda: settings.save(
        env_path, set_secret_fn=keyring.set, delete_secret_fn=keyring.delete))

    assert keyring.store["TELEGRAM_PROXY"] == "socks5://127.0.0.1:1080"
    env_text = env_path.read_text(encoding="utf-8")
    assert "socks5://127.0.0.1:1080" not in env_text     # never in plaintext

    loaded = _with_root(env_home, lambda: Settings.load(env_path, get_secret_fn=keyring.get))
    assert loaded.telegram_proxy == "socks5://127.0.0.1:1080"


def test_clearing_the_proxy_deletes_the_secret(env_home):
    from desktop.settings_model import Settings

    keyring = FakeKeyring()
    keyring.store["TELEGRAM_PROXY"] = "socks5://127.0.0.1:1080"
    env_path = env_home / ".env"
    settings = Settings(transports=["telegram"], telegram_proxy="")
    _with_root(env_home, lambda: settings.save(
        env_path, set_secret_fn=keyring.set, delete_secret_fn=keyring.delete))
    assert "TELEGRAM_PROXY" in keyring.deleted
    assert "TELEGRAM_PROXY" not in keyring.store


# ------------------------------------------------------------- GUI field

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_transports_fields_proxy_round_trip(qapp):
    from desktop.fields import TransportsFields
    from desktop.settings_model import Settings

    fields = TransportsFields()
    fields.load(Settings(transports=["telegram"], telegram_proxy="http://127.0.0.1:8080"))
    assert fields.telegram_proxy.text() == "http://127.0.0.1:8080"
    assert fields.telegram_proxy.placeholderText().startswith(
        "socks5://127.0.0.1:1080 or http://127.0.0.1:8080"
    )

    fields.telegram_proxy.setText("socks5://localhost:1080")
    out = Settings()
    fields.apply(out)
    assert out.telegram_proxy == "socks5://localhost:1080"
