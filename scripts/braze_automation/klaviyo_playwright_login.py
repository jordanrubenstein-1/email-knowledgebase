"""
Klaviyo dashboard authentication for Playwright automation.

Manual-login-only flow (Google SSO / email SSO): on first run the browser
opens and waits for the user to log in; the session is saved so subsequent
runs skip the login step.

Brand-specific session files allow TI and TE accounts to coexist.
"""

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")

KLAVIYO_URL = "https://www.klaviyo.com"

_SESSION_DIR = Path(__file__).parent


def _session_path(brand: str) -> Path:
    return _SESSION_DIR / f".session_state_klaviyo_{brand.upper()}.json"


def _is_logged_in(url: str) -> bool:
    """True if the current URL looks like an authenticated Klaviyo page."""
    if "klaviyo.com" not in url:
        return False
    path = urlparse(url).path.rstrip("/") or "/"
    # Not logged in if on login / auth pages or bare root
    bad = ("/login", "/auth", "/signup", "/register", "/sso")
    if any(path.startswith(b) for b in bad):
        return False
    # Logged in if we're past the root on klaviyo.com
    return path not in ("/", "")


async def wait_for_manual_login(
    page: Page, brand: str = "TI", timeout_ms: int = 300_000
) -> bool:
    """Open the Klaviyo login page and wait for the user to complete login manually."""
    logger.info(
        f"No valid Klaviyo session for {brand} — opening browser for manual login. "
        "Log in, then this window will continue automatically."
    )
    await page.goto(f"{KLAVIYO_URL}/login", wait_until="domcontentloaded", timeout=30_000)

    try:
        await page.wait_for_function(
            """() => {
                const p = window.location.pathname;
                return !p.startsWith('/login') &&
                       !p.startsWith('/auth') &&
                       !p.startsWith('/sso') &&
                       p !== '/' && p !== '';
            }""",
            timeout=timeout_ms,
        )
        logger.info(f"Klaviyo manual login detected for {brand}")
        return True
    except PlaywrightTimeout:
        logger.error(f"Timed out waiting for Klaviyo login ({brand})")
        return False


async def ensure_logged_in(page: Page, brand: str = "TI") -> bool:
    """
    Ensure the page is authenticated with Klaviyo.

    If a saved session exists it is assumed to be valid once the campaigns
    page loads without redirecting to /login. If the session has expired,
    falls back to manual login.
    """
    # Quick check — already on an authenticated Klaviyo page
    if _is_logged_in(page.url):
        logger.info(f"Already logged in to Klaviyo ({brand})")
        return True

    # Try loading campaigns to probe the session
    try:
        await page.goto(
            f"{KLAVIYO_URL}/campaigns/email",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await page.wait_for_timeout(2_000)
    except Exception:
        pass

    if _is_logged_in(page.url):
        logger.info(f"Klaviyo session restored for {brand}")
        return True

    # Session expired or absent — manual login
    ok = await wait_for_manual_login(page, brand)
    return ok


async def create_context_with_session(
    browser: Browser, brand: str = "TI"
) -> BrowserContext:
    """Create a browser context, loading saved session state if available."""
    path = _session_path(brand)
    if path.exists():
        logger.info(f"Loading saved Klaviyo session for {brand}: {path}")
        return await browser.new_context(storage_state=str(path))
    logger.info(f"No saved Klaviyo session for {brand} — creating fresh context")
    return await browser.new_context()


async def save_session(context: BrowserContext, brand: str = "TI") -> Path:
    """Persist the current browser session so the next run can reuse it."""
    path = _session_path(brand)
    await context.storage_state(path=str(path))
    logger.info(f"Klaviyo session saved for {brand}: {path}")
    return path


def clear_session(brand: str = "TI") -> None:
    """Remove a saved Klaviyo session."""
    path = _session_path(brand)
    if path.exists():
        path.unlink()
        logger.info(f"Klaviyo session cleared for {brand}")
