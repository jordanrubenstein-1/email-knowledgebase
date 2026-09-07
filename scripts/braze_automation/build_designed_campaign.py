#!/usr/bin/env python3
"""
Build designed (HTML) email campaigns in Braze from Asana tasks.

Duplicate-based workflow:
  1. Reads task fields: Ref Braze Campaign (source to duplicate) + Banner Image File (Drive URL)
  2. Downloads the banner image from Google Drive
  3. Uploads it to the Braze media library → gets CDN URL
  4. Duplicates the reference campaign in Braze
  5. Renames the duplicate and swaps the banner image in the DnD editor
  6. Saves as draft
  7. Writes the Braze campaign link back to the Asana task

Building block for the eventual full designed-email auto-build workflow.

Usage:
    # Dry run — parse task fields, no Braze changes
    uv run python scripts/braze_automation/build_designed_campaign.py \\
      --task-gid 1234567890 --brand HAV --dry-run

    # Full run
    uv run python scripts/braze_automation/build_designed_campaign.py \\
      --task-gid 1234567890 --brand HAV

    # Skip Asana writeback (useful during testing)
    uv run python scripts/braze_automation/build_designed_campaign.py \\
      --task-gid 1234567890 --brand HAV --skip-asana
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from playwright.async_api import (
    Page,
    async_playwright,
    TimeoutError as PlaywrightTimeout,
)

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from login import (
    create_context_with_session,
    BRAZE_DASHBOARD_URL,
    BRAND_WORKSPACE_DIRECT_URL,
)
from build_pt_campaign import (
    business_days_until,
    STO_MIN_BUSINESS_DAYS,
    fetch_task_by_gid,
    _asana_request,
    _get_custom_field,
    _get_text_value,
    _get_enum_value_gid,
    update_asana_with_braze_link,
    load_brand_config,
    get_brand_entry,
    save_as_draft,
    capture_screenshot,
    get_campaign_url_from_page,
    configure_delivery,
    _set_entry_frequency,
    configure_target_audience,
    active_exclusion_filter_groups,
    _remove_control_group,
    parse_time_string,
    is_pm_send,
    PM_SEND_TIME,
    _convert_24h_to_12h,
    _resolve_task_segment_optional,
    resolve_segment_type_for_task,
    _is_builtin_event,
    _select_conversion_event_type,
    _set_conversion_deadline,
    FIELD_BRAND,
    FIELD_SUBJECT_LINE,
    FIELD_PRE_HEADER,
    FIELD_SEND_TIME,
    FIELD_CHANNEL,
    CHANNEL_OPTIONS,
    FIELD_CATEGORY,
    FIELD_BRAZE_LINK,
    ASANA_BASE_URL,
    ASANA_PROJECT_GID,
    ASANA_WORKSPACE_GID,
    BRAND_OPTIONS,
    FIELD_TASK_STATUS,
    STATUS_READY_TO_CODE,
)
from build_push_campaign import (
    navigate_to_campaigns_list,
    _duplicate_row,
    wait_for_campaign_editor,
    set_campaign_name,
)
from utils.drive_client import download_image

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BRAZE_DASHBOARD_BASE = os.environ.get(
    "BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com"
).rstrip("/")

# Asana custom field GIDs
FIELD_REF_BRAZE_CAMPAIGN = "1214484659930023"
FIELD_BANNER_IMAGE_FILE  = "1214484659930025"
FIELD_EMAIL_SLICES       = "1208664127595091"  # Email Slices/Banners/Blocks Details
FIELD_TYPE               = "1207522425689987"  # Type (Plain-Text vs designed)
TYPE_PLAIN_TEXT          = "1207522425689988"  # Type enum value: "Plain-Text"

# Brand Asana GID -> code, inverted from BRAND_OPTIONS (imported above). Used by the
# HTML/CSS poller-fetch qualifier to resolve a task's brand for cutoff lookup.
_DESIGNED_BRAND_GID_TO_CODE = {gid: code for code, gid in BRAND_OPTIONS.items()}

# Fallback templates for single-slice HAV auto-builds (no Ref Braze Campaign)
HAV_PC_FALLBACK_TEMPLATE   = "P_EM_2026_05_12_HAV_PC_D_Memorial_Day_Sale_Reminder"
HAV_CONV_FALLBACK_TEMPLATE = "P_EM_2026_05_12_HAV_CONV_D_Memorial_Day_EA_Final"

# Asana task status GIDs
STATUS_READY_FOR_QA = "1213535128306988"

_LAST_DAY_KEYWORDS = [
    "last day",
    "final day",
    "final hours",
    "last chance",
    "final chance",
]


# ---------------------------------------------------------------------------
# Send time helpers
# ---------------------------------------------------------------------------

def _business_days_until(send_date_str: str) -> int:
    """Business days (Mon–Fri) from today to send_date_str; 0 if today/past.

    Thin alias for build_pt_campaign.business_days_until() — the PT builder,
    this builder, and the QA delivery check all decide STO-vs-fixed-time off
    the same lead-time calculation, so it lives in one place.
    """
    return business_days_until(send_date_str)


def _is_last_day_sale(task_name: str) -> bool:
    """Return True if task name indicates a last-day / final-hours sale email."""
    name_lower = task_name.lower()
    return any(kw in name_lower for kw in _LAST_DAY_KEYWORDS)


def resolve_send_time_designed(
    task_name: str,
    send_date: str,
    send_time_raw: str,
    sto_threshold: int = STO_MIN_BUSINESS_DAYS,
) -> dict:
    """Determine send time configuration for a designed email campaign.

    Args:
        sto_threshold: minimum business days until send to use Intelligent Timing.
            Default 5 (i.e. > 4) for duplicate-from-ref builds.
            Pass 4 (i.e. >= 4) for HTML/CSS auto-builds, which have more lead time.

    Returns:
        {
            "type": "specific" | "intelligent_timing",
            "time": "HH:MM" | None,       # for specific sends
            "fallback_time": "HH:MM" | None,  # for intelligent timing
            "local_time": True,
        }
    """
    parsed = parse_time_string(send_time_raw)
    default_time = "07:15"

    # No explicit Send time, but the task name signals a PM send
    # ("... - PM", "afternoon") → 4:00 PM local. Checked before the last-day /
    # business-days logic so a PM-tagged send is never scheduled for an AM slot.
    if not parsed and is_pm_send(task_name):
        logger.info("PM indicator in task name → 4:00 PM local")
        return {"type": "specific", "time": PM_SEND_TIME, "fallback_time": None, "local_time": True}

    if _is_last_day_sale(task_name):
        t = parsed or default_time
        logger.info(f"Last-day sale email → specific time {t} local")
        return {"type": "specific", "time": t, "fallback_time": None, "local_time": True}

    bdays = _business_days_until(send_date)
    if bdays >= sto_threshold:
        fb = parsed or default_time
        logger.info(f"{bdays} business days until send → Intelligent Timing (fallback {fb})")
        return {"type": "intelligent_timing", "time": None, "fallback_time": fb, "local_time": True}

    t = parsed or default_time
    logger.info(f"{bdays} business days until send → specific time {t} local")
    return {"type": "specific", "time": t, "fallback_time": None, "local_time": True}


# ---------------------------------------------------------------------------
# Braze API helpers (lightweight — avoids import_braze global state issues)
# ---------------------------------------------------------------------------

def _braze_api_key(brand: str) -> str:
    key_map = {
        "HAV": "BRAZE_API_KEY_HAV",
        "CZ": "BRAZE_API_KEY_CZ",
        "BUR": "BRAZE_API_KEY_BUR",
        "ID": "BRAZE_API_KEY_ID",
        "STF": "BRAZE_API_KEY_STF",
        "TI": "BRAZE_API_KEY_TI",
    }
    env_var = key_map.get(brand.upper(), "BRAZE_API_KEY")
    key = os.environ.get(env_var) or os.environ.get("BRAZE_API_KEY")
    if not key:
        raise RuntimeError(f"No Braze API key found for brand {brand} (tried {env_var})")
    return key


def _braze_rest_base(brand: str) -> str:
    """Return the Braze REST API base URL for a brand."""
    brand_upper = brand.upper()
    return (
        os.environ.get(f"BRAZE_BASE_URL_{brand_upper}")
        or os.environ.get("BRAZE_BASE_URL")
        or "https://rest.iad-07.braze.com"
    ).rstrip("/")


def _braze_get(endpoint: str, params: Dict, brand: str) -> Optional[Dict]:
    """Make a GET request to the Braze REST API."""
    headers = {
        "Authorization": f"Bearer {_braze_api_key(brand)}",
        "Content-Type": "application/json",
    }
    url = f"{_braze_rest_base(brand)}/{endpoint}"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        logger.error(f"Braze API {resp.status_code} for {endpoint}: {resp.text[:300]}")
        return None
    return resp.json()


def find_campaign_api_id_by_name(name: str, brand: str) -> Optional[str]:
    """Search campaigns/list for a campaign with the given name, return its API ID."""
    page_num = 0
    while page_num <= 20:
        data = _braze_get(
            "campaigns/list",
            {"page": page_num, "include_archived": "false"},
            brand,
        )
        if not data:
            break
        campaigns = data.get("campaigns", [])
        if not campaigns:
            break
        for c in campaigns:
            if c.get("name") == name:
                return c.get("id")
        page_num += 1
    logger.warning(f"Campaign '{name}' not found in campaigns/list after {page_num} pages")
    return None


def get_campaign_html(campaign_api_id: str, brand: str) -> Optional[str]:
    """Fetch the first email variant's HTML body from a Braze campaign.

    campaign_api_id must be the UUID API identifier (not the internal ObjectId
    from dashboard URLs).
    """
    data = _braze_get("campaigns/details", {"campaign_id": campaign_api_id}, brand)
    if not data:
        return None
    messages = data.get("messages", {})
    for msg in messages.values():
        if msg.get("channel") == "Email":
            return msg.get("body") or msg.get("html_body")
    # Fallback: return the first message body regardless of channel
    for msg in messages.values():
        body = msg.get("body") or msg.get("html_body")
        if body:
            return body
    return None


# ---------------------------------------------------------------------------
# Campaign name derivation
# ---------------------------------------------------------------------------

_DESIGN_CODES = {"D", "H", "PT"}


def _derive_campaign_name(ref_name: str, task_name: str, send_date: str, brand: str) -> str:
    """Generate a campaign name from task fields using generate_campaign_name().

    Builds the name directly from brand, date, and task description — same
    approach as build_pt_campaign.py.  The ref campaign name is only consulted
    for the HAV audience token (PC/CONV), which isn't available elsewhere.

    Example:
        ref_name  = "P_EM_2026_04_23_CZ_D_Color_Edit_Spring_Palette"
        task_name = "Color Edit: Sunwashed Isles"
        send_date = "2026-06-05"
        brand     = "CZ"
        → "P_EM_2026_06_05_CZ_D_Color_Edit_Sunwashed_Isles"
    """
    from utils.campaign_name import generate_campaign_name

    # Strip " | Channel (Type)" suffixes common in Asana task names
    task_name_clean = re.sub(
        r"\s*\|\s*(?:Email|SMS|Push)(?:\s*\([^)]*\))?\s*$", "", task_name.strip(), flags=re.IGNORECASE
    ).strip()

    # Strip known task-name prefixes that are redundant in the campaign name slug:
    # HAV audience ("MP: ", "DPS: ", "MP/DPS: "), brand codes ("ID: ", "CZ: ", etc.),
    # and channel prefixes ("SMS: ").
    task_name_clean = re.sub(
        r"^(?:MP/DPS|MP|DPS|SMS|" + re.escape(brand.upper()) + r")\s*:\s*",
        "",
        task_name_clean,
        flags=re.IGNORECASE,
    )

    # HAV audience (PC/CONV) is only encoded in the ref campaign name
    hav_variant = None
    if brand.upper() == "HAV":
        upper_parts = ref_name.upper().split("_")
        hav_variant = "CONV" if "CONV" in upper_parts else "PC"

    return generate_campaign_name(
        campaign_type="P",
        channel="EM",
        send_date=send_date,
        brand=brand,
        design_type="D",
        hav_audience=hav_variant,
        description=task_name_clean,
    )


# ---------------------------------------------------------------------------
# Hero image identification
# ---------------------------------------------------------------------------

def find_first_image_src(html: str) -> Optional[str]:
    """Find the src of the first image block in an email HTML string.

    Skips data URIs, Liquid variables, and tracking pixels (both dimensions < 5px).
    Code-only blocks at the top of an email don't contain <img> tags so they are
    naturally skipped. Returns the src of the first qualifying image, or None.
    """
    img_pattern = re.compile(r'<img\s([^>]+)>', re.IGNORECASE | re.DOTALL)
    src_pattern = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
    height_pattern = re.compile(r'\bheight=["\']?(\d+)["\']?', re.IGNORECASE)
    width_pattern = re.compile(r'\bwidth=["\']?(\d+)["\']?', re.IGNORECASE)

    for m in img_pattern.finditer(html):
        attrs = m.group(1)

        src_m = src_pattern.search(attrs)
        if not src_m:
            continue
        src = src_m.group(1)

        # Skip data URIs and Liquid template variables
        if src.startswith("data:") or "{{" in src:
            continue

        height_m = height_pattern.search(attrs)
        height = int(height_m.group(1)) if height_m else None

        width_m = width_pattern.search(attrs)
        width = int(width_m.group(1)) if width_m else None

        # Skip 1px tracking pixels (both dimensions explicitly tiny)
        if height is not None and height < 5 and width is not None and width < 5:
            logger.debug(f"Skipping tracking pixel ({width}x{height}px): {src[:60]}")
            continue

        logger.info(f"Banner image identified: height={height}, width={width}, src={src[:80]}")
        return src

    logger.warning("No qualifying image found in campaign HTML")
    return None


# ---------------------------------------------------------------------------
# Playwright: find email campaign row by exact name
# ---------------------------------------------------------------------------

async def _find_email_row_by_name(page: Page, campaign_name: str) -> Optional[Any]:
    """Find an email campaign row whose link text exactly matches campaign_name."""
    # Primary approach: find the text directly on the page, then walk up to the row.
    # This is more reliable than scanning row.locator("a").first which may pick up
    # tag badge links instead of the campaign name link.
    try:
        name_el = page.get_by_text(campaign_name, exact=True).first
        if await name_el.count() > 0 and await name_el.is_visible(timeout=3000):
            # Walk up to find the enclosing row
            row = name_el.locator(
                "xpath=ancestor::tr[1] | ancestor::*[@role='row'][1]"
            )
            if await row.count() > 0:
                logger.info(f"Found campaign row via get_by_text: {campaign_name}")
                return row
    except Exception:
        pass

    # Fallback: scan all rows
    rows = page.locator("tr, [role='row']")
    row_count = await rows.count()
    logger.info(f"Scanning {row_count} rows for campaign: {campaign_name}")

    for i in range(row_count):
        row = rows.nth(i)
        try:
            # Try all links in the row, not just the first, in case tag badges come first
            links = row.locator("a")
            link_count = await links.count()
            names = []
            for j in range(min(link_count, 5)):
                txt = (await links.nth(j).text_content() or "").strip()
                names.append(txt)
            logger.debug(f"Row {i} link texts: {names}")
        except Exception:
            continue

        for name in names:
            if name == campaign_name:
                logger.info(f"Found campaign row: {name}")
                return row
            if campaign_name and name and campaign_name in name:
                logger.info(f"Found campaign row (partial match): {name}")
                return row

    return None


async def _search_with_enter(page: Page, query: str) -> bool:
    """Fill the campaigns list search box and press Enter to trigger exact search."""
    # Try standard selectors first
    search_selectors = [
        page.get_by_placeholder("Search"),
        page.get_by_placeholder("Search campaigns"),
        page.locator("input[placeholder*='Search' i]").first,
        page.locator("input[type='search']").first,
        page.locator("input[placeholder*='search' i]").first,
        # Braze campaigns list search is often a simple text input near the top-right
        page.locator("input[class*='search' i]").first,
        page.locator("[data-testid*='search' i] input").first,
    ]
    for selector in search_selectors:
        try:
            if await selector.count() > 0 and await selector.first.is_visible(timeout=2000):
                await selector.first.triple_click()
                await selector.first.fill(query)
                await page.wait_for_timeout(500)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)
                logger.info(f"Search entered + Enter pressed: {query!r}")
                return True
        except Exception:
            continue

    # JS fallback: find the input by evaluating all visible inputs on the page
    try:
        found = await page.evaluate("""(query) => {
            const inputs = [...document.querySelectorAll('input')];
            for (const inp of inputs) {
                const ph = (inp.placeholder || '').toLowerCase();
                const visible = inp.offsetParent !== null;
                if (visible && (ph.includes('search') || inp.type === 'search')) {
                    inp.focus();
                    inp.value = '';
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    return inp.placeholder || inp.type || '(found)';
                }
            }
            return null;
        }""", query)
        if found:
            await page.keyboard.type(query, delay=50)
            await page.wait_for_timeout(500)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)
            logger.info(f"Search entered via JS fallback (input: {found!r}): {query!r}")
            return True
    except Exception as e:
        logger.debug(f"JS search fallback failed: {e}")

    logger.warning("Could not find search box")
    return False


async def search_and_duplicate_email_campaign(
    page: Page, campaign_name: str, brand: str
) -> bool:
    """Search for an email campaign by name and duplicate it.

    Strategy:
    1. Set Status = Draft, type full name, press Enter
    2. Set Status = All, type full name, press Enter
    3. Try other statuses (Active, Idle, Stopped) as fallback
    """
    from build_push_campaign import _set_status_filter

    # Wait for the search box to be ready
    for _attempt in range(10):
        try:
            await page.wait_for_selector(
                "input[placeholder*='Search' i], input[type='search']",
                state="visible",
                timeout=3000,
            )
            break
        except Exception:
            await page.wait_for_timeout(1000)

    for status in ("Draft", "All", "Active", "Idle", "Stopped"):
        logger.info(f"Searching for '{campaign_name}' under Status: {status}...")
        await _set_status_filter(page, status)
        await _search_with_enter(page, campaign_name)

        try:
            debug_path = (
                Path(__file__).parent.parent.parent
                / f"debug_search_{status.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
            await page.screenshot(path=str(debug_path), full_page=True)
            logger.info(f"Search screenshot ({status}): {debug_path}")
        except Exception:
            pass

        row = await _find_email_row_by_name(page, campaign_name)
        if row:
            return await _duplicate_row(page, row)

        logger.info(f"Campaign '{campaign_name}' not found under Status: {status}")

    logger.error(f"Campaign '{campaign_name}' not found under Draft, All, Active, Idle, or Stopped")
    return False


# ---------------------------------------------------------------------------
# Playwright: extract campaign ID from URL
# ---------------------------------------------------------------------------

def extract_campaign_id_from_url(url: str) -> Optional[str]:
    """Extract Braze campaign ID (hex string) from a campaign editor URL."""
    m = re.search(r'/campaigns/([a-f0-9]{24})', url)
    if m:
        return m.group(1)
    # Fallback: UUID format
    m = re.search(r'/campaigns/([0-9a-f\-]{32,})', url)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Media library upload — REST API (fast) with Playwright fallback
# ---------------------------------------------------------------------------

BRAZE_MEDIA_MAX_BYTES = 5 * 1024 * 1024  # 5 MB hard limit enforced by Braze


class MediaFileTooLargeError(Exception):
    """Raised when an image exceeds Braze's 5 MB media library limit."""
    def __init__(self, path: Path, size_bytes: int):
        mb = size_bytes / (1024 * 1024)
        super().__init__(
            f"{path.name} is {mb:.1f} MB — exceeds Braze's 5 MB media library limit. "
            f"Compress or resize the file before uploading."
        )
        self.path = path
        self.size_bytes = size_bytes


