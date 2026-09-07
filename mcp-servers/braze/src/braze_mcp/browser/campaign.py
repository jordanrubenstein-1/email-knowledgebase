"""Campaign creation and management via Playwright.

Handles creating draft campaigns and archiving campaigns through the Braze UI.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from .session import SessionManager
from .workspace import select_workspace

logger = logging.getLogger("braze-mcp.browser")


# ---------------------------------------------------------------------------
# Campaign name validation (lightweight, inline version)
# Full utility: scripts/utils/campaign_name.py
# ---------------------------------------------------------------------------

_VALID_TYPE_CODES = {"P", "OT", "CX", "WTL", "SEG"}
_VALID_CHANNEL_CODES = {"EM", "SMS", "PUSH"}
_VALID_BRAND_CODES = {"CZ", "SF", "ID", "HAV", "TI", "BW", "TRADE", "ALL"}


def _warn_if_name_nonconforming(name: str) -> None:
    """Log a warning if the campaign name doesn't follow the naming convention.

    Convention: [TYPE]_[CHANNEL]_[YYYY]_[MM]_[DD]_[BRAND]_...
    This is a non-blocking check — it only logs warnings.
    """
    if not name:
        return

    parts = name.split("_")
    issues: list[str] = []

    # Check minimum length: TYPE + CHANNEL + YYYY + MM + DD + BRAND = 6 parts
    if len(parts) < 6:
        issues.append("Name has fewer than 6 underscore-separated parts.")
    else:
        if parts[0].upper() not in _VALID_TYPE_CODES:
            issues.append(
                f"Campaign type '{parts[0]}' not in {sorted(_VALID_TYPE_CODES)}."
            )
        if parts[1].upper() not in _VALID_CHANNEL_CODES:
            issues.append(
                f"Channel '{parts[1]}' not in {sorted(_VALID_CHANNEL_CODES)}."
            )
        date_str = f"{parts[2]}_{parts[3]}_{parts[4]}"
        if not re.match(r"^\d{4}_\d{2}_\d{2}$", date_str):
            issues.append(f"Date '{date_str}' is not YYYY_MM_DD format.")

        # Brand may be at parts[5] or span parts[5:7] for TRADE_ALL / ALL_TRADE
        brand = parts[5].upper()
        if brand not in _VALID_BRAND_CODES:
            issues.append(
                f"Brand '{parts[5]}' not in {sorted(_VALID_BRAND_CODES)}."
            )

    if issues:
        logger.warning(
            "Campaign name '%s' may not follow the naming convention "
            "(TYPE_CHANNEL_YYYY_MM_DD_BRAND_...): %s",
            name,
            "; ".join(issues),
        )


async def set_audience_filter(
    page: Page,
    filter_attribute: str,
    filter_operator: str,
    filter_value: str,
) -> None:
    """Set audience filter in the Target Users step.

    Args:
        page: Playwright page
        filter_attribute: Attribute to filter on (e.g., "email")
        filter_operator: Operator (e.g., "equals", "does not equal")
        filter_value: Value to filter for
    """
    logger.info(f"Setting audience filter: {filter_attribute} {filter_operator} {filter_value}")

    # Navigate to Target Users tab
    target_tab = page.get_by_role("tab", name="Target Users")
    if await target_tab.count() > 0:
        await target_tab.click()
        await page.wait_for_timeout(1000)

    # Click "Add Filter" button
    add_filter_button = page.get_by_role("button", name="Add Filter")
    if await add_filter_button.count() == 0:
        # Try alternate selector
        add_filter_button = page.locator("button:has-text('Add Filter')")
    await add_filter_button.wait_for(state="visible", timeout=5000)
    await add_filter_button.click()
    await page.wait_for_timeout(500)

    # Search for and select the attribute (e.g., "email")
    # The filter dropdown should have a search field
    filter_search = page.get_by_placeholder("Search filters")
    if await filter_search.count() == 0:
        filter_search = page.get_by_placeholder("Search")
    if await filter_search.count() > 0:
        await filter_search.fill(filter_attribute)
        await page.wait_for_timeout(500)

    # Click on the filter option
    filter_option = page.get_by_role("option", name=filter_attribute)
    if await filter_option.count() == 0:
        # Try text matching
        filter_option = page.locator(f"[role='option']:has-text('{filter_attribute}')")
    if await filter_option.count() == 0:
        # Try menuitem
        filter_option = page.get_by_role("menuitem", name=filter_attribute)
    if await filter_option.count() > 0:
        await filter_option.first.click()
        await page.wait_for_timeout(500)

    # Select operator (equals, etc.)
    operator_dropdown = page.locator("[data-testid='filter-operator']")
    if await operator_dropdown.count() == 0:
        # Try selecting by the current operator text
        operator_dropdown = page.locator("button:has-text('equals')")
    if await operator_dropdown.count() > 0:
        await operator_dropdown.click()
        await page.wait_for_timeout(300)
        operator_option = page.get_by_role("option", name=filter_operator)
        if await operator_option.count() > 0:
            await operator_option.click()

    # Enter the filter value
    value_input = page.locator("[data-testid='filter-value-input']")
    if await value_input.count() == 0:
        # Try finding input near the filter
        value_input = page.locator("input[placeholder*='value']")
    if await value_input.count() == 0:
        value_input = page.locator(".filter-row input[type='text']")
    if await value_input.count() > 0:
        await value_input.fill(filter_value)

    logger.info("Audience filter set")


async def set_schedule(
    page: Page,
    send_date: str,
    send_time: str,
    timezone: str = "America/New_York",
) -> None:
    """Set scheduled send time in the Schedule step.

    Args:
        page: Playwright page
        send_date: Date in YYYY-MM-DD format (e.g., "2026-02-06")
        send_time: Time in HH:MM format (e.g., "07:15")
        timezone: Timezone (default: America/New_York for Eastern)
    """
    logger.info(f"Setting schedule: {send_date} at {send_time} {timezone}")

    # Navigate to Schedule tab - try different selectors
    schedule_tab = page.get_by_role("tab", name="Schedule")
    if await schedule_tab.count() == 0:
        schedule_tab = page.get_by_role("button", name="Step Schedule", exact=True)
    if await schedule_tab.count() == 0:
        schedule_tab = page.locator("button:has-text('Schedule')").first
    if await schedule_tab.count() > 0:
        await schedule_tab.click()
        await page.wait_for_timeout(1000)

    # Select "Scheduled Delivery" option (vs Action-Based or API-Triggered)
    scheduled_option = page.get_by_role("radio", name="Scheduled Delivery")
    if await scheduled_option.count() == 0:
        scheduled_option = page.locator("label:has-text('Scheduled Delivery')")
    if await scheduled_option.count() > 0:
        await scheduled_option.click()
        await page.wait_for_timeout(500)

    # Select "Send at a designated time"
    designated_time = page.get_by_role("radio", name="Send at a designated time")
    if await designated_time.count() == 0:
        designated_time = page.locator("label:has-text('Send at a designated time')")
    if await designated_time.count() > 0:
        await designated_time.click()
        await page.wait_for_timeout(500)

    # Set the date
    date_input = page.locator("input[type='date']")
    if await date_input.count() == 0:
        date_input = page.get_by_label("Date")
    if await date_input.count() == 0:
        # Try finding date picker button
        date_input = page.locator("[data-testid='date-picker']")
    if await date_input.count() > 0:
        await date_input.fill(send_date)
        await page.wait_for_timeout(300)

    # Set the time
    time_input = page.locator("input[type='time']")
    if await time_input.count() == 0:
        time_input = page.get_by_label("Time")
    if await time_input.count() > 0:
        await time_input.fill(send_time)
        await page.wait_for_timeout(300)

    # Set timezone if dropdown is available
    timezone_selector = page.locator("[data-testid='timezone-selector']")
    if await timezone_selector.count() == 0:
        timezone_selector = page.get_by_label("Time Zone")
    if await timezone_selector.count() > 0:
        await timezone_selector.click()
        tz_option = page.get_by_role("option", name=timezone)
        if await tz_option.count() > 0:
            await tz_option.click()

    logger.info("Schedule set")


async def fill_campaign_form(
    page: Page,
    name: str,
    subject: str,
    preheader: str = "",
    body_html: Optional[str] = None,
    body_plain_text: Optional[str] = None,
) -> None:
    """Fill campaign creation form fields.

    Args:
        page: Playwright page
        name: Campaign name
        subject: Email subject line
        preheader: Email preheader text
        body_html: Optional HTML body
        body_plain_text: Optional plain text body (for plain text emails)
    """
    logger.info(f"Filling campaign form: {name}")

    # Fill campaign name
    name_field = page.get_by_role("textbox", name="Enter Campaign Name")
    if await name_field.count() == 0:
        name_field = page.locator("input[placeholder*='Campaign Name']")
    if await name_field.count() == 0:
        name_field = page.locator("input[placeholder*='campaign name']")
    if await name_field.count() > 0:
        await name_field.fill(name)
        logger.info(f"Campaign name filled: {name}")
    else:
        logger.warning("Could not find campaign name field")

    # Check if email composer modal is already open (happens when HTML editor is selected)
    composer_modal = page.locator("#email-message-composer-portal")
    if await composer_modal.count() > 0:
        logger.info("Email composer modal is already open - working within modal")
        # We're already in the composer, no need to navigate
    else:
        # Navigate to Compose tab/step to edit the email
        logger.info("Looking for Compose step...")
        compose_tab = page.get_by_role("button", name="Step Compose Messages")
        if await compose_tab.count() == 0:
            compose_tab = page.get_by_role("button", name="Step Compose", exact=True)
        if await compose_tab.count() == 0:
            compose_tab = page.get_by_role("tab", name="Compose")
        if await compose_tab.count() > 0:
            await compose_tab.first.click()
            await page.wait_for_timeout(2000)
            logger.info("Clicked Compose step")
        else:
            logger.info("No Compose step found, may already be in compose mode")

    # Check if we're in the composer modal
    composer_modal = page.locator("#email-message-composer-portal")
    in_modal = await composer_modal.count() > 0
    
    if in_modal:
        logger.info("Working within composer modal...")
        # Scope our searches to the modal
        container = composer_modal
    else:
        container = page
        # Look for "Edit" button or message variant to click into
        edit_message = container.get_by_role("button", name="Edit")
        if await edit_message.count() == 0:
            edit_message = container.locator("button:has-text('Edit Message')")
        if await edit_message.count() == 0:
            edit_message = container.locator("button:has-text('Edit Variant')")
        if await edit_message.count() > 0:
            await edit_message.first.click()
            await page.wait_for_timeout(2000)
            logger.info("Clicked edit message")

    # Look for subject field (may be in modal or page)
    logger.info("Looking for subject field...")
    subject_field = container.get_by_label("Subject")
    if await subject_field.count() == 0:
        subject_field = container.locator("input[name='subject']")
    if await subject_field.count() == 0:
        subject_field = container.locator("input[placeholder*='Subject']")
    if await subject_field.count() == 0:
        # Try within modal specifically
        subject_field = page.locator("#email-message-composer-portal input[name='subject']")
    if await subject_field.count() == 0:
        subject_field = page.locator("#email-message-composer-portal").get_by_label("Subject")
    
    if await subject_field.count() > 0:
        await subject_field.fill(subject)
        logger.info(f"Subject filled: {subject}")
    else:
        logger.warning("Could not find subject field")

    # Fill preheader
    if preheader:
        logger.info("Looking for preheader field...")
        preheader_field = container.get_by_label("Preheader")
        if await preheader_field.count() == 0:
            preheader_field = container.locator("input[name='preheader']")
        if await preheader_field.count() == 0:
            preheader_field = container.locator("input[placeholder*='Preheader']")
        if await preheader_field.count() == 0:
            preheader_field = page.locator("#email-message-composer-portal input[name='preheader']")
        
        if await preheader_field.count() > 0:
            await preheader_field.fill(preheader)
            logger.info(f"Preheader filled: {preheader[:50]}...")
        else:
            logger.warning("Could not find preheader field")

    # For plain text emails, convert to simple HTML
    if body_plain_text:
        html_content = plain_text_to_html(body_plain_text)
        body_html = html_content

    # Fill HTML body in code editor
    if body_html:
        await _set_editor_content(page, container, body_html)
    
    # If we're in a modal, we may need to click "Done" or close button to apply changes
    if in_modal:
        logger.info("Looking for Done/Apply button in modal...")
        done_button = container.get_by_role("button", name="Done")
        if await done_button.count() == 0:
            done_button = container.locator("button:has-text('Done')")
        if await done_button.count() == 0:
            done_button = container.locator("button:has-text('Apply')")
        if await done_button.count() == 0:
            done_button = container.locator("button:has-text('Save')")
        
        if await done_button.count() > 0:
            await done_button.first.click()
            await page.wait_for_timeout(2000)
            logger.info("Clicked Done/Apply button")
        else:
            logger.info("No Done/Apply button found - modal may auto-save")

    logger.info("Campaign form filling complete")


def plain_text_to_html(text: str) -> str:
    """Convert plain text to simple HTML for email.
    
    Args:
        text: Plain text content
        
    Returns:
        HTML string with proper formatting
    """
    import html
    
    # Escape HTML entities
    escaped = html.escape(text)
    
    # Convert line breaks to <br> tags
    escaped = escaped.replace('\n', '<br>\n')
    
    # Wrap in basic HTML structure
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; color: #333333; margin: 0; padding: 20px;">
{escaped}
</body>
</html>"""


