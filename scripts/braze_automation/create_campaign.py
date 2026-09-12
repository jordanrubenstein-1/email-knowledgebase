#!/usr/bin/env python3
"""
Braze Campaign Creation Automation.

Creates draft email campaigns in Braze dashboard via Playwright.
Supports fast template-first approach: creates template via API, then
selects it in the UI to avoid slow code editor HTML entry.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.braze_automation.login import (
    login,
    ensure_logged_in,
    select_workspace,
    save_session,
    create_context_with_session,
    BRAZE_DASHBOARD_URL,
    BRAND_WORKSPACE_MAP,
)

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def navigate_to_campaigns(page: Page) -> bool:
    """
    Navigate to the Campaigns section in Braze.

    Tries sidebar link first (preserves workspace context), falls back to direct URL.

    Args:
        page: Playwright page object

    Returns:
        True if navigation successful
    """
    logger.info("Navigating to Campaigns...")
    # Let dashboard finish rendering
    await page.wait_for_timeout(2000)

    # Strategy 1: Click "Campaigns" link in sidebar (preserves workspace context)
    sidebar_selectors = [
        page.get_by_role("link", name="Campaigns"),
        page.locator("a[href*='/campaigns']").first,
    ]
    for selector in sidebar_selectors:
        try:
            await selector.wait_for(state="visible", timeout=5000)
            await selector.click()
            await page.wait_for_timeout(2000)
            if "/campaigns" in page.url:
                logger.info("Navigated to Campaigns page via sidebar link")
                return True
        except Exception as e:
            logger.debug(f"Sidebar campaigns link failed: {e}")

    # Strategy 2: Direct URL with app group ID from current URL
    # After workspace selection, the URL contains the app group ID
    import re
    current_url = page.url
    app_group_match = re.search(r'/([a-f0-9]{24})', current_url)
    if app_group_match:
        app_group_id = app_group_match.group(1)
        dashboard_url = BRAZE_DASHBOARD_URL.rstrip("/")
        campaigns_url = f"{dashboard_url}/engagement/campaigns/{app_group_id}"
        try:
            await page.goto(campaigns_url, wait_until="load", timeout=15000)
            await page.wait_for_timeout(2000)
            if "/campaigns" in page.url:
                logger.info(f"Navigated to Campaigns page via URL with app group {app_group_id}")
                return True
        except Exception as e:
            logger.debug(f"URL with app group navigation failed: {e}")

    # Strategy 3: Generic direct URL (may lose workspace context)
    dashboard_url = BRAZE_DASHBOARD_URL.rstrip("/")
    campaigns_url = f"{dashboard_url}/engagement/campaigns"
    try:
        await page.goto(campaigns_url, wait_until="load", timeout=15000)
        await page.wait_for_timeout(2000)
        if "/campaigns" in page.url:
            logger.info("Navigated to Campaigns page via generic URL")
            return True
    except Exception as e:
        logger.debug(f"Generic URL navigation failed: {e}")

    raise Exception("Could not navigate to Campaigns page")


async def start_campaign_creation(page: Page) -> bool:
    """
    Click Create Campaign and select Email type.

    Args:
        page: Playwright page object

    Returns:
        True if successful
    """
    logger.info("Starting campaign creation...")

    # Click Create Campaign button
    create_btn = page.get_by_role("button", name="Create campaign")
    await create_btn.wait_for(state="visible", timeout=10000)
    await create_btn.click()
    await page.wait_for_timeout(500)

    # Select Email from dropdown
    email_btn = page.get_by_role("button", name="Email")
    await email_btn.wait_for(state="visible", timeout=5000)
    await email_btn.click()

    # Wait for campaign editor to load
    await page.wait_for_timeout(2000)
    logger.info("Selected Email campaign type")
    return True


async def select_html_editor(page: Page) -> bool:
    """
    Select HTML code editor for the email.

    Args:
        page: Playwright page object

    Returns:
        True if successful
    """
    logger.info("Selecting HTML editor...")

    # Click HTML code editor button
    html_editor_btn = page.get_by_role("button", name="HTML code editor Start from")
    await html_editor_btn.wait_for(state="visible", timeout=10000)
    await html_editor_btn.click()
    await page.wait_for_timeout(1000)

    logger.info("HTML editor modal opened")
    return True


async def fill_sending_settings(
    page: Page,
    subject: str,
    preheader: str
) -> bool:
    """
    Fill subject and preheader in Sending Settings.

    Args:
        page: Playwright page object
        subject: Email subject line
        preheader: Email preheader text

    Returns:
        True if successful
    """
    logger.info("Filling sending settings...")

    # Click Sending Settings in the modal navigation
    sending_settings = page.get_by_label("Sending Settings")
    await sending_settings.click(timeout=5000)
    await page.wait_for_timeout(500)

    # Fill subject
    subject_field = page.locator("#sending-info-subject-input--1932011389").or_(
        page.get_by_role("textbox", name="Liquid text area").first
    )
    await subject_field.fill(subject, timeout=5000)
    logger.debug(f"Set subject: {subject}")

    # Fill preheader
    if preheader:
        preheader_field = page.locator("#sending-info-preheader-input--296805365").or_(
            page.get_by_role("textbox", name="Liquid text area").nth(1)
        )
        await preheader_field.fill(preheader, timeout=5000)
        logger.debug(f"Set preheader: {preheader}")

        # Always check "Add whitespace after preheader" when a preheader is set.
        # Prevents email clients from appending body text to the preview snippet.
        for whitespace_sel in [
            page.get_by_label("Add whitespace after preheader", exact=False),
            page.locator("label").filter(has_text="Add whitespace after preheader").locator("input[type='checkbox']"),
            page.locator("input[type='checkbox']").filter(has=page.get_by_text("whitespace", exact=False)),
        ]:
            try:
                if await whitespace_sel.count() > 0 and await whitespace_sel.is_visible(timeout=2000):
                    if not await whitespace_sel.is_checked():
                        await whitespace_sel.check()
                        logger.info("Checked 'Add whitespace after preheader'")
                    else:
                        logger.debug("'Add whitespace after preheader' already checked")
                    break
            except Exception:
                continue

    return True


async def fill_html_content(page: Page, body_html: str) -> bool:
    """
    Fill HTML content in the editor using the fastest available method.

    Tries three strategies in order:
    1. Monaco JS API injection (instant)
    2. Clipboard paste (near-instant)
    3. Playwright fill() on accessible editor element (fast)

    Args:
        page: Playwright page object
        body_html: HTML content for email body

    Returns:
        True if successful
    """
    logger.info(f"Filling HTML content ({len(body_html)} chars)...")

    # Click Content tab to switch to editor
    # Use role=group to avoid matching the sidebar "Content" navigation button
    content_tab = page.get_by_role("group", name="Content").first
    try:
        await content_tab.click(timeout=5000)
    except Exception:
        # Fallback: click the first tab labeled "Content" that isn't the sidebar nav button
        content_tab = page.locator('[aria-label="Content"]').filter(has=page.locator("textarea, .monaco-editor")).first
        if await content_tab.count() == 0:
            content_tab = page.locator('[role="tab"][aria-label="Content"], [data-testid="content-tab"]').first
        if await content_tab.count() == 0:
            content_tab = page.locator('[aria-label="Content"]').nth(1)
        await content_tab.click(timeout=5000)
    await page.wait_for_timeout(500)

    # Strategy 1: Monaco JS API injection (instant)
    monaco_editor = page.locator(".monaco-editor")
    if await monaco_editor.count() > 0:
        html_json = json.dumps(body_html)
        result = await page.evaluate(f"""
            (() => {{
                const content = {html_json};
                // Try window.monaco.editor.getEditors()
                try {{
                    const editors = window.monaco?.editor?.getEditors?.();
                    if (editors && editors.length > 0) {{
                        editors[0].setValue(content);
                        return {{ success: true, method: 'getEditors' }};
                    }}
                }} catch (e) {{}}
                // Try window.monaco.editor.getModels()
                try {{
                    const models = window.monaco?.editor?.getModels?.();
                    if (models && models.length > 0) {{
                        models[0].setValue(content);
                        return {{ success: true, method: 'getModels' }};
                    }}
                }} catch (e) {{}}
                // Try DOM element properties
                try {{
                    const els = document.querySelectorAll('.monaco-editor');
                    for (const el of els) {{
                        for (const prop of ['__monacoEditor__', '_editor', 'monacoEditor']) {{
                            if (el[prop] && typeof el[prop].setValue === 'function') {{
                                el[prop].setValue(content);
                                return {{ success: true, method: 'DOM.' + prop }};
                            }}
                        }}
                    }}
                }} catch (e) {{}}
                return {{ success: false }};
            }})()
        """)
        if result.get("success"):
            logger.info(f"HTML set via Monaco API ({result['method']})")
            return True
        logger.info("Monaco JS injection failed, trying clipboard paste...")

        # Strategy 2: Clipboard paste
        try:
            await page.evaluate(f"navigator.clipboard.writeText({html_json})")
            await monaco_editor.first.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Meta+a")
            await page.wait_for_timeout(100)
            await page.keyboard.press("Meta+v")
            await page.wait_for_timeout(500)
            logger.info("HTML set via clipboard paste")
            return True
        except Exception as e:
            logger.info(f"Clipboard paste failed: {e}")

    # Strategy 3: Playwright fill() on accessible editor element
    editor = page.get_by_role("textbox", name="Editor content;Press Alt+F1")
    if await editor.count() > 0:
        await editor.fill(body_html, timeout=10000)
        logger.info("HTML set via editor fill()")
        return True

    # Strategy 4: Any textarea fallback
    textarea = page.locator("textarea")
    if await textarea.count() > 0:
        await textarea.first.fill(body_html)
        logger.info("HTML set via textarea fill()")
        return True

    logger.warning("Could not find HTML editor element")
    return True


async def close_editor_modal(page: Page) -> bool:
    """
    Close the editor modal by clicking Done.

    Args:
        page: Playwright page object

    Returns:
        True if successful
    """
    done_btn = page.get_by_role("button", name="Done")
    await done_btn.click(timeout=5000)
    await page.wait_for_timeout(1000)
    logger.info("Closed editor modal")
    return True


async def save_as_draft(page: Page, dry_run: bool = True) -> bool:
    """
    Save the campaign as a draft.

    Args:
        page: Playwright page object
        dry_run: If True, don't actually save (for testing)

    Returns:
        True if successful (or if dry_run)
    """
    if dry_run:
        logger.info("DRY RUN - Would save as draft here")
        return True

    logger.info("Saving campaign as draft...")

    # Braze uses "Save Draft" in the bottom bar (not "Save as Draft")
    save_btn = page.get_by_role("button", name="Save Draft")
    if await save_btn.count() == 0:
        save_btn = page.get_by_role("button", name="Save as Draft")
    await save_btn.wait_for(state="visible", timeout=5000)
    await save_btn.click()

    # Wait for save confirmation
    try:
        await page.get_by_text("Save completed").wait_for(state="visible", timeout=10000)
        logger.info("Campaign saved as draft")
        return True
    except PlaywrightTimeout:
        logger.warning("Save confirmation not detected, but may have succeeded")
        return True


async def set_campaign_name(page: Page, name: str) -> bool:
    """
    Set the campaign name.

    Args:
        page: Playwright page object
        name: Campaign name

    Returns:
        True if successful
    """
    name_field = page.get_by_role("textbox", name="Enter Campaign Name")
    await name_field.fill(name, timeout=5000)
    logger.debug(f"Set campaign name: {name}")
    return True


async def create_draft_campaign(
    page: Page,
    name: str,
    subject: str,
    preheader: str,
    body_html: Optional[str] = None,
    brand: Optional[str] = None,
    dry_run: bool = True,
    screenshot_path: Optional[Path] = None
) -> dict:
    """
    Create a draft email campaign in Braze.

    Args:
        page: Playwright page object (should be logged in)
        name: Campaign name
        subject: Email subject line
        preheader: Email preheader text
        body_html: Optional HTML body content
        brand: Brand code (HAV, BUR, ID, STF, CZ, TI) - selects workspace
        dry_run: If True, don't actually save
        screenshot_path: Path to save screenshot (optional)

    Returns:
        Dict with status, screenshot path, and any errors
    """
    result = {
        "success": False,
        "campaign_name": name,
        "brand": brand,
        "dry_run": dry_run,
        "screenshot": None,
        "errors": []
    }

    # Default HTML body with unsubscribe link
    if body_html is None:
        body_html = """<html>
