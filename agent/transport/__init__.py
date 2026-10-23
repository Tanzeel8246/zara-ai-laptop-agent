"""Transport seam: how instructions arrive and replies leave.

A transport owns one messaging platform (Discord today; WhatsApp, Telegram and
the companion app in later phases). Brains and tools never see platform
objects — they talk to a TransportChannel.

Contracts
---------
TransportChannel (one conversation):
    send_text(text)                 deliver a message (channel chunks as needed)
    note(text)                      small progress line for a tool call
    send_file(path, caption=None)   deliver a file (screenshot, voice clip...)
    send_voice(path)                optional; defaults to send_file
    confirm(tool, reason, detail)   ask the owner; True = run it, False = cancel
    .user_id                        platform id of the owner on this channel
    .channel_id                     hashable id of the conversation
    .last_spoken / .spoke           voice-reply bookkeeping (as before)

IncomingMessage: what a transport hands to its instruction handler — text,
optional pre-downloaded audio attachment paths, other attachment names, and
the channel to reply on.

Transport: constructed with (brain, helpers) and run()s until stopped.
The instruction handler signature is:
    async def on_instruction(msg: IncomingMessage) -> None
implemented by the composition root (agent/session.py), which owns the
allowlist gate, slash commands, voice transcription and job bookkeeping —
exactly the flow the Discord client ran inline before Phase 0.
"""

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class TransportChannel(Protocol):
    user_id: int
    channel_id: object
    last_spoken: str
    spoke: bool

    async def send_text(self, text): ...
    async def note(self, text): ...
    async def send_file(self, path, caption=None): ...
    async def confirm(self, tool_name, reason, detail) -> bool: ...
    # optional: typing() -> async context manager showing "typing…" if supported


@dataclass
class IncomingMessage:
    channel: TransportChannel
    text: str = ""
    audio_paths: list = field(default_factory=list)        # local files, transport-downloaded (first audio only, as before)
    audio_failed: bool = False                             # an audio attachment existed but could not be downloaded
    other_attachments: list = field(default_factory=list)  # names only (still on the user's phone)


InstructionHandler = Callable[[IncomingMessage], Awaitable[None]]


class Transport(Protocol):
    name: str

    def __init__(self, on_instruction: InstructionHandler, helpers): ...
    def run(self) -> None: ...


__all__ = [
    "TransportChannel",
    "IncomingMessage",
    "InstructionHandler",
    "Transport",
]
