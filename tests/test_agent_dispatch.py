"""Frozen-bundle dispatch (Phase 5): the tray launches the agent as
[exe, --run-agent] when frozen and [python, run.py] from source, and the
exe's argv dispatch runs the headless agent in-process."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from desktop.agent_process import AgentProcess, agent_command


def test_agent_command_dev():
    assert agent_command("python", frozen=False) == ["python", "run.py"]


def test_agent_command_frozen():
    assert agent_command("/app/CodeHubbAssistant.exe", frozen=True) == [
        "/app/CodeHubbAssistant.exe", "--run-agent",
    ]


class _FakeProc:
    pid = 777

    def poll(self):
        return None


def test_agent_process_frozen_uses_run_agent_flag(tmp_path):
    captured = {}

    def popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    agent = AgentProcess(
        root=tmp_path, python_exe="/app/CodeHubbAssistant.exe",
        popen=popen, frozen=True,
    )
    assert agent.start() is True
    assert captured["cmd"] == ["/app/CodeHubbAssistant.exe", "--run-agent"]


def test_agent_process_dev_still_uses_run_py(tmp_path):
    captured = {}

    def popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    agent = AgentProcess(root=tmp_path, popen=popen, frozen=False)
    assert agent.start() is True
    assert captured["cmd"][1] == "run.py"


def test_main_dispatches_run_agent_without_qt(monkeypatch):
    pytest.importorskip("PySide6", reason="GUI dependencies not installed")
    import agent.main
    from desktop import app as desktop_app

    calls = []

    def fake_run():
        calls.append("ran")
        raise SystemExit(3)

    def no_qt(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("QApplication must not be created for --run-agent")

    monkeypatch.setattr(agent.main, "run", fake_run)
    monkeypatch.setattr(desktop_app, "QApplication", no_qt)
    assert desktop_app.main(["CodeHubbAssistant", "--run-agent"]) == 3
    assert calls == ["ran"]


def test_main_dispatch_clean_exit_is_zero(monkeypatch):
    pytest.importorskip("PySide6", reason="GUI dependencies not installed")
    import agent.main
    from desktop import app as desktop_app

    monkeypatch.setattr(agent.main, "run", lambda: None)
    assert desktop_app.main(["CodeHubbAssistant", "--run-agent"]) == 0
