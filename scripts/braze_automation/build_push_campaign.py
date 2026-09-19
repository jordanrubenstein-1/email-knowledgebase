#!/usr/bin/env python3
"""
Build push notification campaigns in Braze from Asana tasks.

End-to-end automation using a *duplicate-based* workflow:
  1. Fetches push tasks from Asana (Channel = Push, Status = "Ready to Code")
  2. Parses push copy (Title / Description) from the task notes
  3. Detects audience: DPS → Pre-Converted (PC), MP → Converted (CONV)
  4. Opens Braze dashboard via Playwright
  5. Navigates to a reference campaign and duplicates it
  6. Edits: campaign name, push title, push message, delivery date
     (audience, deep links, on-click behavior, conversions carry over)
  7. Saves as draft
  8. Writes Braze campaign link back to Asana

Combined tasks (no DPS/MP in name) are split into TWO campaigns — one
PC and one CONV — each with the correct reference campaign, audience,
and deep link.

Usage:
    # Preview what would be built (no browser launched)
    uv run python scripts/braze_automation/build_push_campaign.py \\
      --task 1212881019496721 --dry-run

    # All "Ready to Code" push tasks
    uv run python scripts/braze_automation/build_push_campaign.py \\
      --dry-run

    # Actually build in Braze
    uv run python scripts/braze_automation/build_push_campaign.py \\
      --task 1212881019496721 --no-dry-run

    # Build without confirmation prompts
    uv run python scripts/braze_automation/build_push_campaign.py \\
      --task 1212881019496721 --no-dry-run --yes
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from playwright.async_api import (
    Page,
    async_playwright,
    TimeoutError as PlaywrightTimeout,
)
from dotenv import load_dotenv
import requests

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from login import (
    login,
    ensure_logged_in,
    select_workspace,
    save_session,
    create_context_with_session,
    BRAZE_DASHBOARD_URL,
    BRAND_WORKSPACE_MAP,
    BRAND_WORKSPACE_DIRECT_URL,
)
from element_utils import click_button, fill_field, wait_for_element

# Reuse Playwright helpers from build_pt_campaign for delivery, save, etc.
from build_pt_campaign import (
    save_as_draft,
    capture_screenshot,
    get_campaign_url_from_page,
    _convert_24h_to_12h,
    parse_time_string,
)
from utils.campaign_name import generate_campaign_name

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Asana
# ---------------------------------------------------------------------------
ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"
BRAZE_DASHBOARD_BASE = os.environ.get(
    "BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com"
).rstrip("/")

# Asana custom field GIDs (shared with build_pt_campaign.py / build_sms_campaign.py)
FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_BRAZE_LINK = "1210710306792280"
FIELD_BRAZE_CAMPAIGN_ID = "1210955430688137"
FIELD_SEND_TIME = "1212524397761931"

STATUS_READY_TO_CODE = "1209995669275789"
STATUS_READY_FOR_QA = "1213535128306988"

BRAND_OPTIONS = {
    "HAV": "1207522425689881",
    "CZ": "1207553690167887",
    "ID": "1207522425689882",
    "BUR": "1208572919795447",
    "TI": "1207522425689883",
    "STF": "1207881071843537",
    "TRADE": "1208130746998739",
}
BRAND_GID_TO_CODE = {v: k for k, v in BRAND_OPTIONS.items()}

CHANNEL_OPTIONS = {
    "email": "1207562370794989",
    "sms": "1207562370794990",
    "push": "1207562370794991",
}
CHANNEL_GID_TO_NAME = {v: k for k, v in CHANNEL_OPTIONS.items()}


# =========================================================================
# 1.  CONFIGURATION LOADING
# =========================================================================

def load_brand_config() -> Dict[str, Any]:
    """Load brand_config.yaml."""
    config_path = PROJECT_ROOT / "data" / "brand_config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_push_config(variant: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Get push-specific config for a HAV variant from brand_config.yaml.

    Args:
        variant: "HAV_PC" or "HAV_CONV"
        config: Full config dict from brand_config.yaml

    Returns:
        Dict with segment, deep_link, send_time.

    Raises:
        ValueError: If no push config exists for the variant.
    """
    push_configs = config.get("push_config", {})
    entry = push_configs.get(variant)
    if not entry:
        raise ValueError(
            f"No push config for variant '{variant}'. "
            f"Available: {sorted(push_configs.keys())}"
        )
    return entry


# =========================================================================
# 2.  ASANA HELPERS
# =========================================================================

def _asana_headers() -> Dict[str, str]:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("ASANA_ACCESS_TOKEN not set in .env")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _asana_request(method: str, endpoint: str, json_data=None, params=None):
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=_asana_headers(),
                            json=json_data, params=params, timeout=30)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        logger.warning(f"Asana rate limited — waiting {wait}s")
        time.sleep(wait)
        resp = requests.request(method, url, headers=_asana_headers(),
                                json=json_data, params=params, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"Asana {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json().get("data")


def _get_custom_field(task: Dict, field_gid: str) -> Optional[Dict]:
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            return cf
    return None


def _get_enum_value_gid(task: Dict, field_gid: str) -> Optional[str]:
    cf = _get_custom_field(task, field_gid)
    if cf and cf.get("enum_value"):
        return cf["enum_value"].get("gid")
    return None


def _get_enum_value_name(task: Dict, field_gid: str) -> Optional[str]:
    cf = _get_custom_field(task, field_gid)
    if cf and cf.get("enum_value"):
        return cf["enum_value"].get("name")
    return None


def _get_text_value(task: Dict, field_gid: str) -> Optional[str]:
    cf = _get_custom_field(task, field_gid)
    if not cf:
        return None
    return cf.get("text_value") or cf.get("display_value")


# =========================================================================
# 3.  ASANA TASK PARSING
# =========================================================================

def fetch_task_by_gid(task_gid: str) -> Optional[Dict]:
    """Fetch a single Asana task with all custom fields and notes."""
    opt_fields = ",".join([
        "name", "due_on", "completed", "notes",
        "custom_fields", "custom_fields.gid",
        "custom_fields.enum_value", "custom_fields.enum_value.gid",
        "custom_fields.enum_value.name",
        "custom_fields.text_value", "custom_fields.display_value",
    ])
    return _asana_request("GET", f"tasks/{task_gid}", params={"opt_fields": opt_fields})


def fetch_ready_to_code_push_tasks() -> List[Dict]:
    """Fetch tasks with 'Ready to Code' status and Channel = Push for HAV."""
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
        f"custom_fields.{FIELD_CHANNEL}.value": CHANNEL_OPTIONS["push"],
        f"custom_fields.{FIELD_BRAND}.value": BRAND_OPTIONS["HAV"],
        "opt_fields": ",".join([
            "name", "due_on", "completed", "notes",
            "custom_fields", "custom_fields.gid",
            "custom_fields.enum_value", "custom_fields.enum_value.gid",
            "custom_fields.enum_value.name",
            "custom_fields.text_value", "custom_fields.display_value",
        ]),
        "limit": 100,
    }

    endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
    tasks_data = _asana_request("GET", endpoint, params=params)
    if not tasks_data:
        return []

    results = []
    for task in tasks_data:
        if task.get("completed"):
            continue
        name = task.get("name", "")
        # Filter to push tasks (name starts with "Push:")
        if not name.strip().lower().startswith("push:"):
            continue
        parsed_list = parse_asana_push_task(task)
        results.extend(parsed_list)
    return results


