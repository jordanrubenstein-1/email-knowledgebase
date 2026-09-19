"""
Braze Dashboard authentication.

Handles login flow and session management, including TOTP-based MFA and
email-based 2FA (auto-fetched from Gmail via the Google OAuth refresh token).
"""

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pyotp
from playwright.async_api import Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Braze dashboard configuration
BRAZE_DASHBOARD_URL = os.getenv("BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com")
BRAZE_DASHBOARD_EMAIL = os.getenv("BRAZE_DASHBOARD_EMAIL")
BRAZE_DASHBOARD_PASSWORD = os.getenv("BRAZE_DASHBOARD_PASSWORD")
BRAZE_TOTP_SECRET = os.getenv("BRAZE_TOTP_SECRET")

# Session storage path for persistent login
SESSION_STORAGE_PATH = Path(__file__).parent / ".session_state.json"


def _is_on_dashboard(url: str) -> bool:
    """True if we're on a Braze dashboard page (not on the sign-in page)."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    # Explicitly not logged in if on sign-in / login / MFA pages
    if any(s in path for s in ("/sign_in", "/login", "/sso", "/two-factor", "/two_factor", "/mfa", "/verify")):
        return False
    # Logged in if we're on the dashboard host and past the root
    dashboard_host = urlparse(BRAZE_DASHBOARD_URL).hostname or ""
    if dashboard_host and parsed.hostname == dashboard_host and path not in ("/", ""):
        return True
    # Legacy fallback: /dashboard or /home
    return path.startswith("/dashboard") or path.startswith("/home")


async def handle_mfa(page: Page, totp_secret: Optional[str] = None) -> bool:
    """
    Handle TOTP-based MFA challenge.

    Args:
        page: Playwright page object
        totp_secret: Base32-encoded TOTP secret (uses env var if not provided)

    Returns:
        True if MFA completed successfully

    Raises:
        ValueError: If TOTP secret not available
        Exception: If MFA verification fails
    """
    secret = totp_secret or BRAZE_TOTP_SECRET

    if not secret:
        raise ValueError(
            "TOTP secret not provided for MFA. "
            "Set BRAZE_TOTP_SECRET in .env (extract from 2FA setup QR code or text)"
        )

    # Generate current TOTP code
    totp = pyotp.TOTP(secret)
    code = totp.now()
    logger.info(f"Generated TOTP code: {code[:2]}****")

    # Try multiple selectors for the MFA input field
    mfa_input_selectors = [
        page.get_by_placeholder("000000"),
        page.get_by_placeholder("123456"),
        page.get_by_placeholder("Enter code"),
        page.get_by_label("Verification code", exact=False),
        page.get_by_label("Authentication code", exact=False),
        page.get_by_label("Code", exact=False),
        page.locator("input[name*='otp' i]"),
        page.locator("input[name*='code' i]"),
        page.locator("input[name*='totp' i]"),
        page.locator("input[type='tel']"),  # Often used for numeric codes
        page.locator("input[maxlength='6']"),  # 6-digit code field
    ]

    # Find and fill the MFA input
    mfa_filled = False
    for selector in mfa_input_selectors:
        try:
            await selector.wait_for(state="visible", timeout=2000)
            await selector.fill(code)
            logger.debug("Filled MFA code field")
            mfa_filled = True
            break
        except PlaywrightTimeout:
            continue
        except Exception as e:
            logger.debug(f"MFA selector failed: {e}")
            continue

    if not mfa_filled:
        raise Exception("Could not find MFA input field")

    # Try to submit the MFA code
    submit_selectors = [
        page.get_by_role("button", name="Verify"),
        page.get_by_role("button", name="Submit"),
        page.get_by_role("button", name="Continue"),
        page.get_by_role("button", name="Confirm"),
        page.locator("button[type='submit']"),
    ]

    for selector in submit_selectors:
        try:
            await selector.wait_for(state="visible", timeout=2000)
            await selector.click()
            logger.info("Submitted MFA code")
            break
        except PlaywrightTimeout:
            continue
        except Exception:
            continue

    # Wait for successful navigation after MFA
    try:
        await page.wait_for_url("**/dashboard**", timeout=15000)
        logger.info("MFA successful - redirected to dashboard")
        return True
    except PlaywrightTimeout:
        pass

    try:
        await page.wait_for_url("**/home**", timeout=5000)
        logger.info("MFA successful - redirected to home")
        return True
    except PlaywrightTimeout:
        pass

    # Check for MFA error messages
    error_locator = page.locator(".error-message, .alert-danger, [role='alert']")
    if await error_locator.count() > 0:
        error_text = await error_locator.first.text_content()
        raise Exception(f"MFA verification failed: {error_text}")

    raise Exception("MFA verification failed - unexpected state after code submission")


def _gmail_access_token() -> Optional[str]:
    """Exchange the Google refresh token for a short-lived access token."""
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        return None
    try:
        body = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("access_token")
    except Exception as e:
        logger.warning(f"Could not refresh Google token: {e}")
        return None


def _extract_gmail_body(msg: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    payload = msg.get("payload", {})

    def _walk(part: dict) -> str:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            import base64
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        for sub in part.get("parts", []):
            result = _walk(sub)
            if result:
                return result
        return ""

    return _walk(payload)


async def _fetch_braze_email_code(
    max_wait_seconds: int = 240,
    min_epoch_ms: Optional[int] = None,
) -> Optional[str]:
    """
    Poll Gmail for a Braze email verification code.

    Only accepts emails with internalDate >= min_epoch_ms (milliseconds since
    epoch). Pass int(time.time() * 1000) captured just before triggering the
    2FA request so stale codes from prior sessions are ignored.
    """
    access_token = await asyncio.to_thread(_gmail_access_token)
    if not access_token:
        logger.warning("No Gmail access token available — cannot auto-fetch email 2FA code")
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    deadline = time.monotonic() + max_wait_seconds
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            query = urllib.parse.quote(
                'from:no-reply@braze.com newer_than:10m'
            )
            url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?q={query}&maxResults=5"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            for msg_stub in data.get("messages", []):
                msg_url = (
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                    f"{msg_stub['id']}?format=full"
                )
                req = urllib.request.Request(msg_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    msg = json.loads(resp.read())

                # Skip emails that arrived before the current 2FA request
                if min_epoch_ms is not None:
                    internal_date = int(msg.get("internalDate", 0))
                    if internal_date < min_epoch_ms:
                        logger.debug(
                            f"Skipping stale Braze email (arrived {internal_date} < {min_epoch_ms})"
                        )
                        continue

                body = _extract_gmail_body(msg)
                match = re.search(r'\b(\d{6})\b', body)
                if match:
                    code = match.group(1)
                    logger.info(f"Found Braze email 2FA code (attempt {attempt}): {code[:2]}****")
                    return code

        except Exception as e:
            logger.debug(f"Gmail poll attempt {attempt} error: {e}")

        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(8, remaining))

    logger.warning(f"Timed out after {max_wait_seconds}s waiting for Braze verification email")
    return None


async def handle_email_mfa(page: Page) -> bool:
    """
    Handle Braze's email-based 2FA challenge by auto-fetching the code from Gmail.

    Checks 'Remember this account for 30 days' before submitting so the device
    trust cookie is set and future sessions skip this step for ~30 days.
    """
    logger.info("Email 2FA checkpoint detected — fetching code from Gmail...")

    # Check the "remember" checkbox first so the cookie gets set on submit
    for cb_selector in [
        page.get_by_label("Remember this account for 30 days", exact=False),
        page.locator("input[type='checkbox']"),
    ]:
        try:
            cb = cb_selector.first
            await cb.wait_for(state="visible", timeout=3000)
            if not await cb.is_checked():
                await cb.check()
                logger.info("Checked 'Remember this account for 30 days'")
            break
        except Exception:
            continue

    # Record timestamp so we only accept an email that arrived after this
    # 2FA page was shown (avoids reusing a code from a prior login attempt).
    # Subtract 60s to account for the time between Braze sending the email
    # (when the login button was clicked) and when this checkpoint is reached.
    mfa_requested_at_ms = int(time.time() * 1000) - 60_000

    # Fetch the code from Gmail (polls up to 240s)
    code = await _fetch_braze_email_code(min_epoch_ms=mfa_requested_at_ms)
    if not code:
        raise Exception(
            "Could not retrieve Braze email verification code from Gmail. "
            "Check that GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / "
            "GOOGLE_DRIVE_REFRESH_TOKEN are set and that the token has Gmail read scope."
        )

    # Fill the code input — try progressively broader selectors
    code_filled = False
    for selector in [
        page.locator("input[name='code']"),
        page.get_by_placeholder("Enter this 6-digit code", exact=False),
        page.get_by_placeholder("code", exact=False),
        page.locator("input[maxlength='6']"),
        page.locator("input[type='tel']"),
        page.locator("input[type='number']"),
        page.locator("input[type='text']"),
        page.locator("input:not([type='checkbox']):not([type='hidden']):not([type='submit'])"),
    ]:
        try:
            el = selector.first
            await el.wait_for(state="visible", timeout=2000)
            await el.click()
            await el.fill(code)
            code_filled = True
            logger.info("Filled email 2FA code")
            break
        except Exception:
            continue

    if not code_filled:
        # Last resort: find any visible input and fill it
        try:
            inputs = page.locator("input")
            count = await inputs.count()
            for i in range(count):
                inp = inputs.nth(i)
                inp_type = await inp.get_attribute("type") or "text"
                if inp_type in ("checkbox", "hidden", "submit", "button"):
                    continue
                if await inp.is_visible():
                    await inp.click()
                    await inp.fill(code)
                    code_filled = True
                    logger.info(f"Filled email 2FA code (fallback input #{i})")
                    break
        except Exception as e:
            logger.debug(f"Fallback input fill failed: {e}")

    if not code_filled:
        raise Exception("Could not find email 2FA code input field")

    # Submit
    for btn_selector in [
        page.get_by_role("button", name="Verify"),
        page.get_by_role("button", name="Submit"),
        page.locator("button[type='submit']"),
    ]:
        try:
            await btn_selector.wait_for(state="visible", timeout=3000)
            await btn_selector.click()
            logger.info("Submitted email 2FA code")
            break
        except Exception:
            continue

    # Wait for navigation away from the 2FA page
    try:
        await page.wait_for_function(
            "() => !window.location.pathname.includes('/two-factor')",
            timeout=15000,
        )
        logger.info("Email 2FA successful")
        return True
    except PlaywrightTimeout:
        # Check for error on the page
        err = page.locator(".error-message, .alert-danger, [role='alert']")
        if await err.count() > 0:
            raise Exception(f"Email 2FA failed: {await err.first.text_content()}")
        raise Exception("Email 2FA failed — still on 2FA page after submission")


async def wait_for_manual_login(page: Page, dashboard_url: str, timeout_ms: int = 180_000) -> bool:
    """
    Navigate to Braze and wait for the user to log in manually (e.g. with Google/Gmail).

    Use this when you sign in with Google/SSO instead of email+password.
    The browser window must be visible; log in in the page, then automation continues.

    Args:
        page: Playwright page object
        dashboard_url: Braze dashboard URL
        timeout_ms: How long to wait for URL to become dashboard/home (default 3 min)

    Returns:
        True when URL contains /dashboard or /home
    """
    logger.info("No Braze email/password set — using manual login (e.g. Sign in with Google).")
    logger.info("Log in with Google in the browser window; automation will continue when you reach the dashboard.")
    await page.goto(dashboard_url, wait_until="load", timeout=60000)

    # Already on dashboard (e.g. restored session)
    if _is_on_dashboard(page.url):
        logger.info("Already logged in (session restored)")
        return True

    # Wait for user to complete Google/SSO login
    try:
        await page.wait_for_url(
            lambda u: _is_on_dashboard(u),
            timeout=timeout_ms,
        )
        logger.info("Manual login detected — now on dashboard")
        return True
    except PlaywrightTimeout:
        raise Exception(
            "Timed out waiting for login. Log in with Google in the browser window, "
            "or set BRAZE_DASHBOARD_EMAIL and BRAZE_DASHBOARD_PASSWORD in .env for automated login."
        )


async def login(
    page: Page,
    email: Optional[str] = None,
    password: Optional[str] = None,
    dashboard_url: Optional[str] = None
) -> bool:
    """
    Log in to Braze dashboard.

    Supports:
    - Email + password (and optional TOTP MFA via BRAZE_TOTP_SECRET).
    - Manual login (e.g. Gmail/Google): if BRAZE_DASHBOARD_EMAIL and
      BRAZE_DASHBOARD_PASSWORD are not set, opens the dashboard and waits
      for you to sign in with Google in the browser; session is saved
      so the next run skips login.

    Args:
        page: Playwright page object
        email: Braze dashboard email (uses env var if not provided)
        password: Braze dashboard password (uses env var if not provided)
        dashboard_url: Dashboard URL (uses env var if not provided)

    Returns:
        True if login successful

    Raises:
        Exception: If login fails or times out
    """
    email = email or BRAZE_DASHBOARD_EMAIL
    password = password or BRAZE_DASHBOARD_PASSWORD
    dashboard_url = dashboard_url or BRAZE_DASHBOARD_URL

    # No email/password → use manual login (e.g. Gmail/Google)
    if not email or not password:
        return await wait_for_manual_login(page, dashboard_url)

    logger.info(f"Navigating to Braze dashboard: {dashboard_url}")
    await page.goto(dashboard_url, wait_until="load", timeout=60000)

    # Check if already logged in (redirected to dashboard)
    if _is_on_dashboard(page.url):
        logger.info("Already logged in (session restored)")
        return True

    # Check if the session landed directly on a 2FA page (session partially valid)
    if "two-factor" in page.url or "verify" in page.url:
        if "verify/email" in page.url:
            logger.info("Email 2FA checkpoint detected (session partial) — fetching code from Gmail")
            return await handle_email_mfa(page)
        logger.info("TOTP checkpoint detected (session partial) — completing MFA")
        return await handle_mfa(page)

    # Wait for login form
    logger.info("Waiting for login form...")

    # Step 1: Fill email — Braze may show a two-step flow (email → Continue → password)
    # or a single-step flow (email + password on one page).
    email_selectors = [
        page.get_by_label("Email address", exact=False),
        page.get_by_label("Email", exact=False),
        page.get_by_placeholder("Enter your email address"),
        page.get_by_placeholder("Email"),
        page.locator("input[type='email']"),
    ]
    email_filled = False
    for selector in email_selectors:
        try:
            await selector.wait_for(state="visible", timeout=10000)
            await selector.fill(email)
            email_filled = True
            logger.debug("Filled email field")
            break
        except PlaywrightTimeout:
            continue
    if not email_filled:
        raise Exception("Could not find email input field on login page")

    # Step 2: Check if password is already visible (single-step) or if we need
    # to click "Continue" first (two-step flow).
    password_field = page.get_by_label("Password", exact=False)
    try:
        await password_field.wait_for(state="visible", timeout=2000)
        logger.debug("Password field visible (single-step login)")
    except PlaywrightTimeout:
        # Two-step flow: click Continue to reveal password field
        logger.debug("Password not visible — trying two-step flow (Continue button)")
        continue_selectors = [
            page.get_by_role("button", name="Continue"),
            page.get_by_role("button", name="Next"),
            page.locator("button[type='submit']"),
        ]
        for selector in continue_selectors:
            try:
                await selector.click(timeout=3000)
                logger.debug("Clicked Continue/Next button")
                break
            except (PlaywrightTimeout, Exception):
                continue

        # Wait for password field after Continue
        password_selectors = [
            page.get_by_label("Password", exact=False),
            page.get_by_placeholder("Enter your password"),
            page.get_by_placeholder("Password"),
            page.locator("input[type='password']"),
        ]
        password_field = None
        for selector in password_selectors:
            try:
                await selector.wait_for(state="visible", timeout=10000)
                password_field = selector
                break
            except PlaywrightTimeout:
                continue
        if password_field is None:
            raise Exception("Could not find password field after Continue step")

    # Fill password
    await password_field.fill(password)
    logger.debug("Filled password field")

    # Click login/submit button
    login_selectors = [
        page.get_by_role("button", name="Log In"),
        page.get_by_role("button", name="Sign In"),
        page.get_by_role("button", name="Sign in"),
        page.get_by_role("button", name="Continue"),
        page.locator("button[type='submit']"),
    ]
    for selector in login_selectors:
        try:
            await selector.click(timeout=3000)
            logger.info("Clicked login button")
            break
        except (PlaywrightTimeout, Exception):
            continue

    # Wait for navigation — could land on dashboard, home, or MFA page
    try:
        await page.wait_for_load_state("load", timeout=30000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    # Check if we landed on the dashboard (login complete, no MFA)
    if _is_on_dashboard(page.url):
        logger.info("Login successful - redirected to dashboard")
        return True

    # Check for 2FA/MFA prompt
    if "two-factor" in page.url or "verify" in page.url or "mfa" in page.url:
        if "verify/email" in page.url:
            logger.info("Email 2FA page detected — fetching code from Gmail")
            return await handle_email_mfa(page)
        logger.info("MFA/2FA page detected — attempting TOTP authentication")
        return await handle_mfa(page)

    # Check for MFA indicators on the page itself
    email_mfa_indicators = [
        page.get_by_text("two-factor authentication by email", exact=False),
        page.get_by_text("verification code to your email", exact=False),
    ]
    for indicator in email_mfa_indicators:
        try:
            if await indicator.count() > 0:
                logger.info("Email 2FA prompt detected — fetching code from Gmail")
                return await handle_email_mfa(page)
        except Exception:
            continue

    totp_indicators = [
        page.get_by_text("verification code", exact=False),
        page.get_by_text("two-factor", exact=False),
        page.get_by_text("2FA", exact=False),
        page.get_by_text("authenticator", exact=False),
        page.locator("input[maxlength='6']"),
    ]
    for indicator in totp_indicators:
        try:
            if await indicator.count() > 0:
                logger.info("MFA/2FA prompt detected — attempting TOTP authentication")
                return await handle_mfa(page)
        except Exception:
            continue

    # Check for error messages
    error_locator = page.locator(".error-message, .alert-danger, [role='alert']")
    if await error_locator.count() > 0:
        error_text = await error_locator.first.text_content()
        raise Exception(f"Login failed: {error_text}")

    raise Exception("Login failed - unexpected state")


async def ensure_logged_in(page: Page) -> bool:
    """
    Ensure we're logged in, attempt login if not.

    Args:
        page: Playwright page object

    Returns:
        True if logged in (or login successful)
    """
    # Check current URL
    if _is_on_dashboard(page.url):
        logger.debug("Already on dashboard")
        return True

    # Navigate to dashboard to check auth
    await page.goto(BRAZE_DASHBOARD_URL, wait_until="load", timeout=60000)

    # If redirected to login, perform login
    if "login" in page.url.lower() or "signin" in page.url.lower():
        return await login(page)

    # Check if on dashboard
    if _is_on_dashboard(page.url):
        return True

    # Session restored but MFA checkpoint — complete without re-navigating
    if "two-factor" in page.url or "totp" in page.url or "verify" in page.url:
        if "verify/email" in page.url:
            logger.info("Email 2FA checkpoint detected — fetching code from Gmail")
            return await handle_email_mfa(page)
        logger.info("TOTP checkpoint detected — completing MFA")
        return await handle_mfa(page)

    # Unknown state, try login
    return await login(page)


async def save_session(context: BrowserContext) -> Path:
    """
    Save browser session state for later reuse.

    This allows skipping login on subsequent runs.

    Args:
        context: Playwright browser context

    Returns:
        Path to saved session file
    """
    await context.storage_state(path=str(SESSION_STORAGE_PATH))
    logger.info(f"Session saved to {SESSION_STORAGE_PATH}")
    return SESSION_STORAGE_PATH


async def create_context_with_session(browser: Browser) -> BrowserContext:
    """
    Create a browser context with saved session state.

    Args:
        browser: Playwright browser object

    Returns:
        Browser context (with session if available)
    """
    if SESSION_STORAGE_PATH.exists():
        logger.info("Loading saved session state")
        return await browser.new_context(storage_state=str(SESSION_STORAGE_PATH))
    else:
        logger.info("No saved session, creating fresh context")
        return await browser.new_context()


async def logout(page: Page) -> bool:
    """
    Log out from Braze dashboard.

    Args:
        page: Playwright page object

    Returns:
        True if logout successful
    """
    try:
        # Click user menu
        user_menu = page.locator("[data-testid='user-menu'], .user-menu, .avatar")
        await user_menu.click(timeout=5000)

        # Click logout
        logout_button = page.get_by_role("button", name="Log Out")
        await logout_button.click(timeout=5000)

        # Wait for redirect to login
        await page.wait_for_url("**/login**", timeout=10000)
        logger.info("Logged out successfully")
        return True
    except Exception as e:
        logger.warning(f"Logout may have failed: {e}")
        return False


def clear_session():
    """Remove saved session state."""
    if SESSION_STORAGE_PATH.exists():
        SESSION_STORAGE_PATH.unlink()
        logger.info("Session cleared")


# Mapping of brand codes to Braze workspace names
BRAND_WORKSPACE_MAP = {
    "HAV": "havenly",
    "BUR": "Burrow - Production",
    "ID": "Interior Define",
    "STF": "St Frank",
    "CZ": "The Citizenry",
    "TI": "The Inside",
}

# Direct workspace URLs — skip the UI switcher entirely when available.
# Add ID and TI once their workspace URLs are known.
BRAND_WORKSPACE_DIRECT_URL = {
    "HAV": "https://dashboard-07.braze.com/dashboard/app_usage/664223fb71bcf3005760dfc2",
    "CZ":  "https://dashboard-07.braze.com/dashboard/app_usage/666672a4d8965b005ac6c1bd",
    "BUR": "https://dashboard-07.braze.com/dashboard/app_usage/67093a1f24ebbe0065cb9c77",
    "STF": "https://dashboard-07.braze.com/dashboard/app_usage/666716b3858150005b566956",
    "ID":  "https://dashboard-07.braze.com/dashboard/app_usage/6666726b459b5e0059d7d687",
    "TI":  "https://dashboard-07.braze.com/dashboard/app_usage/666672c6459b5e0059d7d77d",
}


async def select_workspace(page: Page, brand: str) -> bool:
    """
    Select the correct Braze workspace for a given brand.

    Args:
        page: Playwright page object (should be logged in)
        brand: Brand code (HAV, BUR, ID, STF, CZ, TI)

    Returns:
        True if workspace selected successfully

    Raises:
        ValueError: If brand code not recognized
        Exception: If workspace selection fails
    """
    workspace_name = BRAND_WORKSPACE_MAP.get(brand.upper())
    if not workspace_name:
        raise ValueError(
            f"Unknown brand code: {brand}. "
            f"Valid codes: {', '.join(BRAND_WORKSPACE_MAP.keys())}"
        )

    logger.info(f"Selecting workspace for brand {brand}: {workspace_name}")

    # Fast path: navigate directly to the workspace URL if known (~25s faster than UI switcher)
    direct_url = BRAND_WORKSPACE_DIRECT_URL.get(brand.upper())
    if direct_url:
        logger.info(f"Navigating directly to workspace URL for {brand}")
        await page.goto(direct_url)
        try:
            await page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)
        app_group_id = direct_url.rstrip("/").split("/")[-1].split("?")[0]
        # Check app_group_id appears in the URL path (not just in the ?origin= query param)
        if f"/app_usage/{app_group_id}" in page.url or f"/campaigns/{app_group_id}" in page.url:
            logger.info(f"Selected workspace: {workspace_name} (direct URL)")
            logger.info(f"Workspace page loaded. Current URL: {page.url}")
            logger.info(f"Workspace selection complete for {brand}")
            return True
        # If we landed on /auth, the workspace switch triggered a fresh auth challenge — re-authenticate
        if "/auth" in page.url:
            logger.info(f"Workspace navigation triggered auth challenge (URL: {page.url}) — re-authenticating")
            await login(page)
            await page.goto(direct_url)
            try:
                await page.wait_for_load_state("load", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            if f"/app_usage/{app_group_id}" in page.url or f"/campaigns/{app_group_id}" in page.url:
                logger.info(f"Selected workspace: {workspace_name} (after re-auth)")
                return True
        # Email 2FA checkpoint triggered by workspace switch — handle automatically
        if "verify/email" in page.url:
            logger.info(f"Workspace switch triggered email 2FA — fetching code from Gmail")
            await handle_email_mfa(page)
            await page.goto(direct_url)
            try:
                await page.wait_for_load_state("load", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            if f"/app_usage/{app_group_id}" in page.url or f"/campaigns/{app_group_id}" in page.url:
                logger.info(f"Selected workspace: {workspace_name} (after email 2FA)")
                return True
        logger.warning(f"Direct URL navigation may have failed (URL: {page.url}), falling back to UI switcher")

    # Slow path: use the UI workspace switcher
    # Dismiss any promotional modals that Braze may show after login.
    # These block clicks on the workspace selector button.
    # Wait a beat for async modals to render, then try multiple dismissal strategies.
    await page.wait_for_timeout(1500)
    for _attempt in range(3):
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        except Exception:
            pass
        dismissed = False
        for close_selector in [
            page.get_by_role("button", name="Close", exact=False),
            page.locator("button[aria-label='Close']"),
            page.locator("button[aria-label='close']"),
            page.locator("button[aria-label*='lose' i]"),
            page.locator("button[aria-label*='ismiss' i]"),
            page.locator(".modal-close"),
            page.locator("[data-dismiss='modal']"),
            page.locator("[role='dialog'] button[class*='close' i]"),
            page.locator("[role='dialog'] button:last-child"),
        ]:
            try:
                if await close_selector.count() > 0 and await close_selector.first.is_visible():
                    await close_selector.first.click(timeout=1500)
                    await page.wait_for_timeout(500)
                    logger.debug("Dismissed modal dialog before workspace selection")
                    dismissed = True
                    break
            except Exception:
                pass
        if dismissed:
            break

    # Dismiss Braze in-app message modals (rendered inside an iframe, e.g. "What's new in Braze").
    # These are invisible to regular page selectors — remove via JS if present.
    try:
        iam_root = page.locator(".ab-iam-root")
        if await iam_root.count() > 0:
            await page.evaluate("document.querySelectorAll('.ab-iam-root').forEach(el => el.remove())")
            await page.wait_for_timeout(400)
            logger.debug("Dismissed Braze in-app message modal via JS")
    except Exception:
        pass
    all_workspace_names = list(BRAND_WORKSPACE_MAP.values())

    # Check if the workspace selector is already open (e.g. session restored with it open).
    # If any workspace name is already visible as a link/menuitem, skip the open step.
    already_open = False
    for ws_name in all_workspace_names:
        try:
            item = page.get_by_role("link", name=ws_name, exact=False)
            if await item.count() > 0 and await item.first.is_visible():
                already_open = True
                logger.debug("Workspace selector already open — skipping open click")
                break
        except Exception:
            continue

    workspace_selector_opened = already_open

    if not already_open:
        # Dismiss Braze in-app message modals that may have loaded async after navigation.
        # The modal lives in .ab-iam-root and intercepts all pointer events.
        try:
            await page.wait_for_selector(".ab-iam-root", timeout=3000)
            await page.evaluate("document.querySelectorAll('.ab-iam-root').forEach(el => el.remove())")
            await page.wait_for_timeout(400)
            logger.debug("Dismissed async Braze in-app message modal before workspace click")
        except Exception:
            pass  # No modal present — that's fine

        # The workspace selector button's aria-label is the current workspace name.
        # Try clicking a button whose aria-label matches any known workspace name.
        for ws_name in all_workspace_names:
            try:
                ws_btn = page.get_by_role("button", name=ws_name, exact=True)
                await ws_btn.click(timeout=3000)
                workspace_selector_opened = True
                logger.debug(f"Clicked workspace button (current: {ws_name})")
                break
            except Exception:
                continue

        if not workspace_selector_opened:
            # Try non-exact button name match (handles avatar text like "H havenly")
            for ws_name in all_workspace_names:
                try:
                    ws_btn = page.get_by_role("button", name=ws_name, exact=False)
                    if await ws_btn.count() > 0:
                        await ws_btn.first.click(timeout=3000)
                        workspace_selector_opened = True
                        logger.debug(f"Clicked workspace button via non-exact match (current: {ws_name})")
                        break
                except Exception:
                    continue

        if not workspace_selector_opened:
            # Try text-based locator as another fallback
            for ws_name in all_workspace_names:
                try:
                    ws_btn = page.locator(f"button:has-text('{ws_name}')")
                    if await ws_btn.count() > 0:
                        await ws_btn.first.click(timeout=3000)
                        workspace_selector_opened = True
                        logger.debug(f"Clicked workspace button via text selector (current: {ws_name})")
                        break
                except Exception:
                    continue

        if not workspace_selector_opened:
            # Fallback: look for legacy selectors
            fallback_selectors = [
                page.get_by_role("button", name="company profile image", exact=False),
                page.locator("[data-testid='workspace-selector']"),
            ]
            for selector in fallback_selectors:
                try:
                    await selector.click(timeout=3000)
                    workspace_selector_opened = True
                    logger.debug("Opened workspace selector via fallback")
                    break
                except Exception:
                    continue

    if not workspace_selector_opened:
        raise Exception("Could not open workspace selector")

    await page.wait_for_timeout(1000)

    # Switch to "All workspaces" tab so the target is visible even if not favorited
    try:
        all_ws_tab = page.get_by_role("tab", name="All workspaces")
        if await all_ws_tab.count() == 0:
            all_ws_tab = page.get_by_text("All workspaces", exact=True)
        if await all_ws_tab.count() == 0:
            all_ws_tab = page.locator("button:has-text('All workspaces')")
        if await all_ws_tab.count() > 0:
            await all_ws_tab.first.click()
            await page.wait_for_timeout(500)
            logger.debug("Switched to 'All workspaces' tab")
    except Exception as e:
        logger.debug(f"Could not switch to All workspaces tab: {e}")

    # Find and click the target workspace
    # Try multiple selector strategies
    workspace_selected = False
    selectors_to_try = [
        page.get_by_role("menuitem", name=workspace_name, exact=False),
        page.get_by_role("link", name=workspace_name, exact=False),
        page.locator(f"text='{workspace_name}'"),
    ]
    for selector in selectors_to_try:
        try:
            await selector.wait_for(state="visible", timeout=3000)
            await selector.click()
            workspace_selected = True
            logger.info(f"Selected workspace: {workspace_name}")
            break
        except Exception:
            continue

    if not workspace_selected:
        raise Exception(f"Could not find workspace '{workspace_name}' in selector")

    # Wait for page to fully load with new workspace
    # The workspace switch triggers a page reload/navigation
    try:
        await page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(3000)
    logger.info(f"Workspace page loaded. Current URL: {page.url}")

    # Verify workspace was selected by checking the page title or URL
    logger.info(f"Workspace selection complete for {brand}")
    return True


async def get_current_workspace(page: Page) -> Optional[str]:
    """
    Get the name of the currently active workspace.

    Args:
        page: Playwright page object

    Returns:
        Workspace name or None if not found
    """
    try:
        # Open navigation menu
        menu_btn = page.get_by_role("button", name="Open navigation menu")
        await menu_btn.click(timeout=5000)
        await page.wait_for_timeout(300)

        # Look for "Active" indicator in workspace list
        active_workspace = page.get_by_role("menuitem").filter(has_text="Active")
        if await active_workspace.count() > 0:
            text = await active_workspace.first.text_content()
            # Clean up the text (remove "Active" suffix)
            workspace_name = text.replace("Active", "").strip()
            logger.debug(f"Current workspace: {workspace_name}")

            # Close menu
            close_btn = page.get_by_role("button", name="Close menu")
            await close_btn.click(timeout=3000)

            return workspace_name

        # Close menu
        close_btn = page.get_by_role("button", name="Close menu")
        await close_btn.click(timeout=3000)

        return None
    except Exception as e:
        logger.warning(f"Could not determine current workspace: {e}")
        return None
