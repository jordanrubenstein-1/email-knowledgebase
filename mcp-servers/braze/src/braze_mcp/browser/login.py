"""Braze dashboard authentication.

Handles login flow including TOTP-based MFA and Google SSO.
"""

from __future__ import annotations

import logging

import pyotp
from playwright.async_api import Page

from ..config import get_dashboard_config

logger = logging.getLogger("braze-mcp.browser")


def generate_totp(secret: str) -> str:
    """Generate current TOTP code.

    Args:
        secret: Base32-encoded TOTP secret

    Returns:
        6-digit TOTP code

    Raises:
        Exception: If secret is invalid
    """
    totp = pyotp.TOTP(secret)
    return totp.now()


async def perform_login(page: Page, email: str, password: str) -> None:
    """Fill and submit login form.

    Braze uses a sequential login flow:
    1. /sign_in page - enter email, click Next
    2. /auth page - enter password, click Sign In
    3. MFA page (handled separately)

    Args:
        page: Playwright page
        email: Braze dashboard email
        password: Braze dashboard password
    """
    logger.info(f"Logging in as {email}...")
    logger.info(f"Current URL: {page.url}")

    # Step 1: Handle /sign_in page (email entry)
    if "/sign_in" in page.url:
        logger.info("On sign_in page, entering email...")
        email_field = page.get_by_placeholder("Enter your email address")
        await email_field.wait_for(state="visible", timeout=5000)
        await email_field.fill(email)
        continue_button = page.get_by_role("button", name="Continue")
        await continue_button.click()

        # Wait for password field to appear
        password_field = page.get_by_role("textbox", name="Password")
        await password_field.wait_for(state="visible", timeout=5000)
        logger.info("Password field visible")

    # Step 2: Handle /auth page (password entry)
    password_field = page.get_by_role("textbox", name="Password")
    if await password_field.count() > 0:
        logger.info("Entering password...")
        await password_field.fill(password)
        sign_in_button = page.get_by_role("button", name="Sign In")
        await sign_in_button.click()

        # Wait briefly for page to transition
        await page.wait_for_load_state("domcontentloaded")
        logger.info(f"After password, URL: {page.url}")


async def handle_mfa(page: Page, totp_secret: str) -> bool:
    """Handle MFA prompt if present.

    TOTP page has input for 6-digit code. MFA may not always be required.

    Args:
        page: Playwright page
        totp_secret: Base32-encoded TOTP secret

    Returns:
        True if MFA was handled, False if not present
    """
    # Check if we're on the MFA page by URL
    if "/two-factor" not in page.url:
        logger.info(f"Not on MFA page (URL: {page.url}), skipping MFA")
        return False

    logger.info("On MFA page, looking for code input...")

    # Try multiple selectors for the MFA field
    mfa_field = page.get_by_placeholder("Enter the 6 digit code")
    if await mfa_field.count() == 0:
        mfa_field = page.locator("#code")
    if await mfa_field.count() == 0:
        mfa_field = page.get_by_label("Code")

    # Check if MFA field is present
    try:
        await mfa_field.wait_for(state="visible", timeout=5000)
        logger.info("MFA field found")
    except Exception:
        logger.warning("MFA field not found despite being on MFA page")
        return False

    code = generate_totp(totp_secret)
    logger.info(f"Generated TOTP code: {code[:2]}****")

    # Clear field first in case of retry
    await mfa_field.fill("")
    await mfa_field.fill(code)

    # Check "Remember this account for 30 days" to avoid future MFA prompts
    remember_checkbox = page.get_by_label("Remember this account for 30 days")
    if await remember_checkbox.count() > 0:
        await remember_checkbox.check()
        logger.info("Checked 'Remember for 30 days'")

    # Submit - look for verify/submit button
    verify_button = page.get_by_role("button", name="Verify")
    if await verify_button.count() == 0:
        verify_button = page.get_by_role("button", name="Submit")
    await verify_button.click()

    logger.info("MFA code submitted")
    return True