async def _set_editor_content(page: Page, container, body_html: str) -> None:
    """Set HTML content in the code editor using the fastest available method.

    Tries three strategies in order:
    1. Monaco JS API injection (instant)
    2. Clipboard paste (near-instant)
    3. Playwright fill() on textarea (fast for non-Monaco editors)

    Args:
        page: Playwright page
        container: Scoped locator (modal or page)
        body_html: HTML content to set
    """
    import json

    logger.info(f"Setting HTML content ({len(body_html)} chars)...")

    # Monaco editor (used by Braze's HTML editor)
    monaco_editor = container.locator(".monaco-editor")
    if await monaco_editor.count() == 0:
        monaco_editor = page.locator("#email-message-composer-portal .monaco-editor")

    if await monaco_editor.count() > 0:
        logger.info("Found Monaco editor - attempting fast content injection")
        html_json = json.dumps(body_html)

        # Strategy 1: Monaco JS API injection (instant, ~0ms)
        # Try multiple ways to find the Monaco editor instance
        result = await page.evaluate(f"""
            (() => {{
                const content = {html_json};
                const strategies = [];

                // Strategy A: window.monaco.editor.getEditors()
                try {{
                    const editors = window.monaco?.editor?.getEditors?.();
                    if (editors && editors.length > 0) {{
                        editors[0].setValue(content);
                        return {{ success: true, method: 'monaco.editor.getEditors' }};
                    }}
                    strategies.push('getEditors: ' + (editors ? 'empty' : 'not available'));
                }} catch (e) {{
                    strategies.push('getEditors error: ' + e.message);
                }}

                // Strategy B: window.monaco.editor.getModels()
                try {{
                    const models = window.monaco?.editor?.getModels?.();
                    if (models && models.length > 0) {{
                        models[0].setValue(content);
                        return {{ success: true, method: 'monaco.editor.getModels' }};
                    }}
                    strategies.push('getModels: ' + (models ? 'empty' : 'not available'));
                }} catch (e) {{
                    strategies.push('getModels error: ' + e.message);
                }}

                // Strategy C: Find editor via DOM element properties
                try {{
                    const editorElements = document.querySelectorAll('.monaco-editor');
                    for (const el of editorElements) {{
                        // Try common property names where Monaco attaches the instance
                        const props = ['__monacoEditor__', '_editor', 'monacoEditor',
                                       '__editor', '_codeEditor'];
                        for (const prop of props) {{
                            const editor = el[prop];
                            if (editor && typeof editor.setValue === 'function') {{
                                editor.setValue(content);
                                return {{ success: true, method: 'DOM.' + prop }};
                            }}
                        }}
                        // Try React fiber approach
                        const fiberKey = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (fiberKey) {{
                            let fiber = el[fiberKey];
                            for (let i = 0; i < 20 && fiber; i++) {{
                                const state = fiber.memoizedState;
                                if (state && state.memoizedState) {{
                                    let s = state;
                                    while (s) {{
                                        if (s.memoizedState && typeof s.memoizedState === 'object' && 
                                            s.memoizedState.setValue && typeof s.memoizedState.setValue === 'function') {{
                                            s.memoizedState.setValue(content);
                                            return {{ success: true, method: 'ReactFiber' }};
                                        }}
                                        s = s.next;
                                    }}
                                }}
                                fiber = fiber.return;
                            }}
                        }}
                    }}
                    strategies.push('DOM scan: no editor instance found on ' + editorElements.length + ' elements');
                }} catch (e) {{
                    strategies.push('DOM scan error: ' + e.message);
                }}

                // Strategy D: Check for require/define globals (AMD module)
                try {{
                    if (typeof require === 'function') {{
                        const monacoEditor = require('vs/editor/editor.main');
                        if (monacoEditor && monacoEditor.editor) {{
                            const editors = monacoEditor.editor.getEditors();
                            if (editors.length > 0) {{
                                editors[0].setValue(content);
                                return {{ success: true, method: 'AMD require' }};
                            }}
                        }}
                    }}
                    strategies.push('AMD require: not available or no editors');
                }} catch (e) {{
                    strategies.push('AMD require error: ' + e.message);
                }}

                return {{ success: false, strategies: strategies }};
            }})()
        """)

        if result.get("success"):
            logger.info(f"HTML body set via Monaco API ({result['method']})")
            return
        else:
            logger.warning(
                f"Monaco JS injection failed. Strategies tried: {result.get('strategies', [])}"
            )

        # Strategy 2: Clipboard paste (near-instant, ~1s)
        logger.info("Falling back to clipboard paste...")
        try:
            # Use page.evaluate to write to clipboard (works without special permissions)
            await page.evaluate(
                f"navigator.clipboard.writeText({html_json})"
            )
            await monaco_editor.first.click()
            await page.wait_for_timeout(200)
            # Select all existing content, then paste
            await page.keyboard.press("Meta+a")
            await page.wait_for_timeout(100)
            await page.keyboard.press("Meta+v")
            await page.wait_for_timeout(500)
            logger.info("HTML body set via clipboard paste")
            return
        except Exception as e:
            logger.warning(f"Clipboard paste failed: {e}")

        # Strategy 3: dispatchEvent with InputEvent (bypass typing)
        logger.info("Falling back to InputEvent dispatch...")
        try:
            await monaco_editor.first.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Meta+a")
            await page.wait_for_timeout(100)
            # Use execCommand as last resort before character typing
            success = await page.evaluate(f"""
                (() => {{
                    try {{
                        document.execCommand('insertText', false, {html_json});
                        return true;
                    }} catch (e) {{
                        return false;
                    }}
                }})()
            """)
            if success:
                logger.info("HTML body set via execCommand")
                return
        except Exception as e:
            logger.warning(f"execCommand failed: {e}")

        # Final fallback: character typing (SLOW but reliable)
        logger.warning(
            f"All fast methods failed. Falling back to keyboard typing "
            f"({len(body_html)} chars - this will be slow)..."
        )
        await monaco_editor.first.click()
        await page.wait_for_timeout(300)
        await page.keyboard.press("Meta+a")
        await page.wait_for_timeout(100)
        for i in range(0, len(body_html), 500):
            chunk = body_html[i : i + 500]
            await page.keyboard.type(chunk, delay=0)
        logger.info("HTML body typed via keyboard (slow fallback)")
        return

    # Non-Monaco editors (Ace, CodeMirror, textarea)
    html_editor = container.locator("textarea.ace_text-input")
    if await html_editor.count() == 0:
        html_editor = container.locator(".CodeMirror textarea")
    if await html_editor.count() == 0:
        html_editor = container.locator("textarea")

    if await html_editor.count() > 0:
        await html_editor.first.fill(body_html)
        logger.info("HTML body filled via textarea")
    else:
        logger.warning("Could not find HTML body editor")