def _detect_audience_from_name(task_name: str) -> List[str]:
    """Detect which audience(s) a push task targets from its name.

    Returns a list of variant keys: ["HAV_PC"], ["HAV_CONV"], or
    ["HAV_PC", "HAV_CONV"] for combined tasks.

    Naming patterns:
      - "Push: DPS ..." or "DPS: ..." → HAV_PC  (pre-converted / DPS)
      - "Push: MP ..."  or "MP: ..."  → HAV_CONV (converted / marketplace)
      - "Push: ..."     or "..."      → both (combined task, no audience prefix)
      - "DPS and MP: ..." or "DPS/MP: ..." → both
    """
    # Strip the "Push:" or "Push" prefix (colon optional) and examine what follows
    after_push = re.sub(r'^Push:?\s*', '', task_name, flags=re.IGNORECASE).strip()
    # Strip trailing colon from first word so "MP: ..." matches the same as "MP ..."
    first_word = after_push.split()[0].upper().rstrip(':') if after_push else ""

    if first_word == "DPS":
        # Check for combined "DPS and MP" / "DPS & MP" / "DPS/MP"
        if re.match(r'^DPS\s+(?:and|&)\s+MP\b', after_push, flags=re.IGNORECASE) or \
           re.match(r'^DPS\s*/\s*MP\b', after_push, flags=re.IGNORECASE):
            return ["HAV_PC", "HAV_CONV"]
        return ["HAV_PC"]
    elif first_word == "MP":
        # Check for combined "MP and DPS" / "MP & DPS" / "MP/DPS"
        if re.match(r'^MP\s+(?:and|&)\s+DPS\b', after_push, flags=re.IGNORECASE) or \
           re.match(r'^MP\s*/\s*DPS\b', after_push, flags=re.IGNORECASE):
            return ["HAV_PC", "HAV_CONV"]
        return ["HAV_CONV"]
    else:
        # Combined task — build for both audiences
        return ["HAV_PC", "HAV_CONV"]


def _extract_push_description(task_name: str) -> str:
    """Extract the description portion from a push task name for campaign naming.

    Strips channel words ("Push", "Email", "SMS"), audience prefixes
    ("DPS", "MP", "DPS and MP", etc.), and returns a Title_Case underscore
    string suitable for campaign naming.

    Examples:
        "Push: DPS Presidents Day Sale Starts"  → "Presidents_Day_Sale_Starts"
        "Push: MP Presidents Day Sale Starts"   → "Presidents_Day_Sale_Starts"
        "Push DPS and MP Sale Reminder"         → "Sale_Reminder"
        "Push: Winter Sale Reminder"            → "Winter_Sale_Reminder"
    """
    # Strip "Push:" or "Push" prefix (colon optional)
    desc = re.sub(r'^Push:?\s*', '', task_name, flags=re.IGNORECASE).strip()
    # Strip combined audience prefix ("DPS and MP", "DPS & MP", "DPS/MP", "MP and DPS", "MP/DPS", etc.)
    desc = re.sub(r'^(?:DPS\s+(?:and|&)\s+MP|DPS\s*/\s*MP|MP\s+(?:and|&)\s+DPS|MP\s*/\s*DPS)[:\s]*', '', desc, flags=re.IGNORECASE).strip()
    # Strip single audience prefix (DPS or MP), with optional trailing colon/spaces (e.g. "MP: ...", "MP:...")
    desc = re.sub(r'^(?:DPS|MP)[:\s]+', '', desc, flags=re.IGNORECASE).strip()
    # Strip any remaining channel words (email, sms, push) that are
    # redundant with the channel portion of the campaign name
    desc = re.sub(r'\b(?:email|sms|push)\b', '', desc, flags=re.IGNORECASE).strip()
    # Collapse multiple spaces left by removals
    desc = re.sub(r'\s{2,}', ' ', desc).strip()

    if not desc:
        desc = "Push_Notification"

    # Convert to Title_Case_Underscored format
    words = desc.split()
    return "_".join(
        w[0].upper() + w[1:] if len(w) > 1 else w.upper()
        for w in words if w
    )


def extract_push_copy(notes: str) -> Tuple[str, str]:
    """Extract Title and Description (message) from Asana task notes.

    Looks for lines starting with "Title:" and "Description:" and extracts
    the value after the colon.  Ignores conversational/editorial text that
    may also appear in the notes.

    Args:
        notes: Raw task notes text.

    Returns:
        Tuple of (title, message).

    Raises:
        ValueError: If Title or Description cannot be found.
    """
    title = ""
    message = ""

    for line in notes.strip().splitlines():
        stripped = line.strip()

        # Match "Title: ..." (case-insensitive)
        title_match = re.match(r'^Title:\s*(.+)', stripped, re.IGNORECASE)
        if title_match and not title:
            title = title_match.group(1).strip()
            continue

        # Match "Description:" or "Body:" (case-insensitive)
        desc_match = re.match(r'^(?:Description|Body):\s*(.+)', stripped, re.IGNORECASE)
        if desc_match and not message:
            message = desc_match.group(1).strip()
            continue

    if not title:
        raise ValueError(
            "Could not find 'Title:' in task notes. "
            "Expected format: 'Title: Your push title here'"
        )
    if not message:
        raise ValueError(
            "Could not find 'Description:' or 'Body:' in task notes. "
            "Expected format: 'Description: Your push message here'"
        )

    return title, message


def parse_asana_push_task(task: Dict) -> List[Dict[str, Any]]:
    """Parse a raw Asana task into one or more push campaign records.

    A single Asana task may produce TWO records when it targets both
    DPS (PC) and MP (CONV) audiences.

    Returns a list of parsed campaign dicts.
    """
    task_gid = task.get("gid")
    task_name = task.get("name", "")
    due_on = task.get("due_on")  # YYYY-MM-DD
    notes = task.get("notes", "")

    # Brand must be HAV for push
    brand_gid = _get_enum_value_gid(task, FIELD_BRAND)
    brand_code = BRAND_GID_TO_CODE.get(brand_gid) if brand_gid else None
    if brand_code != "HAV":
        logger.warning(f"Task {task_gid} ({task_name}): not HAV brand, skipping")
        return []

    # Channel must be push
    channel_gid = _get_enum_value_gid(task, FIELD_CHANNEL)
    channel = CHANNEL_GID_TO_NAME.get(channel_gid) if channel_gid else None
    if channel != "push":
        logger.warning(f"Task {task_gid} ({task_name}): not push channel, skipping")
        return []

    # Check if Braze link already exists
    braze_link = _get_text_value(task, FIELD_BRAZE_LINK)

    # Read Asana "Send time" field (used by resolve_push_send_time)
    send_time_raw = _get_text_value(task, FIELD_SEND_TIME) or ""

    # Extract push copy from notes
    try:
        push_title, push_message = extract_push_copy(notes)
    except ValueError as e:
        logger.warning(f"Task {task_gid} ({task_name}): {e}")
        return []

    # Determine audience variant(s)
    variants = _detect_audience_from_name(task_name)
    description = _extract_push_description(task_name)

    results = []
    for variant in variants:
        hav_audience = "PC" if variant == "HAV_PC" else "CONV"

        # Generate campaign name
        try:
            campaign_name = generate_campaign_name(
                campaign_type="P",
                channel="PUSH",
                send_date=due_on,
                brand="HAV",
                hav_audience=hav_audience,
                description=description,
            )
        except ValueError as e:
            logger.warning(f"Campaign name generation failed: {e}")
            date_str = due_on.replace("-", "_") if due_on else "XXXX_XX_XX"
            campaign_name = f"P_PUSH_{date_str}_HAV_{hav_audience}_{description}"

        results.append({
            "gid": task_gid,
            "name": task_name,
            "brand": "HAV",
            "channel": "push",
            "due_on": due_on,
            "notes": notes,
            "push_title": push_title,
            "push_message": push_message,
            "variant": variant,  # "HAV_PC" or "HAV_CONV"
            "hav_audience": hav_audience,
            "campaign_name": campaign_name,
            "braze_link": braze_link,
            "is_combined_task": len(variants) > 1,
            "send_time_raw": send_time_raw,
        })

    return results


