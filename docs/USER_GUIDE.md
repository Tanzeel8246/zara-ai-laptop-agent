# CodeHubb Assistant — User Guide

Welcome! CodeHubb Assistant is an AI assistant that lives on **your Windows
PC** and takes instructions from your phone through **WhatsApp, Telegram or
Discord**. You send a message; it works on your computer — opening apps,
managing files, browsing the web, taking screenshots — and replies in the
same chat, in your language.

This guide walks you through installing it, setting it up, and using it
well.

---

## 1. Installing

1. Download and run **`CodeHubbAssistant-Setup-<version>.exe`**.
2. The installer is per-user: no administrator password is needed, and it
   installs into your own user folder. If Windows SmartScreen warns about
   an unsigned app, choose **More info → Run anyway** (the installer is
   not yet code-signed; this is expected in the launch release).
3. At the end of the installer, leave **Launch CodeHubb Assistant** ticked.
   A tray icon appears near the clock, and the **setup wizard** opens
   automatically the first time.

> **Updating:** when a new version is published, the tray icon offers
> **Check for Updates**. Downloads are verified against a published SHA-256
> checksum before anything is applied, and **Restart to Update** applies
> the update for you.

## 2. The setup wizard, page by page

You can re-run the wizard at any time: right-click the tray icon →
**Setup Wizard…**. The pages are:

### Page 1 — Welcome
A summary of what the assistant is, plus general settings: the product
name and your assistant's **persona name**. Call it whatever you like —
"Zara", "Buddy", anything — it answers to that name.

### Page 2 — License
- **Development builds** say "licensing disabled" — nothing to do here.
- **Release builds** start a **14-day free trial** automatically
  (full features). To activate a purchased copy, paste your license key
  and press **Activate**. The panel shows your plan, expiry date and how
  many machines your key has used.
