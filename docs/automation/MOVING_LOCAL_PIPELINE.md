# Moving the local automation pipeline to a new machine

This is the runbook for handing off the machine-dependent half of this repo's
automation — the Playwright-driven Braze build/QA pipeline, the Asana webhook
server, and their supporting launchd services — from one person's Mac to
another's. It was written for the Jordan → Jake handoff (2026-09-24), but
applies to any future move.

This doc is only about the six `com.havenly.*` launchd services that
currently run on Jordan's Mac, all six of which move.

## What's moving, in one sentence each

| Service | What it does |
|---|---|
| `com.havenly.webhook-server` | FastAPI server (port 8765) that receives the Asana webhook and dispatches Playwright builds + auto-QA |
| `com.havenly.ngrok-webhook` | Tunnels port 8765 to a public URL so Asana can reach it |
| `com.havenly.webhook-ensure-registered` | Re-points the Asana webhook at ngrok's current URL (runs at login + hourly, since the free ngrok URL changes on restart) |
| `com.havenly.poll-ready-tasks` | 15-min safety-net poller for tasks the webhook missed |
| `com.havenly.braze-session-refresh` | Daily 8am: logs the Braze bot account into the dashboard via Playwright, saves the session cookie |
| `com.havenly.notify-lee-completions` | Slack alert when Lee marks a task complete herself |

The auto-QA process (`qa_designed_email.py`) is **not** a separate system —
it's imported directly by `webhook_server.py` and runs in the same process,
same Playwright session, same machine. Moving the webhook server moves QA
with it.

## Why this can't just be "copy the repo"

Two things are coupled to a specific person's identity, not to the code:

1. **The Braze dashboard bot login.** `scripts/braze_automation/login.py`
   drives the real Braze *dashboard UI* via Playwright — there's no REST API
   for campaign composition, hence Monaco-editor scraping etc. This needs a
   Braze user account with dashboard credentials in `.env`
   (`BRAZE_DASHBOARD_EMAIL` / `BRAZE_DASHBOARD_PASSWORD`).