# =========================================================================
# 3b. SEND TIME RESOLUTION (Push-specific)
# =========================================================================

def resolve_push_send_time(
    task: Dict[str, Any],
    push_config: Dict[str, Any],
) -> str:
    """Determine send time for a push campaign.

    Priority:
      1. Asana "Send time" field (if explicitly set)
      2. Push default from config (3:00 PM)

    Returns "HH:MM" string.
    """
    send_time_raw = task.get("send_time_raw", "")
    parsed = parse_time_string(send_time_raw)
    if parsed:
        logger.info(f"Push send time from Asana field: {parsed}")
        return parsed

    default_time = push_config.get("send_time", "15:00")
    logger.info(f"Push send time using config default: {default_time}")
    return default_time


# =========================================================================
# 4.  CAMPAIGN CONFIG BUILDER
# =========================================================================

def build_campaign_config(
    task: Dict[str, Any],
    global_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a complete push campaign configuration.

    Returns a dict with everything needed to build the campaign in Braze.
    """
    variant = task["variant"]
    push_cfg = get_push_config(variant, global_config)

    push_message = task["push_message"]
    # Replace trailing LINK placeholder (any capitalization) with the actual deep link.
    # Producers sometimes write "Shop now LINK" — strip it so the real URL is used.
    if re.search(r'\bLINK\s*$', push_message, re.IGNORECASE):
        push_message = re.sub(r'\s*\bLINK\s*$', '', push_message, flags=re.IGNORECASE).rstrip()
        logger.info(f"Replaced trailing LINK placeholder in push message with deep link")

    return {
        "campaign_name": task["campaign_name"],
        "brand_code": "HAV",
        "variant": variant,
        "hav_audience": task["hav_audience"],
        "workspace": "havenly",
        "push_title": task["push_title"],
        "push_message": push_message,
        "segment": push_cfg["segment"],
        "deep_link": push_cfg["deep_link"],
        "send_time": resolve_push_send_time(task, push_cfg),
        "launch_date": task["due_on"],
        "asana_gid": task["gid"],
        "is_combined_task": task["is_combined_task"],
    }


# =========================================================================
# 5.  PLAYWRIGHT — DUPLICATE-BASED PUSH CAMPAIGN AUTOMATION
# =========================================================================

async def navigate_to_campaigns_list(page: Page, brand: str = None) -> bool:
    """Navigate to the Campaigns list in the Braze sidebar.

    Args:
        page: Playwright page object
        brand: Brand code (HAV, CZ, BUR, etc.) — when provided, navigates
               directly to the workspace-specific campaigns URL to avoid
               landing in the wrong workspace via the generic sidebar link.
    """
    logger.info("Navigating to Campaigns list...")

    # Strategy 0: workspace-specific direct URL (avoids sidebar link resolving
    # to wrong workspace when multiple workspaces exist in session)
    if brand:
        import re
        workspace_url = BRAND_WORKSPACE_DIRECT_URL.get(brand.upper())
        if workspace_url:
            m = re.search(r'/([a-f0-9]{24})$', workspace_url)
            if m:
                app_group_id = m.group(1)
                dashboard_url = BRAZE_DASHBOARD_URL.rstrip("/")
                campaigns_url = f"{dashboard_url}/engagement/campaigns/{app_group_id}"
                try:
                    await page.goto(campaigns_url, wait_until="load", timeout=15000)
                    await page.wait_for_timeout(2000)
                    if "/campaigns" in page.url:
                        logger.info(f"Navigated via workspace-specific URL for {brand}")
                        # Wait for the campaign list to actually render (async data load)
                        try:
                            await page.wait_for_selector(
                                "input[placeholder*='Search' i], input[type='search']",
                                state="visible",
                                timeout=15000,
                            )
                        except Exception:
                            await page.wait_for_timeout(3000)
                        return True
                except Exception as e:
                    logger.debug(f"Workspace-specific campaigns URL failed: {e}")

    try:
        link = page.get_by_role("link", name="Campaigns")
        await link.wait_for(state="visible", timeout=5000)
        await link.click()
        await page.wait_for_timeout(3000)
        if "/campaigns" in page.url:
            logger.info("Navigated to Campaigns list via sidebar")
            try:
                await page.wait_for_selector(
                    "input[placeholder*='Search' i], input[type='search']",
                    state="visible", timeout=15000,
                )
            except Exception:
                await page.wait_for_timeout(3000)
            return True
    except Exception:
        pass

    try:
        link = page.locator("a[href*='/campaigns']").first
        await link.click(timeout=5000)
        await page.wait_for_timeout(3000)
        logger.info("Navigated to Campaigns list via locator")
        try:
            await page.wait_for_selector(
                "input[placeholder*='Search' i], input[type='search']",
                state="visible", timeout=15000,
            )
        except Exception:
            await page.wait_for_timeout(3000)
        return True
    except Exception:
        pass

    # Direct URL fallback
    base = BRAZE_DASHBOARD_BASE
    await page.goto(f"{base}/engagement/campaigns", wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_selector(
            "input[placeholder*='Search' i], input[type='search']",
            state="visible", timeout=15000,
        )
    except Exception:
        await page.wait_for_timeout(5000)
    logger.info("Navigated to Campaigns list via direct URL")
    return True


async def _set_status_filter(page: Page, status: str) -> None:
    """Set the Status filter on the campaigns list page.

    Args:
        status: The status label to filter by (e.g. "Active", "Draft").
                Pass "All" to clear any existing filter.
    """
    # "All" means no filter — just clear whatever is set
    if status == "All":
        try:
            any_status_tag = page.locator("text=/^Status: /")
            if await any_status_tag.count() > 0 and await any_status_tag.first.is_visible(timeout=2000):
                close_btn = any_status_tag.locator("xpath=ancestor::*[1]").locator(
                    "button, svg, [class*='close'], [class*='remove']"
                )
                if await close_btn.count() > 0:
                    await close_btn.first.click()
                    await page.wait_for_timeout(1500)
                    logger.info("Cleared status filter (All)")
            else:
                logger.info("Status filter already cleared (All)")
        except Exception:
            pass
        return

    expected_tag = f"Status: {status}"

    # Check if it's already set
    try:
        tag = page.locator(f"text='{expected_tag}'")
        if await tag.count() > 0 and await tag.first.is_visible():
            logger.info(f"'{expected_tag}' filter is already applied")
            return
    except Exception:
        pass

    # Clear any existing Status tag first (e.g. "Status: Active ×")
    try:
        any_status_tag = page.locator("text=/^Status: /")
        if await any_status_tag.count() > 0 and await any_status_tag.first.is_visible(timeout=2000):
            close_btn = any_status_tag.locator("xpath=ancestor::*[1]").locator(
                "button, svg, [class*='close'], [class*='remove']"
            )
            if await close_btn.count() > 0:
                await close_btn.first.click()
                await page.wait_for_timeout(1500)
                logger.debug("Cleared existing status filter tag")
    except Exception:
        pass

    # Open the Status dropdown and select the requested status
    try:
        # The Status dropdown is a <select>-style component near the top
        status_dropdown = page.locator(
            "[class*='select'], select"
        ).filter(has_text="Status").first

        # Fallback: look for the dropdown by placeholder
        if await status_dropdown.count() == 0:
            status_dropdown = page.get_by_text("Status").locator(
                "xpath=following::select[1] | following::*[contains(@class,'select')][1]"
            ).first

        if await status_dropdown.count() > 0:
            await status_dropdown.click()
            await page.wait_for_timeout(500)
            opt = page.get_by_text(status, exact=True)
            if await opt.count() > 0:
                await opt.first.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Set status filter to {status}")
                return
    except Exception:
        pass

    logger.debug(f"Could not set status filter to {status} — proceeding")


async def _find_push_row(page: Page, variant_kw: str) -> Optional[Any]:
    """Scan the current campaign list rows for a Push Notification matching the variant.

    Returns the matching Playwright row locator, or None.
    """
    rows = page.locator("tr, [role='row']")
    row_count = await rows.count()
    logger.info(f"Found {row_count} rows in the campaign list")

    for i in range(row_count):
        row = rows.nth(i)
        row_text = (await row.text_content() or "").strip()

        # Must be a Push Notification row
        if "Push Notification" not in row_text:
            continue

        # Extract the actual campaign name from the row's first link,
        # not the full row text (which mixes in status, creator, etc.).
        try:
            link = row.locator("a").first
            name = (await link.text_content() or "").strip() if await link.count() > 0 else ""
        except Exception:
            name = ""
        if not name:
            continue

        logger.debug(f"Row {i} push campaign name: {name}")

        # Check the NAME for the correct variant at a token boundary
        if variant_kw:
            if f"_{variant_kw}_" not in name and not name.endswith(f"_{variant_kw}"):
                logger.debug(f"  Skipping — does not match variant {variant_kw}")
                continue

        logger.info(f"Found {variant_kw} push campaign to duplicate: {name}")
        return row

    return None


async def _duplicate_row(page: Page, target_row) -> bool:
    """Click the Duplicate action on a campaign row's kebab menu."""
    await target_row.hover()
    await page.wait_for_timeout(1000)

    kebab_selectors = [
        target_row.locator("button").last,
        target_row.locator("[aria-label*='action' i], [aria-label*='more' i]"),
        target_row.locator("button:has(svg)").last,
        target_row.locator("[class*='kebab'], [class*='action']"),
    ]

    for kebab in kebab_selectors:
        try:
            if await kebab.count() > 0 and await kebab.first.is_visible():
                await kebab.first.click()
                await page.wait_for_timeout(1500)

                dup = page.get_by_text("Duplicate", exact=True)
                if await dup.count() > 0 and await dup.first.is_visible():
                    await dup.first.click()
                    await page.wait_for_timeout(5000)
                    logger.info("Duplicated via row action menu")
                    return True

                dup_item = page.get_by_role("menuitem", name="Duplicate")
                if await dup_item.count() > 0 and await dup_item.first.is_visible():
                    await dup_item.first.click()
                    await page.wait_for_timeout(5000)
                    logger.info("Duplicated via menuitem")
                    return True

                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
        except Exception:
            continue

    logger.error("Found the push campaign row but could not click Duplicate in its menu")
    return False


async def _enter_search_query(page: Page, query: str) -> bool:
    """Fill the search box on the campaigns list page."""
    search_selectors = [
        page.get_by_placeholder("Search"),
        page.get_by_placeholder("Search campaigns"),
        page.locator("input[placeholder*='Search' i]"),
        page.locator("input[type='search']"),
    ]

    for selector in search_selectors:
        try:
            if await selector.count() > 0 and await selector.first.is_visible():
                await selector.first.click()
                await page.wait_for_timeout(300)
                await selector.first.fill(query)
                await page.wait_for_timeout(4000)  # Wait for filter
                logger.info("Search query entered")
                return True
        except Exception:
            continue

    logger.warning("Could not find search box")
    return False


async def search_and_duplicate_campaign(
    page: Page, campaign_name: str, variant: str = ""
) -> bool:
    """Search for a push campaign and duplicate it.

    Tries Status: Active first, then falls back to Status: Idle (sent
    One-Time campaigns move to Idle after their send completes).

    We verify the campaign NAME contains the correct variant keyword
    (``_PC_`` or ``_CONV_``) to avoid duplicating the wrong audience.
    """
    variant_kw = ("PC" if "PC" in variant else "CONV") if variant else ""

    for status in ("Active", "Idle", "Stopped"):
        logger.info(
            f"Searching for {variant_kw} push campaign to duplicate "
            f"(Status: {status})..."
        )

        await _set_status_filter(page, status)
        await _enter_search_query(page, campaign_name)

        # Debug screenshot
        try:
            debug_path = (
                Path(__file__).parent
                / f"debug_search_{status.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
            await page.screenshot(path=str(debug_path), full_page=True)
            logger.info(f"Search results screenshot ({status}): {debug_path}")
        except Exception:
            pass

        target_row = await _find_push_row(page, variant_kw)

        if target_row:
            return await _duplicate_row(page, target_row)

        logger.info(
            f"No {variant_kw} push campaign found under Status: {status}"
        )

    logger.error(
        f"No Push Notification campaign with _{variant_kw}_ in its name "
        f"found under Active, Idle, or Stopped status"
    )
    return False


async def duplicate_campaign(page: Page, variant: str, brand: str = None) -> bool:
    """Find the most recent push campaign of the correct variant and duplicate it.

    Instead of navigating to a specific reference campaign, we:
      1. Navigate to the campaigns list
      2. Search for recent push campaigns matching the variant (PC or CONV)
      3. Pick the first (most recent) match
      4. Use the row's action menu to duplicate it

    This ensures we always duplicate from a recent, known-good push
    campaign with the correct audience, deep link, and conversions.
    """
    logger.info(f"Finding most recent {variant} push campaign to duplicate...")

    # Navigate to campaigns list
    await navigate_to_campaigns_list(page, brand=brand)

    # Search for push campaigns matching the variant.
    # Use "P_PUSH" as search term to surface all push campaigns, then
    # let the row-level filtering (in search_and_duplicate_campaign)
    # pick the first row with the correct variant (PC or CONV).
    search_term = "P_PUSH"

    return await search_and_duplicate_campaign(page, search_term, variant=variant)


async def wait_for_campaign_editor(page: Page) -> bool:
    """Wait for the duplicated campaign editor to fully load.

    After duplication, Braze redirects to the new campaign's editor.
    We wait for the campaign name input to be available.
    """
    logger.info("Waiting for campaign editor to load...")

    # Wait for the URL to change (should be a new campaign ID)
    try:
        await page.wait_for_url("**/campaigns/**", timeout=15000)
    except PlaywrightTimeout:
        logger.warning("URL did not change to a campaign editor URL")

    # Wait for the campaign name field to appear
    name_selectors = [
        page.get_by_role("textbox", name="Enter Campaign Name"),
        page.get_by_placeholder("Enter Campaign Name"),
        page.locator("input[placeholder*='Campaign Name']"),
    ]

    for selector in name_selectors:
        try:
            await selector.wait_for(state="visible", timeout=10000)
            logger.info("Campaign editor loaded (name field visible)")
            return True
        except PlaywrightTimeout:
            continue

    # Fallback: just wait a bit and hope it loaded
    await page.wait_for_timeout(5000)
    logger.warning("Could not confirm editor loaded, proceeding anyway")
    return True


async def set_campaign_name(page: Page, name: str) -> bool:
    """Set the campaign name field, clearing any existing value."""
    logger.info(f"Setting campaign name: {name}")

    name_selectors = [
        page.get_by_role("textbox", name="Enter Campaign Name"),
        page.get_by_placeholder("Enter Campaign Name"),
        page.locator("input[placeholder*='Campaign Name']"),
    ]

    for selector in name_selectors:
        try:
            if await selector.count() > 0 and await selector.first.is_visible():
                await selector.first.click()
                await page.wait_for_timeout(200)
                # Select all and replace
                await page.keyboard.press("Meta+A")
                await page.wait_for_timeout(100)
                await page.keyboard.type(name)
                await page.wait_for_timeout(500)
                logger.info("Campaign name set")
                return True
        except Exception as e:
            logger.debug(f"Name field selector failed: {e}")
            continue

    logger.error("Could not find campaign name field")
    return False


async def edit_push_content(page: Page, title: str, message: str) -> bool:
    """Edit the push notification Title and Message fields.

    The Braze push compose step shows:
      - A "Compose" tab and a "Settings" tab
      - Under Compose: Title and Message fields (Monaco editors)
      - A phone preview on the left side
      - iOS / Android / Web tabs

    After duplicating, we land on the Compose Messages step with the
    push editor already visible (no need to click "Edit message").
    The Title and Message fields use Monaco editors.
    """
    logger.info("Editing push content...")

    # Ensure we're on the Compose Messages step
    compose_nav = [
        page.get_by_text("Compose Messages", exact=True),
        page.get_by_role("button", name="Compose Messages"),
        page.get_by_role("button", name="Compose"),
    ]
    for selector in compose_nav:
        try:
            if await selector.count() > 0 and await selector.first.is_visible():
                await selector.first.click()
                await page.wait_for_timeout(2000)
                logger.info("Navigated to Compose Messages step")
                break
        except Exception:
            continue

    # Ensure we're on the Compose sub-tab (not Settings or Test)
    compose_tab = page.get_by_role("tab", name="Compose")
    if await compose_tab.count() == 0:
        compose_tab = page.locator("button:has-text('Compose'), [role='tab']:has-text('Compose')")
    try:
        if await compose_tab.count() > 0 and await compose_tab.first.is_visible():
            await compose_tab.first.click()
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    # The push Title and Message Monaco editors are BELOW the viewport fold.
    # Scroll down to bring them into view before trying to fill them.
    await page.evaluate("window.scrollBy(0, 600)")
    await page.wait_for_timeout(1500)

    # Also try to scroll within the main content area (Braze uses nested scrollers)
    try:
        main_content = page.locator("main, [class*='content-area'], [class*='main-content']").first
        if await main_content.count() > 0:
            await main_content.evaluate("el => el.scrollBy(0, 600)")
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    # Take a debug screenshot to see the push compose UI after scrolling
    try:
        debug_path = Path(__file__).parent / f"debug_compose_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(debug_path), full_page=True)
        logger.info(f"Compose step screenshot: {debug_path}")
    except Exception:
        pass

    # --- Fill Title and Message ---
    # The push compose step has Title and Message fields.  These may be:
    #   - Monaco editors (.monaco-editor)
    #   - Regular input/textarea fields
    #   - Or contenteditable divs
    # We try multiple strategies, scrolling each candidate into view first.
    import json as _json

    await page.wait_for_timeout(1000)

    title_filled = False
    message_filled = False

    # --- Strategy A: Look for labeled sections "Title" and "Message" ---
    # Braze labels the push fields with visible text headers.
    # Find the "Title" label and then interact with the editor below it.
    try:
        title_label = page.get_by_text("Title", exact=True)
        if await title_label.count() > 0:
            # Scroll the title label into view
            await title_label.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)

            # The Monaco editor should be nearby (sibling or child)
            # Click into it and fill via keyboard
            title_editor = title_label.locator("xpath=following::div[contains(@class, 'monaco-editor')]").first
            if await title_editor.count() > 0:
                await title_editor.click()
                await page.wait_for_timeout(300)
                await page.keyboard.press("Meta+A")
                await page.wait_for_timeout(100)
                await page.keyboard.type(title)
                await page.wait_for_timeout(300)
                title_filled = True
                logger.info(f"Push title set via Title label + Monaco: {title}")
    except Exception as e:
        logger.debug(f"Title label strategy failed: {e}")

    try:
        if not message_filled:
            msg_label = page.get_by_text("Message", exact=True)
            if await msg_label.count() > 0:
                await msg_label.first.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)

                msg_editor = msg_label.locator("xpath=following::div[contains(@class, 'monaco-editor')]").first
                if await msg_editor.count() > 0:
                    await msg_editor.click()
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Meta+A")
                    await page.wait_for_timeout(100)
                    await page.keyboard.type(message)
                    await page.wait_for_timeout(300)
                    message_filled = True
                    logger.info(f"Push message set via Message label + Monaco: {message}")
    except Exception as e:
        logger.debug(f"Message label strategy failed: {e}")

    # --- Strategy B: Monaco editors by index (scroll each into view) ---
    if not title_filled or not message_filled:
        monaco_editors = page.locator(".monaco-editor")
        editor_count = await monaco_editors.count()
        logger.info(f"Found {editor_count} Monaco editors on the compose step")

        # Scroll through editors and try to fill title (first unfilled) then message
        for idx in range(editor_count):
            editor = monaco_editors.nth(idx)
            try:
                await editor.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                if not await editor.is_visible():
                    continue
            except Exception:
                continue

            if not title_filled:
                if await _fill_via_monaco(page, title, field_index=idx):
                    title_filled = True
                    logger.info(f"Push title set via Monaco[{idx}]: {title}")
                    continue

            if not message_filled:
                if await _fill_via_monaco(page, message, field_index=idx):
                    message_filled = True
                    logger.info(f"Push message set via Monaco[{idx}]: {message}")
                    break

    # --- Strategy C: Fallback to regular input/textarea selectors ---
    if not title_filled:
        title_selectors = [
            page.get_by_placeholder("Title"),
            page.get_by_label("Title"),
            page.locator("input[placeholder*='Title' i]"),
            page.locator("input[aria-label*='Title' i]"),
        ]
        for selector in title_selectors:
            try:
                if await selector.count() > 0:
                    await selector.first.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    if await selector.first.is_visible():
                        await selector.first.click()
                        await page.wait_for_timeout(200)
                        await page.keyboard.press("Meta+A")
                        await page.wait_for_timeout(100)
                        await page.keyboard.type(title)
                        await page.wait_for_timeout(300)
                        title_filled = True
                        logger.info(f"Push title set via input: {title}")
                        break
            except Exception:
                continue

    if not message_filled:
        message_selectors = [
            page.get_by_placeholder("Message"),
            page.get_by_label("Message"),
            page.locator("textarea[placeholder*='Message' i]"),
            page.locator("textarea[aria-label*='Message' i]"),
        ]
        for selector in message_selectors:
            try:
                if await selector.count() > 0:
                    await selector.first.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    if await selector.first.is_visible():
                        await selector.first.click()
                        await page.wait_for_timeout(200)
                        await page.keyboard.press("Meta+A")
                        await page.wait_for_timeout(100)
                        await page.keyboard.type(message)
                        await page.wait_for_timeout(300)
                        message_filled = True
                        logger.info(f"Push message set via textarea: {message}")
                        break
            except Exception:
                continue

    if not title_filled:
        logger.error("Could not fill push title")
    if not message_filled:
        logger.error("Could not fill push message")

    if not title_filled or not message_filled:
        # Take screenshot to help debug
        try:
            err_path = Path(__file__).parent / f"debug_content_fail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=str(err_path), full_page=True)
            logger.info(f"Content fill debug screenshot: {err_path}")
        except Exception:
            pass
        return False

    logger.info("Push content updated successfully")
    return True


