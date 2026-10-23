# Changelog — CodeHubb Assistant

## 1.0.4 — 2026-10-23

- **The wizard now checks chat apps before letting you finish.** A
  switched-on Discord/Telegram group with an empty bot token or
  allowlist used to save silently — the agent then refused to start and
  the app bounced the user with a "Setup needed first" dialog. The
  Transports page now blocks in place, naming the app, what is missing
  and the remedy (fill it in, or untick the app). Leaving every app
  unticked is blocked too. The Settings dialog refuses to save the same
  state, with the same messages — one shared check
  (`transport_problems`) behind the wizard page, the dialog and
  `Settings.validate()`.
- **WhatsApp scanning tips in the pairing panel.** A short hint under
  the pairing status spells out the official-app route (Settings →
  Linked devices → Link a device, not the camera) and warns that
  WhatsApp may pause linking after several failed attempts.

## 1.0.3 — 2026-10-23

- **A crashed WhatsApp bridge now says why.** The wizard's pairing
  sidecar used to discard the bridge's output entirely, so a crash
  surfaced as a bare "The WhatsApp bridge stopped (exit code 1)". The
  output now goes to `.runtime/whatsapp/pairing.log`, and the pairing
  status carries the bridge's own last lines after that message. The
  most common cause — a leftover bridge still holding the port
  (`EADDRINUSE`) — leads with the plain-language remedy (end `node.exe`
  in Task Manager or restart the PC, then pair again).
- **The agent keeps the same evidence.** The supervisor already relayed
  sidecar output to its console; it now also persists it to
  `.runtime/whatsapp/sidecar.log`, drains the final lines before
  reporting a death, and re-prints the tail when the bridge exits
  unexpectedly (the logged-out vs crash distinction is unchanged).
- **Diagnostics shows both WhatsApp logs.** The support bundle gains
  the last 15 lines of `pairing.log` and `sidecar.log` whenever they
  exist, so a bridge failure can be diagnosed from the bundle alone.

## 1.0.2 — 2026-10-23

