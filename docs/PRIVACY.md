# Privacy — CodeHubb Assistant

Short version: **CodeHubb Assistant is local-first. There is no
telemetry, no analytics, no advertising, and no account with us required
to use the software.** This page says exactly what data goes where.

## What stays on your computer

Everything the assistant remembers lives on **your** machine:

- **Conversations, facts, tasks and schedules** — a local SQLite
  database in the app's `.runtime` folder (`memory.db`).
- **Audit log** — one JSON line per tool call, in `.runtime/audit.jsonl`.
- **Screenshots and voice notes it creates while working** — local files
  under `.runtime/` (sent to your chat only when a tool result includes
  them or you ask).
- **Settings** — `.env` in the install folder plus the app's settings
  store.

Deleting the app and its `.runtime` folder deletes all of this. Nothing
of it is copied to the Seller.

## What is sent to your AI provider

The assistant works by sending your instructions — and, when a task
needs them, screenshots, tool outputs and file contents it reads — to
**the AI provider you chose** (your Claude subscription, or Anthropic /
OpenAI / Google / DeepSeek / a custom endpoint, under **your** account
and that provider's privacy policy). The Seller is not in this path and
receives none of it.

Speech works the same way: if you configure a Groq or ElevenLabs key,
voice audio/text goes to that provider under your account. With no keys
configured, transcription runs locally on your CPU.

## What travels over your chat transport

Your messages, the assistant's replies, screenshots and files it sends
you pass through the transport you enabled (Discord, Telegram, or the
WhatsApp bridge) under those services' terms — the same as if you were
chatting there yourself. Only IDs/numbers on your allowlist can command
the assistant, but the transport provider can see message content as it
normally would.

## What the license server sees

Only what licensing needs:

- your **license key** and **plan**;
- a **one-way hash** of your machine's identity (used to enforce the
  machine limit — raw hardware identifiers are never sent or stored);
- your **email address**, provided at purchase, so your key can be
  issued, delivered and recovered.

Payment details (card numbers etc.) are handled by the payment provider
(Lemon Squeezy or Paddle) as merchant of record — the Seller and the
license server never see them. The license server does **not** receive
your conversations, files, screenshots or AI keys.

## Secrets storage

API keys (AI providers, Groq, ElevenLabs), bot tokens and your license
key are stored in the **operating system keyring** (Windows Credential
Manager via the `keyring` library) — not in plain-text files. The
`.env` file holds non-secret configuration and bot/transport settings;
treat it as sensitive anyway, because allowlists and tokens for the
headless (source) configuration live there in development setups.

## Updates

If an update feed is configured, the app fetches a small JSON file
(version, download URL, checksum) from the Seller's host. This is a
plain download — it carries no identifier about you beyond what any web
request carries (such as your IP address, visible to the host).

## Contact

Privacy questions: use the support email on the product page.