async def set_push_on_click_behavior(page: Page, deep_link: str) -> bool:
    """Set the On-Click Behavior deep link URL.

    Handles two cases:
    - Dropdown already set (Deeplink into application / Redirect to Web URL): just update the URL.
    - Dropdown unset: open it, select an option, then fill the URL.

    In both cases, uses scroll_into_view + force-click + fill on the URL input,
    with a JS React-setter fallback.
    """
    logger.info(f"Setting push on-click behavior: {deep_link[:80]}...")

    # Step 1: Scroll "On-click behavior" into view
    try:
        on_click_heading = page.get_by_text("On-click behavior", exact=False).first
        await on_click_heading.scroll_into_view_if_needed(timeout=5000)
        await page.wait_for_timeout(500)
    except Exception:
        await page.evaluate("window.scrollBy(0, 600)")
        await page.wait_for_timeout(500)

    # Step 2: Check if a URL input is already visible (dropdown already set).
    # If so, skip the dropdown interaction entirely.
    async def _find_url_input():
        """Return the first visible URL input near the on-click section, or None."""
        candidates = [
            page.get_by_label("Web URL"),
            page.get_by_placeholder("https://"),
            page.locator("input[placeholder*='https' i]").last,
            page.locator("input[aria-label*='URL' i]").last,
            page.locator("input[aria-label*='url' i]").last,
        ]
        try:
            on_click_section = page.get_by_text("On-click behavior", exact=False).first
            candidates.insert(0, on_click_section.locator("xpath=following::input[1]"))
        except Exception:
            pass
        for c in candidates:
            try:
                if await c.count() > 0 and await c.first.is_visible(timeout=1000):
                    return c.first
            except Exception:
                continue
        return None

    url_input = await _find_url_input()
    dropdown_set = url_input is not None

    if dropdown_set:
        logger.info("On-Click Behavior dropdown already set — URL input visible, skipping dropdown interaction")
    else:
        # Step 3: Dropdown not yet set — open it and pick an option
        # Try native <select> first
        native_selectors = [
            page.get_by_label("On-Click Behavior"),
            page.locator("select[aria-label*='On-Click' i]"),
            page.locator("select[aria-label*='on click' i]"),
            page.locator("select[aria-label*='on-click' i]"),
        ]
        for sel in native_selectors:
            try:
                if await sel.count() > 0 and await sel.first.is_visible():
                    await sel.first.select_option(label="Redirect to Web URL")
                    await page.wait_for_timeout(500)
                    dropdown_set = True
                    logger.info("On-Click Behavior set via native select")
                    break
            except Exception:
                continue

        # React custom dropdown
        if not dropdown_set:
            try:
                on_click_section = page.get_by_text("On-click behavior", exact=False).first
                trigger_selectors = [
                    on_click_section.locator("xpath=following::*[self::button or self::div][contains(@class,'select') or contains(@class,'dropdown') or @role='button' or @role='combobox'][1]"),
                    page.locator("[role='combobox'][aria-label*='click' i]"),
                    page.locator("[role='combobox'][aria-label*='behavior' i]"),
                    on_click_section.locator("xpath=following::div[contains(@class,'control')][1]"),
                ]
                for trigger in trigger_selectors:
                    try:
                        if await trigger.count() > 0 and await trigger.first.is_visible():
                            await trigger.first.scroll_into_view_if_needed()
                            await trigger.first.click()
                            await page.wait_for_timeout(500)
                            for option_text in ["Deeplink into application", "Redirect to Web URL"]:
                                opt = page.get_by_role("option", name=option_text)
                                if await opt.count() == 0:
                                    opt = page.get_by_text(option_text, exact=False)
                                if await opt.count() > 0:
                                    await opt.first.click()
                                    await page.wait_for_timeout(500)
                                    dropdown_set = True
                                    logger.info(f"On-Click Behavior set via React dropdown ({option_text})")
                                    break
                            if dropdown_set:
                                break
                    except Exception:
                        continue
            except Exception:
                pass

        if not dropdown_set:
            logger.warning("Could not set On-Click Behavior dropdown — URL field may not appear")

        # Re-find URL input after dropdown interaction
        try:
            await page.wait_for_selector(
                "input[placeholder*='https' i], input[aria-label*='URL' i], input[aria-label*='url' i]",
                state="visible", timeout=3000,
            )
        except Exception:
            pass
        url_input = await _find_url_input()

    # Step 4: Fill the URL via the Monaco editor's hidden textarea.
    # Braze renders the on-click URL in a Monaco editor (db-liquid-textarea),
    # not a plain <input>. The Monaco editor at textarea.inputarea index 2
    # (after Title=0, Message=1) is the URL field. We focus its hidden textarea
    # and type directly — this fires the real keyboard events Monaco listens to.
    url_filled = False
    URL_MONACO_INDEX = 2  # Title=0, Message=1, OnClick URL=2
    try:
        textareas = page.locator("textarea.inputarea")
        count = await textareas.count()
        logger.info(f"Monaco inputarea count: {count}")
        if count > URL_MONACO_INDEX:
            ta = textareas.nth(URL_MONACO_INDEX)
            el = await ta.element_handle()
            if el is None:
                raise Exception("element_handle returned None")
            # Focus via JS (works even outside viewport), then select-all + type
            await page.evaluate("el => el.focus()", el)
            await page.wait_for_timeout(200)
            await page.keyboard.press("Meta+A")
            await page.wait_for_timeout(100)
            await page.keyboard.type(deep_link, delay=5)
            await page.keyboard.press("Escape")  # dismiss any Monaco suggestion
            await page.wait_for_timeout(300)
            url_filled = True
            logger.info(f"On-Click URL filled via Monaco textarea[{URL_MONACO_INDEX}]: {deep_link[:80]}")
        else:
            logger.warning(f"Only {count} Monaco textareas found, expected >{URL_MONACO_INDEX}")
    except Exception as e:
        logger.warning(f"Monaco textarea fill failed: {e}")

    if not url_filled:
        logger.warning("Could not fill on-click URL input")
        try:
            dbg = Path(__file__).parent / f"debug_onclick_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=str(dbg), full_page=True)
            logger.info(f"On-click debug screenshot: {dbg}")
        except Exception:
            pass

    return url_filled