def upload_to_media_library_rest(image_path: str, brand: str) -> Optional[str]:
    """Upload an image to Braze media library via REST API.

    Requires BRAZE_API_KEY_MEDIA_{BRAND} in .env with media_library.create permission.
    Returns CDN URL or None if the key is missing / upload fails.
    Raises MediaFileTooLargeError if the file exceeds Braze's 5 MB limit.
    """
    media_key = os.environ.get(f"BRAZE_API_KEY_MEDIA_{brand.upper()}")
    if not media_key:
        return None
    base_url = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
    path = Path(image_path)

    size_bytes = path.stat().st_size
    if size_bytes > BRAZE_MEDIA_MAX_BYTES:
        raise MediaFileTooLargeError(path, size_bytes)

    ext = path.suffix.lstrip(".")
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                f"{base_url}/media_library/create",
                headers={"Authorization": f"Bearer {media_key}"},
                files={"asset_file": (path.name, f, f"image/{ext}")},
                data={"name": path.name},
                timeout=60,
            )
        if resp.status_code in (200, 201):
            assets = resp.json().get("new_assets", [])
            if assets:
                url = assets[0]["url"]
                logger.info(f"REST media upload succeeded: {url}")
                return url
        logger.warning(f"REST media upload failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"REST media upload error: {e}")
    return None


async def upload_to_media_library(page: Page, image_path: str, brand: str) -> Optional[str]:
    """Upload an image to the Braze media library and return its CDN URL.

    Tries REST API first (fast, no browser needed). Falls back to Playwright
    if the brand doesn't have a media API key configured.
    """
    logger.info(f"Uploading {image_path} to Braze media library...")

    # Try REST API first — fast, no browser needed
    cdn_url = upload_to_media_library_rest(image_path, brand)
    if cdn_url:
        return cdn_url
    logger.info("No media API key for this brand — falling back to Playwright upload")

    # Build media library URL with workspace ID if available
    workspace_url = BRAND_WORKSPACE_DIRECT_URL.get(brand.upper(), "")
    m = re.search(r'/([a-f0-9]{24})$', workspace_url)
    app_group_id = m.group(1) if m else None

    # Strategy 1: direct URL using the confirmed path pattern
    navigated = False
    candidate_urls = []
    if app_group_id:
        candidate_urls.append(
            f"{BRAZE_DASHBOARD_BASE}/engagement/templates_and_media/media_library/{app_group_id}"
        )
    candidate_urls.append(
        f"{BRAZE_DASHBOARD_BASE}/engagement/templates_and_media/media_library"
    )

    for media_url in candidate_urls:
        try:
            await page.goto(media_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            current = page.url
            logger.info(f"Media library URL → {current}")
            if "media_library" in current or "templates_and_media" in current:
                logger.info("Media library reached via direct URL")
                navigated = True
                break
        except Exception as e:
            logger.debug(f"Direct URL {media_url} failed: {e}")

    # Strategy 2: sidebar — click "Content" to expand, then "Media Library"
    if not navigated:
        logger.info("Trying sidebar navigation: Content → Media Library...")
        try:
            content_btn = page.locator("button").filter(has_text="Content")
            if await content_btn.count() > 0:
                await content_btn.first.click()
                await page.wait_for_timeout(1500)
            media_link = page.locator("a").filter(has_text="Media Library")
            if await media_link.count() > 0:
                await media_link.first.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Navigated via sidebar Content → Media Library: {page.url}")
                navigated = True
        except Exception as e:
            logger.debug(f"Sidebar navigation failed: {e}")

    if not navigated:
        logger.error(f"Could not navigate to media library (current URL: {page.url})")
        # Take a screenshot so we can see where we ended up
        try:
            err_path = Path(__file__).parent / f"debug_media_nav_fail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=str(err_path), full_page=True)
            logger.info(f"Navigation failure screenshot: {err_path}")
        except Exception:
            pass
        return None

    # Screenshot the media library so we can see what's there
    debug_path = Path(__file__).parent / f"debug_media_library_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        await page.screenshot(path=str(debug_path), full_page=True)
        logger.info(f"Media library screenshot: {debug_path}")
    except Exception:
        pass

    # Intercept the upload API response to capture the CDN URL directly
    cdn_url: Optional[str] = None

    async def _capture_upload_response(response):
        nonlocal cdn_url
        if cdn_url:
            return
        try:
            if response.status in (200, 201) and any(
                kw in response.url for kw in ("media", "upload", "asset", "image")
            ):
                data = await response.json()
                for key in ("url", "image_url", "cdn_url", "asset_url", "hosted_url", "public_url"):
                    val = data.get(key, "")
                    if val and val.startswith("http"):
                        cdn_url = val
                        logger.info(f"CDN URL captured from upload response: {cdn_url[:80]}")
                        return
        except Exception:
            pass

    page.on("response", _capture_upload_response)

    # Strategy 1: set file input directly (works even when input is hidden)
    # This is the reliable path; the file-chooser button approach consistently
    # times out on this media library page.
    uploaded = False
    for file_input_sel in [
        page.locator("input[type='file']"),
        page.locator("input[accept*='image']"),
    ]:
        try:
            if await file_input_sel.count() > 0:
                await file_input_sel.first.set_input_files(image_path)
                logger.info("File set via direct file input")
                uploaded = True
                break
        except Exception:
            continue

    if not uploaded:
        logger.error(
            "Could not find upload button or file input in media library. "
            f"Check screenshot: {debug_path}"
        )
        return None

    # Wait for upload to complete and file to appear in the library
    await page.wait_for_timeout(6000)

    if cdn_url:
        return cdn_url

    # Take post-upload screenshot
    try:
        post_path = Path(__file__).parent / f"debug_media_post_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(post_path), full_page=True)
        logger.info(f"Post-upload screenshot: {post_path}")
    except Exception:
        pass

    # Find the uploaded file row and extract its CDN URL.
    image_name = Path(image_path).name
    logger.info(f"Finding '{image_name}' in media library to get CDN URL...")

    # Locate the row for our file (by name), fall back to the most recent row
    file_row = page.locator("tbody tr").filter(has_text=image_name).first
    if await file_row.count() == 0:
        file_row = page.locator("tbody tr").first
        logger.info("Using first row in media library (most recently uploaded)")

    # Strategy A: get the CDN URL from the row's preview img src
    try:
        row_img = file_row.locator("img").first
        if await row_img.count() > 0:
            src = await row_img.get_attribute("src") or ""
            if src.startswith("http") and ("braze-images" in src or "appboy" in src or "cdn.braze" in src):
                # The src is typically the thumbnail; derive the original URL
                # e.g. https://braze-images.com/.../images/{id}/original.png
                original_url = re.sub(r'/[^/]+$', '/original', src)
                # Re-attach file extension
                ext = Path(image_name).suffix or ".png"
                if not original_url.endswith(ext):
                    original_url = original_url + ext
                logger.info(f"CDN URL derived from row img src: {original_url[:80]}")
                return original_url
    except Exception as e:
        logger.debug(f"Row img src extraction failed: {e}")

    # Strategy B: hover row, click "Copy asset URL", read clipboard
    try:
        await file_row.hover()
        await page.wait_for_timeout(800)
        copy_btn = file_row.get_by_role("button", name="Copy asset URL")
        if await copy_btn.count() == 0:
            copy_btn = page.get_by_role("button", name="Copy asset URL")
        if await copy_btn.count() > 0:
            await copy_btn.first.click()
            await page.wait_for_timeout(500)
            cdn_url_from_clipboard = await page.evaluate("navigator.clipboard.readText()")
            if cdn_url_from_clipboard and cdn_url_from_clipboard.startswith("http"):
                logger.info(f"CDN URL from clipboard: {cdn_url_from_clipboard[:80]}")
                return cdn_url_from_clipboard
    except Exception as e:
        logger.debug(f"Copy asset URL button failed: {e}")

    logger.error("Could not extract CDN URL — check the post-upload screenshot")
    return None


# ---------------------------------------------------------------------------
# Playwright: extract Campaign API UUID from compose page
# ---------------------------------------------------------------------------

async def extract_campaign_api_uuid_from_page(page: Page) -> Optional[str]:
    """Read the Campaign API UUID from the Campaign ID field on the compose page.

    Braze shows the UUID API identifier in a readonly input on the Compose step.
    This is faster and more reliable than searching campaigns/list by name.
    """
    uuid_re = re.compile(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I
    )
    try:
        inputs = page.locator("input")
        count = await inputs.count()
        for i in range(count):
            val = (await inputs.nth(i).input_value()) or ""
            if uuid_re.match(val.strip()):
                logger.info(f"Campaign API UUID read from page: {val}")
                return val.strip()
    except Exception as e:
        logger.debug(f"Could not read campaign API UUID from page inputs: {e}")

    # Fallback: try the clipboard via the "Copy" button next to Campaign ID
    try:
        copy_btn = page.get_by_role("button", name="Copy")
        if await copy_btn.count() > 0:
            await copy_btn.first.click()
            await page.wait_for_timeout(300)
            val = await page.evaluate("navigator.clipboard.readText()")
            if val and uuid_re.match(val.strip()):
                logger.info(f"Campaign API UUID from clipboard: {val}")
                return val.strip()
    except Exception as e:
        logger.debug(f"Clipboard UUID extraction failed: {e}")

    return None


# ---------------------------------------------------------------------------
# Playwright: close DnD editor
# ---------------------------------------------------------------------------

async def _close_dnd_editor(page: Page) -> bool:
    """Click the 'Done' button to close the DnD editor portal."""
    for sel in [
        page.locator('[aria-label="Done"]'),
        page.get_by_role("button", name="Done"),
        page.locator("#email-message-composer-portal button[aria-label='Done']"),
        page.locator("#email-message-composer-portal .bcl-button-primary"),
    ]:
        try:
            if await sel.count() > 0:
                await sel.first.click(force=True)
                await page.wait_for_timeout(2000)
                logger.info("DnD editor closed (clicked Done)")
                return True
        except Exception as e:
            logger.debug(f"Close DnD editor attempt: {e}")
    logger.warning("Could not find 'Done' button to close DnD editor")
    return False


async def _set_image_alt_text_in_bee(page: Any, alt_text: str) -> bool:
    """Set the alt text field in the BEE editor properties panel (best effort).

    Should be called while the image properties panel is still open (immediately
    after swap_hero_image_in_dnd succeeds). Searches the BEE iframe for a text
    input whose placeholder contains "alt" and fills it with alt_text.
    Returns True if the field was found and filled, False otherwise (caller logs warning).
    """
    bee_frame = None
    for frame in page.frames:
        if "getbee.io" in frame.url:
            bee_frame = frame
            break

    if bee_frame is None:
        logger.warning("Alt text: BEE iframe not found — cannot set alt text")
        return False

    try:
        # Strategy A: find input by placeholder containing "alt"
        alt_input = bee_frame.locator("input[placeholder*='alt' i], input[placeholder*='Alt' i]").first
        if await alt_input.count() > 0:
            await alt_input.click()
            await alt_input.fill(alt_text)
            await alt_input.press("Tab")
            await page.wait_for_timeout(400)
            logger.info(f"Alt text set to {alt_text!r} via placeholder-match input")
            return True

        # Strategy B: look for a label containing "Alt" and find the adjacent input
        alt_label = bee_frame.locator("label:has-text('Alt')")
        if await alt_label.count() > 0:
            # The input is usually a sibling or child of the label container
            container = alt_label.locator("..").locator("input[type='text']").first
            if await container.count() > 0:
                await container.click()
                await container.fill(alt_text)
                await container.press("Tab")
                await page.wait_for_timeout(400)
                logger.info(f"Alt text set to {alt_text!r} via label-adjacent input")
                return True
    except Exception as e:
        logger.debug(f"Alt text update failed: {e}")

    logger.warning(
        "Alt text: could not find alt text input in BEE properties panel — "
        "please set it manually to 'Shop Now'"
    )
    return False


# ---------------------------------------------------------------------------
# Playwright: swap hero image in DnD editor
# ---------------------------------------------------------------------------

async def swap_hero_image_in_dnd(
    page: Page, current_src: str, new_cdn_url: str
) -> bool:
    """Enter the DnD editor via 'Edit message', click the hero image block,
    update its URL, and close the editor via 'Done'.
    """
    logger.info(f"Swapping hero image in DnD editor...")
    logger.info(f"  Current src: {current_src[:80]}")
    logger.info(f"  New CDN URL: {new_cdn_url[:80]}")

    # ------------------------------------------------------------------
    # Enter the DnD editor by clicking "Edit message"
    # (we're on the Compose overview — not yet inside the full editor)
    # ------------------------------------------------------------------
    edit_btn_selectors = [
        page.get_by_role("button", name="Edit message"),
        page.locator("button:has-text('Edit message')"),
        page.get_by_role("link", name="Edit message"),
    ]
    opened_editor = False
    for sel in edit_btn_selectors:
        try:
            if await sel.count() > 0 and await sel.first.is_visible():
                await sel.first.click()
                await page.wait_for_timeout(5000)
                logger.info("Clicked 'Edit message' — waiting for DnD editor to load")
                opened_editor = True
                break
        except Exception:
            continue

    if not opened_editor:
        logger.warning("'Edit message' button not found — may already be inside the editor")

    # Screenshot to see the editor state
    try:
        debug_path = Path(__file__).parent / f"debug_dnd_editor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(debug_path), full_page=True)
        logger.info(f"DnD editor screenshot: {debug_path}")
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Click the hero image block
    # Check all frames (the email preview is often inside an iframe)
    # ------------------------------------------------------------------
    src_filename = _url_filename(current_src)
    clicked = False

    all_frames = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
    for frame in all_frames:
        for sel_str in [
            f'img[src="{current_src}"]',
            f'img[src*="{src_filename}"]',
        ]:
            try:
                img = frame.locator(sel_str)
                if await img.count() > 0:
                    await img.first.scroll_into_view_if_needed()
                    await img.first.click()
                    await page.wait_for_timeout(2000)
                    frame_label = "main frame" if frame == page.main_frame else f"iframe ({frame.url[:60]})"
                    logger.info(f"Clicked hero image in {frame_label} — selector: {sel_str}")
                    clicked = True
                    break
            except Exception as e:
                logger.debug(f"Click attempt failed ({sel_str}): {e}")
        if clicked:
            break

    # Screenshot after click attempt
    try:
        debug_path2 = Path(__file__).parent / f"debug_dnd_after_click_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(debug_path2), full_page=True)
        logger.info(f"Post-click screenshot: {debug_path2}")
    except Exception:
        pass

    if not clicked:
        logger.error(
            "Could not click hero image in DnD editor — "
            "check debug_dnd_editor_*.png"
        )
        await _close_dnd_editor(page)
        return False

    # ------------------------------------------------------------------
    # Find the BEE editor iframe — the properties panel lives inside it
    # ------------------------------------------------------------------
    bee_frame = None
    for frame in page.frames:
        if "getbee.io" in frame.url:
            bee_frame = frame
            break

    if bee_frame is None:
        logger.warning("BEE editor iframe not found — cannot interact with properties panel")
    else:
        logger.info(f"BEE frame: {bee_frame.url[:60]}")

    # Log BEE frame inputs/buttons for debugging
    if bee_frame:
        try:
            bee_info = await bee_frame.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll('input')).slice(0, 20).map(inp => ({
                    type: inp.type || '',
                    value: (inp.value || '').slice(0, 80),
                    placeholder: inp.placeholder || '',
                    id: inp.id || '',
                }));
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).slice(0, 40).map(el => ({
                    tagName: el.tagName,
                    text: (el.textContent || '').trim().slice(0, 40),
                    ariaLabel: el.getAttribute('aria-label') || '',
                }));
                return {inputs, buttons};
            }""")
            logger.debug(f"BEE inputs ({len(bee_info['inputs'])}):")
            for inp in bee_info["inputs"]:
                logger.debug(f"  type={inp['type']!r} ph={inp['placeholder']!r} val={inp['value'][:50]!r}")
            logger.debug(f"BEE buttons ({len(bee_info['buttons'])}):")
            for btn in bee_info["buttons"]:
                logger.debug(f"  {btn['tagName']} text={btn['text']!r} aria={btn['ariaLabel']!r}")
        except Exception as e:
            logger.debug(f"BEE DOM inspection failed: {e}")

    # ------------------------------------------------------------------
    # Update the image URL — work directly within the BEE frame
    # After clicking the image, BEE shows a properties panel with a
    # type='text' input holding the current CDN URL (confirmed via DOM inspection).
    # DON'T click "Change Image" — that opens a media picker dialog which
    # closes without committing the change when "Done" is pressed.
    # ------------------------------------------------------------------
    updated = False
    cdn_url_js = new_cdn_url.replace("'", "\\'")

    # Strategy A: Playwright .fill() on the BEE URL text input
    # The image URL is the first type='text' input after the properties panel opens.
    if bee_frame and not updated:
        await page.wait_for_timeout(1000)  # Let properties panel fully render
        try:
            # Confirm this is the right input (should contain current CDN URL)
            first_text = bee_frame.locator("input[type='text']").first
            if await first_text.count() > 0:
                current_val = await first_text.input_value()
                if "braze-images" in current_val or "appboy/communication" in current_val:
                    await first_text.click()
                    await first_text.fill(new_cdn_url)
                    await first_text.press("Tab")
                    await page.wait_for_timeout(500)
                    logger.info(f"Hero image URL updated via .fill() on BEE text input (was: {current_val[:60]})")
                    updated = True
                else:
                    logger.warning(f"First BEE text input value unexpected: {current_val[:60]!r}")
        except Exception as e:
            logger.debug(f"BEE .fill() update failed: {e}")

    # Strategy B: JS native value setter + React synthetic events
    if bee_frame and not updated:
        try:
            updated = await bee_frame.evaluate(f"""() => {{
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    if (inp.value && (inp.value.includes('braze-images') || inp.value.includes('appboy/communication'))) {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, '{cdn_url_js}');
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true}}));
                        return true;
                    }}
                }}
                return false;
            }}""")
            if updated:
                logger.info("Hero image URL updated via JS native value setter in BEE frame")
                await page.wait_for_timeout(800)
        except Exception as e:
            logger.debug(f"BEE JS native value setter failed: {e}")

    # Screenshot of final state before closing editor
    try:
        debug_path3 = Path(__file__).parent / f"debug_dnd_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(debug_path3), full_page=True)
        logger.info(f"DnD final state screenshot: {debug_path3}")
    except Exception:
        pass

    if not updated:
        logger.error(
            "Could not update image URL in the DnD editor. "
            "Check debug_dnd_after_click_*.png and debug_dnd_final_*.png."
        )

    # Always close the DnD editor so save_as_draft can proceed
    await _close_dnd_editor(page)
    await page.wait_for_timeout(1000)

    return updated


def _url_filename(url: str) -> str:
    """Extract just the filename from a URL for partial matching."""
    path = url.split("?")[0]
    return path.split("/")[-1] if "/" in path else path


# ---------------------------------------------------------------------------
# Playwright: set subject and preheader on compose page
# ---------------------------------------------------------------------------

async def set_subject_preheader(page: Page, subject: str, preheader: str) -> bool:
    """Fill subject and preheader fields on the campaign compose overview.

    Called after rename, while still on the compose step (not inside the DnD editor).
    Uses the same field selectors as the PT builder's configure_email_content.
    """
    if not subject and not preheader:
        logger.info("No subject or preheader to set — skipping")
        return True

    logger.info(f"Setting subject: {subject!r}  preheader: {preheader!r}")

    subject_filled = False
    preheader_filled = False

    # Designed (DnD) campaigns show subject/preheader as static text under a
    # "Sending info" section with an "Edit sending info" button — not as direct
    # inputs.  Click that button first to reveal the editable fields.
    panel_opened = False
    try:
        edit_btn = page.get_by_role("button", name="Edit sending info", exact=False)
        if await edit_btn.count() > 0 and await edit_btn.is_visible(timeout=4000):
            await edit_btn.click()
            await page.wait_for_timeout(1000)
            logger.info("Clicked 'Edit sending info' to open sending info panel")
            panel_opened = True
            # Debug: capture panel state so we can identify correct selectors
            try:
                from datetime import datetime as _dt
                _ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                _dbg = str(Path(__file__).parent / f"debug_sending_info_{_ts}.png")
                await page.screenshot(path=_dbg, full_page=False)
                logger.info(f"Sending info panel screenshot: {_dbg}")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"'Edit sending info' button not found or not needed: {e}")

    # Find Subject and Preheader inputs by their proximity to the label text.
    # Do NOT use nth() — the campaign name header is also a textbox and will
    # be accidentally filled if we select by index.
    async def _fill_monaco_field(field_id_fragment: str, value: str) -> bool:
        """Click a Monaco editor field and replace its content.

        Braze uses Monaco Editor for subject/preheader Liquid inputs.  The hidden
        <textarea> is blocked by a .view-lines overlay, so direct clicks fail.
        Strategy: navigate to the ancestor .monaco-editor div and click its
        .view-lines child (the visible, interactive surface), then Ctrl+A + type.
        """
        textarea = page.locator(f"[id*='{field_id_fragment}']")
        try:
            await textarea.wait_for(state="attached", timeout=4000)
            view_lines = textarea.locator(
                "xpath=ancestor::div[contains(@class,'monaco-editor')][1]"
                "//div[contains(@class,'view-lines')]"
            )
            if await view_lines.count() > 0:
                await view_lines.click()
            else:
                # Fallback: force-click the textarea directly
                await textarea.click(force=True)
            # On Mac, Meta+a (Cmd+A) selects all in Monaco.
            # Control+a moves cursor to beginning of line (Emacs behavior).
            await page.keyboard.press("Meta+a")
            await page.keyboard.type(value)
            return True
        except Exception as exc:
            logger.warning(f"Could not fill Monaco field '{field_id_fragment}': {exc}")
            return False

    if subject:
        subject_filled = await _fill_monaco_field("subject-input", subject)
        if subject_filled:
            logger.info("Subject filled")

    if preheader:
        preheader_filled = await _fill_monaco_field("preheader-input", preheader)
        if preheader_filled:
            logger.info("Preheader filled")

    # Debug screenshot: capture state of panel after filling fields so we can
    # verify the values are correct before closing.
    try:
        _ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
        _dbg2 = str(Path(__file__).parent / f"debug_sending_info_after_{_ts2}.png")
        await page.screenshot(path=_dbg2, full_page=False)
        logger.info(f"Sending info after-fill screenshot: {_dbg2}")
    except Exception:
        pass

    # Close the sending info panel via "Done" — always, even on failure.
    # "Done" navigates back to the compose step cleanly.
    # NEVER use Escape here — it exits the campaign editor entirely.
    if panel_opened:
        try:
            done_btn = page.get_by_role("button", name="Done", exact=True)
            await done_btn.wait_for(state="visible", timeout=3000)
            await done_btn.click()
            await page.wait_for_timeout(1000)
            logger.info("Sending info panel closed via Done")
        except Exception as e:
            logger.warning(f"Could not click Done to close panel: {e}")

    return subject_filled or not subject  # success if subject was set (or wasn't required)


# ---------------------------------------------------------------------------
# Playwright: test send
# ---------------------------------------------------------------------------

async def send_test_email(page: Page, recipient: str) -> bool:
    """Send a test email from the current campaign editor page.

    Navigates to the Compose Messages step, opens the Preview & Test modal,
    switches to the Test send tab, adds the recipient, and fires the send.
    Non-fatal — logs a warning on failure and returns False.
    """
    logger.info(f"Sending test email to {recipient}...")
    try:
        # Navigate to Compose Messages step
        for compose_name in ("Compose Messages", "Compose"):
            btn = page.get_by_role("button", name=compose_name)
            if await btn.count() > 0:
                try:
                    if await btn.is_visible(timeout=3000):
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        logger.info(f"Navigated to '{compose_name}' step")
                        break
                except Exception:
                    pass

        # Click "Preview and test" button (bottom-right of compose view)
        preview_btn = None
        for btn_name in ("Preview and test", "Preview & test", "Preview and Test"):
            candidate = page.get_by_role("button", name=btn_name, exact=False)
            if await candidate.count() > 0:
                preview_btn = candidate
                break
        if preview_btn is None:
            preview_btn = page.get_by_text("Preview and test", exact=False).first
        await preview_btn.wait_for(state="visible", timeout=10000)
        await preview_btn.click()
        await page.wait_for_timeout(1500)

        # Switch to "Text Send" tab in the modal (Braze labels it "Text Send" not "Test send")
        for tab_name in ("Text Send", "Test send", "Test Send"):
            tab = page.get_by_role("tab", name=tab_name, exact=False)
            if await tab.count() == 0:
                tab = page.get_by_text(tab_name, exact=True).first
            if await tab.count() > 0:
                await tab.click()
                await page.wait_for_timeout(500)
                break

        # Fill recipient — "Add individual users" is a label above a plain input (no placeholder).
        # Try get_by_label first; fall back to JS-driven React value setter.
        typed = False
        label_input = page.get_by_label("Add individual users", exact=False)
        if await label_input.count() > 0:
            try:
                await label_input.first.wait_for(state="visible", timeout=4000)
                await label_input.first.fill(recipient)
                await label_input.first.press("Tab")
                typed = True
            except Exception:
                pass

        if not typed:
            # JS fallback: find the first visible input inside the container that holds the
            # "Add individual users" label and set its value via React's synthetic event.
            typed = await page.evaluate("""(recipient) => {
                const visible = [...document.querySelectorAll('input')].filter(
                    el => el.offsetParent !== null
                );
                for (const input of visible) {
                    let node = input.parentElement;
                    for (let i = 0; i < 8; i++) {
                        if (!node) break;
                        if (node.textContent && node.textContent.includes('Add individual users')) {
                            input.focus();
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            setter.call(input, recipient);
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                        node = node.parentElement;
                    }
                }
                return false;
            }""", recipient)
            await page.keyboard.press("Tab")

        if not typed:
            raise RuntimeError("Could not locate the 'Add individual users' input field")

        await page.wait_for_timeout(1500)

        # Click "Send Test"
        send_btn = page.get_by_role("button", name="Send Test", exact=False)
        await send_btn.wait_for(state="visible", timeout=5000)
        await send_btn.click()

        # Wait for success confirmation (non-fatal if toast doesn't appear)
        try:
            await page.get_by_text("Test message sent", exact=False).wait_for(
                state="visible", timeout=15000
            )
        except Exception:
            logger.warning("Test send confirmation toast not detected — check inbox")

        logger.info(f"Test email dispatched to {recipient}")
        return True

    except Exception as e:
        logger.warning(f"Test send failed (non-fatal): {e}")
        return False


async def _conversions_look_correct(page: "Page", expected: dict) -> bool:
    """Return True if the Assign Conversions page already shows all expected events.

    Checks two things:
      1. Enough "Conversion event type" labels exist (one per slot).
      2. Every expected event name (or its Braze UI label for built-ins) is
         visible in the page text.

    This is intentionally lenient — a false negative just means we re-apply
    the correct values, which is harmless.
    """
    label_count = await page.get_by_text("Conversion event type", exact=True).count()
    if label_count < len(expected):
        return False

    page_text = await page.inner_text("body")
    for slot_config in expected.values():
        event_name = slot_config.get("event", "")
        is_builtin, braze_label = _is_builtin_event(event_name)
        check_name = braze_label if is_builtin else event_name
        if check_name not in page_text:
            return False

    return True


async def configure_conversions_designed(page: "Page", brand: str) -> None:
    """Navigate to Assign Conversions and set the correct events for this brand.

    Reads expected events from brand_config.yaml.  If all slots already show
    the right values, logs and returns immediately.  Otherwise adds any missing
    slots and updates each event type and deadline.
    """
    brand_entry = get_brand_entry(brand, load_brand_config())
    if not brand_entry:
        logger.warning(f"No brand config entry for {brand} — skipping conversion events")
        return

    expected = brand_entry.get("conversion_events", {})
    if not expected:
        logger.warning(f"No conversion_events defined for {brand} — skipping")
        return

    # Navigate to the Assign Conversions step
    navigated = False
    for nav_name in ("Assign Conversions", "Assign"):
        try:
            btn = page.get_by_role("button", name=nav_name)
            await btn.wait_for(state="visible", timeout=5000)
            await btn.click()
            await page.wait_for_timeout(2000)
            navigated = True
            break
        except Exception:
            continue
    if not navigated:
        logger.warning("Could not navigate to Assign Conversions step — skipping")
        return

    # Check current state before making any changes
    if await _conversions_look_correct(page, expected):
        logger.info("Conversion events already correct — skipping")
        return

    logger.info("Conversion events need updating — configuring...")

    for idx, slot in enumerate(["A", "B", "C", "D"]):
        slot_config = expected.get(slot)
        if not slot_config:
            continue

        event_name = slot_config.get("event", "")
        deadline = slot_config.get("deadline_days", 3)
        is_builtin, braze_label = _is_builtin_event(event_name)

        # Add the slot if it isn't on the page yet
        label_count = await page.get_by_text("Conversion event type", exact=True).count()
        if idx >= label_count:
            add_btn = page.get_by_role("button", name="Add Conversion Event")
            try:
                await add_btn.scroll_into_view_if_needed()
                await add_btn.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Added conversion slot {slot}")
            except Exception as e:
                logger.warning(f"Could not add conversion slot {slot}: {e}")
                continue

        if is_builtin:
            logger.info(f"Conversion {slot}: {braze_label} (built-in), {deadline}d")
        else:
            logger.info(f"Conversion {slot}: Performs Custom Event → '{event_name}', {deadline}d")

        await _select_conversion_event_type(page, idx, slot, is_builtin, braze_label, event_name)
        await _set_conversion_deadline(page, idx, slot, deadline)

    logger.info("Conversion events configured")


async def configure_delivery_designed(
    page: "Page",
    send_time_config: dict,
    launch_date: str,
) -> bool:
    """Configure the Delivery step for a designed campaign.

    Thin wrapper around the PT builder's configure_delivery, which already
    sets the Intelligent Timing fallback time itself (via _set_it_fallback_time)
    when send_time_config["type"] == "intelligent_timing". Do not duplicate
    that here — a second, separate fallback-time-setting pass previously
    lived in this function and reopened Braze's picker after configure_delivery
    had already set it correctly; that second pass used a plain (non-scrolling)
    DOM query that can't reach items outside the picker's visible window, so
    it silently failed to reselect the minute/period and left the field on
    whatever stale value Braze defaulted to — confirmed 2026-08-27 via a live
    test campaign where an intended 07:15 AM fallback ended up as 5:00 PM.
    """
    return await configure_delivery(page, send_time_config, launch_date, skip_tz_checkbox=True)


# ---------------------------------------------------------------------------
# Audience helpers
# ---------------------------------------------------------------------------

_DESIGN_CODES_SET = {"D", "H", "PT"}


def _score_task_name_match(task_name: str, ref_campaign: str) -> int:
    """Score how closely an Asana task name matches the ref campaign name.

    Extracts the description tokens from the campaign name (words after the
    design-type token), normalises both strings, and counts how many description
    words appear in the task name.  Higher is better.
    """
    parts = ref_campaign.split("_")
    desc_start: Optional[int] = None
    for i, p in enumerate(parts):
        if p.upper() in _DESIGN_CODES_SET and i >= 5:
            desc_start = i + 1
            break
    if desc_start is None:
        desc_start = max(0, len(parts) - 3)

    desc_words = [w.lower() for w in parts[desc_start:] if len(w) > 2]
    task_lower = task_name.lower()
    return sum(1 for w in desc_words if w in task_lower)


def _find_ref_campaign_segment_type(ref_campaign: str, brand: str) -> Optional[str]:
    """Search Asana for the task that produced the ref campaign and return its segment type.

    Three-pass matching strategy:
      1. Date — use YYYY-MM-DD from campaign name positions 2-4 + brand filter
      2. Channel — keep only email tasks (designed campaigns are always email)
      3. Keywords — if multiple email tasks remain, score each by how many
         description words from the campaign name appear in the task name;
         use the highest-scoring task

    Returns "full_file", "engaged", or None if no confident match is found.
    """
    parts = ref_campaign.split("_")

    # --- Pass 1: parse date ---
    if (
        len(parts) >= 5
        and re.match(r"^\d{4}$", parts[2])
        and re.match(r"^\d{2}$", parts[3])
        and re.match(r"^\d{2}$", parts[4])
    ):
        ref_date = f"{parts[2]}-{parts[3]}-{parts[4]}"
    else:
        logger.debug(f"Could not parse date from ref campaign name {ref_campaign!r}")
        return None

    logger.info(f"Looking up ref campaign segment: {ref_campaign!r} → date {ref_date}, brand {brand}")
    brand_gid = BRAND_OPTIONS.get(brand.upper())

    try:
        ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
        day_before = (ref_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        day_after = (ref_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return None

    params: Dict[str, Any] = {
        "projects.any": ASANA_PROJECT_GID,
        "due_on.after": day_before,
        "due_on.before": day_after,
        "opt_fields": "name,custom_fields,due_on",
        "limit": "50",
    }
    if brand_gid:
        params[f"custom_fields.{FIELD_BRAND}.value"] = brand_gid

    data = _asana_request("GET", f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search", params=params)
    if not data:
        logger.debug(f"No Asana tasks found on {ref_date} for brand {brand}")
        return None

    # Exact date match only
    candidates = [t for t in data if t.get("due_on") == ref_date]
    if not candidates:
        logger.debug(f"No tasks with due_on={ref_date} in search results")
        return None

    logger.debug(f"Pass 1 (date): {len(candidates)} candidate(s) on {ref_date}")

    # --- Pass 2: channel filter — keep email tasks only ---
    email_gid = CHANNEL_OPTIONS["email"]
    email_candidates = [
        t for t in candidates
        if _get_enum_value_gid(t, FIELD_CHANNEL) == email_gid
    ]
    # Fall back to all candidates if none are tagged as email
    # (older tasks may not have Channel set)
    if email_candidates:
        candidates = email_candidates
        logger.debug(f"Pass 2 (channel=email): {len(candidates)} candidate(s)")
    else:
        logger.debug("Pass 2: no email-channel tasks found — keeping all channel candidates")

    # --- Single match: use it directly ---
    if len(candidates) == 1:
        task = candidates[0]
        seg_type = _resolve_task_segment_optional(task, brand.upper(), send_date=ref_date)
        logger.info(f"Single match: {task.get('name')!r} → segment_type={seg_type}")
        return seg_type

    # --- Pass 3: keyword scoring ---
    scored = [
        (t, _score_task_name_match(t.get("name", ""), ref_campaign))
        for t in candidates
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_task, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else -1

    if best_score == 0:
        logger.debug(
            f"Pass 3: no keyword match among {len(candidates)} candidates — cannot determine ref segment"
        )
        return None

    if best_score == second_score:
        # Tie — not confident enough to pick one
        logger.debug(
            f"Pass 3: tie at score={best_score} among {len(candidates)} candidates — cannot determine ref segment"
        )
        return None

    seg_type = _resolve_task_segment_optional(best_task, brand.upper(), send_date=ref_date)
    logger.info(
        f"Pass 3 best match (score={best_score}): {best_task.get('name')!r} → segment_type={seg_type}"
    )
    return seg_type


def _qualifies_htmlcss_task(task: Dict, htmlcss_cutoffs: Dict[str, str]) -> bool:
    """True if a task qualifies for a from-scratch HTML/CSS build even without a
    Ref Braze Campaign. Mirrors the poller's / webhook's `is_htmlcss_designed` gate:
    brand in the cutoff map, Type != Plain-Text, due_on >= brand cutoff, and a Drive
    URL in the Email Slices field. Kept identical so every no-ref task admitted here
    is guaranteed to hit the HTML/CSS branch downstream (never the DnD path, which
    would fail without a ref campaign)."""
    brand_gid = _get_enum_value_gid(task, FIELD_BRAND)
    brand_code = _DESIGNED_BRAND_GID_TO_CODE.get(brand_gid or "")
    cutoff = htmlcss_cutoffs.get(brand_code or "")
    if not cutoff:
        return False
    if _get_enum_value_gid(task, FIELD_TYPE) == TYPE_PLAIN_TEXT:
        return False
    if (task.get("due_on") or "") < cutoff:
        return False
    drive_url = _get_text_value(task, FIELD_EMAIL_SLICES) or ""
    return "drive.google.com" in drive_url


def fetch_ready_to_code_designed_tasks(
    brand_filter: Optional[str] = None,
    htmlcss_cutoffs: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Fetch tasks with 'Ready to Code' status and Channel=Email.

    By default returns only tasks with a Ref Braze Campaign set (required by the DnD
    duplicator and the Klaviyo ref-campaign clone path).

    When `htmlcss_cutoffs` (brand code -> first-eligible send date) is provided, ALSO
    returns tasks with no Ref Braze Campaign that qualify as a from-scratch HTML/CSS
    build (Drive URL + on/after cutoff + not PT). This lets the 15-min poller safety
    net cover the HTML/CSS builders (CZ/STF Braze, TI Klaviyo) for tasks briefed with
    only a Drive folder and no ref campaign — the webhook already handles them in
    real time, this closes the gap when the webhook missed one.
    """
    params: Dict[str, Any] = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
        f"custom_fields.{FIELD_CHANNEL}.value": CHANNEL_OPTIONS["email"],
        "opt_fields": ",".join([
            "name", "due_on", "completed",
            "custom_fields", "custom_fields.gid",
            "custom_fields.enum_value", "custom_fields.enum_value.gid",
            "custom_fields.enum_value.name",
            "custom_fields.text_value", "custom_fields.display_value",
        ]),
        "limit": 100,
    }
    if brand_filter:
        brand_gid = BRAND_OPTIONS.get(brand_filter.upper())
        if brand_gid:
            params[f"custom_fields.{FIELD_BRAND}.value"] = brand_gid

    data = _asana_request("GET", f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search", params=params)
    if not data:
        return []

    results = []
    for task in data:
        if task.get("completed"):
            continue
        # Ref Braze Campaign set → always a build candidate (DnD / ref-campaign clone).
        if _get_text_value(task, FIELD_REF_BRAZE_CAMPAIGN):
            results.append(task)
            continue
        # No ref campaign → admit only if it qualifies as a Drive-URL HTML/CSS build.
        if htmlcss_cutoffs and _qualifies_htmlcss_task(task, htmlcss_cutoffs):
            results.append(task)
    return results


async def _clear_audience_selection(page: Page) -> None:
    """Remove all filter rows and exclusion group entries from a duplicated campaign.

    The row-level trash Remove button (data-cy="filter-actions-remove") only renders
    into the DOM when the ROW is hovered. We hover the drag handle (left side of the
    row) so mouseenter fires on the row without opening the select dropdown, then
    click the row-level button (data-cy="filter-actions-remove") — not the chip-level
    × buttons (aria-label="Remove") that live inside the select and are always present.
    """
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(500)

    removed_count = 0
    no_progress_rounds = 0

    for _attempt in range(30):
        # Each filter row has a react-beautiful-dnd drag handle at its left edge.
        handles = page.locator("[data-rbd-drag-handle-draggable-id]")
        handle_count = await handles.count()
        if handle_count == 0:
            break

        clicked_this_round = False
        for idx in range(handle_count):
            try:
                handle = handles.nth(idx)
                await handle.scroll_into_view_if_needed()
                # Move mouse away first so mouseenter fires when we enter the row.
                await page.mouse.move(0, 0)
                await page.wait_for_timeout(50)
                # hover() on the drag handle triggers the row's mouseenter without
                # opening the select dropdown (which requires clicking the control).
                await handle.hover()
                await page.wait_for_timeout(250)
                # Target the row-level trash button, not chip-level × buttons.
                remove_btn = page.locator('button[data-cy="filter-actions-remove"]')
                if await remove_btn.count() > 0:
                    await remove_btn.first.click()
                    await page.wait_for_timeout(400)
                    removed_count += 1
                    clicked_this_round = True
                    break  # Re-evaluate after each removal (DOM shifts)
            except Exception as e:
                logger.debug(f"Clear attempt handle {idx}: {e}")

        if not clicked_this_round:
            no_progress_rounds += 1
            if no_progress_rounds >= 3:
                break
        else:
            no_progress_rounds = 0

    logger.info(f"Cleared {removed_count} filter/exclusion rows")


async def configure_audience_designed(
    page: Page,
    desired_segment_type: Optional[str],
    ref_segment_type: Optional[str],
    brand: str,
    hav_variant: Optional[str] = None,
    launch_date: Optional[str] = None,
) -> bool:
    """Configure the Target Audience step for a designed email campaign.

    If desired_segment_type matches ref_segment_type, the audience is already
    correct and no changes are made.  Otherwise, existing selections are cleared
    and the audience is reconfigured using the brand config.

    Args:
        desired_segment_type: "full_file" | "engaged" | None (from current task)
        ref_segment_type: segment of the ref campaign (None if unknown)
        brand: brand code (HAV, CZ, BUR, ID, STF, TI)
        hav_variant: "PC" | "CONV" (HAV only)
        launch_date: Campaign send date (ISO YYYY-MM-DD). Used to drop
            `exclusion_filter_groups` entries whose `expires_before` has passed.
            Always pass this when known; omitting it falls back to today.
    """
    if not desired_segment_type:
        # Shouldn't happen (caller defaults to full_file), but guard anyway
        logger.warning("desired_segment_type is None — skipping audience configuration")
        return True

    # Always reconfigure the audience — even when desired==ref, the duplicate may
    # carry Holdout filters or other artifacts that need to be removed.
    logger.info(
        f"Configuring audience: desired={desired_segment_type!r} (ref was {ref_segment_type!r})"
    )

    # Load the brand audience config for the desired segment type
    global_config = load_brand_config()
    brand_entry = get_brand_entry(brand, global_config, hav_variant=hav_variant)
    audience_config = brand_entry.get("audiences", {}).get(desired_segment_type)
    if not audience_config:
        logger.warning(
            f"No audience config found for {brand}/{desired_segment_type} — skipping"
        )
        return False

    # Navigate to Target Audiences step (configure_target_audience does this, but
    # we need to clear existing selections first, so navigate explicitly here).
    target_selectors = [
        page.get_by_role("button", name="Target Audiences"),
        page.get_by_role("button", name="Target"),
        page.get_by_text("Target Audiences", exact=True),
    ]
    for sel in target_selectors:
        try:
            await sel.wait_for(state="visible", timeout=5000)
            await sel.click()
            await page.wait_for_timeout(2000)
            logger.info("Navigated to Target Audiences step for audience configuration")
            break
        except Exception:
            continue

    # Remove control group (carry over from PT builder)
    await _remove_control_group(page)

    # Debug: screenshot of audience step before clearing so we can see existing filters.
    try:
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _dbg = str(Path(__file__).parent / f"debug_audience_before_{_ts}.png")
        await page.screenshot(path=_dbg, full_page=True)
        logger.info(f"Audience-before screenshot: {_dbg}")
    except Exception:
        pass

    # Clear existing segment + filter selections from the duplicate
    await _clear_audience_selection(page)
    await page.wait_for_timeout(500)

    # Debug: screenshot after clearing so we can verify what was removed.
    try:
        _ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
        _dbg2 = str(Path(__file__).parent / f"debug_audience_after_clear_{_ts2}.png")
        await page.screenshot(path=_dbg2, full_page=True)
        logger.info(f"Audience-after-clear screenshot: {_dbg2}")
    except Exception:
        pass

    # Re-configure using the PT builder's configure_target_audience logic,
    # but skip its navigation step (we're already on the right page).
    # We call the lower-level helpers directly.
    from build_pt_campaign import (
        _select_segment,
        _add_audience_filter,
        _add_exclusion_filter_group,
        _set_variant1_to_100,
    )

    audience_type = audience_config.get("type", "segment")
    segment_name = audience_config.get("segment", "")
    filters = audience_config.get("filters", [])

    # Strip exclusion filter groups that have expired. Keyed off the campaign's
    # own send date, not today — see active_exclusion_filter_groups().
    active_exclusions = active_exclusion_filter_groups(audience_config, launch_date)

    if segment_name:
        await _select_segment(page, segment_name)

    for f in filters:
        await _add_audience_filter(page, f)

    # Add exclusion filter groups (separate AND groups with "Not Included")
    for excl in active_exclusions:
        excl_name = excl.get("name", "")
        if excl_name:
            await _add_exclusion_filter_group(page, excl_name)

    # Set variant to 100% LAST — segment picker interactions cause React re-renders
    # that revert any earlier DOM manipulation of the variant % input.
    await _set_variant1_to_100(page)

    logger.info(
        f"Audience configured: {audience_type} / {segment_name}, "
        f"{len(active_exclusions)} exclusion(s)"
    )
    return True


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def build_designed_campaign(
    task_gid: str,
    brand: str,
    dry_run: bool = True,
    headless: bool = True,
    skip_asana: bool = False,
    auto_confirm: bool = False,
    ref_campaign_override: Optional[str] = None,
    banner_drive_url_override: Optional[str] = None,
    single_slice_build: bool = False,
) -> Dict[str, Any]:
    """Run the full pipeline for one Asana task.

    Returns a result dict with success, braze_url, errors, etc.

    For single-slice auto-builds (no Ref Braze Campaign on the task), pass
    ref_campaign_override and banner_drive_url_override explicitly, and set
    single_slice_build=True to trigger status→Ready for QA and the appropriate
    Asana comment.
    """
    result: Dict[str, Any] = {
        "success": False,
        "task_gid": task_gid,
        "brand": brand,
        "dry_run": dry_run,
        "errors": [],
        "braze_url": None,
    }

    # ------------------------------------------------------------------
    # 1. Fetch Asana task
    # ------------------------------------------------------------------
    logger.info(f"Fetching Asana task {task_gid}...")
    task = fetch_task_by_gid(task_gid)
    if not task:
        result["errors"].append("Could not fetch Asana task")
        return result

    task_name = task.get("name", "")
    send_date = task.get("due_on") or ""
    ref_campaign = ref_campaign_override or _get_text_value(task, FIELD_REF_BRAZE_CAMPAIGN)
    banner_drive_url = banner_drive_url_override or _get_text_value(task, FIELD_BANNER_IMAGE_FILE)
    subject_line = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""
    send_time_raw = _get_text_value(task, FIELD_SEND_TIME) or ""

    if not ref_campaign:
        result["errors"].append("Ref Braze Campaign field is empty on the Asana task")
        return result
    if not send_date:
        result["errors"].append(
            "Task has no due date — set a due date (the send date) before building"
        )
        return result

    new_campaign_name = _derive_campaign_name(ref_campaign, task_name, send_date, brand)
    send_time_config = resolve_send_time_designed(task_name, send_date, send_time_raw)
    desired_segment_type = resolve_segment_type_for_task(task, brand.upper(), send_date=send_date)

    # Determine ref campaign's segment (used to decide if audience changes are needed)
    ref_segment_type: Optional[str] = None
    if desired_segment_type:
        ref_segment_type = _find_ref_campaign_segment_type(ref_campaign, brand)

    # HAV audience variant (PC vs CONV) from campaign name
    hav_variant: Optional[str] = None
    if brand.upper() == "HAV":
        upper_parts = ref_campaign.upper().split("_")
        if "CONV" in upper_parts:
            hav_variant = "CONV"
        else:
            hav_variant = "PC"

    # Summarise send time for display
    if send_time_config["type"] == "intelligent_timing":
        send_time_display = f"Intelligent Timing (fallback {send_time_config['fallback_time']} local)"
    else:
        send_time_display = f"{send_time_config['time']} local"

    # Audience display
    segment_source = f"from Segment field" if segment_raw else "defaulting to full_file"
    if ref_segment_type == desired_segment_type:
        audience_display = f"{desired_segment_type} ({segment_source}, matches ref — no changes)"
    else:
        ref_display = ref_segment_type or "ref unknown"
        audience_display = f"{desired_segment_type} ({segment_source}, ref was {ref_display} — will adjust)"

    print("\n" + "=" * 60)
    print("DESIGNED CAMPAIGN BUILD SUMMARY")
    print("=" * 60)
    print(f"  Task:              {task_name}")
    print(f"  Brand:             {brand}")
    print(f"  Send date:         {send_date}")
    print(f"  Send time:         {send_time_display}")
    print(f"  Audience:          {audience_display}")
    print(f"  Ref campaign:      {ref_campaign}")
    print(f"  Banner image URL:  {banner_drive_url or '(not provided — skipping swap)'}")
    print(f"  Subject:           {subject_line or '(not set)'}")
    print(f"  Preheader:         {preheader or '(not set)'}")
    print(f"  New campaign name: {new_campaign_name}")
    print("=" * 60)

    if dry_run:
        print("\nDRY RUN — no changes will be made.")
        result["success"] = True
        return result

    if not auto_confirm:
        confirm = input("\nProceed? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return result

    # ------------------------------------------------------------------
    # 2. Download banner image from Google Drive (only if provided)
    # ------------------------------------------------------------------
    image_path = None
    if banner_drive_url:
        logger.info("Downloading banner image from Google Drive...")
        try:
            image_path = download_image(banner_drive_url)
            logger.info(f"Banner image downloaded to: {image_path}")
        except Exception as e:
            result["errors"].append(f"Failed to download banner image: {e}")
            return result

    # ------------------------------------------------------------------
    # 3. Launch Playwright
    # ------------------------------------------------------------------
    try:
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

            from login import ensure_logged_in, select_workspace
            await ensure_logged_in(page)
            await select_workspace(page, brand)

            # --------------------------------------------------------------
            # 4. Upload hero image to Braze media library (only if provided)
            # --------------------------------------------------------------
            cdn_url = None
            if banner_drive_url:
                cdn_url = await upload_to_media_library(page, image_path, brand)
                if not cdn_url:
                    result["errors"].append(
                        "Media library upload failed or CDN URL could not be captured — "
                        "check debug_media_library_*.png screenshots"
                    )
                    # Don't abort — proceed with duplication, swap will be skipped gracefully
                else:
                    logger.info(f"Hero image CDN URL: {cdn_url}")

            # --------------------------------------------------------------
            # 5. Duplicate the reference campaign
            # --------------------------------------------------------------
            await navigate_to_campaigns_list(page, brand=brand)
            duplicated = await search_and_duplicate_email_campaign(
                page, ref_campaign, brand
            )
            if not duplicated:
                result["errors"].append(
                    f"Could not find or duplicate reference campaign: {ref_campaign}"
                )
                return result

            # --------------------------------------------------------------
            # 6. Wait for editor + rename
            # --------------------------------------------------------------
            await wait_for_campaign_editor(page)
            await set_campaign_name(page, new_campaign_name)

            # Extract internal campaign ID from URL (for the Braze URL we return later)
            campaign_id = extract_campaign_id_from_url(page.url)
            logger.info(f"New campaign ID (internal): {campaign_id}")

            # --------------------------------------------------------------
            # 6b. Set subject and preheader
            # --------------------------------------------------------------
            if subject_line or preheader:
                await set_subject_preheader(page, subject_line, preheader)

            # --------------------------------------------------------------
            # 7. Identify banner image src + swap in DnD editor (while still on
            #    Compose Messages step — must happen before audience navigation)
            # --------------------------------------------------------------
            banner_src = None
            if banner_drive_url and cdn_url:
                # Try to read the new campaign's API UUID from the page first
                new_api_uuid = await extract_campaign_api_uuid_from_page(page)
                if new_api_uuid:
                    logger.info(f"Campaign API UUID from page: {new_api_uuid}")
                    html = get_campaign_html(new_api_uuid, brand)
                    if html:
                        banner_src = find_first_image_src(html)
                    else:
                        logger.warning("Could not fetch new campaign HTML via API")

                if not banner_src:
                    # Fall back: fetch ref campaign HTML (duplicate has identical structure)
                    logger.info(f"Looking up API ID for ref campaign: {ref_campaign}...")
                    ref_api_id = find_campaign_api_id_by_name(ref_campaign, brand)
                    if ref_api_id:
                        logger.info(f"Ref campaign API ID: {ref_api_id}")
                        html = get_campaign_html(ref_api_id, brand)
                        if html:
                            banner_src = find_first_image_src(html)
                        else:
                            logger.warning("Could not fetch ref campaign HTML via API")
                    else:
                        logger.warning(f"Ref campaign '{ref_campaign}' not found in campaigns/list")

            # --------------------------------------------------------------
            # 8. Swap banner image in DnD editor (only if banner provided)
            # --------------------------------------------------------------
            if banner_drive_url:
                if cdn_url and banner_src:
                    swapped = await swap_hero_image_in_dnd(page, banner_src, cdn_url)
                    if not swapped:
                        result["errors"].append(
                            "Banner image swap may have failed — check debug screenshots. "
                            "Manual update in Braze may be needed."
                        )
                    # For single-slice builds, set alt text to "Shop Now" (best effort).
                    # The BEE properties panel stays open after the URL swap, so we can
                    # find and fill the alt text input while we're still on the image.
                    if single_slice_build:
                        await _set_image_alt_text_in_bee(page, "Shop Now")
                elif not cdn_url:
                    logger.warning("Skipping image swap — no CDN URL available")
                else:
                    logger.warning(
                        "Skipping image swap — could not identify banner image src. "
                        "Manual update in Braze may be needed."
                    )
            else:
                logger.info("No banner image provided — skipping swap step")

            # --------------------------------------------------------------
            # 6c. Configure target audience
            # --------------------------------------------------------------
            await configure_audience_designed(
                page,
                desired_segment_type=desired_segment_type,
                ref_segment_type=ref_segment_type,
                brand=brand,
                hav_variant=hav_variant,
                launch_date=send_date,
            )

            # --------------------------------------------------------------
            # 8b. Configure delivery schedule
            # --------------------------------------------------------------
            await configure_delivery_designed(page, send_time_config, send_date)

            # --------------------------------------------------------------
            # 8c. Configure conversion events
            # --------------------------------------------------------------
            await configure_conversions_designed(page, brand)

            # --------------------------------------------------------------
            # 9. Save as draft
            # --------------------------------------------------------------
            await save_as_draft(page, dry_run=False)

            braze_url = get_campaign_url_from_page(page.url)
            if not braze_url:
                braze_url = page.url
            result["braze_url"] = braze_url
            logger.info(f"Campaign saved as draft: {braze_url}")

            # Screenshot for verification
            await capture_screenshot(page, new_campaign_name)

            # Test send (before closing browser)
            if not dry_run:
                test_recipient = os.getenv("QA_TEST_RECIPIENT", "jordan.rubenstein@havenly.com")
                await send_test_email(page, test_recipient)

            await context.close()
            await browser.close()

    except Exception as e:
        logger.exception("Playwright session failed")
        result["errors"].append(f"Playwright error: {e}")
        return result
    finally:
        # Clean up temp image file
        if image_path:
            try:
                Path(image_path).unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 10. Write Braze link back to Asana
    # ------------------------------------------------------------------
    if result["braze_url"] and not skip_asana:
        logger.info(f"Writing Braze link to Asana task {task_gid}...")
        ok = update_asana_with_braze_link(task_gid, result["braze_url"])
        if ok:
            logger.info("Asana task updated with Braze campaign link")
        else:
            result["errors"].append("Asana writeback failed (campaign was created successfully)")

    # ------------------------------------------------------------------
    # 11. Post Asana comment tagging the producer (task assignee)
    # ------------------------------------------------------------------
    if result["braze_url"] and not skip_asana:
        import html as _html
        assignee = task.get("assignee") or {}
        assignee_gid = assignee.get("gid")

        if single_slice_build:
            body_text = (
                "this designed email has been automatically built in Braze. "
                "The template has been duplicated and the banner image from the design "
                "assets folder has been swapped in. Please QA the email, subject line "
                "and preheader, audience, and send schedule before sending to the QA group.\n\n"
                f"Campaign link: {result['braze_url']}"
            )
        else:
            body_text = (
                "this designed email campaign has been automatically built in Braze. "
                "The campaign shell (name, subject/preheader, audience, and send schedule) "
                "is configured, but the email itself still needs to be built in the "
                "Drag & Drop editor, and all aspects of the campaign need QA.\n\n"
                f"Campaign link: {result['braze_url']}"
            )

        if assignee_gid:
            html_body = _html.escape(body_text, quote=False)
            _url_text = _html.escape(result["braze_url"], quote=False)
            _url_attr = _html.escape(result["braze_url"], quote=True)
            html_body = html_body.replace(
                _url_text,
                f'<a href="{_url_attr}">{_url_text}</a>',
            )
            html_body = f'<a data-asana-gid="{assignee_gid}"/>, {html_body}'
            payload = {"data": {"html_text": f"<body>{html_body}</body>", "is_pinned": False}}
        else:
            body_text = body_text[0].upper() + body_text[1:]
            payload = {"data": {"text": body_text, "is_pinned": False}}

        comment_ok = _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload)
        if comment_ok:
            logger.info("Posted auto-build comment on Asana task")
        else:
            logger.warning("Failed to post auto-build comment on Asana task")

    # ------------------------------------------------------------------
    # 12. For single-slice builds: update Asana status to Ready for QA
    # ------------------------------------------------------------------
    if single_slice_build and result["braze_url"] and not skip_asana:
        qa_payload = {"data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}}
        qa_ok = _asana_request("PUT", f"tasks/{task_gid}", json_data=qa_payload)
        if qa_ok:
            logger.info("Asana task status updated to Ready for QA")
        else:
            logger.warning("Failed to update Asana task status to Ready for QA")

    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build a designed Braze email campaign from an Asana task."
    )
    parser.add_argument(
        "--task-gid", required=True,
        help="Asana task GID to process",
    )
    parser.add_argument(
        "--brand", required=True,
        choices=["HAV", "CZ", "BUR", "ID", "STF", "TI"],
        help="Brand code",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Parse task fields only — no Braze changes (default: True)",
    )
    parser.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually build the campaign in Braze",
    )
    parser.add_argument(
        "--skip-asana", action="store_true",
        help="Skip writing the Braze link back to Asana",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--no-headless", dest="headless", action="store_false", default=True,
        help="Show the browser window (useful for debugging DnD selectors)",
    )
    args = parser.parse_args()

    result = asyncio.run(
        build_designed_campaign(
            task_gid=args.task_gid,
            brand=args.brand,
            dry_run=args.dry_run,
            headless=args.headless,
            skip_asana=args.skip_asana,
            auto_confirm=args.yes,
        )
    )

    print()
    if result["success"]:
        print("SUCCESS")
        if result.get("braze_url"):
            print(f"  Braze URL: {result['braze_url']}")
    else:
        print("FAILED")

    if result.get("errors"):
        print("  Errors:")
        for e in result["errors"]:
            print(f"    - {e}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
