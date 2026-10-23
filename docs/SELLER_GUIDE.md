# CodeHubb Assistant — Seller Guide

Everything the seller (MindCrafts AI / CodeHubb) needs to ship, sell and
support v1.0. Buyer-facing material lives in [USER_GUIDE.md](USER_GUIDE.md);
server deployment detail lives in
[../license_server/README.md](../license_server/README.md) — this guide
recaps it and adds the release and sales checklists.

---

## 1. Release build checklist

Run on a **Windows** machine (PyInstaller cannot cross-compile):

- [ ] **Generate the seller keypair (once, ever):**
      ```powershell
      python tools/issue_license.py --init --private-key-out $HOME\seller-keys\license_private.pem
      ```
      `--init` refuses to write the private key anywhere inside the repo,
      and `.gitignore` covers `*.pem` / `license_private*` as a second
      line of defence. Back the private key up offline — if it leaks,
      anyone can mint keys; if it is lost, you cannot issue keys buyers'
      installs will accept.
- [ ] **Set the public key in the release configuration:** put the printed
      public key in the release build's `.env` as `LICENSE_PUBLIC_KEY`.
      This is what switches a build from "development" (licensing
      disabled) to "release" (14-day trial + activation on). The public
      key is not a secret; the private key never ships.
- [ ] **Set release values** in the release `.env`: `LICENSE_SERVER_URL`
      (your license server, §2), `UPDATE_FEED_URL` (§5), and confirm
      `CONFIRM_RISKY` defaults to **on** for distributed builds.
- [ ] **Bump the version if needed:** `agent/version.py` is the single
      source of truth — update the Inno `#define AppVersion` and
      `packaging/version_info.txt` to match (`tests/test_version.py` and
      `build_windows.ps1` both refuse to proceed when they disagree).
- [ ] **Build:**
      ```powershell
      .\packaging\build_windows.ps1            # full build incl. installer
      .\packaging\build_windows.ps1 -SkipInno  # onedir app only
      ```
      Output: `dist\CodeHubbAssistant` and the Inno installer
      (`CodeHubbAssistant-Setup-<version>.exe`).
- [ ] **Measure the bundle** and note it for the product page: check the
      size of `dist\CodeHubbAssistant` and of the final installer. The
      known heavy items are the PySide6 runtime and the staged Playwright
      Chromium. Trim levers, in order: prune unused Qt modules/plugins in
      `packaging/codehubb_assistant.spec`, exclude test/dev packages from
      the venv before building, and re-check whether both Chromium and
      headless-shell variants got staged. Expect a few hundred MB in
      v1.0 — say so honestly on the download page (see README
      "Status & limitations").
- [ ] **Smoke-test on a clean Windows VM/machine:** fresh install →
      wizard → trial starts → pair one transport → one command →
      `/license` shows the trial.
- [ ] Run the test suite before every release build:
      `python -m pytest` (expect 285+ passing, 1 skipped — the
      live-Chromium smoke test).

## 2. License server deployment (recap)

Full detail: [license_server/README.md](../license_server/README.md).

- [ ] Install on any small VPS / cheap Python host:
      `pip install -r license_server/requirements.txt`, run from the repo
      root with `uvicorn license_server.app:app --host 0.0.0.0 --port 8787`,
      behind Caddy/nginx with HTTPS.
- [ ] Environment: `LICENSE_PRIVATE_KEY_PATH` (or `LICENSE_PRIVATE_KEY`),
      a long random `LICENSE_ADMIN_TOKEN`, plus the payment variables in
      §3/§4 and SMTP if you want keys emailed automatically.
- [ ] Point buyers' builds at it with `LICENSE_SERVER_URL`.
- [ ] Sanity-check `GET /health` (liveness + whether issuing is
      configured) and one manual activation end-to-end.

## 3. Lemon Squeezy setup checklist

Lemon Squeezy is the merchant of record (cards, tax/VAT) and the
**verified-first** international route.

- [ ] Create products/variants in Lemon Squeezy — one variant per plan
      (Personal, Pro; a Lifetime variant if you run the launch deal).
- [ ] Map variants to plans in the license server's environment:
      `LS_VARIANT_MAP` — JSON of variant id →
      `{"plan": "personal"|"pro", "days": <period days>, "machines": <n>}`
      (e.g. Personal 35 days/1 machine, Pro 35 days/2 machines; renewals
      extend server-side expiry on `subscription_payment_success`).
- [ ] In LS → Settings → Webhooks, add a webhook to
      `https://<your-host>/webhooks/lemonsqueezy` with events
      `order_created`, `subscription_created`,
      `subscription_payment_success`; copy its signing secret into
      `LEMONSQUEEZY_WEBHOOK_SECRET`.
- [ ] Configure SMTP on the server if buyers should receive keys by
      email automatically; otherwise keys are retrievable via
      `GET /admin/licenses?email=`.