- **WhatsApp bridge packages install themselves.** On first pairing
  (wizard) and on the agent's first start, a missing `sidecar`
  `node_modules` is now installed automatically via `npm install` —
  nobody is sent to a terminal again. The wizard shows an
  "Installing WhatsApp bridge packages — first time only…" state with
  a working Stop; the agent logs the attempt loudly. The manual
  `npm install` command survives only as the fallback text when npm
  cannot be found or the automatic install fails (with the tail of
  npm's own output attached).

## 1.0.1 — 2026-10-23

First-run hotfix from the owner's Windows testing of 1.0.0.

- **Wizard pages scroll.** Page bodies are wrapped in scroll areas
  (Welcome, License, Brain, Chats, Behaviour, Ready), so on shorter
  windows nothing is cut off any more — most importantly the WhatsApp
  pairing QR, which is now also scaled to fit the page (max 320×320).
- **Brain "Test connection" explains a missing package.** If the
  Python environment the app runs from lacks `litellm` (or any other
  module), the test now says the setup is incomplete and gives the fix
  (activate `.venv`, `pip install -r requirements-gui.txt`, relaunch
  from the same window) instead of a raw `ModuleNotFoundError`.
  Genuine provider errors are truncated to ~300 characters.
- **Model field guidance.** The field shows the provider's exact
  default model ID as a placeholder plus a hint that an exact ID is
  required; an empty field falls back to the provider's default on
  apply/Test instead of saving a blank model.

## 1.0.0 — 2026-10-23

First commercial release: the personal "Zara" laptop agent rebuilt as
**CodeHubb Assistant** by MindCrafts AI / CodeHubb — a packaged Windows
product with a desktop app, licensing, and three chat transports.

### Phase 6 — Branding, documentation, release
- README rewritten for the product; full doc set
  ([User Guide](USER_GUIDE.md), [Seller Guide](SELLER_GUIDE.md),
  [EULA](EULA.md), [Privacy](PRIVACY.md),
  [WhatsApp Disclaimer](WHATSAPP_DISCLAIMER.md),
  [Security](SECURITY.md)); standalone product page in `website/`.
- Final wording pass: tool descriptions are transport-neutral
  (no more "in Discord" in the screenshot/speak tools); legacy launchers
  renamed `START.bat` / `STOP.bat`; proprietary LICENSE.
- Release verification from a clean checkout (see the phase report).

### Phase 5 — Packaging & auto-update
- Version single source of truth (`agent/version.py` = 1.0.0) enforced
  across the Inno define and Windows version resource by tests.
- PyInstaller onedir build + Inno Setup per-user installer +
  `packaging/build_windows.ps1` one-command release build.
- Node bootstrap for the WhatsApp sidecar (system / bundled portable /
  pinned, SHA-256-verified download).
- Auto-update: seller-hosted JSON feed, SHA-256-gated staged download,
  tray **Check for Updates** / **Restart to Update**, `apply_update.ps1`.
- **Test suite: 285 passing, 1 skipped.**

### Phase 4 — Licensing & payments
- Ed25519-signed license keys (`CA1.` format): plan, buyer email,
  machine limit, expiry or lifetime.
- 14-day trial with a tamper-evident seal; state machine
  (trial / active / grace 7 days / expired / revoked / invalid);
  licensing disabled entirely in development builds (no public key
  configured) — a build-time choice, not a bypass.
- Activation server (FastAPI + SQLite): activate/validate with machine
  limits and revocation, admin issue/revoke/list, optional SMTP key
  delivery.
- Lemon Squeezy webhook (HMAC-verified) issues and renews licenses;
  Paddle adapter implemented from public docs (sandbox confirmation
  pending — see `license_server/paddle.py`).
- Seller tools: `tools/issue_license.py` (keypair `--init` refuses to
  write inside the repo) and `tools/revoke_license.py`; real License
  panel in the wizard and Settings; `/license` command.

### Phase 3 — Tier-1 capabilities
- **Tools: 38 → 49** (memory ×3, browser ×5, scheduler ×3).
- Persistent memory in SQLite: conversations survive restarts (with
  interrupted-turn sanitising), durable facts via
  `remember_fact` / `recall_facts` / `forget_fact`.
- Unified task queue: busy no longer means "refused" — instructions
  queue, `/queue` lists them, `/cancel <id>` cancels, stranded tasks
  recover after a crash.
- Playwright browser tools (`browser_open/snapshot/click/type/close`)
  with an SSRF guard (loopback/private/link-local refused, redirect
  re-check).
- Scheduler: daily / weekly / interval / once jobs in laptop-local
  time; a job missed while the PC was off fires once on return.
- **Test suite: 183 passing, 1 skipped.**

### Phase 2 — Desktop shell
- PySide6 system-tray app: status, start/stop, settings, audit-log
  viewer, one-click diagnostics bundle (booleans only — never secrets).
- Six-page setup wizard: Welcome, License (placeholder at the time),
  Brain (provider picker with a live test call), Chats & messaging
  (including the WhatsApp QR pairing panel), Behaviour & safety,
  Ready.
- Safe `.env` writing (comments/order preserved); GUI secrets go to the
  keyring only. **Test suite: 129 passing.**

### Phase 1 — Transports
- Telegram transport: official Bot API, long polling, inline-button
  confirmations, voice notes in/out.
- WhatsApp transport (Route A): Baileys sidecar (Node.js), QR pairing,
  YES/NO + Urdu confirmation replies, group chats dropped, self-chat as
  the primary path.
- Discord carried over behind the shared transport interface; session
  keys namespaced per transport. **Test suite: 79 passing.**

### Phase 0 — Foundation
- Architecture seams: transport / brain / tools interfaces;
  transport-neutral session flow.
- One safety pipeline (classify → confirm → audit) wrapped around
  **both** brains — closing the hole where the subscription (SDK) brain
  skipped the security classifier.
- Multi-provider API brain via LiteLLM: Anthropic, OpenAI, Gemini,
  DeepSeek, custom OpenAI-compatible — with per-model capability flags
  (vision-less models degrade loudly, never silently).
- Secrets moved to the OS keyring with `.env` fallback; product/persona
  names in config; pytest scaffold (**50 passing**) + CI.

## Pre-1.0 — "Zara" prototype (August 2026)

The original personal project this product grew from:

- Windows laptop agent controlled from a private Discord bot; Claude
  brain via API loop or Claude subscription (Agent SDK); **38 tools**
  (screenshot/screen-reading, PowerShell, files, apps/windows,
  mouse/keyboard, WhatsApp GUI automation, Wi-Fi self-repair,
  system/power, spoken replies).
- Voice in via Groq Whisper or local faster-whisper; voice out via
  edge-tts or ElevenLabs; English + Urdu.
- Auto-start at login, a 3-minute watchdog, and power-cut Wi-Fi
  recovery.
