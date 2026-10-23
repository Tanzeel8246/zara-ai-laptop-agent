# CodeHubb Assistant

**Your own AI assistant for your Windows PC — controlled from your phone.**
By [MindCrafts AI](https://codehubb.com) / CodeHubb.

CodeHubb Assistant lives on your Windows computer and takes instructions from
the chat apps already on your phone — **WhatsApp, Telegram or Discord** (pick
one, or run several at once). Send a text or voice message from anywhere:
*"open Chrome and download the invoice"*, *"find every PDF about taxes and send
me the biggest"*, *"what's eating my RAM?"* — the assistant looks at your
screen, plans the steps, uses its tools, and replies in the same chat with the
result, in your language (English, Urdu and more).

You bring your own AI account (**BYOK** — Bring Your Own Key): a Claude
subscription, or an API key from Anthropic, OpenAI, Google (Gemini), DeepSeek,
or any OpenAI-compatible endpoint (OpenRouter, Groq, Mistral, xAI, Together,
local Ollama / LM Studio). There is no AI bill from us — you pay your provider
directly, or nothing extra at all if you use your Claude subscription.

> **Repository note:** this project is developed in the repository originally
> created for the prototype, so the repo keeps its original name
> (`zara-ai-laptop-agent`) for now. Clone URL:
> `https://github.com/Tanzeel8246/zara-ai-laptop-agent`

---

## What it does

- **Three chat transports, all optional** — WhatsApp (QR pairing, unofficial
  bridge — read [docs/WHATSAPP_DISCLAIMER.md](docs/WHATSAPP_DISCLAIMER.md)),
  Telegram (official Bot API, inline confirmation buttons) and Discord
  (official Bot API). They can run simultaneously and share one brain.
- **Your choice of brain** — Claude subscription mode (Claude Code login, no
  per-token API cost), or the API brain via LiteLLM: Anthropic, OpenAI,
  Gemini, DeepSeek, or a custom OpenAI-compatible endpoint. Models that can't
  see images are flagged honestly in the wizard — the assistant never fails
  silently on a screenshot.
- **49 tools** — screenshots and screen reading, PowerShell, files, apps and
  windows, mouse/keyboard, web browsing (Playwright), memory, scheduling,
  system health, Wi-Fi repair, voice replies, and more.
- **Persistent memory** — conversations, facts and preferences live in a
  local SQLite database (`.runtime/`), so the assistant remembers across
  restarts. A task queue runs instructions one at a time (`/queue`,
  `/cancel`), and a scheduler fires recurring jobs ("every morning at 9,
  check the downloads folder") even if the PC was off at the scheduled time.
- **Safety pipeline on every tool call** — allowlist-only access (only
  *your* IDs can command it), risk classification, tap-to-confirm for
  destructive actions, and an audit log of everything it did (viewable in
  the desktop app).
- **Desktop app** — a PySide6 system-tray app with a step-by-step setup
  wizard, settings, audit-log viewer, one-click diagnostics for support,
  and signed auto-updates.
- **Commercial licensing** — Ed25519-signed license keys, a 14-day trial,
  machine limits per plan, an optional activation server
  ([license_server/](license_server/README.md)), and Lemon Squeezy / Paddle /
  manual payment routes for sellers.

## Quick start (end users)

1. Run the **installer** (`CodeHubbAssistant-Setup-<version>.exe`) — it is a
   per-user install; no admin rights and no Python/Node setup needed.
2. The **setup wizard** opens on first run:
   - **License** — start the free trial or paste a purchased key.
   - **Brain** — choose your Claude subscription or paste an API key
     (keys go to the Windows keyring, never into plain-text files), then
     press *Test* to verify with one tiny call.
   - **Chats & messaging** — enable Discord, Telegram and/or WhatsApp
     (WhatsApp shows a QR code to scan with your phone).
   - **Behaviour & safety** — confirmations for risky actions (on by
     default in release builds) and auto-start.
3. Message your assistant from your phone and send `/help`.

Full walkthrough: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

## Developers — run from source

Requirements: Windows 10/11, Python 3.10+, Node.js 18+ (only for the
WhatsApp sidecar), Git.

```bash
git clone https://github.com/Tanzeel8246/zara-ai-laptop-agent
cd zara-ai-laptop-agent

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-gui.txt        # includes requirements.txt + PySide6
playwright install chromium                # one-time, for the browser tools

cd sidecar && npm install && cd ..         # WhatsApp bridge dependencies

copy .env.example .env                     # then fill in your tokens/IDs
python run_app.py                          # tray app + setup wizard
python run.py                              # headless agent only (no GUI)
```

- `run_app.py` starts the tray app; the agent itself runs as the same
  executable relaunched with `--run-agent` in packaged builds.
- Development builds (no `LICENSE_PUBLIC_KEY` set) run with licensing
  disabled. See [docs/SELLER_GUIDE.md](docs/SELLER_GUIDE.md) for the release
  build checklist.

## Configuration

Everything is configured through the wizard/settings window, which writes
`.env` and stores secrets in the OS keyring. The main knobs (see
`.env.example` for the annotated full list):

| Setting | Meaning |
|---|---|
| `TRANSPORTS` | `discord,telegram,whatsapp` — any subset |
| `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USER_IDS` | Discord bot + who may command it |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS` | Telegram bot (via @BotFather) + allowlist |
| `WHATSAPP_ALLOWED_NUMBERS` | WhatsApp allowlist (QR pairing, no token) |
| `BRAIN` | `subscription` · `api` · `auto` |
| `API_PROVIDER` | `anthropic` · `openai` · `gemini` · `deepseek` · `custom` |
| `CONFIRM_RISKY` | Ask before destructive actions (release default: on) |
| `ASSISTANT_NAME` | Your assistant's persona name — name it anything |
| `LICENSE_PUBLIC_KEY`, `LICENSE_SERVER_URL` | Licensing (release builds) |
| `UPDATE_FEED_URL` | Auto-update feed (release builds) |

## Safety model (summary)

This software gives an AI real control of a PC, so the design is strict:

- **Allowlists everywhere** — messages from anyone but the owner's IDs are
  ignored on every transport.
- **Confirmations** — risky tool calls (delete, shutdown, registry, sending
  messages, browser clicks…) pause for the owner's approval; on Telegram
  these are real inline buttons.
- **Audit log** — every tool call is appended to `.runtime/audit.jsonl`
  and viewable from the tray app.
- **Content is data, not orders** — instructions planted in web pages,
  documents or chats are not obeyed.
- **Browser SSRF guard** — the browser tools refuse local/private network
  addresses.
- **Secrets in the keyring** — API keys and license keys are stored via the
  OS keyring, not in `.env`.

Details: **[docs/SECURITY.md](docs/SECURITY.md)** ·
Privacy: **[docs/PRIVACY.md](docs/PRIVACY.md)** ·
Terms: **[docs/EULA.md](docs/EULA.md)**

## Project layout

```
agent/            the agent core
  transport/      discord / telegram / whatsapp transports
  brain/          subscription (SDK) + API (LiteLLM) brains, provider registry
  tools/          the 49 tools (screen, shell, files, browser, memory, …)
  licensing.py    Ed25519 license keys, trial, activation client
  safety.py       classify → confirm → audit pipeline
  queue.py        persistent task queue          store.py   SQLite store
  scheduler.py    recurring jobs                 updater.py auto-update
desktop/          PySide6 tray app, setup wizard, settings, audit viewer
license_server/   seller-hosted activation + payment-webhook server (FastAPI)
sidecar/          WhatsApp bridge (Node.js, Baileys)
packaging/        PyInstaller spec, Inno Setup script, build_windows.ps1
tools/            seller tools (issue/revoke license keys)
docs/             user guide, seller guide, EULA, privacy, security
website/          standalone product page (single HTML file)
```

## Development & testing

```bash
pip install -r requirements-dev.txt
python -m pytest          # full suite (GUI tests run headless/offscreen)
```

The version lives in `agent/version.py` (single source of truth); the
packaging files are kept in step by `tests/test_version.py`.

## Status & limitations (honest list)

- **Windows only.** macOS/Linux are not supported in v1.0.
- **First live checks happen on a real Windows machine:** the WhatsApp QR
  pairing and the full installer build (`packaging/build_windows.ps1`) are
  exercised there — the sandbox used for development cannot reach WhatsApp's
  servers or run a Windows build.
- **Paddle webhooks** are implemented from Paddle's public docs; the four
  confirmation items in `license_server/paddle.py` must be checked once
  against a live (sandbox) Paddle dashboard before relying on them.
  Lemon Squeezy is the verified-first route.
- **Bundle size:** the installer (Python runtime + PySide6 + a staged
  Chromium) is a few hundred MB. A local speech model (~0.5 GB) downloads
  on first voice use unless a Groq key is configured.
- **WhatsApp Route A is unofficial** and can get a number restricted —
  use a dedicated number. An official Cloud API route is planned as a
  future Pro feature.

## License

Proprietary — © MindCrafts AI / CodeHubb, all rights reserved.
See [LICENSE](LICENSE) and [docs/EULA.md](docs/EULA.md).
