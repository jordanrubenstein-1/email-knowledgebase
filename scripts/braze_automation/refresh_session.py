#!/usr/bin/env python3
"""
Refresh the Braze bot session using credentials from .env.

Run this whenever campaign builds fail with a login/session error:

    uv run python scripts/braze_automation/refresh_session.py

Uses BRAZE_DASHBOARD_EMAIL, BRAZE_DASHBOARD_PASSWORD, and BRAZE_TOTP_SECRET
from .env — no manual login required.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from login import clear_session, login, save_session, SESSION_STORAGE_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Clearing stale session...")
    clear_session()

    logger.info("Logging in with .env credentials...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        ok = await login(page)
        if not ok:
            logger.error("Login failed — check BRAZE_DASHBOARD_EMAIL / BRAZE_DASHBOARD_PASSWORD / BRAZE_TOTP_SECRET in .env")
            await browser.close()
            sys.exit(1)

        await save_session(context)
        await browser.close()

    logger.info(f"Session refreshed and saved to {SESSION_STORAGE_PATH}")
    logger.info("Campaign builds should now work.")


if __name__ == "__main__":
    asyncio.run(main())
