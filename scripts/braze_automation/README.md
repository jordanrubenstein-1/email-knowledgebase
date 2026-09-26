# Braze Dashboard Automation

Playwright-based automation for Braze dashboard operations.

## Status: POC

This is a proof-of-concept for automating Braze campaign creation. Currently supports:

- Login to Braze dashboard
- Navigate to campaign creation
- Fill campaign fields (name, subject, preheader)
- Save as draft
- Screenshot capture for verification

## Setup

### 1. Install Dependencies

```bash
# Playwright is already available via MCP plugin, but for standalone use:
uv add playwright
uv run playwright install chromium
```

### 2. Configure Environment

**Option A: Gmail / Google sign-in (recommended if you use “Sign in with Google”)**

If you log into Braze with your Gmail account, you don’t need email/password in `.env`. Set only the dashboard URL:

```bash
# Braze Dashboard (required)
BRAZE_DASHBOARD_URL=https://dashboard-07.braze.com
# Leave BRAZE_DASHBOARD_EMAIL and BRAZE_DASHBOARD_PASSWORD unset
```

On the first run, the script opens a browser, goes to Braze, and waits for you to **log in with Google** in that window. Once you reach the dashboard, the script saves your session and continues. Later runs reuse the saved session and skip login.

**Important:** For Gmail login, run **without** `--headless` the first time so you can see the browser and complete sign-in (e.g. `uv run python scripts/braze_automation/create_campaign.py --name "Test" --subject "Test" --preheader "Test" --no-dry-run`). After the session is saved, later runs can use `--headless` if you like.

**Option B: Email + password**

Add to your `.env` file:

```bash
# Braze Dashboard Credentials
BRAZE_DASHBOARD_URL=https://dashboard-07.braze.com
BRAZE_DASHBOARD_EMAIL=your-email@example.com
BRAZE_DASHBOARD_PASSWORD=your-password

# TOTP Secret for MFA (if 2FA is enabled)
BRAZE_TOTP_SECRET=your-base32-secret
```

### 2b. Setting up TOTP for MFA

If your Braze account has 2FA enabled, you need to extract the TOTP secret:

**Option A: During 2FA Setup**
1. Go to Braze Settings > Security > Two-Factor Authentication
2. When shown the QR code, look for "Can't scan? Enter this text code" or similar
3. Copy the base32 secret string (e.g., `JBSWY3DPEHPK3PXP`)

**Option B: From Existing Authenticator App**
- Some apps (like Authy) let you export/view the secret
- Or disable and re-enable 2FA to get a new secret

**Option C: Decode the QR Code**
1. Screenshot the QR code during setup
2. Decode it (online tools or `zbarimg` CLI)
3. Extract the `secret` parameter from the URL:
   ```
   otpauth://totp/Braze:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Braze
   ```
   The secret is `JBSWY3DPEHPK3PXP`

**Note:** If your account uses SSO/SAML, you may need to use session storage after manual login. See "Session Persistence" below.

### 3. Test Login

```bash
# Quick test - just login and take screenshot
uv run python -c "
import asyncio
from playwright.async_api import async_playwright
from scripts.braze_automation.login import login

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await login(page)
        await page.screenshot(path='braze_login_test.png')
        await browser.close()
        print('Login successful! Screenshot saved.')

asyncio.run(test())
"
```

## Usage

### Create a Draft Campaign

```bash
# Dry run (default) - won't save, just screenshots
uv run python scripts/braze_automation/create_campaign.py \
  --name "Test Campaign $(date +%s)" \
  --subject "Test Subject Line" \
  --preheader "Test preheader text"

# Actually save the draft
uv run python scripts/braze_automation/create_campaign.py \
  --name "Test Campaign $(date +%s)" \
  --subject "Test Subject Line" \
  --preheader "Test preheader text" \
  --no-dry-run

# With HTML body
uv run python scripts/braze_automation/create_campaign.py \
  --name "Test Campaign" \
  --subject "Test Subject" \
  --preheader "Preview text" \
  --body path/to/email.html \
  --no-dry-run

# Headless mode
uv run python scripts/braze_automation/create_campaign.py \
  --name "Test Campaign" \
  --subject "Test Subject" \
  --preheader "Preview" \
  --headless
```

