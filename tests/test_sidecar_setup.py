"""Hotfix 1.0.2: shared sidecar package setup (agent/sidecar_setup.py).

npm resolution (sibling of node first, PATH fallback) and the blocking
install used by the agent supervisor — all with fakes, no real Node.
"""

from types import SimpleNamespace

from agent import sidecar_setup


# ------------------------------------------------------------- resolve_npm

def test_resolve_npm_prefers_sibling_cmd_on_windows_layout(tmp_path):
    node = tmp_path / "nodejs" / "node.exe"
    node.parent.mkdir(parents=True)
    node.write_bytes(b"")
    (node.parent / "npm.cmd").write_bytes(b"")
    assert sidecar_setup.resolve_npm(str(node)) == str(node.parent / "npm.cmd")


def test_resolve_npm_prefers_sibling_posix(tmp_path):
    node = tmp_path / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_bytes(b"")
    (node.parent / "npm").write_bytes(b"")
    found = sidecar_setup.resolve_npm(str(node), which=lambda name: None)
    assert found == str(node.parent / "npm")


def test_resolve_npm_falls_back_to_path(tmp_path):
    node = tmp_path / "node"  # no npm sibling exists
    found = sidecar_setup.resolve_npm(
        str(node), which=lambda name: "/usr/bin/npm" if name == "npm" else None
    )
    assert found == "/usr/bin/npm"


def test_resolve_npm_none_when_nowhere(tmp_path):
    found = sidecar_setup.resolve_npm(
        str(tmp_path / "node"), which=lambda name: None
    )
    assert found is None


# ---------------------------------------------------------- install_packages

def _runner_returning(rc, stdout="", stderr=""):
    def runner(cmd, **kwargs):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)
    return runner


def test_install_packages_success(tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()

    def runner(cmd, **kwargs):
        assert cmd[1] == "install"
        assert kwargs["cwd"] == str(sidecar)
        (sidecar / "node_modules").mkdir()
        return SimpleNamespace(returncode=0, stdout="added 42 packages", stderr="")

    ok, detail = sidecar_setup.install_packages(
        sidecar, node="node", npm="npm", runner=runner
    )
    assert ok is True
    assert "installed" in detail


def test_install_packages_failure_returns_output_tail(tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    ok, detail = sidecar_setup.install_packages(
        sidecar, node="node", npm="npm",
        runner=_runner_returning(1, stdout="npm ERR! code E404"),
    )
    assert ok is False
    assert "npm ERR!" in detail
    assert not (sidecar / "node_modules").exists()


def test_install_packages_zero_exit_but_no_modules_is_failure(tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    ok, _detail = sidecar_setup.install_packages(
        sidecar, node="node", npm="npm", runner=_runner_returning(0)
    )
    assert ok is False


def test_install_packages_without_npm(tmp_path, monkeypatch):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    monkeypatch.setattr(sidecar_setup, "resolve_npm", lambda node=None: None)
    ok, detail = sidecar_setup.install_packages(
        sidecar, node="node", runner=_runner_returning(0)
    )
    assert ok is False
    assert "not found" in detail


def test_packages_installed_and_manual_hint(tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    assert sidecar_setup.packages_installed(sidecar) is False
    (sidecar / "node_modules").mkdir()
    assert sidecar_setup.packages_installed(sidecar) is True
    hint = sidecar_setup.manual_install_hint(sidecar)
    assert "npm install" in hint and str(sidecar) in hint