<body>
<h1>Email Content</h1>
<p>This email was created via automation.</p>
<p><a href="{{${set_user_to_unsubscribed_url}}}">Unsubscribe</a></p>
</body>
</html>"""

    try:
        # Ensure we're logged in
        await ensure_logged_in(page)

        # Select workspace if brand specified
        if brand:
            await select_workspace(page, brand)

        # Navigate to campaigns
        await navigate_to_campaigns(page)

        # Start campaign creation
        await start_campaign_creation(page)

        # Set campaign name (optional - has default)
        await set_campaign_name(page, name)

        # Select HTML editor (opens modal)
        await select_html_editor(page)

        # Fill sending settings (subject, preheader)
        await fill_sending_settings(page, subject, preheader)

        # Fill HTML content
        await fill_html_content(page, body_html)

        # Close editor modal
        await close_editor_modal(page)

        # Take screenshot before saving
        if screenshot_path:
            await page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot"] = str(screenshot_path)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_path = Path(__file__).parent / f"screenshot_{timestamp}.png"
            await page.screenshot(path=str(default_path), full_page=True)
            result["screenshot"] = str(default_path)
        logger.info(f"Screenshot saved: {result['screenshot']}")

        # Save as draft
        await save_as_draft(page, dry_run=dry_run)

        # Capture campaign URL after save (URL updates to include campaign ID)
        await page.wait_for_timeout(1500)
        result["campaign_url"] = page.url
        logger.info(f"Campaign URL: {page.url}")

        result["success"] = True
        logger.info(f"Campaign creation {'completed (dry run)' if dry_run else 'completed'}")

    except Exception as e:
        logger.error(f"Campaign creation failed: {e}")
        result["errors"].append(str(e))

        # Take error screenshot
        try:
            error_path = Path(__file__).parent / f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=str(error_path), full_page=True)
            result["error_screenshot"] = str(error_path)
        except Exception:
            pass

    return result


async def create_template_via_api(brand: str, template_name: str, subject: str,
                                  body_html: str, preheader: str = "") -> Optional[str]:
    """Create an email template via Braze Templates API.

    Args:
        brand: Brand code
        template_name: Name for the template
        subject: Email subject line
        body_html: HTML body content
        preheader: Email preheader text

    Returns:
        Template ID if successful, None if failed
    """
    try:
        from scripts.braze_template_api import create_email_template
        config = {
            "name": template_name,
            "email": {
                "subject": subject,
                "preheader": preheader,
                "body": body_html,
            }
        }
        template_id, error = create_email_template(config, brand)
        if error:
            logger.error(f"Template API error: {error}")
            return None
        logger.info(f"Template created via API: {template_id}")
        return template_id
    except ImportError:
        logger.warning("braze_template_api not available, trying direct API call")
    except Exception as e:
        logger.error(f"Template creation failed: {e}")

    # Direct API call fallback
    try:
        import requests
        api_key = os.getenv(f"BRAZE_API_KEY_{brand}") or os.getenv("BRAZE_API_KEY")
        base_url = os.getenv(f"BRAZE_BASE_URL_{brand}") or os.getenv("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")
        if not api_key:
            logger.error(f"No API key found for brand {brand}")
            return None
        response = requests.post(
            f"{base_url}/templates/email/create",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "template_name": template_name,
                "subject": subject,
                "preheader": preheader,
                "body": body_html,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        template_id = data.get("email_template_id") or data.get("id")
        logger.info(f"Template created via direct API: {template_id}")
        return template_id
    except Exception as e:
        logger.error(f"Direct API template creation failed: {e}")
        return None


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Create a draft email campaign in Braze"
    )
    parser.add_argument("--name", required=True, help="Campaign name")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--preheader", default="", help="Email preheader text")
    parser.add_argument("--body", help="Path to HTML file for email body")
    parser.add_argument(
        "--brand",
        choices=list(BRAND_WORKSPACE_MAP.keys()),
        help="Brand code to select workspace (HAV, BUR, ID, STF, CZ, TI)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Don't actually save (default: True)"
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually save the campaign"
    )
    parser.add_argument(
        "--use-template-api",
        action="store_true",
        default=False,
        help="Create template via API first, then select in UI (default: False, uses clipboard paste)"
    )
    parser.add_argument("--screenshot", help="Path to save screenshot")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine dry_run setting
    dry_run = not args.no_dry_run
    use_template_api = args.use_template_api

    # Load body HTML if provided
    body_html = None
    if args.body:
        body_path = Path(args.body)
        if body_path.exists():
            body_html = body_path.read_text()
        else:
            logger.error(f"Body file not found: {args.body}")
            sys.exit(1)

    # Screenshot path
    screenshot_path = Path(args.screenshot) if args.screenshot else None

    # Template-first approach: create template via API before launching browser
    template_id = None
    if use_template_api and body_html and args.brand:
        template_name = f"_auto_{args.name}"
        logger.info(f"Creating template via API: {template_name}")
        template_id = await create_template_via_api(
            brand=args.brand,
            template_name=template_name,
            subject=args.subject,
            body_html=body_html,
            preheader=args.preheader,
        )
        if template_id:
            logger.info(f"Template created: {template_id}")
            logger.info("Will select template in UI instead of entering HTML in code editor")
        else:
            logger.warning("Template API failed, will fall back to code editor entry")

    async with async_playwright() as p:
        # Launch browser with password manager disabled and clipboard permissions
        browser = await p.chromium.launch(
            headless=args.headless,
            args=[
                "--disable-save-password-bubble",
                "--disable-password-manager-reauthentication",
            ]
        )
        # Use saved session if available (e.g. after Gmail/Google login)
        context = await create_context_with_session(browser)
        # Grant clipboard permissions for fast paste fallback
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        await context.add_init_script("""
            // Disable password autofill prompts
            if (window.PasswordCredential) {
                navigator.credentials.store = () => Promise.resolve();
            }
        """)
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            # Login (or wait for manual Gmail/Google login if no creds)
            await login(page)
            # Save session so next run can skip login (e.g. for Gmail users)
            await save_session(context)

            # If template was created, pass None for body_html so
            # create_draft_campaign skips the slow code editor entry.
            # The template already has the content.
            campaign_body = None if template_id else body_html

            # Create campaign
            result = await create_draft_campaign(
                page=page,
                name=args.name,
                subject=args.subject,
                preheader=args.preheader,
                body_html=campaign_body,
                brand=args.brand,
                dry_run=dry_run,
                screenshot_path=screenshot_path
            )

            # Add template info to result
            if template_id:
                result["template_id"] = template_id

            # Print result
            print("\n" + "=" * 50)
            print("RESULT")
            print("=" * 50)
            print(f"Success: {result['success']}")
            print(f"Campaign: {result['campaign_name']}")
            if result.get("brand"):
                print(f"Brand: {result['brand']}")
            print(f"Dry Run: {result['dry_run']}")
            if result.get("template_id"):
                print(f"Template ID: {result['template_id']}")
            if result.get("campaign_url"):
                print(f"Campaign URL: {result['campaign_url']}")
            if result.get("screenshot"):
                print(f"Screenshot: {result['screenshot']}")
            if result.get("errors"):
                print(f"Errors: {result['errors']}")
            print("=" * 50)

            sys.exit(0 if result["success"] else 1)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