async def _fill_via_monaco(page: Page, text: str, field_index: int = 0) -> bool:
    """Attempt to fill a field via the Monaco editor API.

    The Braze push compose UI may use Monaco editors for the Title and
    Message fields.  field_index 0 = Title, 1 = Message.
    """
    import json as _json
    text_json = _json.dumps(text)

    monaco_editors = page.locator(".monaco-editor")
    count = await monaco_editors.count()
    if count <= field_index:
        return False

    try:
        result = await page.evaluate(f"""
            (() => {{
                const content = {text_json};
                const idx = {field_index};
                try {{
                    const editors = window.monaco?.editor?.getEditors?.();
                    if (editors && editors.length > idx) {{
                        editors[idx].setValue(content);
                        return {{ success: true, method: 'getEditors' }};
                    }}
                }} catch (e) {{}}
                try {{
                    const models = window.monaco?.editor?.getModels?.();
                    if (models && models.length > idx) {{
                        models[idx].setValue(content);
                        return {{ success: true, method: 'getModels' }};
                    }}
                }} catch (e) {{}}
                return {{ success: false }};
            }})()
        """)
        return result.get("success", False)
    except Exception as e:
        logger.debug(f"Monaco fill failed: {e}")
        return False


async def verify_target_segment(page: Page, expected_segment: str) -> bool:
    """Navigate to Target Audiences and verify the segment is correct.

    When duplicating a campaign, the audience carries over.  This step
    confirms the segment matches what we expect for the variant and logs
    a warning if it doesn't.  We don't change the segment automatically
    to avoid accidentally breaking a known-good audience config — the
    user should fix the source campaign if there's a mismatch.
    """
    logger.info(f"Verifying target segment: {expected_segment}")

    # Navigate to "Target Audiences" step
    target_selectors = [
        page.get_by_role("button", name="Target Audiences"),
        page.get_by_text("Target Audiences", exact=True),
        page.get_by_role("button", name="Target"),
        page.locator("button:has-text('Target')"),
    ]

    navigated = False
    for selector in target_selectors:
        try:
            await selector.wait_for(state="visible", timeout=5000)
            await selector.click()
            await page.wait_for_timeout(3000)
            navigated = True
            logger.info("Navigated to Target Audiences step")
            break
        except Exception:
            continue

    if not navigated:
        logger.warning("Could not navigate to Target Audiences step")
        return False

    # Take a screenshot to see the current audience config
    try:
        debug_path = (
            Path(__file__).parent
            / f"debug_target_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        await page.screenshot(path=str(debug_path), full_page=True)
        logger.info(f"Target Audiences screenshot: {debug_path}")
    except Exception:
        pass

    # Look for the expected segment name in the page content
    page_text = await page.text_content("body") or ""
    if expected_segment in page_text:
        logger.info(f"Target segment verified: {expected_segment}")
        return True
    else:
        logger.warning(
            f"Expected segment '{expected_segment}' not found on Target "
            f"Audiences page. The duplicated campaign may have the wrong "
            f"audience — please verify manually."
        )
        return False


async def update_delivery_date(page: Page, launch_date: str, send_time: str) -> bool:
    """Update the delivery date on the Schedule Delivery step.

    Since we duplicated the campaign, the scheduling type (Once) and local
    time zone settings carry over.  We only need to update the date and
    potentially confirm the time.
    """
    logger.info("Updating delivery schedule...")

    # Navigate to "Schedule Delivery" step
    delivery_selectors = [
        page.get_by_role("button", name="Schedule Delivery"),
        page.get_by_role("button", name="Schedule"),
        page.get_by_text("Schedule Delivery", exact=True),
        page.locator("button:has-text('Schedule')"),
    ]

    for selector in delivery_selectors:
        try:
            await selector.wait_for(state="visible", timeout=5000)
            await selector.click()
            await page.wait_for_timeout(2000)
            logger.info("Navigated to Schedule Delivery step")
            break
        except Exception:
            continue

    # --- Update the On date ---
    if launch_date:
        date_formatted = launch_date.replace("-", "/")
        date_input = page.get_by_placeholder("yyyy/mm/dd")
        if await date_input.count() == 0:
            date_input = page.locator("input[aria-label='Select Date']")
        if await date_input.count() > 0:
            await date_input.scroll_into_view_if_needed()
            await date_input.click()
            await page.wait_for_timeout(300)
            await page.keyboard.press("Meta+A")
            await page.wait_for_timeout(200)
            await page.keyboard.type(date_formatted)
            await page.wait_for_timeout(500)
            # Close any date picker popup
            await date_input.press("Escape")
            await page.wait_for_timeout(500)
            # Verify the value
            actual_val = await date_input.input_value()
            if actual_val == date_formatted:
                logger.info(f"Set On date: {date_formatted}")
            else:
                logger.warning(
                    f"Date mismatch: expected '{date_formatted}', got '{actual_val}' — retrying"
                )
                await date_input.click()
                await page.wait_for_timeout(200)
                await date_input.fill("")
                await page.wait_for_timeout(200)
                await page.keyboard.type(date_formatted)
                await page.wait_for_timeout(300)
                await date_input.press("Escape")
                await page.wait_for_timeout(500)
                logger.info(f"Set On date (retry): {date_formatted}")
        else:
            logger.warning("Could not find On date input")

    # --- Confirm Start Time (should carry over, but update if needed) ---
    time_12h = _convert_24h_to_12h(send_time)
    time_input = page.get_by_placeholder("h:mm am")
    if await time_input.count() == 0:
        time_input = page.locator("input[placeholder*='h:mm']")
    if await time_input.count() > 0:
        current_time = await time_input.input_value()
        if current_time != time_12h:
            await time_input.scroll_into_view_if_needed()
            await time_input.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Meta+A")
            await page.wait_for_timeout(100)
            await page.keyboard.type(time_12h)
            await page.wait_for_timeout(300)
            logger.info(f"Updated Start Time: {time_12h}")
        else:
            logger.info(f"Start Time already set correctly: {time_12h}")

    logger.info("Delivery schedule updated")
    return True


# =========================================================================
# 6.  ASANA WRITEBACK
# =========================================================================

def update_asana_with_braze_link(task_gid: str, braze_url: str) -> bool:
    """Write the Braze campaign link back to the Asana task."""
    payload = {
        "data": {
            "custom_fields": {
                FIELD_BRAZE_LINK: braze_url,
            }
        }
    }
    result = _asana_request("PUT", f"tasks/{task_gid}", json_data=payload)
    return result is not None


def append_asana_comment(task_gid: str, comment: str) -> bool:
    """Add a comment to an Asana task."""
    payload = {
        "data": {
            "text": comment,
        }
    }
    result = _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload)
    return result is not None


