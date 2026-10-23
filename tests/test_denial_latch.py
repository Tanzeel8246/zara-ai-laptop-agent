"""Hotfix 1.0.10: a refused confirmation is FINAL, and failures are never silent.

Live evidence (owner's first Telegram run): a folder-create task finished
~10 minutes late and the write had executed, although the owner never saw
— let alone tapped — an Allow/Deny prompt. The audit behind this file
found the mechanisms:

  * SafetyPipeline.check was STATELESS. A denial (or a confirmation
    timeout) only returned a "DENIED: ..." text to the model. Nothing
    stopped the brain from re-proposing the same call (another full
    CONFIRM_TIMEOUT per attempt) or an EQUIVALENT call that classify()
    does not flag — write_file refused, then run_powershell Set-Content
    executing with no prompt at all.
  * PTB's ApplicationBuilder defaults to max_concurrent_updates=1, so a
    long update handler starves the callback queries that answer prompts.
  * litellm.acompletion was called with no timeout / retry bound, so a
    provider 503 storm could burn unbounded minutes invisibly.
  * TaskQueue marked a raised task "failed" in the store only — the user
    was never told.

These tests pin the guarantees: denial latches for the rest of the turn
(same action AND state-changing equivalents), the latch resets on the
next turn, read-only tools keep working after a denial, a confirmation
timeout resolves as a refusal, the Telegram app processes updates
concurrently, provider calls are bounded, and a runner exception reaches
the chat as an agent error.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from agent.brain.api_brain import ApiBrain
from agent.config import CONFIG
from agent.queue import TaskQueue
from agent.safety import HANDLERS, ToolExecutor
from agent.store import SqliteHistoryStore, Store
from agent.transport.telegram_transport import TelegramChannel, build_application
from tests.fakes import FakeChannel


# ------------------------------------------------------------- scripting --

def completion(content="", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class SpyHandlers(dict):
    """Real registry, with the interesting handlers replaced by spies."""

    def __init__(self, *names):
        super().__init__(HANDLERS)
        self.ran = []
        for name in names:
            self[name] = self._spy(name)

    def _spy(self, name):
        def handler(**kwargs):
            self.ran.append((name, kwargs))
            return {"text": f"{name} executed"}

        return handler


def make_brain(monkeypatch, tmp_path, responses, handlers, confirm_answer):
    state = {"calls": []}

    async def fake_acompletion(**kwargs):
        state["calls"].append(kwargs)
        index = min(len(state["calls"]) - 1, len(responses) - 1)
        return responses[index]

    monkeypatch.setattr("agent.brain.api_brain.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr(CONFIG, "api_provider", "anthropic")
    monkeypatch.setattr(CONFIG, "_provider_model_raw", "")
    monkeypatch.setattr(CONFIG, "model", "claude-opus-5")
    monkeypatch.setattr(CONFIG, "confirm_risky", True)
    store = Store(tmp_path / "memory.db")
    executor = ToolExecutor(brain_label="test", handlers=handlers, announce=False)
    brain = ApiBrain(executor=executor, history_store=SqliteHistoryStore(store))
    chan = FakeChannel(confirm_answer=confirm_answer)
    return brain, chan, state


def tool_results(state, call_index):
    messages = state["calls"][call_index]["messages"]
    return [m["content"] for m in messages if m.get("role") == "tool"]


# ------------------------------------------------------ the safety latch --

async def test_denied_write_cannot_be_reached_via_powershell_equivalent(
    monkeypatch, tmp_path
):
    handlers = SpyHandlers("write_file", "run_powershell")
    brain, chan, state = make_brain(
        monkeypatch,
        tmp_path,
        [
            completion(
                tool_calls=[
                    tool_call("t1", "write_file", {"path": "x.txt", "content": "hi"})
                ]
            ),
            # The model routes around the refusal with an unclassified shell
            # equivalent — exactly what DENIED_TEXT merely ASKS it not to do.
            completion(
                tool_calls=[
                    tool_call(
                        "t2",
                        "run_powershell",
                        {"command": "Set-Content -Path x.txt -Value hi"},
                    )
                ]
            ),
            completion(content="Understood, I stopped."),
        ],
        handlers,
        confirm_answer=False,  # the owner refuses (or never answers)
    )

    await brain.handle("chat", "write the file", chan)

    assert handlers.ran == [], f"a refused action executed anyway: {handlers.ran}"
    assert len(chan.confirm_calls) == 1, "the equivalent must not be re-prompted either"
    assert "Understood, I stopped." in chan.texts
    second = tool_results(state, 2)
    assert second and second[-1].startswith("ERROR: DENIED"), second


async def test_same_action_is_not_reprompted_after_denial(monkeypatch, tmp_path):
    handlers = SpyHandlers("write_file")
    brain, chan, state = make_brain(
        monkeypatch,
        tmp_path,
        [
            completion(
                tool_calls=[
                    tool_call("t1", "write_file", {"path": "x.txt", "content": "hi"})
                ]
            ),
            completion(
                tool_calls=[
                    tool_call("t2", "write_file", {"path": "x.txt", "content": "hi"})
                ]
            ),
            completion(content="Stopped."),
        ],
        handlers,
        confirm_answer=False,
    )

    await brain.handle("chat", "write the file", chan)

    assert handlers.ran == []
    assert len(chan.confirm_calls) == 1, "a refused action must not burn another prompt"
    assert "Stopped." in chan.texts


async def test_readonly_tools_still_work_after_denial(monkeypatch, tmp_path):
    handlers = SpyHandlers("write_file", "list_dir")
    brain, chan, state = make_brain(
        monkeypatch,
        tmp_path,
        [
            completion(
                tool_calls=[
                    tool_call("t1", "write_file", {"path": "x.txt", "content": "hi"})
                ]
            ),
            completion(tool_calls=[tool_call("t2", "list_dir", {"path": str(tmp_path)})]),
            completion(content="Here is what I can see."),
        ],
        handlers,
        confirm_answer=False,
    )

    await brain.handle("chat", "write, then look", chan)

    assert [name for name, _ in handlers.ran] == ["list_dir"]
    assert "Here is what I can see." in chan.texts


async def test_denial_latch_resets_on_the_next_turn(monkeypatch, tmp_path):
    handlers = SpyHandlers("write_file")
    write = completion(
        tool_calls=[tool_call("t1", "write_file", {"path": "x.txt", "content": "hi"})]
    )
    # One brain, one executor, a four-response script spanning two turns.
    brain, chan, state = make_brain(
        monkeypatch,
        tmp_path,
        [write, completion(content="ok"), write, completion(content="ok")],
        handlers,
        confirm_answer=False,
    )

    # Turn 1: the owner refuses — nothing runs.
    await brain.handle("chat", "write it", chan)
    assert handlers.ran == []
    assert len(chan.confirm_calls) == 1

    # Turn 2: the owner asks again and this time approves — it must run,
    # so the latch is scoped to a turn, not to the conversation.
    chan._confirm_answer = True
    await brain.handle("chat", "write it", chan)
    assert [name for name, _ in handlers.ran] == ["write_file"]
    assert len(chan.confirm_calls) == 2


# ------------------------------------------------- timeout counts as "no" --

async def test_telegram_confirm_timeout_is_a_refusal(monkeypatch):
    import agent.transport.telegram_transport as tt

    monkeypatch.setattr(tt, "CONFIRM_TIMEOUT", 0.2)

    sent = {}

    class Bot:
        async def send_message(self, chat_id, text, reply_markup=None):
            sent["markup"] = reply_markup
            return SimpleNamespace(edit_text=_noop_edit)

    async def _noop_edit(text, reply_markup=None):
        return None

    transport = SimpleNamespace(
        register_confirm=lambda cid, uid, fut: None,
        drop_confirm=lambda cid: None,
    )
    chan = TelegramChannel(Bot(), chat_id=7, user_id=42, transport=transport)

    started = time.monotonic()
    approved = await chan.confirm("write_file", "writes a file", "path: x")
    elapsed = time.monotonic() - started

    assert approved is False, "an unanswered confirmation must resolve as refusal"
    assert elapsed < 5, f"timeout path took {elapsed:.1f}s"


# ------------------------------------------- confirmations stay answerable --

class _RecordingBuilder:
    def __init__(self):
        self.calls = []

    def token(self, value):
        self.calls.append(("token", value))
        return self

    def concurrent_updates(self, value):
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


def test_telegram_app_processes_updates_concurrently(monkeypatch):
    builder = _RecordingBuilder()
    fake_app = SimpleNamespace(builder=staticmethod(lambda: builder))
    monkeypatch.setattr(
        "agent.transport.telegram_transport.Application",
        fake_app,
        raising=False,
    )
    # build_application imports Application inside the function; patch the
    # source module attribute it resolves from.
    import telegram.ext

    monkeypatch.setattr(telegram.ext, "Application", fake_app)

    app, calls = build_application("123:token")
    kinds = [kind for kind, _ in calls]
    assert "concurrent_updates" in kinds, (
        "PTB defaults to max_concurrent_updates=1: one slow handler would "
        "starve the owner's confirmation taps and /cancel"
    )
    value = dict(calls)["concurrent_updates"]
    assert value is True or (isinstance(value, int) and value > 1)


# ------------------------------------------------- bounded provider calls --

def test_provider_calls_are_time_and_retry_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(CONFIG, "api_provider", "anthropic")
    monkeypatch.setattr(CONFIG, "_provider_model_raw", "")
    monkeypatch.setattr(CONFIG, "model", "claude-opus-5")
    store = Store(tmp_path / "memory.db")
    brain = ApiBrain(history_store=SqliteHistoryStore(store))
    kwargs = brain._call_kwargs()
    assert kwargs.get("timeout"), "no per-request timeout: a hung provider call can stall a turn for LiteLLM's 6000s fallback"
    assert kwargs["timeout"] <= 300
    assert kwargs.get("num_retries") is not None, "unbounded library retries during a 503 storm"
    assert kwargs["num_retries"] <= 3


# ------------------------------------------------- failures are never silent --

async def test_runner_exception_reaches_the_chat(tmp_path):
    store = Store(tmp_path / "memory.db")

    async def exploding_runner(row, chan, live):
        raise RuntimeError("kaboom")

    queue = TaskQueue(store, exploding_runner)
    chan = FakeChannel()
    task_id, _ahead = queue.submit("fake:7", "do something", chan=chan)
    row = store.get_task(task_id)
    await queue._execute({**row})
    final = store.get_task(task_id)
    assert final["status"] == "failed"
    assert any("Agent error" in text and "kaboom" in text for text in chan.texts), (
        f"the failure never reached the user: {chan.texts}"
    )