async def wait_for_manual_login(page: Page, timeout_seconds: int = 180) -> bool:
    """Wait for user to complete manual login (e.g., Google SSO).

    Polls for the workspace button to appear, indicating successful login.

    Args:
        page: Playwright page
        timeout_seconds: How long to wait for login (default 3 minutes)

    Returns:
        True if login detected within timeout
    """
    import asyncio
    
    print("\n" + "=" * 60)
    print("🔐 MANUAL LOGIN REQUIRED")
    print("=" * 60)
    print("Please complete the Google SSO login in the browser window.")
    print(f"Waiting up to {timeout_seconds // 60} minutes for login...")
    print("=" * 60 + "\n")
    
    logger.info("MANUAL LOGIN REQUIRED - complete Google SSO in browser")
    
    workspace_btn = page.locator('[aria-controls="workspace-navigation-menu"]')
    
    for i in range(timeout_seconds):
        try:
            if await workspace_btn.count() > 0:
                is_visible = await workspace_btn.is_visible()
                if is_visible:
                    print("\n✅ Login detected! Continuing with automation...")
                    logger.info("Login detected! Workspace button is visible.")
                    return True
        except Exception:
            pass
        
        if i > 0 and i % 15 == 0:
            remaining = timeout_seconds - i
            print(f"⏳ Still waiting for login... ({i}s elapsed, {remaining}s remaining)")
            logger.info(f"Still waiting for login... ({i}s elapsed)")
        
        await asyncio.sleep(1)
    
    return False


async def login(page: Page) -> bool:
    """Full login flow including MFA and Google SSO.

    Supports two login methods:
    - "password": Automated email/password + optional TOTP
    - "google": Manual Google SSO (user completes OAuth in browser)

    Flow:
    1. Navigate to dashboard URL
    2. If already logged in, return
    3. For password method: enter credentials and handle MFA
    4. For google method: wait for user to complete OAuth
    5. Verify we're on the dashboard

    Args:
        page: Playwright page

    Returns:
        True if login successful

    Raises:
        BrazeConfigError: If config is missing
    """
    config = get_dashboard_config()
    login_method = config.get("login_method", "password")

    # Navigate to dashboard
    logger.info(f"Navigating to {config['url']}...")
    await page.goto(config["url"], timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=30000)
    logger.info(f"Page loaded: {page.url}")

    # Check if already logged in (on dashboard, not on any login page)
    if "/dashboard" in page.url and "/sign_in" not in page.url and "/auth" not in page.url:
        logger.info("Already logged in")
        return True

    # Check if we need to login
    if "/sign_in" in page.url or "/auth" in page.url:
        if login_method == "google":
            # For Google SSO, wait for user to complete login manually
            logger.info("Google SSO login - waiting for manual authentication...")
            if not await wait_for_manual_login(page, timeout_seconds=180):
                raise RuntimeError(
                    "Login timeout - please complete Google SSO login within 3 minutes"
                )
        else:
            # Password-based login
            logger.info("Login required, performing login...")
            await perform_login(page, config["email"], config["password"])

            # Handle MFA if needed (check if we're on MFA page)
            if config["totp_secret"]:
                await handle_mfa(page, config["totp_secret"])

    # Verify login successful - wait for workspace button to be visible
    # Use longer timeout to handle slow MFA verification
    try:
        workspace_btn = page.locator('[aria-controls="workspace-navigation-menu"]')
        await workspace_btn.wait_for(state="visible", timeout=30000)
        logger.info(f"Login successful, dashboard loaded. URL: {page.url}")
        return True
    except Exception as e:
        logger.error(f"Login failed, current URL: {page.url}")
        # Take screenshot for debugging
        try:
            await page.screenshot(path="/tmp/braze_login_failure.png")
            logger.error("Screenshot saved to /tmp/braze_login_failure.png")
        except Exception:
            pass
        raise RuntimeError(f"Login failed: {e}")