async def _select_template_in_ui(
    page: Page,
    template_name: str,
) -> bool:
    """Select an existing template during campaign editor selection.

    After clicking Email > HTML Editor, Braze shows a 'Start from' panel
    where you can pick an existing template. This function searches for
    and selects the named template.

    Args:
        page: Playwright page
        template_name: Name of the template to select

    Returns:
        True if template was selected, False if selection failed
    """
    logger.info(f"Looking for template selection UI for '{template_name}'...")

    # After selecting HTML Editor, Braze may show a template picker
    # Look for "Start from template" or "Use template" or similar
    await page.wait_for_timeout(2000)

    # Try to find template selection area
    # Braze typically shows: "Start from scratch" vs existing templates
    template_selectors = [
        page.get_by_text("Existing Template", exact=False),
        page.get_by_text("Start from template", exact=False),
        page.get_by_text("Use template", exact=False),
        page.get_by_role("tab", name="Templates"),
        page.locator("[data-testid='template-tab']"),
        page.locator("button:has-text('Template')"),
    ]

    for selector in template_selectors:
        if await selector.count() > 0:
            await selector.first.click()
            await page.wait_for_timeout(1000)
            logger.info("Clicked template selection tab/button")
            break
    else:
        logger.info("No explicit template tab found, checking if templates are already shown")

    # Search for the template by name
    search_field = page.get_by_placeholder("Search")
    if await search_field.count() == 0:
        search_field = page.get_by_placeholder("Search templates")
    if await search_field.count() == 0:
        search_field = page.locator("input[type='search']")
    if await search_field.count() == 0:
        search_field = page.locator("input[placeholder*='earch']")

    if await search_field.count() > 0:
        await search_field.first.fill(template_name)
        await page.wait_for_timeout(1500)
        logger.info(f"Searched for template: {template_name}")
    else:
        logger.warning("Could not find template search field")

    # Click on the template in results
    template_option = page.get_by_text(template_name, exact=True)
    if await template_option.count() == 0:
        template_option = page.locator(f"[data-testid='template-option']:has-text('{template_name}')")
    if await template_option.count() == 0:
        # Try partial match
        template_option = page.get_by_text(template_name, exact=False)
    if await template_option.count() == 0:
        # Try within a list/grid of templates
        template_option = page.locator(f"[role='option']:has-text('{template_name}')")
    if await template_option.count() == 0:
        template_option = page.locator(f"[role='listitem']:has-text('{template_name}')")

    if await template_option.count() > 0:
        await template_option.first.click()
        await page.wait_for_timeout(1000)
        logger.info(f"Selected template: {template_name}")

        # Confirm selection if there's an "Apply" or "Use" button
        confirm_buttons = [
            page.get_by_role("button", name="Apply Template"),
            page.get_by_role("button", name="Use Template"),
            page.get_by_role("button", name="Apply"),
            page.get_by_role("button", name="Insert"),
            page.locator("button:has-text('Apply')"),
        ]
        for btn in confirm_buttons:
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(1000)
                logger.info("Confirmed template selection")
                break

        return True

    logger.warning(f"Could not find template '{template_name}' in UI")
    return False


