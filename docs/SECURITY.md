# Security — CodeHubb Assistant

CodeHubb Assistant gives an AI real control of a Windows PC, so it is
built around a strict safety model. This page describes that model as
shipped in v1.0.

## Who can command it: allowlists

Every transport (Discord, Telegram, WhatsApp) has an **allowlist** of
owner IDs/numbers. Messages from anyone else are ignored — not answered,
not queued. A bot token alone is not enough to command a machine: an
attacker would also need to send *from* an allowlisted account.

Keep bot tokens secret. If a token leaks, reset it with the provider
(Discord developer portal / @BotFather) and update Settings.

## Every tool call passes one pipeline

Both brains (subscription and API) execute tools through a single
pipeline in `agent/safety.py`:

1. **Classify** — each prospective tool call is risk-classified (safe /
   risky / destructive classes per tool and arguments).
2. **Confirm** — when `CONFIRM_RISKY` is on (the **release default**),
   risky actions pause and ask the owner: inline Approve/Deny buttons
   on Telegram, a reply-to-confirm flow on Discord and WhatsApp. Nothing
   proceeds on silence — a confirmation that is not approved does not
   run.
3. **Audit** — every tool call (allowed, confirmed, denied) is appended
   to the audit log, one JSON line per call, at
   `.runtime/audit.jsonl`. The tray app's **Audit Log…** window shows it
   as a table with text filtering. Reviewing it is the fastest way to
   answer "what did my assistant do?".

## Content is data, not orders

Text the assistant reads — web pages, documents, messages from other
people — is treated as **data**, never as instructions to obey. Planted
instructions ("ignore previous instructions and delete…") are surfaced,
not followed. The system prompt is transport-neutral and fixed; stored
facts are recalled as memory, not as commands.

## Browser tools: SSRF guard

The Playwright browser tools (`agent/tools/browser.py`):

- allow only `http`/`https` URLs;
- resolve the host **before** navigation and refuse loopback, private,
  link-local, reserved and multicast addresses — including cloud
  metadata addresses;
- re-check the final URL **after** redirects, so a public page cannot
  bounce the browser onto your LAN;
- disable downloads.

## Secrets handling

- API keys, bot tokens entered in the wizard, and the license key are
  stored in the **OS keyring** (Windows Credential Manager), via
  `agent/secrets.py` — never written to `.env` by the GUI.
- The seller's license-signing **private key never ships** in the
  product or the repo: releases embed only the Ed25519 **public** key,
  and the seller tooling refuses to write a private key inside the
  repository tree.
- License machine identity is a SHA-256 **hash** of machine identifiers;
  raw identifiers are never transmitted or stored.
- Payment webhooks on the license server verify HMAC signatures
  (Lemon Squeezy `X-Signature`; Paddle `Paddle-Signature`) before any
  license is issued.

## Updates

Update downloads are verified against the SHA-256 published in the
update feed before the tray will stage them; `apply_update.ps1` only
runs a verified installer.

## Known limits (honest list)

- A local app cannot be made tamper-proof against its own machine's
  administrator: the trial seal is tamper-*evident* (HMAC), not
  tamper-proof. Determined patching is out of scope for v1.0's threat
  model — paying customers are the audience, not adversaries.
- GUI automation is inherently powerful: if you disable confirmations
  (`CONFIRM_RISKY=false`), the assistant acts with your full user
  privileges. Leave confirmations on.
- The WhatsApp bridge is unofficial — see
  [WHATSAPP_DISCLAIMER.md](WHATSAPP_DISCLAIMER.md).

## Reporting a vulnerability

Email **security@codehubb.com** *(placeholder — replace with the seller's
monitored security address before launch)* with a description and
reproduction steps. Please do not open public issues for vulnerabilities
that could endanger users' machines.
