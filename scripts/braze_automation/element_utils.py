"""
Selector utilities for Braze dashboard automation.

Strategy: Try standard Playwright selectors first, fall back to AI-assisted
element finding when needed.
"""

import logging
from typing import Optional
from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# Default timeout for element interactions (ms)
DEFAULT_TIMEOUT = 5000


async def fill_field(
    page: Page,
    label: str,
    value: str,
    timeout: int = DEFAULT_TIMEOUT
) -> bool:
    """
    Fill a form field, trying multiple selector strategies.

    Args:
        page: Playwright page object
        label: Human-readable label for the field
        value: Value to fill
        timeout: Timeout in ms for each attempt

    Returns:
        True if successful, raises exception otherwise
    """
    strategies = [
        # Strategy 1: By label association
        lambda: page.get_by_label(label, exact=False),
        # Strategy 2: By role with name
        lambda: page.get_by_role("textbox", name=label),
        # Strategy 3: By placeholder
        lambda: page.get_by_placeholder(label, exact=False),
        # Strategy 4: Label contains text, find sibling input
        lambda: page.locator(f"label:has-text('{label}')").locator(".. >> input, .. >> textarea").first,
        # Strategy 5: Aria-label attribute
        lambda: page.locator(f"[aria-label*='{label}' i]"),
        # Strategy 6: Name attribute
        lambda: page.locator(f"input[name*='{label.lower().replace(' ', '_')}' i], textarea[name*='{label.lower().replace(' ', '_')}' i]"),
    ]

    for i, get_locator in enumerate(strategies, 1):
        try:
            locator = get_locator()
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.fill(value, timeout=timeout)
            logger.debug(f"Filled '{label}' using strategy {i}")
            return True
        except (PlaywrightTimeout, Exception) as e:
            logger.debug(f"Strategy {i} failed for '{label}': {e}")
            continue

    # All strategies failed
    raise ValueError(f"Could not find field '{label}' with any selector strategy")


async def click_button(
    page: Page,
    name: str,
    timeout: int = DEFAULT_TIMEOUT,
    wait_for_navigation: bool = False
) -> bool:
    """
    Click a button, trying multiple selector strategies.

    Args:
        page: Playwright page object
        name: Button text or name
        timeout: Timeout in ms
        wait_for_navigation: If True, wait for navigation after click

    Returns:
        True if successful
    """
    strategies = [
        # Strategy 1: By role with exact name
        lambda: page.get_by_role("button", name=name, exact=True),
        # Strategy 2: By role with partial name
        lambda: page.get_by_role("button", name=name, exact=False),
        # Strategy 3: By text content
        lambda: page.get_by_text(name, exact=True),
        # Strategy 4: Link with name (sometimes buttons are links)
        lambda: page.get_by_role("link", name=name),
        # Strategy 5: Any clickable with text
        lambda: page.locator(f"button:has-text('{name}'), a:has-text('{name}'), [role='button']:has-text('{name}')").first,
        # Strategy 6: Data-testid or similar
        lambda: page.locator(f"[data-testid*='{name.lower().replace(' ', '-')}' i]"),
    ]

    for i, get_locator in enumerate(strategies, 1):
        try:
            locator = get_locator()
            await locator.wait_for(state="visible", timeout=timeout)

            if wait_for_navigation:
                async with page.expect_navigation(timeout=timeout * 2):
                    await locator.click(timeout=timeout)
            else:
                await locator.click(timeout=timeout)

            logger.debug(f"Clicked '{name}' using strategy {i}")
            return True
        except (PlaywrightTimeout, Exception) as e:
            logger.debug(f"Strategy {i} failed for button '{name}': {e}")
            continue

    raise ValueError(f"Could not find button '{name}' with any selector strategy")


async def wait_for_element(
    page: Page,
    text: str,
    timeout: int = DEFAULT_TIMEOUT * 2,
    state: str = "visible"
) -> Locator:
    """
    Wait for an element containing text to be in a specific state.

    Args:
        page: Playwright page object
        text: Text to find
        timeout: Timeout in ms
        state: State to wait for (visible, hidden, attached, detached)

    Returns:
        The locator if found
    """
    locator = page.get_by_text(text, exact=False)
    await locator.wait_for(state=state, timeout=timeout)
    return locator


async def select_option(
    page: Page,
    label: str,
    value: str,
    timeout: int = DEFAULT_TIMEOUT
) -> bool:
    """
    Select an option from a dropdown.

    Args:
        page: Playwright page object
        label: Dropdown label
        value: Option value or text to select
        timeout: Timeout in ms

    Returns:
        True if successful
    """
    strategies = [
        # Strategy 1: By label -> select
        lambda: page.get_by_label(label).select_option(value, timeout=timeout),
        # Strategy 2: Combobox role
        lambda: page.get_by_role("combobox", name=label).select_option(value, timeout=timeout),
        # Strategy 3: Click dropdown, then option (for custom dropdowns)
        None,  # Handled separately
    ]

    # Try native select strategies first
    for i, action in enumerate(strategies[:2], 1):
        if action is None:
            continue
        try:
            await action()
            logger.debug(f"Selected '{value}' in '{label}' using strategy {i}")
            return True
        except Exception as e:
            logger.debug(f"Strategy {i} failed for select '{label}': {e}")

    # Strategy 3: Custom dropdown (click to open, then click option)
    try:
        # Find and click the dropdown trigger
        dropdown = page.locator(f"[aria-label*='{label}' i], [data-testid*='{label.lower().replace(' ', '-')}']").first
        await dropdown.click(timeout=timeout)
        await page.wait_for_timeout(500)  # Wait for dropdown animation

        # Click the option
        option = page.get_by_role("option", name=value)
        await option.click(timeout=timeout)
        logger.debug(f"Selected '{value}' in '{label}' using custom dropdown strategy")
        return True
    except Exception as e:
        logger.debug(f"Custom dropdown strategy failed: {e}")

    raise ValueError(f"Could not select '{value}' in dropdown '{label}'")


async def navigate_menu(
    page: Page,
    menu_path: list[str],
    timeout: int = DEFAULT_TIMEOUT
) -> bool:
    """
    Navigate through a menu hierarchy.

    Args:
        page: Playwright page object
        menu_path: List of menu items to click in order, e.g., ["Messaging", "Campaigns"]
        timeout: Timeout in ms for each click

    Returns:
        True if successful
    """
    for item in menu_path:
        await click_button(page, item, timeout=timeout)
        await page.wait_for_timeout(500)  # Wait for menu animation/loading

    return True


async def get_text_content(
    page: Page,
    selector_or_label: str,
    timeout: int = DEFAULT_TIMEOUT
) -> Optional[str]:
    """
    Get text content from an element.

    Args:
        page: Playwright page object
        selector_or_label: CSS selector or label text
        timeout: Timeout in ms

    Returns:
        Text content or None if not found
    """
    try:
        # Try as label first
        locator = page.get_by_label(selector_or_label)
        await locator.wait_for(state="visible", timeout=timeout)
        return await locator.text_content()
    except Exception:
        pass

    try:
        # Try as text locator
        locator = page.get_by_text(selector_or_label, exact=False).first
        await locator.wait_for(state="visible", timeout=timeout)
        return await locator.text_content()
    except Exception:
        pass

    try:
        # Try as CSS selector
        locator = page.locator(selector_or_label).first
        await locator.wait_for(state="visible", timeout=timeout)
        return await locator.text_content()
    except Exception:
        return None