async def create_campaign_from_template(
    brand: str,
    name: str,
    subject: str,
    preheader: str = "",
    body_html: Optional[str] = None,
    body_plain_text: Optional[str] = None,
    schedule_date: Optional[str] = None,
    schedule_time: Optional[str] = None,
    schedule_timezone: str = "America/New_York",
    audience_filter_attribute: Optional[str] = None,
    audience_filter_operator: str = "equals",
    audience_filter_value: Optional[str] = None,
    dry_run: bool = True,
    screenshot_path: Optional[Path] = None,
    headless: Optional[bool] = None,
) -> dict:
    """Create a draft email campaign using the Template API-first approach.

    This is the FAST path for campaign creation. Instead of entering HTML
    into the code editor (which is slow), it:
    1. Creates an email template via the Braze Templates API (instant)
    2. Uses browser automation to create a campaign that selects that template
    3. The template pre-fills subject, preheader, and body -- no code editor needed

    Falls back to the standard create_campaign() flow if template selection
    in the UI fails.

    Args:
        brand: Brand code
        name: Campaign name
        subject: Email subject line
        preheader: Email preheader text
        body_html: HTML body content
        body_plain_text: Plain text body (converted to HTML if body_html not provided)
        schedule_date: Optional date in YYYY-MM-DD format
        schedule_time: Optional time in HH:MM format
        schedule_timezone: Timezone (default: America/New_York)
        audience_filter_attribute: Attribute to filter on
        audience_filter_operator: Filter operator
        audience_filter_value: Value to filter for
        dry_run: If True, don't save the campaign
        screenshot_path: Optional path for screenshot
        headless: Run browser visibly (False) or headless (True)

    Returns:
        Dict with success status and details
    """
    # Validate campaign name against naming convention
    _warn_if_name_nonconforming(name)

    from ..tools.api_tools import create_template

    # Step 1: Create the template via API (instant, no browser needed)
    template_name = f"_auto_{name}"  # Prefix with _auto_ so it's clearly automation-generated
    logger.info(f"Creating template via API: {template_name}")

    try:
        template_result = await create_template(
            brand=brand,
            template_name=template_name,
            subject=subject,
            body_html=body_html,
            body_plain_text=body_plain_text,
            preheader=preheader,
        )
        template_id = template_result.get("template_id")
        logger.info(f"Template created: {template_id}")
    except Exception as e:
        logger.warning(
            f"Template API creation failed: {e}. "
            "Falling back to standard campaign creation with code editor."
        )
        return await create_campaign(
            brand=brand,
            name=name,
            subject=subject,
            preheader=preheader,
            body_html=body_html,
            body_plain_text=body_plain_text,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            schedule_timezone=schedule_timezone,
            audience_filter_attribute=audience_filter_attribute,
            audience_filter_operator=audience_filter_operator,
            audience_filter_value=audience_filter_value,
            dry_run=dry_run,
            screenshot_path=screenshot_path,
            headless=headless,
        )

    # Step 2: Browser automation - create campaign and select the template
    manager = SessionManager.get_instance()
    page = await manager.ensure_logged_in(headless=headless)

    # Select workspace
    await select_workspace(page, brand)
    await page.wait_for_timeout(2000)

    # Navigate to campaigns
    logger.info("Navigating to campaigns page...")
    await page.goto(
        "https://dashboard-07.braze.com/engagement/campaigns", timeout=90000
    )
    await page.wait_for_load_state("domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    # Verify workspace
    await select_workspace(page, brand)
    await page.wait_for_timeout(1000)

    # Click Create Campaign
    logger.info("Clicking Create Campaign...")
    create_button = page.get_by_role("button", name="Create Campaign")
    await create_button.wait_for(state="visible", timeout=10000)
    await create_button.click()

    # Select Email channel
    logger.info("Selecting Email channel...")
    await page.wait_for_timeout(1000)
    email_option = page.get_by_role("button", name="Email")
    if await email_option.count() == 0:
        email_option = page.locator("button:has-text('Email')")
    await email_option.wait_for(state="visible", timeout=5000)
    await email_option.click()

    # Select HTML Editor
    logger.info("Selecting HTML Editor...")
    await page.wait_for_timeout(2000)

    html_editor = page.locator("[data-testid='html-editor']")
    if await html_editor.count() == 0:
        html_editor = page.get_by_role("button", name="HTML Editor")
    if await html_editor.count() == 0:
        html_editor = page.get_by_text("HTML Editor", exact=True)
    if await html_editor.count() == 0:
        html_editor = page.get_by_text("HTML Code Editor")
    if await html_editor.count() == 0:
        html_editor = page.locator("button:has-text('HTML')")
    if await html_editor.count() == 0:
        html_editor = page.locator(
            "[class*='card']:has-text('HTML'), [class*='option']:has-text('HTML')"
        )

    if await html_editor.count() > 0:
        await html_editor.first.click()
        logger.info("Selected HTML Editor")
        await page.wait_for_timeout(1000)
    else:
        logger.warning("Could not find HTML Editor option")

    # Try to select the template in the UI
    template_selected = await _select_template_in_ui(page, template_name)

    # Wait for campaign form to load
    logger.info("Waiting for campaign form...")
    name_field = page.get_by_role("textbox", name="Enter Campaign Name")
    if await name_field.count() == 0:
        name_field = page.locator("input[placeholder*='Campaign Name']")
    if await name_field.count() == 0:
        name_field = page.locator("input[placeholder*='campaign name']")
    await name_field.wait_for(state="visible", timeout=15000)

    if template_selected:
        # Template was selected -- subject/preheader/body already filled
        # Just set campaign name
        await name_field.fill(name)
        logger.info(f"Campaign name filled: {name}")

        # Still fill subject/preheader in case template didn't populate them
        # (some Braze flows require manual entry even with templates)
        composer_modal = page.locator("#email-message-composer-portal")
        in_modal = await composer_modal.count() > 0
        container = composer_modal if in_modal else page

        if not in_modal:
            compose_tab = page.get_by_role("button", name="Step Compose Messages")
            if await compose_tab.count() == 0:
                compose_tab = page.get_by_role("button", name="Step Compose", exact=True)
            if await compose_tab.count() == 0:
                compose_tab = page.get_by_role("tab", name="Compose")
            if await compose_tab.count() > 0:
                await compose_tab.first.click()
                await page.wait_for_timeout(2000)

            composer_modal = page.locator("#email-message-composer-portal")
            in_modal = await composer_modal.count() > 0
            container = composer_modal if in_modal else page

        # Verify subject is filled (templates should pre-fill, but check)
        subject_field = container.get_by_label("Subject")
        if await subject_field.count() == 0:
            subject_field = container.locator("input[name='subject']")
        if await subject_field.count() > 0:
            current_value = await subject_field.input_value()
            if not current_value:
                await subject_field.fill(subject)
                logger.info("Subject was empty after template - filled manually")

        # Close modal if open
        if in_modal:
            done_button = container.get_by_role("button", name="Done")
            if await done_button.count() == 0:
                done_button = container.locator("button:has-text('Done')")
            if await done_button.count() > 0:
                await done_button.first.click()
                await page.wait_for_timeout(2000)
    else:
        # Template selection failed - fall back to filling the form with code editor
        logger.warning(
            "Template UI selection failed. Falling back to code editor entry."
        )
        await fill_campaign_form(
            page, name, subject, preheader, body_html, body_plain_text
        )

    # Set audience filter if specified
    if audience_filter_attribute and audience_filter_value:
        await set_audience_filter(
            page,
            audience_filter_attribute,
            audience_filter_operator,
            audience_filter_value,
        )

    # Set schedule if specified
    if schedule_date and schedule_time:
        await set_schedule(
            page,
            schedule_date,
            schedule_time,
            schedule_timezone,
        )

    # Take screenshot if requested
    if screenshot_path:
        await page.screenshot(path=str(screenshot_path))

    if dry_run:
        logger.info("Dry run - not saving campaign")
        return {
            "success": True,
            "dry_run": True,
            "campaign_name": name,
            "template_id": template_id,
            "template_selected_in_ui": template_selected,
            "message": "Dry run completed - campaign not saved (template created via API)",
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
            "current_url": page.url,
        }

    # Save as draft
    logger.info("Saving campaign as draft...")
    save_button = page.get_by_role("button", name="Save as Draft")
    if await save_button.count() == 0:
        save_button = page.locator("button:has-text('Save as Draft')")
    if await save_button.count() == 0:
        save_button = page.locator("[data-testid='save-draft-button']")

    await save_button.wait_for(state="visible", timeout=10000)
    await save_button.click()
    await page.wait_for_timeout(3000)

    success_toast = page.locator("text='Campaign saved'")
    url_changed = "/campaigns/" in page.url and "/edit" not in page.url

    if await success_toast.count() > 0 or url_changed:
        logger.info(f"Campaign created: {name}")
    else:
        logger.info(f"Save clicked, current URL: {page.url}")

    return {
        "success": True,
        "dry_run": False,
        "campaign_name": name,
        "template_id": template_id,
        "template_selected_in_ui": template_selected,
        "message": "Campaign saved as draft (created via template-first approach)",
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "current_url": page.url,
    }


async def create_campaign(
    brand: str,
    name: str,
    subject: str,
    preheader: str = "",
    body_html: Optional[str] = None,
    body_plain_text: Optional[str] = None,
    schedule_date: Optional[str] = None,
    schedule_time: Optional[str] = None,
    schedule_timezone: str = "America/New_York",
    audience_filter_attribute: Optional[str] = None,
    audience_filter_operator: str = "equals",
    audience_filter_value: Optional[str] = None,
    dry_run: bool = True,
    screenshot_path: Optional[Path] = None,
    headless: Optional[bool] = None,
    use_template_api: bool = False,
) -> dict:
    """Create a draft email campaign.

    HTML content is injected into the code editor using fast methods:
    clipboard paste (~1s) or Monaco JS injection (~0s). The slow
    character-by-character typing fallback is only used as a last resort.

    Optionally, set use_template_api=True to use the template-first approach
    instead: creates an email template via API, then selects it in the
    browser UI, avoiding code editor interaction entirely.

    Args:
        brand: Brand code
        name: Campaign name
        subject: Email subject line
        preheader: Email preheader text
        body_html: Optional HTML body
        body_plain_text: Optional plain text body (for plain text emails)
        schedule_date: Optional date in YYYY-MM-DD format (e.g., "2026-02-06")
        schedule_time: Optional time in HH:MM format (e.g., "07:15")
        schedule_timezone: Timezone (default: America/New_York)
        audience_filter_attribute: Attribute to filter on (e.g., "email")
        audience_filter_operator: Filter operator (default: "equals")
        audience_filter_value: Value to filter for
        dry_run: If True, don't save the campaign
        screenshot_path: Optional path for screenshot
        headless: Run browser visibly (False) or headless (True)
        use_template_api: If True and body content is provided, use the
            template-first approach instead of clipboard paste (default: False)

    Returns:
        Dict with success status and details
    """
    # Validate campaign name against naming convention
    _warn_if_name_nonconforming(name)

    # Optionally route to template-first approach
    if use_template_api and (body_html or body_plain_text):
        logger.info("Template API mode enabled - using template-first approach")
        return await create_campaign_from_template(
            brand=brand,
            name=name,
            subject=subject,
            preheader=preheader,
            body_html=body_html,
            body_plain_text=body_plain_text,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            schedule_timezone=schedule_timezone,
            audience_filter_attribute=audience_filter_attribute,
            audience_filter_operator=audience_filter_operator,
            audience_filter_value=audience_filter_value,
            dry_run=dry_run,
            screenshot_path=screenshot_path,
            headless=headless,
        )

    manager = SessionManager.get_instance()
    page = await manager.ensure_logged_in(headless=headless)

    # Select workspace BEFORE navigating to campaigns
    await select_workspace(page, brand)
    
    # Wait for workspace switch to fully complete
    await page.wait_for_timeout(2000)

    # Navigate to campaigns - use longer timeout and domcontentloaded
    logger.info("Navigating to campaigns page...")
    await page.goto("https://dashboard-07.braze.com/engagement/campaigns", timeout=90000)
    await page.wait_for_load_state("domcontentloaded", timeout=60000)
    # Give the page time to render
    await page.wait_for_timeout(3000)
    
    # Verify workspace is still correct after navigation (Braze can reset it)
    logger.info("Verifying workspace after navigation...")
    await select_workspace(page, brand)
    await page.wait_for_timeout(1000)

    # Click Create Campaign
    logger.info("Clicking Create Campaign...")
    create_button = page.get_by_role("button", name="Create Campaign")
    await create_button.wait_for(state="visible", timeout=10000)
    await create_button.click()

    # Select Email channel from the campaign type picker
    logger.info("Selecting Email channel...")
    await page.wait_for_timeout(1000)  # Wait for modal to appear
    email_option = page.get_by_role("button", name="Email")
    if await email_option.count() == 0:
        email_option = page.locator("button:has-text('Email')")
    await email_option.wait_for(state="visible", timeout=5000)
    await email_option.click()

    # Select HTML Editor from the editor type picker
    logger.info("Selecting HTML Editor...")
    await page.wait_for_timeout(2000)  # Wait for editor options to appear
    
    # Take screenshot to see what's available
    await page.screenshot(path="/tmp/braze_editor_selection.png")
    logger.info("Screenshot saved to /tmp/braze_editor_selection.png")
    
    # Try multiple selectors for HTML editor option
    # Look for cards/buttons with HTML-related text
    html_editor = page.locator("[data-testid='html-editor']")
    if await html_editor.count() == 0:
        html_editor = page.get_by_role("button", name="HTML Editor")
    if await html_editor.count() == 0:
        html_editor = page.get_by_text("HTML Editor", exact=True)
    if await html_editor.count() == 0:
        html_editor = page.get_by_text("HTML Code Editor")
    if await html_editor.count() == 0:
        html_editor = page.locator("button:has-text('HTML')")
    if await html_editor.count() == 0:
        # Look for card/panel with HTML text
        html_editor = page.locator("div:has-text('HTML Editor')").locator("button, [role='button']")
    if await html_editor.count() == 0:
        # Try finding radio button or checkbox for HTML
        html_editor = page.get_by_role("radio", name="HTML")
    if await html_editor.count() == 0:
        # Look for any clickable element containing "HTML"
        html_editor = page.locator("[class*='card']:has-text('HTML'), [class*='option']:has-text('HTML')")
    
    if await html_editor.count() > 0:
        await html_editor.first.click()
        logger.info("Selected HTML Editor")
        await page.wait_for_timeout(1000)
    else:
        logger.warning("Could not find HTML Editor option")
        # Print available buttons for debugging
        buttons = await page.locator("button").all_text_contents()
        logger.info(f"Available buttons: {buttons[:10]}")  # First 10

    # Wait for campaign form to load
    logger.info("Waiting for campaign form...")
    name_field = page.get_by_role("textbox", name="Enter Campaign Name")
    if await name_field.count() == 0:
        name_field = page.locator("input[placeholder*='Campaign Name']")
    if await name_field.count() == 0:
        name_field = page.locator("input[placeholder*='campaign name']")
    await name_field.wait_for(state="visible", timeout=15000)

    # Fill the form (name, subject, preheader, body)
    await fill_campaign_form(page, name, subject, preheader, body_html, body_plain_text)

    # Set audience filter if specified
    if audience_filter_attribute and audience_filter_value:
        await set_audience_filter(
            page,
            audience_filter_attribute,
            audience_filter_operator,
            audience_filter_value,
        )

    # Set schedule if specified
    if schedule_date and schedule_time:
        await set_schedule(
            page,
            schedule_date,
            schedule_time,
            schedule_timezone,
        )

    # Take screenshot if requested
    screenshot_data = None
    if screenshot_path:
        screenshot_data = await page.screenshot(path=str(screenshot_path))

    if dry_run:
        logger.info("Dry run - not saving campaign")
        return {
            "success": True,
            "dry_run": True,
            "campaign_name": name,
            "message": "Dry run completed - campaign not saved",
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
            "current_url": page.url,
        }

    # Save as draft
    logger.info("Saving campaign as draft...")
    save_button = page.get_by_role("button", name="Save as Draft")
    if await save_button.count() == 0:
        # Try alternate selectors
        save_button = page.locator("button:has-text('Save as Draft')")
    if await save_button.count() == 0:
        save_button = page.locator("[data-testid='save-draft-button']")
    
    await save_button.wait_for(state="visible", timeout=10000)
    await save_button.click()
    
    # Wait for save to complete - look for success toast or URL change
    # Give it time to save rather than relying on networkidle
    await page.wait_for_timeout(3000)
    
    # Check for success indicators
    success_toast = page.locator("text='Campaign saved'")
    url_changed = "/campaigns/" in page.url and "/edit" not in page.url
    
    if await success_toast.count() > 0 or url_changed:
        logger.info(f"Campaign created: {name}")
    else:
        logger.info(f"Save clicked, current URL: {page.url}")

    return {
        "success": True,
        "dry_run": False,
        "campaign_name": name,
        "message": "Campaign saved as draft",
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "current_url": page.url,
    }


async def archive_campaign(
    brand: str,
    campaign_name: str,
) -> dict:
    """Archive a campaign by name.

    Args:
        brand: Brand code
        campaign_name: Name of campaign to archive

    Returns:
        Dict with success status
    """
    manager = SessionManager.get_instance()
    page = await manager.ensure_logged_in()

    # Select workspace
    await select_workspace(page, brand)

    # Navigate to campaigns
    await page.goto("https://dashboard-07.braze.com/engagement/campaigns", timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=30000)

    # Clear status filter to show all campaigns including drafts
    status_filter = page.locator("[data-testid='status-filter']")
    if await status_filter.count() > 0:
        await status_filter.click()
        # Clear any filters
        clear_button = page.get_by_role("button", name="Clear")
        if await clear_button.count() > 0:
            await clear_button.click()
            await page.wait_for_load_state("networkidle", timeout=10000)

    # Search for campaign
    search_box = page.get_by_placeholder("Search")
    if await search_box.count() > 0:
        await search_box.fill(campaign_name)
        # Wait for search results to update
        await page.wait_for_load_state("networkidle", timeout=10000)

    # Find the campaign row
    campaign_row = page.get_by_role("row", name=campaign_name)
    if await campaign_row.count() == 0:
        return {
            "success": False,
            "message": f"Campaign not found: {campaign_name}",
        }

    # Click More Actions
    more_actions = campaign_row.get_by_role("button", name="More Actions")
    await more_actions.click()

    # Click Archive
    archive_option = page.get_by_role("menuitem", name="Archive")
    await archive_option.wait_for(state="visible", timeout=5000)
    await archive_option.click()

    # Confirm archive
    confirm_button = page.get_by_role("button", name="Archive campaign")
    await confirm_button.wait_for(state="visible", timeout=5000)
    await confirm_button.click()

    # Wait for archive to complete
    await page.wait_for_load_state("networkidle", timeout=10000)

    logger.info(f"Campaign archived: {campaign_name}")
    return {
        "success": True,
        "campaign_name": campaign_name,
        "message": "Campaign archived successfully",
    }


async def render_html(
    html: str,
    output_path: Optional[str] = None,
    width: int = 600,
) -> str:
    """Render HTML to PNG screenshot.

    Args:
        html: HTML content to render
        output_path: Output file path (auto-generated if not provided)
        width: Viewport width in pixels

    Returns:
        Path to screenshot file
    """
    manager = SessionManager.get_instance()
    page = await manager.get_page()

    # Generate output path if not provided
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"/tmp/braze_render_{timestamp}.png"

    # Set viewport width
    await page.set_viewport_size({"width": width, "height": 900})

    # Load HTML content
    await page.set_content(html)
    await page.wait_for_load_state("networkidle")

    # Take full-page screenshot
    await page.screenshot(path=output_path, full_page=True)

    logger.info(f"HTML rendered to: {output_path}")
    return output_path


async def close_session() -> dict:
    """Close browser session.

    Returns:
        Dict with success status
    """
    manager = SessionManager.get_instance()
    await manager.close()

    return {
        "success": True,
        "message": "Browser session closed",
    }