2. **The 2FA fetch.** The account currently configured uses **email-based
   2FA** (Braze emails a code to the account's inbox on login), and
   `handle_email_mfa()` in `login.py` fetches that code automatically via the
   Gmail API, using a Google OAuth refresh token
   (`GOOGLE_DRIVE_REFRESH_TOKEN`) minted against whoever's Google identity
   granted consent. Today that's Jordan's `@havenly.com` Google account. If
   that account is ever deactivated, this breaks outright, independent of
   the Braze password.

So a real handoff needs: a **new Braze bot account** at Jake's address, and
**Jake's own Google OAuth consent** (with Gmail read scope) so the automation
can read 2FA codes from *his* inbox. This is exactly the "identity-coupling
risk" flagged in `CLAUDE.md` under "Braze Dashboard login / MFA".

## Prerequisites (per the ask — already true for Jake)

- [x] Repo cloned
- [x] `.env` present (see below for what still needs adding/changing in it)
- [x] GitLab admin access

---

## Step 1 — Create the new Braze bot account

1. In Braze (an existing admin), create a new dashboard user at **an address
   under Jake's own `@havenly.com` mailbox**. The current bot account is
   `jordan.rubenstein+brazebot@havenly.com` — a `+brazebot` alias off
   Jordan's own address, not a separate mailbox. Jake can mirror that
   convention (e.g. `jake.lastname+brazebot@havenly.com`) for the new
   account. **The alias is cosmetic only — it does not create a separate
   Google identity.** A `+alias` still delivers to, and is still owned by,
   the same underlying Gmail account, so the Google OAuth consent in Step 2
   is tied to Jake's whole Google account either way, alias or not. This is
   exactly the coupling risk being fixed by this move — using an alias again
   doesn't change that dependency, it's just a naming convention for
   recognizing the bot's mail in an inbox.

   Give the new user whatever role level the current bot account has (check
   Braze Settings → Users for the existing one, or ask whoever owns Braze
   user management).
2. Set a password for it and set up 2FA. Braze will offer either:
   - **Email 2FA** (matches today's setup exactly — no code changes needed) — just note it and move to Step 2.
   - **Authenticator/TOTP 2FA** — if this is offered/preferred instead, grab
     the base32 secret during setup (`docs/... README.md` → "Path 1 — TOTP"
     below has three ways to extract it) and skip Step 2 entirely; go
     straight to Step 3 with `BRAZE_TOTP_SECRET` instead of the Google OAuth
     vars.
3. Note the REST API keys are **workspace-level, not user-level** —
   `BRAZE_API_KEY_*` / `BRAZE_API_KEY_MEDIA_*` in Jake's existing `.env`
   don't need to change. Only the *dashboard login* is per-user.

## Step 2 — Google OAuth consent for Jake's own Gmail (skip if using TOTP)

Only needed if the new Braze bot account uses email-based 2FA.

The refresh token this needs is the **same one** used for Google Drive
access elsewhere in the repo (`scripts/utils/drive_client.py`), generated by
`scripts/setup_google_drive_auth.py` — but that script currently only
requests `drive.readonly` scope, which **cannot** read the 2FA email. Before
running it:

1. Open `scripts/setup_google_drive_auth.py` and confirm/update its `SCOPES`
   list to include Gmail read access:
   ```python
   SCOPES = [
       "https://www.googleapis.com/auth/drive.readonly",
       "https://www.googleapis.com/auth/gmail.readonly",
   ]
   ```
   (If this has already been fixed by the time you're reading this, skip the
   edit.)
2. The OAuth **client ID/secret** (`GOOGLE_OAUTH_CLIENT_ID` /
   `GOOGLE_OAUTH_CLIENT_SECRET`) is an app registration in Google Cloud
   Console, not a per-user credential — Jake can reuse the existing values
   already in his `.env` as long as the app is approved for the
   `havenly.com` Workspace (it should be, since both accounts are on the
   same Workspace).
3. Run the script as **Jake**, signed into **his own base `@havenly.com`
   Google account** when the consent screen opens (the same account behind
   whichever `+alias` the new bot address uses, per the Step 1 note — the
   alias itself isn't a separate account to sign into):
   ```bash
   uv run python scripts/setup_google_drive_auth.py
   ```
   This mints a fresh `GOOGLE_DRIVE_REFRESH_TOKEN` scoped to Jake's Gmail —
   replace the value in `.env` with this new token. **Do not reuse Jordan's
   token** — it's scoped to Jordan's inbox, which is where the new bot
   account's 2FA emails will *not* be landing.

## Step 3 — Local environment

```bash
# Playwright browser binary (Chromium) — not installed by `uv sync` alone
uv sync
uv run playwright install chromium

# Confirm uv's absolute path — the plists below need it, and it's often
# different per machine (Homebrew vs .local/bin vs pyenv, etc.)
which uv
```

## Step 4 — `.env` changes

Only these keys are identity-coupled and need new values. Everything else in
Jake's existing `.env` (all `BRAZE_API_KEY_*`, `KLAVIYO_API_KEY_*`,
`ASANA_ACCESS_TOKEN`, `SNOWFLAKE_*`, `SLACK_WEBHOOK_URL_TEAM_LIFECYCLE`,
`FIGMA_ACCESS_TOKEN`, `AIR_*`, `ANTHROPIC_API_KEY`, etc.) is workspace-level
and doesn't need to change.

| Key | New value |
|---|---|
| `BRAZE_DASHBOARD_EMAIL` | Jake's new bot account email (Step 1) |
| `BRAZE_DASHBOARD_PASSWORD` | Jake's new bot account password (Step 1) |
| `BRAZE_TOTP_SECRET` | Only if the new account uses TOTP 2FA (Step 1) — otherwise leave unset |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | Jake's freshly-minted token (Step 2) — only if using email 2FA |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Can stay as-is (shared app registration) — confirm they're already present |

Also confirm `BRAZE_DASHBOARD_URL` matches the org's dashboard instance
(currently `https://dashboard-07.braze.com`) — this shouldn't change, just
worth a sanity check.

Do **not** copy `scripts/braze_automation/.session_state.json` or
`.session_state_klaviyo_TI.json` from Jordan's machine — those are Playwright
session cookies for the *old* bot account and are gitignored for exactly this
reason. Let the pipeline regenerate them fresh (Step 7 does this).

## Step 5 — ngrok

The tunnel is on ngrok's **free tier with no reserved/static domain** — the
plist just runs `ngrok http 8765`, and `webhook-ensure-registered` handles
re-pointing the Asana webhook whenever the resulting URL changes (that's the
whole reason that service exists and runs hourly). Jake doesn't need to buy
or configure a static domain — a free account is enough:

```bash
brew install ngrok/ngrok/ngrok
ngrok config add-authtoken <JAKE_OWN_NGROK_TOKEN>   # from https://dashboard.ngrok.com, free account
```

## Step 6 — Install the launchd services

The six plists on Jordan's Mac hardcode `/Users/jordan.rubenstein/...` paths
in `ProgramArguments` and `WorkingDirectory` — they cannot be copied as-is.
Use the generator script instead, which fills in Jake's own home directory,
repo path, and `uv` path automatically:

```bash
bash scripts/braze_automation/setup_launchd_agents.sh
```

This writes the six `com.havenly.*.plist` files to
`~/Library/LaunchAgents/` and loads them via `launchctl`. See the script's
own header comment for what it does step by step, and re-run it any time
(e.g. after moving the repo to a new path) to regenerate and reload.

Verify all six are running:

```bash
launchctl list | grep havenly
curl -sf http://localhost:8765/health
```

## Step 7 — First login + webhook registration

1. Let `braze-session-refresh` run once to establish a fresh session under
   the new bot account (or trigger it manually rather than waiting for 8am):
   ```bash
   uv run python scripts/braze_automation/refresh_session.py
   ```
   Watch for the MFA path it takes — confirms Step 1/2 actually worked.
2. Register the Asana webhook against the new ngrok URL:
   ```bash
   curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"
   uv run python scripts/braze_automation/register_webhook.py register \
     --url <that-url>/webhook/asana
   ```
   (`webhook-ensure-registered` will also do this automatically within an
   hour of the services starting, so this step is just to confirm sooner.)

## Step 8 — Verification checklist

- [ ] `curl http://localhost:8765/health` responds, `queue_depth: 0`
- [ ] `launchctl list | grep havenly` shows all 6 services with no crash-loop PIDs
- [ ] `refresh_session.py` completes without an MFA timeout
- [ ] A test Asana task flipped to Ready to Code triggers a real build (watch `/tmp/webhook-server.log`)
- [ ] `qa_designed_email.py` runs against that same build (same log)
- [ ] `uv run python scripts/braze_automation/register_webhook.py list` shows exactly one active webhook pointed at the current ngrok URL

## Step 9 — Decommission Jordan's copy

Once Jake's pipeline is confirmed working end-to-end, **stop the services on
Jordan's Mac** so the two machines don't race each other building the same
Asana tasks:

```bash
for svc in webhook-server ngrok-webhook webhook-ensure-registered poll-ready-tasks braze-session-refresh notify-lee-completions; do
  launchctl bootout "gui/$(id -u)/com.havenly.$svc"
done
```

Also deactivate/delete the old Braze bot account
(`jordan.rubenstein+brazebot@havenly.com`) once Jake's account is confirmed
working, and revoke the old Google OAuth grant (Google Account → Security →
Third-party access) so a stale refresh token isn't sitting around with
standing Gmail read access.