# =========================================================================
# 7.  MAIN ORCHESTRATOR
# =========================================================================

async def build_single_push_campaign(
    task: Dict[str, Any],
    global_config: Dict[str, Any],
    dry_run: bool = True,
    auto_confirm: bool = False,
    headless: bool = True,
) -> Dict[str, Any]:
    """Build a single push campaign in Braze from an Asana task (one variant).

    Returns a result dict with status, errors, screenshot path, etc.
    """
    result = {
        "success": False,
        "task_gid": task["gid"],
        "task_name": task["name"],
        "variant": task["variant"],
        "campaign_name": task["campaign_name"],
        "dry_run": dry_run,
        "errors": [],
        "screenshot": None,
        "braze_url": None,
    }

    try:
        config = build_campaign_config(task, global_config)

        # Print summary
        print("\n" + "=" * 60)
        print("PUSH CAMPAIGN BUILD SUMMARY")
        print("=" * 60)
        print(f"  Asana task:     {task['name']}")
        print(f"  Braze name:     {config['campaign_name']}")
        print(f"  Variant:        {config['variant']} ({config['hav_audience']})")
        print(f"  Workspace:      {config['workspace']}")
        print(f"  Push title:     {config['push_title']}")
        print(f"  Push message:   {config['push_message']}")
        print(f"  Segment:        {config['segment']}")
        print(f"  Deep link:      {config['deep_link'][:80]}...")
        print(f"  Send time:      {config['send_time']} local")
        print(f"  Launch date:    {config['launch_date']}")
        print(f"  Source:         Most recent {config['variant']} push campaign")
        if config["is_combined_task"]:
            print(f"  ** Combined task — building {config['variant']} variant")
        print("=" * 60)

        if dry_run:
            print("\nDRY RUN — no changes will be made.")
            result["success"] = True
            return result

        # Confirm before proceeding
        if not auto_confirm:
            confirm = input("\nProceed with building this campaign? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                return result

        # Launch Playwright and build the campaign
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-save-password-bubble",
                    "--disable-password-manager-reauthentication",
                ],
            )
            context = await create_context_with_session(browser)
            await context.grant_permissions(["clipboard-read", "clipboard-write"])
            page = await context.new_page()
            await page.set_viewport_size({"width": 1920, "height": 1080})

            try:
                # Login
                await login(page)
                await save_session(context)

                # Select Havenly workspace
                await select_workspace(page, "HAV")

                # Step 1+2: Find most recent push campaign of the right
                # variant and duplicate it
                if not await duplicate_campaign(page, variant=config["variant"], brand=config.get("brand_code", "HAV")):
                    # Capture a screenshot before failing
                    try:
                        fail_path = Path(__file__).parent / f"fail_dup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        await page.screenshot(path=str(fail_path), full_page=True)
                        result["error_screenshot"] = str(fail_path)
                        logger.info(f"Failure screenshot saved: {fail_path}")
                    except Exception:
                        pass
                    result["errors"].append("Could not duplicate campaign")
                    return result

                # Step 3: Wait for the editor to load
                await wait_for_campaign_editor(page)

                # Step 4: Set the new campaign name
                await set_campaign_name(page, config["campaign_name"])

                # Step 5: Edit push content (title + message)
                content_ok = await edit_push_content(page, config["push_title"], config["push_message"])
                if not content_ok:
                    logger.warning("Push content fill had issues — continuing to save what we can")

                # Step 5b: Set On-Click Behavior to the configured deep link.
                # This is explicitly set (not just inherited from the duplicate) to
                # ensure the correct UTM-tagged URL is always used.
                await set_push_on_click_behavior(page, config["deep_link"])

                # Close any open modals/overlays before navigating
                try:
                    done_btns = page.get_by_role("button", name="Done")
                    if await done_btns.count() > 0 and await done_btns.first.is_visible():
                        await done_btns.first.click()
                        await page.wait_for_timeout(1000)
                        logger.info("Closed overlay/modal via Done button")
                except Exception:
                    pass

                # Step 6: Verify target segment
                segment_ok = await verify_target_segment(page, config["segment"])
                if not segment_ok:
                    result["errors"].append(
                        f"Segment mismatch — expected '{config['segment']}'. "
                        f"Check the duplicated campaign's Target Audiences."
                    )
                    # Continue anyway so the user can fix it manually in the draft

                # Step 7: Update delivery date
                await update_delivery_date(page, config["launch_date"], config["send_time"])

                # Screenshot before saving
                screenshot_path = await capture_screenshot(page, config["campaign_name"])
                result["screenshot"] = screenshot_path

                # Step 8: Save as draft
                await save_as_draft(page, dry_run=False)

                # Get campaign URL
                braze_url = get_campaign_url_from_page(page.url)
                result["braze_url"] = braze_url

                result["success"] = True
                logger.info(f"Push campaign built successfully: {config['campaign_name']}")

            except Exception as e:
                logger.error(f"Push campaign build failed: {e}")
                result["errors"].append(str(e))

                # Error screenshot
                try:
                    err_path = Path(__file__).parent / f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    await page.screenshot(path=str(err_path), full_page=True)
                    result["error_screenshot"] = str(err_path)
                    logger.info(f"Error screenshot saved: {err_path}")
                except Exception as ss_err:
                    logger.warning(f"Could not save error screenshot: {ss_err}")

            finally:
                await browser.close()

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        result["errors"].append(str(e))

    return result


