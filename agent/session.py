"""Conversation session: what happens to one instruction, transport-neutral.

Before Phase 0 this flow lived inline in the Discord client's on_message.
It now sits behind the Transport seam: a transport gates the sender against
the allowlist, packages the message as an IncomingMessage, and hands it here.
Commands, voice-note handling, job bookkeeping (/stop) and the spoken-reply
logic are unchanged behaviour, just no longer Discord-shaped.
"""

import asyncio
import contextlib

from . import voice
from .config import CONFIG

HELP = """**{name} - your laptop, from your phone**

Talk to me in plain English - by text OR by voice (hold the mic in Discord to send a voice note).
I understand English and Urdu, and I'll reply by voice when you talk to me by voice.

> what's on my screen right now?
> is the laptop plugged in and how much battery is left?
> open chrome and go to gmail, then screenshot it
> WhatsApp par Ali ko bhejo: main 10 min mein aa raha hoon
> find every invoice PDF in Documents from this year and send me the biggest one
> what's using all my RAM? close the worst offender

**Commands**
`/new` - forget this conversation and start fresh
`/stop` - cancel whatever I'm doing right now
`/shot` - instant screenshot, no thinking
`/status` - instant system health
`/voice on` / `/voice off` / `/voice auto` - control voice replies
`/help` - this message"""


class AgentSession:
    def __init__(self, brain, brain_label=""):
        self.brain = brain
        self.brain_label = brain_label
        self.jobs = {}          # channel_id -> asyncio.Task running brain.handle
        self.voice_mode = {}    # channel_id -> per-channel voice override

    @property
    def model_label(self):
        return getattr(self.brain, "model_label", "")

    async def handle_message(self, msg):
        chan = msg.channel
        key = chan.channel_id
        text = (msg.text or "").strip()

        if text.startswith("/"):
            if await self._command(text, key, chan):
                return

        came_by_voice = False
        if msg.audio_paths or msg.audio_failed:
            heard, lang = "", ""
            if msg.audio_paths:
                heard, lang = await self._listen(msg.audio_paths[0], chan)
            if heard:
                # tell the model it arrived as speech, so it replies by voice in the same language
                spoken_lang = "Urdu" if str(lang).startswith("ur") else (
                    "Hindi/Urdu" if str(lang).startswith("hi") else "English"
                )
                text = (
                    f"{text}\n{heard}".strip()
                    + f"\n\n[This came in as a VOICE NOTE spoken in {spoken_lang}. "
                    f"Reply using the `speak` tool in the same language, plus a short text line.]"
                )
                came_by_voice = True
                await chan.send_text(f"-# 🎙️ heard: {heard[:300]}")
            elif not text:
                await chan.send_text(
                    "I got your voice note but couldn't make out any words. "
                    "Try speaking a bit longer, or type it."
                )
                return

        if not text and not msg.other_attachments:
            return

        if msg.other_attachments:
            names = ", ".join(msg.other_attachments)
            text = f"{text}\n\n(The user attached: {names} - these are on their phone, not the laptop.)"

        voice.SPOKE_CHANNELS.discard(key)   # fresh turn: no voice sent yet

        # The original showed Discord's "typing…" for the whole job; channels
        # that support it expose typing(), the rest skip it.
        typing_cm = chan.typing() if hasattr(chan, "typing") else contextlib.nullcontext()
        async with typing_cm:
            job = asyncio.create_task(self.brain.handle(key, text, chan))
            self.jobs[key] = job
            try:
                await job
            except asyncio.CancelledError:
                pass
            finally:
                self.jobs.pop(key, None)

        await self._maybe_speak(key, came_by_voice, chan)

    async def _listen(self, path, chan):
        """Transcribe an already-downloaded voice note. Returns (text, language)."""
        try:
            if not voice.available():
                await chan.send_text(
                    "Voice recognition isn't installed. Run `install.bat` again to add it, "
                    "or just type your command."
                )
                return "", ""
            return await asyncio.to_thread(voice.transcribe, path)
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    async def _maybe_speak(self, key, came_by_voice, chan):
        # The `speak` tool already sent audio this turn -> never send a second clip.
        # Checked by channel ID because a brain may hand tools a stale channel object.
        spoke_via_tool = key in voice.SPOKE_CHANNELS
        voice.SPOKE_CHANNELS.discard(key)
        if spoke_via_tool or getattr(chan, "spoke", False):
            return
        mode = self.voice_mode.get(key, CONFIG.voice_replies)
        if mode == "never" or mode == "off":
            return
        if mode in ("auto", "") and not came_by_voice:
            return
        # mode == 'always'/'on', or 'auto' with a voice input
        spoken = chan.last_spoken.strip()
        if not spoken:
            return
        clip = await voice.synthesize(spoken)
        if clip:
            await chan.send_file(clip, None)

    async def _command(self, text, key, chan):
        command = text.split()[0].lower()

        if command in ("/help", "/start"):
            await chan.send_text(HELP.format(name=CONFIG.assistant_name))
            return True

        if command == "/voice":
            arg = (text.split() + [""])[1].lower()
            if arg in ("on", "always"):
                self.voice_mode[key] = "always"
                await chan.send_text("Voice replies: ON - I'll speak every reply.")
            elif arg in ("off", "never"):
                self.voice_mode[key] = "never"
                await chan.send_text("Voice replies: OFF - text only.")
            elif arg in ("auto", ""):
                self.voice_mode[key] = "auto"
                await chan.send_text("Voice replies: AUTO - I'll speak when you talk to me by voice.")
            else:
                await chan.send_text("Use `/voice on`, `/voice off`, or `/voice auto`.")
            return True

        if command == "/new":
            self.brain.reset(key)
            await chan.send_text("Fresh start - I've forgotten the previous conversation.")
            return True

        if command == "/stop":
            job = self.jobs.get(key)
            if job and not job.done():
                job.cancel()
                await chan.send_text("Stopping.")
            else:
                await chan.send_text("Nothing running.")
            return True

        if command == "/shot":
            from .tools.screen import screenshot

            result = await asyncio.to_thread(screenshot)
            for path in result.get("images", []):
                await chan.send_file(path)
            return True

        if command == "/status":
            from .tools.system import system_status

            result = await asyncio.to_thread(system_status)
            await chan.send_text(f"```\n{result['text']}\n```")
            return True

        return False