- [ ] Put the LS checkout links/overlay on the product page (§6).
- [ ] **Test order** with a Lemon Squeezy test-mode purchase: confirm the
      webhook fires, a license appears in the admin list, the emailed/
      retrieved key activates a clean install, and a renewal extends
      expiry.

## 4. Paddle sandbox verification checklist

The Paddle adapter (`license_server/paddle.py`) implements the signature
scheme from Paddle's public docs, and its test vectors are computed
against that implementation — **not** against Paddle. Before relying on
Paddle for real sales, confirm these four items against a live
**(sandbox)** Paddle dashboard:

1. [ ] The exact `Paddle-Signature` header format and signed-payload
       construction (`ts=<unix>;h1=<hex>` over `f"{ts}:" + raw_body`) for
       current Paddle Billing notification destinations.
2. [ ] Whether a timestamp tolerance should be enforced (the verifier
       checks the HMAC, with an optional caller-supplied max age).
3. [ ] The transaction payload fields used (`items[0].price.id`,
       `customer_id`) and the event name `transaction.completed`.
4. [ ] Buyer-email resolution: webhooks carry a `customer_id`, not an
       email — confirm the API base for sandbox
       (`https://sandbox-api.paddle.com`) vs live
       (`https://api.paddle.com`) and that your `PADDLE_API_KEY` has
       customer read scope. Without an API key, Paddle licenses are
       issued with an empty email and retrieved via the admin list.

Then: create the notification destination for `transaction.completed`,
set `PADDLE_WEBHOOK_SECRET` and `PADDLE_VARIANT_MAP`, and run a sandbox
transaction end-to-end.

## 5. Publishing an update

Buyers' apps check `UPDATE_FEED_URL` — a small static JSON you host
(anywhere static: your web host, GitHub Releases assets host, etc.).

1. Build the new installer (§1) and note its exact file name.
2. Compute its checksum:
   ```powershell
   Get-FileHash .\CodeHubbAssistant-Setup-<version>.exe -Algorithm SHA256
   ```
3. Upload the installer to your download location.
4. Publish/update the feed JSON:
   ```json
   {
     "version": "1.1.0",
     "url": "https://<your-host>/downloads/CodeHubbAssistant-Setup-1.1.0.exe",
     "sha256": "<hex from step 2>",
     "notes": "What changed, in one or two lines.",
     "mandatory": false
   }
   ```
   The tray only offers the update when `version` is newer than the
   installed one; the download is verified against `sha256` before the
   tray will stage it, and **Restart to Update** runs the shipped
   `apply_update.ps1`. Set `mandatory: true` only for critical fixes.
5. Keep the previous installer downloadable for rollback, and announce
   the release (the feed `notes` are what users see).

## 6. Manual sales flow (JazzCash / bank transfer)

For Pakistani buyers paying outside Lemon Squeezy/Paddle:

1. Buyer pays by JazzCash / bank transfer and sends proof.
2. Issue the key locally:
   ```powershell
   $env:LICENSE_PRIVATE_KEY_PATH = "$HOME\seller-keys\license_private.pem"
   python tools/issue_license.py --email buyer@example.com --plan pro --days 365 --machines 2
   # or --lifetime instead of --days for a lifetime key
   ```
3. Send the printed key to the buyer (WhatsApp/email). They paste it
   into the wizard's License page; the first activation registers their
   machine against the key's machine limit.
4. Keep a record (buyer, plan, key/license id) — the admin list on the
   server (`GET /admin/licenses?email=`) is the retrieval path when a
   buyer loses a key.
5. Refunds/abuse: revoke with `tools/revoke_license.py` (admin API, or
   it prints the SQL to run when no server is configured). Revocation
   takes effect at the buyer's next validation (immediately if their app
   is online and checking).

## 7. Suggested pricing (current)

From the approved plan — labelled **suggested launch pricing**; adjust
freely, the code has no prices baked in:

| Plan | Price | Machines | Notes |
|---|---|---|---|
| **Personal** | ~Rs 2,500–3,500 / **$12–15 per month** | 1 | All three transports, full features |
| **Pro** | ~Rs 6,000–8,000 / **$25–30 per month** | 2 | Priority support; official WhatsApp Cloud route when it ships |
| **Lifetime (launch offer)** | one-time, limited quantity | per plan | Early-buyer deal for first revenue + testimonials |

Remember the model when pricing: **BYOK** — the buyer's AI cost is
theirs (their subscription/API key), so the license price is pure
software value.

## 8. Support notes

- Ask buyers for the **diagnostics bundle** (tray → Run Diagnostics)
  with every problem report — it contains versions, configuration
  booleans and log tails, never keys or tokens.
- The buyer's **audit log** (tray → Audit Log…) answers most "it did
  something unexpected" reports: every tool call, allowed/confirmed/
  denied.
- Never ask a buyer for their license key, bot tokens or API keys.