# =========================================================================
# 8.  CLI ENTRY POINT
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Build push notification campaigns in Braze from Asana tasks."
    )
    parser.add_argument(
        "--task", type=str,
        help="Asana task GID to process (fetches full task details)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Preview without building (default: True)",
    )
    parser.add_argument(
        "--no-dry-run", action="store_true",
        help="Actually build campaigns in Braze",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Build even if the task already has a Braze campaign link",
    )
    parser.add_argument(
        "--no-headless", action="store_false", dest="headless",
        help="Show browser window (default: headless)",
    )
    parser.set_defaults(headless=True)
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    dry_run = not args.no_dry_run

    # Load brand config
    global_config = load_brand_config()

    # Determine which tasks to process
    tasks_to_process: List[Dict] = []

    if args.task:
        # Fetch a single task by GID
        logger.info(f"Fetching Asana task {args.task}...")
        raw_task = fetch_task_by_gid(args.task)
        if not raw_task:
            print(f"Error: Could not fetch task {args.task}")
            sys.exit(1)
        parsed_list = parse_asana_push_task(raw_task)
        if not parsed_list:
            print(f"Error: Task {args.task} could not be parsed (missing brand/channel/copy?)")
            sys.exit(1)
        tasks_to_process = parsed_list
    else:
        # Fetch all "Ready to Code" push tasks
        logger.info("Scanning Asana for 'Ready to Code' push tasks...")
        tasks_to_process = fetch_ready_to_code_push_tasks()

    if not tasks_to_process:
        print("No push tasks found to process.")
        return

    # Group by Asana task GID for display
    task_gids = set(t["gid"] for t in tasks_to_process)
    campaign_count = len(tasks_to_process)
    print(f"\nFound {len(task_gids)} Asana task(s) → {campaign_count} push campaign(s) to process.\n")
    if campaign_count > len(task_gids):
        combined = campaign_count - len(task_gids)
        print(f"  ({combined} extra campaign(s) from combined DPS+MP tasks)\n")

    force = args.force

    # Process each campaign variant
    results = []
    for i, task in enumerate(tasks_to_process, 1):
        print(f"\n[{i}/{campaign_count}] {task['variant']}: {task['campaign_name']}")

        if task.get("braze_link") and not task.get("is_combined_task") and not force:
            print(f"  Skipping — already has Braze campaign link: {task['braze_link']}")
            print(f"  (use --force to build anyway)")
            continue

        result = asyncio.run(
            build_single_push_campaign(
                task=task,
                global_config=global_config,
                dry_run=dry_run,
                auto_confirm=args.yes,
                headless=args.headless,
            )
        )
        results.append(result)

    # --- Asana writeback ---
    if not dry_run:
        _writeback_to_asana(results, tasks_to_process)

    # --- Summary ---
    print("\n" + "=" * 60)
    print("BATCH SUMMARY")
    print("=" * 60)
    success = sum(1 for r in results if r["success"])
    failed = sum(1 for r in results if not r["success"])
    print(f"  Processed: {len(results)}")
    print(f"  Success:   {success}")
    print(f"  Failed:    {failed}")
    if dry_run:
        print("  (dry run — no changes were made)")
    for r in results:
        status = "OK" if r["success"] else "FAIL"
        url = r.get("braze_url", "")
        print(f"  [{status}] {r['campaign_name']}")
        if url:
            print(f"         {url}")
        for err in r.get("errors", []):
            print(f"         ERROR: {err}")
    print("=" * 60)


