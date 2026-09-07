#!/usr/bin/env python3
"""Edit the existing BUR PT Memorial Day Final Hours campaign in Braze.

Regenerates the email HTML + subject from the Asana task, runs HTML QA, then
updates the existing campaign (Edit Draft → Compose → Edit message → fill
subject + HTML → UTM templates → Done → Save), then runs the full QA flow.

Campaign: P_EM_2026_06_02_BW_PT_Memorial_Day_Final_Hours
Braze:     https://dashboard-07.braze.com/engagement/campaigns/6a18e3e715f1550081b16a3e/67093a1f24ebbe0065cb9c77
Asana GID: 1214163987538987
"""
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_pt_campaign import (
    _configure_link_templates,
    build_campaign_config,
    fetch_task_by_gid,
    get_campaign_url_from_page,
    load_brand_config,
    parse_asana_task,
    save_as_draft,
)
from build_push_campaign import wait_for_campaign_editor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BRAND = "BUR"
CAMPAIGN_ID = "6a18e3e715f1550081b16a3e"
WORKSPACE_ID = "67093a1f24ebbe0065cb9c77"
ASANA_GID = "1214163987538987"
SCRIPT_DIR = Path(__file__).parent


async def _debug(page, name: str) -> None:
    try:
        path = str(SCRIPT_DIR / f"debug_bur_pt_edit_{name}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info("Screenshot: %s", path)
    except Exception:
        pass


async def edit_campaign(subject: str, html_body: str, utm_templates) -> str:
    """Navigate to the existing campaign, update subject + HTML, save. Returns final URL."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-save-password-bubble", "--disable-password-manager-reauthentication"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            await ensure_logged_in(page)
            await select_workspace(page, BRAND)

            campaign_url = f"https://dashboard-07.braze.com/engagement/campaigns/{CAMPAIGN_ID}/{WORKSPACE_ID}"
            logger.info("Navigating to campaign: %s", campaign_url)
            await page.goto(campaign_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            await _debug(page, "01_after_nav")

            # Click "Edit Draft" if present
            for sel in [
                page.get_by_role("button", name="Edit Draft"),
                page.get_by_role("link", name="Edit Draft"),
                page.locator("a:has-text('Edit Draft')"),
                page.locator("button:has-text('Edit Draft')"),
            ]:
                try:
                    if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                        await sel.first.click()
                        await page.wait_for_timeout(3000)
                        logger.info("Clicked 'Edit Draft'")
                        break
                except Exception:
                    continue

            await _debug(page, "02_after_edit_draft")

            try:
                await wait_for_campaign_editor(page)
            except Exception as e:
                logger.warning("wait_for_campaign_editor: %s", e)

            # Navigate to Compose step
            for compose_name in ["Compose Messages", "Compose"]:
                try:
                    btn = page.get_by_role("button", name=compose_name)
                    if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        logger.info("Clicked '%s'", compose_name)
                        break
                except Exception:
                    continue

            await _debug(page, "03_compose_step")

            # Log visible buttons for diagnostics
            btn_texts = await page.evaluate("""() => {
                return [...document.querySelectorAll('button, a[role="button"]')]
                    .filter(el => el.offsetParent !== null)
                    .map(el => el.textContent.trim().substring(0, 50))
                    .filter(t => t.length > 0);
            }""")
            logger.info("Visible buttons: %s", btn_texts[:30])

            # Open HTML editor via "Edit message" button
            opened = False
            for sel_name in ["Edit message", "Edit Message", "Edit"]:
                for sel in [
                    page.get_by_role("button", name=sel_name),
                    page.locator(f"button:has-text('{sel_name}')"),
                ]:
                    try:
                        if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                            await sel.first.click()
                            await page.wait_for_timeout(4000)
                            logger.info("Clicked '%s' — editor should be open", sel_name)
                            opened = True
                            break
                    except Exception:
                        continue
                if opened:
                    break

            await _debug(page, "04_editor_open")

            if not opened:
                raise RuntimeError("Could not open email editor — check debug screenshots")

            # Verify Monaco (not BEE)
            monaco_count = await page.locator(".monaco-editor").count()
            bee_count = len([f for f in page.frames if "getbee.io" in f.url])
            logger.info("Monaco editors: %d, BEE frames: %d", monaco_count, bee_count)
            if bee_count > 0 and monaco_count == 0:
                raise RuntimeError("BEE editor opened — this is a DnD campaign. Aborting.")

            # --- Update subject in Sending Settings tab ---
            # The subject field is a Monaco editor — use the Monaco JS API to
            # set the value (clicking the underlying textarea times out because
            # Monaco's overlay div intercepts pointer events).
            sending_tab = page.get_by_label("Sending Settings")
            try:
                await sending_tab.click(timeout=5000)
                await page.wait_for_timeout(500)
            except Exception as e:
                logger.warning("Could not click Sending Settings tab: %s", e)

            subject_json = json.dumps(subject)
            subj_result = await page.evaluate(f"""
                (() => {{
                    const s = {subject_json};
                    // When Sending Settings tab is active, the subject editor is the
                    // first Monaco editor; the HTML body editor has not been initialized
                    // yet (Content tab not yet visited), so there should be only 1-2 editors.
                    // Prefer the model with the shortest current value (subject vs preheader).
                    try {{
                        const models = window.monaco?.editor?.getModels?.() || [];
                        // Sort by value length ascending; subject is the shortest
                        const sorted = [...models].sort((a, b) => a.getValue().length - b.getValue().length);
                        if (sorted.length > 0) {{
                            sorted[0].setValue(s);
                            return {{ ok: true, method: 'models_sorted', models: models.length }};
                        }}
                    }} catch (e) {{}}
                    try {{
                        const editors = window.monaco?.editor?.getEditors?.() || [];
                        if (editors.length > 0) {{
                            editors[0].setValue(s);
                            return {{ ok: true, method: 'editors[0]' }};
                        }}
                    }} catch (e) {{}}
                    return {{ ok: false }};
                }})()
            """)
            if subj_result.get("ok"):
                logger.info("Subject set via Monaco (%s): %s", subj_result.get("method"), subject)
            else:
                # Clipboard fallback: paste into Monaco subject editor
                logger.warning("Monaco API failed for subject (%s) — using clipboard", subj_result)
                subj_monaco = page.locator(".monaco-editor").first
                await page.evaluate(f"navigator.clipboard.writeText({subject_json})")
                await subj_monaco.click()
                await page.wait_for_timeout(200)
                await page.keyboard.press("Meta+a")
                await page.wait_for_timeout(100)
                await page.keyboard.press("Meta+v")
                await page.wait_for_timeout(300)
                logger.info("Subject set via clipboard paste: %s", subject)

            # --- Update HTML in Content tab ---
            content_tab = page.locator("button[aria-label='Content']:not([data-route])")
            if await content_tab.count() == 0:
                content_tab = page.get_by_label("Content").nth(1)
            try:
                await content_tab.click(timeout=5000)
                await page.wait_for_timeout(500)
            except Exception as e:
                logger.warning("Could not click Content tab: %s", e)

            html_json = json.dumps(html_body)
            monaco_editor = page.locator(".monaco-editor")
            if await monaco_editor.count() > 0:
                result = await page.evaluate(f"""
                    (() => {{
                        const content = {html_json};
                        try {{
                            const editors = window.monaco?.editor?.getEditors?.();
                            if (editors && editors.length > 0) {{
                                editors[0].setValue(content);
                                return {{ success: true, method: 'getEditors' }};
                            }}
                        }} catch (e) {{}}
                        try {{
                            const models = window.monaco?.editor?.getModels?.();
                            if (models && models.length > 0) {{
                                models[0].setValue(content);
                                return {{ success: true, method: 'getModels' }};
                            }}
                        }} catch (e) {{}}
                        return {{ success: false }};
                    }})()
                """)
                if result.get("success"):
                    logger.info("HTML set via Monaco API (%s)", result["method"])
                else:
                    await page.evaluate(f"navigator.clipboard.writeText({html_json})")
                    await monaco_editor.first.click()
                    await page.wait_for_timeout(200)
                    await page.keyboard.press("Meta+a")
                    await page.wait_for_timeout(100)
                    await page.keyboard.press("Meta+v")
                    await page.wait_for_timeout(500)
                    logger.info("HTML set via clipboard paste")
            else:
                # Textarea fallback
                editor = page.get_by_role("textbox", name="Editor content;Press Alt+F1")
                if await editor.count() > 0:
                    await editor.fill(html_body, timeout=10000)
                    logger.info("HTML set via textarea fill()")
                else:
                    logger.warning("No Monaco editor or textarea found")

            await _debug(page, "05_html_injected")

            # Apply UTM link templates
            await _configure_link_templates(page, utm_templates)

            # Close editor
            for done_sel in [
                page.get_by_role("button", name="Done", exact=True),
                page.locator("button:has-text('Done')").last,
            ]:
                try:
                    if await done_sel.count() > 0 and await done_sel.is_visible(timeout=3000):
                        await done_sel.click()
                        await page.wait_for_timeout(1500)
                        logger.info("Editor closed via Done")
                        break
                except Exception:
                    continue

            # Save as draft
            await save_as_draft(page, dry_run=False)
            await page.wait_for_timeout(2000)
            braze_url = get_campaign_url_from_page(page.url) or page.url
            logger.info("Saved. URL: %s", braze_url)

            await _debug(page, "06_final")
            return braze_url

        finally:
            await context.close()
            await browser.close()


def main() -> None:
    # --- Step 1: Generate email content from Asana task ---
    global_config = load_brand_config()

    logger.info("Fetching Asana task %s...", ASANA_GID)
    task_raw = fetch_task_by_gid(ASANA_GID)
    if not task_raw:
        raise RuntimeError(f"Could not fetch Asana task {ASANA_GID}")

    task = parse_asana_task(task_raw)
    if not task:
        raise RuntimeError("parse_asana_task returned None — check brand/channel fields")

    config = build_campaign_config(task, None, global_config)

    subject = config["subject"]
    html_body = config["html_body"]
    utm_templates = config.get("utm_templates", "all")

    logger.info("Subject:    %s", subject)
    logger.info("Body text:\n%s", task["body_copy"])
    logger.info("HTML body:  %d chars", len(html_body))

    # --- Step 2: HTML QA ---
    logger.info("Running HTML QA...")
    try:
        from validate_html import validate_html as _validate_html
        errors, warnings = _validate_html(
            html_content=html_body,
            brand=BRAND,
            channel="email",
            subscription_group="Marketing",
        )
        if warnings:
            print(f"\n  QA WARNINGS ({len(warnings)}):")
            for w in warnings:
                print(f"    WARN: {w}")
        if errors:
            print(f"\n  QA ERRORS ({len(errors)}):")
            for e in errors:
                print(f"    ERROR: {e}")
            raise RuntimeError("HTML QA failed — fix errors before injecting")
        logger.info("HTML QA passed")
    except ImportError:
        logger.warning("validate_html not available — skipping HTML QA")

    # --- Step 3: Edit existing campaign in Braze ---
    logger.info("Editing campaign %s...", CAMPAIGN_ID)
    braze_url = asyncio.run(edit_campaign(subject, html_body, utm_templates))
    print(f"\nEdit complete. Campaign: {braze_url}")

    # --- Step 4: Full QA (browser + test send) ---
    logger.info("Running full QA flow...")
    qa_result = subprocess.run(
        [
            "uv", "run", "python",
            "scripts/braze_automation/qa_designed_email.py",
            "--task-gid", ASANA_GID,
            "--brand", BRAND,
        ],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if qa_result.returncode != 0:
        logger.warning("QA script exited with code %d", qa_result.returncode)


if __name__ == "__main__":
    main()