- The key is stored in the Windows keyring — never in a text file.
- Offline? The app keeps working within a 7-day grace window and
  re-validates when a connection (or the seller's activation server) is
  reachable.

Check your status at any time by sending `/license` in the chat, or from
the tray icon's status line.

### Page 3 — Brain (your AI account)
CodeHubb Assistant is **BYOK — Bring Your Own Key**. You choose the AI and
pay your provider directly; we never see or mark up your AI usage.

Options:

| Choice | What you need | Notes |
|---|---|---|
| **Claude subscription** | A Claude Pro/Max login (Claude Code) on this PC | No per-token API cost. Claude only. |
| **Anthropic API** | An API key from console.anthropic.com | Pay-per-token. |
| **OpenAI** | An API key from OpenAI | GPT models. |
| **Google Gemini** | An API key from Google AI Studio | Gemini models. |
| **DeepSeek** | An API key from DeepSeek | Text-strong; see the vision note below. |
| **Custom (OpenAI-compatible)** | A base URL + key | OpenRouter, Groq, Mistral, xAI, Together — or a **local** Ollama / LM Studio server for fully offline AI. |

Type or paste the key (it is saved to the **Windows keyring**, not into
`.env`), pick a model, and press **Test** — the wizard makes one tiny call
to confirm everything works before you continue.

> **Vision note:** the assistant "sees" via screenshots. If you pick a
> model that cannot process images (for example DeepSeek's text models),
> the wizard warns you clearly: screenshots will still be *sent to you*,
> but the assistant's decisions will be based on text only.

### Page 4 — Chats & messaging
Enable only the apps you want. Each can be skipped and set up later in
**Settings**.

**Discord**
1. At <https://discord.com/developers/applications>, create an application
   and add a **Bot**.
2. Turn **ON** the **Message Content Intent** (Privileged Gateway
   Intents) — without it the bot appears online but reads nothing.
3. Copy the bot **token** into the wizard, invite the bot to a server you
   share with it, and add **your Discord user ID** to the allowlist
   (Discord → Settings → Advanced → Developer Mode → right-click your
   name → Copy User ID).

**Telegram**
1. Message **@BotFather**, send `/newbot`, and follow the steps.
2. Paste the bot **token** into the wizard.
3. Add **your numeric Telegram user ID** to the allowlist (message
   @userinfobot to learn it).

**WhatsApp**
1. Tick WhatsApp and press **Start pairing** — a **QR code** appears.
2. On your phone: WhatsApp → Settings → **Linked devices** → Link a
   device → scan the QR.
3. Add **your own number** (international format, digits only, e.g.
   `923001234567`) to the allowlist.

> ⚠️ **Use a dedicated number for WhatsApp.** This route is an unofficial
> bridge and WhatsApp can restrict numbers that use it — never your main
> or business number. Read [WHATSAPP_DISCLAIMER.md](WHATSAPP_DISCLAIMER.md).
> You message the assistant from your own chat with that linked account
> ("Message yourself" / the linked device chat).

Only the IDs/numbers on the allowlist can command your PC. Everyone else
is ignored.

### Page 5 — Behaviour & safety
- **Confirm risky actions** — *recommended on* (the release default).
  Destructive or outward-facing actions (deleting files, shutting down,
  sending messages, clicking in the browser, editing the registry…) pause
  and ask you first. On Telegram you get real **Approve / Deny buttons**;
  on Discord and WhatsApp you reply to the confirmation message.
- **Voice replies** — `auto` (speak only when you sent a voice note),
  `always`, or `never`.
- **Auto-start** — start the assistant when you log in to Windows.

### Page 6 — Ready
A summary plus a short diagnostics preview. Tick **Start the agent when I
finish** and click Finish.

## 3. Talking to your assistant

Everything is plain language — text or voice notes, in English, Urdu, or
a mix. Examples:

- *"Take a screenshot and tell me what's on my screen."*
- *"Open Chrome, go to my email, and read me the latest invoice."*
- *"Find every PDF in Documents from this year and send me the largest."*
- *"What's eating my RAM? Close the worst offender."* *(asks first, if
  confirmations are on)*
- *"My downloads folder is a mess — sort it into folders by type."*
- *"Is my internet working? If not, fix the Wi-Fi."*

### Commands

| Command | What it does |
|---|---|
| `/help` (or `/start`) | Show help |
| `/status` | Instant system health (CPU, RAM, disk, battery) |
| `/shot` | Instant screenshot |
| `/new` | Forget the current conversation and start fresh |
| `/stop` | Cancel what the assistant is doing |
| `/queue` | Show the waiting/in-progress task list |
| `/cancel <id>` | Cancel a queued task |
| `/license` | Show license/trial status |
| `/voice on` · `off` · `auto` | Control voice replies |

## 4. Memory, the task queue, and the scheduler

**Memory.** Conversations survive restarts — the assistant picks up where
you left off. Tell it things worth keeping and it stores them as durable
facts:

- *"Remember: my office is in Sargodha and invoices go in D:\Accounts."*
- Later: *"Where do invoices go?"* — it recalls instead of asking again.
- *"What do you remember about me?"* lists stored facts; *"Forget the
  fact about …"* deletes one. Facts live in a local SQLite database in the
  app's `.runtime` folder — on your machine only.

**Task queue.** If you send a second instruction while the assistant is
busy, it is **queued**, not lost. `/queue` shows what's waiting; the reply
tells you its position; `/cancel 3` removes task 3. After a crash or
reboot, unfinished tasks resume from the queue.

**Scheduler.** Ask for recurring work in plain language:

- *"Every day at 8 AM, give me a morning briefing: weather, my calendar
  summary and the top headlines."*
- *"Every Friday at 6 PM, list the files I downloaded this week."*
- *"In 30 minutes, remind me to call Ahmed."*

Jobs are stored on the PC and fire at the laptop's local time. If the PC
was off at the scheduled time, the job runs **once** when the assistant
starts again — it never fires a burst of missed copies.

**Browser tools.** The assistant can drive a real (Chromium) browser —
open pages, read them, click and type — which is more reliable than
clicking pixels in web apps. It refuses to open local/private network
addresses, and clicks/typing ask for confirmation like other risky
actions.

## 5. Voice

Send a voice note and (in `auto` mode) the reply comes back as a voice
note in the same language. Two optional keys improve it (Settings →
Voice, or the helper scripts in a source install):

- **Groq key** (free tier available) — speech recognition in ~1–2 seconds
  with much better Urdu accuracy than the offline model.
- **ElevenLabs key** — realistic, emotional voices. Without it, free
  Microsoft neural voices are used.

Without any key, transcription runs locally on your CPU (a ~0.5 GB model
downloads once) — fully offline, just slower.

## 6. If something goes wrong — diagnostics

Right-click the tray icon → **Run Diagnostics**. You get a plain-text
report: version, configuration check results, which transports are
configured (booleans only — **never your keys or tokens**), license
state, and recent log tails. **Copy** it and send it with your support
message — it is designed to be safe to share.

The tray menu also has **Audit Log…**: a table of every tool call the
assistant made, what was allowed, confirmed or denied. Check it any time
you want to know exactly what your assistant did.

### Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| Discord bot is online but never replies | **Message Content Intent** is off. Enable it in the developer portal (Wizard page 4 instructions). |
| "You are not authorised" / messages ignored | Your ID/number is not on that transport's allowlist, or you pasted the bot's ID instead of your own. Re-check in Settings. |
| WhatsApp QR never appears or pairing fails | The sidecar needs Node.js 18+. The app normally resolves/downloads Node itself; check Diagnostics, then restart the agent. Re-pair from the wizard's Transports page. |
| WhatsApp stopped working days later | The linked session may have been logged out (or the number restricted — see the disclaimer). Re-pair with the QR; consider a fresh dedicated number. |
| Voice notes are ignored / very slow | First voice note downloads the offline speech model once. Add a free Groq key for ~1-second transcription. |
| Assistant stops mid-task | It hit the step limit (`MAX_ITERATIONS`). Send "continue", or raise the limit in Settings. |
| "Activation required" replies | Trial ended or the key was rejected. Run `/license`, then activate a valid key in the wizard's License page. |
| Update offered but install fails | Close the app fully (tray → Quit), then run the downloaded installer manually. Your settings and memory are kept. |
| Wizard page is cut off — the bottom (or the WhatsApp QR) is off-screen and cannot be reached | Fixed in **1.0.1**: every wizard page scrolls and the QR is sized to fit the page. Update to 1.0.1 or later. |
| Brain **Test connection** says "Setup incomplete: the 'litellm' package is not installed…" (older builds show a raw `ModuleNotFoundError: No module named 'litellm'`) | The app's Python packages were installed into a different environment than the one the app is running from. Close the wizard, open PowerShell **in the app folder**, activate the virtual environment (`.venv\Scripts\activate`), run `pip install -r requirements-gui.txt`, then start the app again **from that same window**. |
| Brain **Test connection** fails right after typing a model name | The Model field needs the **exact model ID** (e.g. `gemini-2.5-pro`), not a display name like "Gemini 3.8 Flash". Leave the prefilled value, or clear the field — an empty field uses the provider's default ID. |

## 7. FAQ

**Do I pay for the AI as well as the software?**
You pay your own AI provider under your own account (BYOK) — or nothing
extra if you use a Claude subscription you already have. CodeHubb
Assistant itself is a one-time/subscription software license; there is no
per-message charge from us.

**Where is my data?**
On your PC. Conversations, facts and schedules are in a local SQLite
database; keys and tokens are in the Windows keyring. What you ask the
assistant to do is processed by *your chosen AI provider* under *their*
privacy policy. See [PRIVACY.md](PRIVACY.md).

**Can someone else command my PC?**
No. Every transport checks the sender against your allowlist, and risky
actions ask for your confirmation. Keep your bot tokens secret — anyone
with a token *and* your allowlisted ID context should be treated as a
security incident; reset the token in that case.

**Does it work with the PC locked or asleep?**
The PC must be on, logged in and unlocked for screen/mouse tools. Chat
commands still queue while it sleeps and run when it wakes.

**Can I use it on a Mac?**
Not in v1.0 — Windows 10/11 only.