def _writeback_to_asana(results: List[Dict], tasks: List[Dict]) -> None:
    """Write Braze campaign links back to Asana tasks.

    For combined tasks (one Asana task → two campaigns), writes both
    links as a comment and puts the first link in the Braze Link field.
    """
    # Group results by Asana task GID
    by_gid: Dict[str, List[Dict]] = {}
    for r in results:
        if r["success"] and r.get("braze_url"):
            gid = r["task_gid"]
            by_gid.setdefault(gid, []).append(r)

    for gid, gid_results in by_gid.items():
        if len(gid_results) == 1:
            # Single campaign — write link to Braze Link field
            braze_url = gid_results[0]["braze_url"]
            if update_asana_with_braze_link(gid, braze_url):
                logger.info(f"Asana task {gid} updated with Braze link")
            else:
                logger.warning(f"Failed to update Asana task {gid}")
            payload = {"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
            if _asana_request("PUT", f"tasks/{gid}", json_data=payload):
                logger.info(f"Asana task {gid} status set to Ready for QA")
            else:
                logger.warning(f"Failed to update task status for {gid}")

        elif len(gid_results) >= 2:
            # Combined task — write both links to the Braze Link field
            link_lines = []
            for r in gid_results:
                variant_label = "Pre-Converted (DPS)" if "PC" in r["variant"] else "Converted (MP)"
                link_lines.append(f"- {variant_label}: {r['braze_url']}")
            combined_links = "\n".join(link_lines)
            if update_asana_with_braze_link(gid, combined_links):
                logger.info(f"Asana task {gid} updated with both Braze links")
            payload = {"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
            if _asana_request("PUT", f"tasks/{gid}", json_data=payload):
                logger.info(f"Asana task {gid} status set to Ready for QA")
            else:
                logger.warning(f"Failed to update task status for {gid}")

            # Add a comment with all links
            lines = [
                "Push campaigns have been automatically created in Braze "
                "and are ready for review and scheduling.\n",
            ]
            for r in gid_results:
                variant_label = "Pre-Converted (DPS)" if "PC" in r["variant"] else "Converted (MP)"
                lines.append(f"- {variant_label}: {r['braze_url']}")

            comment = "\n".join(lines)
            if append_asana_comment(gid, comment):
                logger.info(f"Asana task {gid} comment added with both Braze links")
            else:
                logger.warning(f"Failed to add comment to Asana task {gid}")


if __name__ == "__main__":
    main()