### CLI Options

| Option | Description |
|--------|-------------|
| `--name` | Campaign name (required) |
| `--subject` | Email subject line (required) |
| `--preheader` | Email preheader/preview text |
| `--body` | Path to HTML file for email body |
| `--brand` | Brand code to select workspace (HAV, BUR, ID, STF, CZ, TI) |
| `--dry-run` | Don't save (default: True) |
| `--no-dry-run` | Actually save the campaign |
| `--screenshot` | Custom screenshot path |
| `--headless` | Run browser in headless mode |
| `-v, --verbose` | Enable debug logging |

### Brand/Workspace Mapping

| Code | Braze Workspace |
|------|-----------------|
| HAV | havenly |
| BUR | Burrow - Production |
| ID | Interior Define |
| STF | St Frank |
| CZ | The Citizenry |
| TI | The Inside |

### Programmatic Usage

```python
import asyncio
from playwright.async_api import async_playwright
from scripts.braze_automation import login, create_draft_campaign

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Login
        await login(page)

        # Create campaign
        result = await create_draft_campaign(
            page=page,
            name="My Campaign",
            subject="Subject Line",
            preheader="Preview text",
            dry_run=True  # Set to False to actually save
        )

        print(f"Success: {result['success']}")
        print(f"Screenshot: {result['screenshot']}")

        await browser.close()

asyncio.run(main())
```

## MFA Handling

The automation handles TOTP-based MFA automatically when `BRAZE_TOTP_SECRET` is configured.

### How It Works

1. Login detects MFA prompt (looks for "verification code", "2FA", etc.)
2. Generates a 6-digit TOTP code using `pyotp`
3. Fills and submits the code automatically
4. Continues to dashboard

### Session persistence (Gmail / Google / SSO)

If you sign in with **Gmail/Google** (or SSO), the script uses session persistence automatically:

1. First run: browser opens → log in with Google in the window → script waits until you reach the dashboard, then saves the session and continues.
2. Later runs: script loads the saved session and skips login (until the session expires).

Session is saved to `scripts/braze_automation/.session_state.json` (gitignored). To force a fresh login, delete that file.

### Fallback: Manual session save (programmatic)

For other SSO setups you can save session state after manual login in code:

```python
from scripts.braze_automation.login import save_session, create_context_with_session

# After manual login, save session:
await save_session(context)

# On subsequent runs, restore session:
context = await create_context_with_session(browser)
```

Session is saved to `scripts/braze_automation/.session_state.json` (gitignored).

**Note:** Session tokens typically expire after 7-30 days depending on Braze settings.

## Safety Features

1. **Dry Run Default**: All operations default to dry-run mode
2. **No Launch/Send**: Code never clicks "Launch" or "Send" buttons
3. **Screenshots**: Every operation captures screenshots for verification
4. **Logging**: All actions logged for debugging

## Troubleshooting

### Login Fails

1. Check credentials in `.env`
2. Verify dashboard URL matches your Braze instance
3. For SSO: Login manually once, save session
4. Check for MFA prompts

### Selectors Not Working

Braze UI may vary by version. The selector utilities try multiple strategies:

1. Label association
2. Role + name
3. Placeholder text
4. Parent/sibling traversal
5. Data attributes

If elements aren't found, run with `--verbose` to see which strategies are tried.

### Element Not Found

Run without `--headless` to watch the browser and identify the issue. Take note of:

- Actual element labels/text
- Modal dialogs that may block interaction
- Loading states

## Architecture

```
scripts/braze_automation/
├── __init__.py           # Module exports
├── login.py              # Authentication handling
├── create_campaign.py    # Campaign creation workflow
├── element_utils.py      # Selector utilities with fallbacks
└── README.md             # This file
```

## Future Enhancements

- [ ] MCP server integration
- [ ] Campaign editing (not just creation)
- [ ] Template selection
- [ ] Segment targeting
- [ ] A/B variant setup
- [ ] Schedule configuration
