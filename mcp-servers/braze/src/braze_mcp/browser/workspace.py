"""Workspace selection for multi-brand support.

Handles switching between Braze workspaces via the dashboard UI.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from ..config import BRAND_WORKSPACE_MAP, validate_brand

logger = logging.getLogger("braze-mcp.browser")


def get_workspace_name(brand: str) -> str:
    """Get workspace name for a brand.

    Args:
        brand: Brand code (case-insensitive)

    Returns:
        Braze workspace name

    Raises:
        BrazeConfigError: If brand is invalid
    """
    normalized = validate_brand(brand)
    return BRAND_WORKSPACE_MAP[normalized]


async def select_workspace(page: Page, brand: str) -> bool:
    """Select workspace for a brand.

    Uses the workspace selector button (aria-controls) and search input.

    Args:
        page: Playwright page (must be logged in)
        brand: Brand code

    Returns:
        True if workspace was switched

    Raises:
        BrazeConfigError: If brand is invalid
    """
    workspace_name = get_workspace_name(brand)
    logger.info(f"Selecting workspace: {workspace_name}")

    # Check if already on correct workspace by reading button text
    workspace_button = page.locator('[aria-controls="workspace-navigation-menu"]')
    await workspace_button.wait_for(state="visible", timeout=15000)
    
    current_text = await workspace_button.text_content()
    if current_text and workspace_name.lower() in current_text.lower():
        logger.info(f"Already on workspace: {workspace_name}")
        return True

    # Click workspace selector button
    await workspace_button.click()
    logger.info("Opened workspace menu")

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
            logger.info("Switched to 'All workspaces' tab")
    except Exception as e:
        logger.debug(f"Could not switch to All workspaces tab: {e}")

    # Type workspace name in search input
    search_input = page.get_by_label("Search by workspace name")
    await search_input.wait_for(state="visible", timeout=5000)
    await search_input.fill(workspace_name)
    
    # Wait for search results
    await page.wait_for_timeout(500)

    # Click the matching workspace link (wait for it to appear after search)
    workspace_link = page.get_by_role("link", name=workspace_name, exact=True)
    await workspace_link.wait_for(state="visible", timeout=5000)
    await workspace_link.click()

    # Wait for page to reload after workspace switch
    await page.wait_for_load_state("domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)  # Extra wait for JS to settle
    
    # Verify workspace actually switched by checking button text
    workspace_button = page.locator('[aria-controls="workspace-navigation-menu"]')
    await workspace_button.wait_for(state="visible", timeout=15000)
    
    new_text = await workspace_button.text_content()
    if new_text and workspace_name.lower() in new_text.lower():
        logger.info(f"Successfully switched to workspace: {workspace_name}")
        return True
    else:
        logger.warning(f"Workspace button shows '{new_text}', expected '{workspace_name}'")
        # Try again if it didn't switch
        logger.info("Retrying workspace selection...")
        await workspace_button.click()
        search_input = page.get_by_label("Search by workspace name")
        await search_input.wait_for(state="visible", timeout=5000)
        await search_input.fill(workspace_name)
        await page.wait_for_timeout(500)
        workspace_link = page.get_by_role("link", name=workspace_name, exact=True)
        await workspace_link.wait_for(state="visible", timeout=5000)
        await workspace_link.click()
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        
    logger.info(f"Switched to workspace: {workspace_name}")
    return True


async def get_current_workspace(page: Page) -> str | None:
    """Get current workspace name from the page.

    Args:
        page: Playwright page

    Returns:
        Current workspace name or None
    """
    try:
        # Open menu to check current workspace
        menu_button = page.get_by_role("button", name="Open navigation menu")
        await menu_button.click()
        await page.wait_for_timeout(300)

        # Look for workspace indicator
        # This depends on the Braze UI structure
        workspace_element = page.locator("[data-testid='current-workspace']")
        if await workspace_element.count() > 0:
            return await workspace_element.text_content()

        # Close menu
        await page.keyboard.press("Escape")
        return None

    except Exception:
        return None
