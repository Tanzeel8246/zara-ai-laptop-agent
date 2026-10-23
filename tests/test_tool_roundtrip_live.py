"""Hotfix 1.0.10 reproduction: the tool round-trip in PRODUCTION topology.

The owner's first live Telegram run stalled forever right after the
"⚙️ <tool> …" echo: no confirmation buttons, no tool execution, no final
answer, no error — while plain conversation and a provider 503 error both
reached the chat fine. Every pre-existing test drove the pipeline on ONE
loop with a FakeChannel, which cannot see cross-loop failures.

Here the wiring matches production (agent/main.py):

  - a "home loop" in its own thread plays the Telegram transport loop;
  - the channel is the REAL TelegramChannel (real confirm machinery,
    real TelegramTransport registry) over a recording FakeBot;
  - AgentSession + TaskQueue run with the real worker thread;
  - ApiBrain is real, with litellm.acompletion scripted: first response
    is a tool call, second is the final answer;
  - the tool handlers are the real ones (list_dir / write_file).

Every wait has a hard deadline, so a regression fails fast instead of
hanging the suite.
"""

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from agent.brain.api_brain import ApiBrain
from agent.config import CONFIG
from agent.session import AgentSession
from agent.store import SqliteHistoryStore, Store
from agent.transport import IncomingMessage
from agent.transport.telegram_transport import TelegramChannel, TelegramTransport

OWNER_ID = 42
CHAT_ID = 7
DEADLINE = 30.0


# ------------------------------------------------------------ fake bot ----

class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.edits = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append(text)


class FakeBot:
    """Records everything TelegramChannel sends; no network."""

    def __init__(self):
        self.sent = []            # (text, reply_markup)
        self._lock = threading.Lock()

    async def send_message(self, chat_id, text, reply_markup=None):
        with self._lock:
            self.sent.append((str(text), reply_markup))
        return FakeMessage(text)

    def texts(self):
        with self._lock:
            return [text for text, _ in self.sent]

    def confirm_markup(self):
        """The reply_markup of the first message that carried buttons."""
        with self._lock:
            for _text, markup in self.sent:
                if markup is not None:
                    return markup
        return None


# ------------------------------------------------------------ home loop ---

class HomeLoop:
    """An asyncio loop in its own thread — the PTB transport loop's stand-in."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run, name="fake-home-loop", daemon=True
        )

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self):
        self.thread.start()
        return self

    def run(self, coro, timeout=DEADLINE):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)


# ------------------------------------------------------------- scripting --

def completion(content="", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def scripted_brain(monkeypatch, store, responses):
    """Real ApiBrain, LiteLLM replaced by a script of responses."""
    state = {"calls": []}

    async def fake_acompletion(**kwargs):
        state["calls"].append(kwargs)
        index = min(len(state["calls"]) - 1, len(responses) - 1)
        return responses[index]

    monkeypatch.setattr("agent.brain.api_brain.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr(CONFIG, "api_provider", "anthropic")
    monkeypatch.setattr(CONFIG, "_provider_model_raw", "")
    monkeypatch.setattr(CONFIG, "model", "claude-opus-5")
    brain = ApiBrain(history_store=SqliteHistoryStore(store))
    return brain, state


def wait_terminal(store, session_key, timeout=DEADLINE):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = store.list_tasks(session_key=session_key, limit=5)
        if rows and rows[-1]["status"] in ("done", "failed", "cancelled"):
            return rows[-1]
        time.sleep(0.05)
    rows = store.list_tasks(session_key=session_key, limit=5)
    return rows[-1] if rows else None


@pytest.fixture
def rig(tmp_path, monkeypatch):
    store = Store(tmp_path / "memory.db")
    home = HomeLoop().start()
    parts = {"store": store, "home": home}
    yield parts
    home.stop()


def build_session(rig, brain):
    session = AgentSession(brain, "test", store=rig["store"])
    transport = TelegramTransport(session)
    bot = FakeBot()
    chan = TelegramChannel(bot, CHAT_ID, OWNER_ID, transport=transport)
    session.queue.start()
    return session, transport, bot, chan


def submit(rig, session, chan, text):
    rig["home"].run(session.handle_message(IncomingMessage(channel=chan, text=text)))


# --------------------------------------------------------------- scenario -

def test_plain_tool_round_trip_cross_loop(rig, monkeypatch, tmp_path):
    """list_dir: brain tool call -> executor -> result -> final answer."""
    (tmp_path / "a.txt").write_text("x")
    brain, state = scripted_brain(
        monkeypatch,
        rig["store"],
        [
            completion(tool_calls=[tool_call("t1", "list_dir", {"path": str(tmp_path)})]),
            completion(content="Listing done."),
        ],
    )
    session, _transport, bot, chan = build_session(rig, brain)

    submit(rig, session, chan, "what is in this folder?")

    row = wait_terminal(rig["store"], "telegram:7")
    assert row is not None and row["status"] == "done", (
        f"task never finished: {row and row['status']}"
    )
    assert any("list_dir" in text for text in bot.texts()), bot.texts()
    assert "Listing done." in bot.texts()
    # The second provider call must carry the tool result back.
    tool_messages = [
        m for m in state["calls"][1]["messages"] if m.get("role") == "tool"
    ]
    assert tool_messages and "a.txt" in tool_messages[0]["content"]


def test_confirm_tool_round_trip_cross_loop(rig, monkeypatch, tmp_path):
    """write_file (always-confirm): buttons must appear, a tap must run it."""
    monkeypatch.setattr(CONFIG, "confirm_risky", True)
    target = tmp_path / "note.txt"
    brain, _state = scripted_brain(
        monkeypatch,
        rig["store"],
        [
            completion(
                tool_calls=[
                    tool_call("t1", "write_file", {"path": str(target), "content": "hello"})
                ]
            ),
            completion(content="File written."),
        ],
    )
    session, transport, bot, chan = build_session(rig, brain)

    submit(rig, session, chan, "write a note for me")

    # The confirmation prompt (with buttons) must reach the chat.
    deadline = time.monotonic() + DEADLINE
    markup = None
    while time.monotonic() < deadline:
        markup = bot.confirm_markup()
        if markup is not None:
            break
        time.sleep(0.05)
    assert markup is not None, f"no confirmation buttons were sent; chat got: {bot.texts()}"

    button = markup.inline_keyboard[0][0]
    answered = []

    async def answer():
        answered.append(True)

    query = SimpleNamespace(
        data=button.callback_data,
        from_user=SimpleNamespace(id=OWNER_ID),
        answer=answer,
    )
    rig["home"].run(transport._on_callback(SimpleNamespace(callback_query=query), None))
    assert answered == [True]

    row = wait_terminal(rig["store"], "telegram:7")
    assert row is not None and row["status"] == "done", (
        f"task never finished after approval: {row and row['status']}"
    )
    assert target.read_text() == "hello"
    assert "File written." in bot.texts()
