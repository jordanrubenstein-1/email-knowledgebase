"""Persistent browser session management.

Manages a singleton Playwright browser instance that persists across tool calls.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger("braze-mcp.browser")


def _get_headless_default() -> bool:
    """Get headless mode from environment variable.

    Set BRAZE_HEADLESS=false to run browser visibly for debugging.
    """
    val = os.environ.get("BRAZE_HEADLESS", "true").lower()
    return val not in ("false", "0", "no")


class SessionManager:
    """Singleton manager for Playwright browser session."""

    _instance: Optional["SessionManager"] = None

    def __init__(self):
        """Initialize session state (use get_instance() instead)."""
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._is_logged_in: bool = False
        self._current_workspace: Optional[str] = None

    @classmethod
    def get_instance(cls) -> "SessionManager":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (for testing)."""
        if cls._instance is not None:
            cls._instance = None

    @property
    def browser(self) -> Optional[Browser]:
        """Get current browser instance."""
        return self._browser

    @property
    def page(self) -> Optional[Page]:
        """Get current page instance."""
        return self._page

    @property
    def is_logged_in(self) -> bool:
        """Check if currently logged into Braze."""
        return self._is_logged_in

    @property
    def current_workspace(self) -> Optional[str]:
        """Get current workspace name."""
        return self._current_workspace

    async def ensure_browser(self, headless: bool | None = None) -> Page:
        """Ensure browser is running and return page.

        Uses a persistent browser context to maintain login state across runs.

        Args:
            headless: Run browser in headless mode (default from BRAZE_HEADLESS env)

        Returns:
            Playwright Page instance
        """
        if self._browser is None:
            if headless is None:
                headless = _get_headless_default()
            logger.info(f"Launching browser (headless={headless})...")
            self._playwright = await async_playwright().start()
            
            # Use persistent context to maintain login sessions across runs
            # This saves cookies, localStorage, etc. to a directory
            import tempfile
            from pathlib import Path
            
            # Store browser state in a consistent location
            user_data_dir = Path(tempfile.gettempdir()) / "braze-browser-session"
            user_data_dir.mkdir(exist_ok=True)
            logger.info(f"Using persistent browser data: {user_data_dir}")
            
            # Launch with persistent context (combines browser + context)
            # Grant clipboard permissions so we can paste HTML into editors
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
                viewport={"width": 1280, "height": 900},
                permissions=["clipboard-read", "clipboard-write"],
                args=[
                    "--disable-save-password-bubble",
                    "--disable-password-manager-reauthentication",
                ],
            )
            self._browser = self._context  # In persistent context, context acts as browser
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            logger.info("Browser launched with persistent session")

        return self._page

    async def get_page(self, headless: bool | None = None) -> Page:
        """Get page, launching browser if needed."""
        return await self.ensure_browser(headless)

    async def ensure_logged_in(self, headless: bool | None = None) -> Page:
        """Ensure logged into Braze and return page.

        Args:
            headless: Run browser in headless mode (default from BRAZE_HEADLESS env)

        Returns:
            Playwright Page instance
        """
        page = await self.ensure_browser(headless)

        if not self._is_logged_in:
            from .login import login

            await login(page)
            self._is_logged_in = True

        return page

    def set_logged_in(self, value: bool) -> None:
        """Set login state."""
        self._is_logged_in = value

    def set_workspace(self, workspace: str) -> None:
        """Set current workspace."""
        self._current_workspace = workspace

    async def close(self) -> None:
        """Close browser and cleanup."""
        import asyncio

        logger.info("Closing browser session...")

        # Navigate to blank page first to terminate WebSocket connections
        if self._page:
            try:
                await asyncio.wait_for(
                    self._page.goto("about:blank"), timeout=2.0
                )
            except Exception:
                pass

        # For persistent context, browser and context are the same object
        # Just close the context (which closes everything)
        if self._context:
            try:
                await asyncio.wait_for(self._context.close(), timeout=5.0)
            except (asyncio.TimeoutError, RuntimeError) as e:
                logger.warning(f"Context close issue: {e}")
            self._context = None
            self._browser = None  # Same object in persistent context
            self._page = None

        if self._playwright:
            try:
                await asyncio.wait_for(self._playwright.stop(), timeout=2.0)
            except (asyncio.TimeoutError, RuntimeError) as e:
                logger.warning(f"Playwright stop issue: {e}")
            self._playwright = None

        self._is_logged_in = False
        self._current_workspace = None
        logger.info("Browser session closed")
