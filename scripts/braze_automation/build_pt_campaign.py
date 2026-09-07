#!/usr/bin/env python3
"""
Build plain text email campaigns in Braze from Asana tasks.

End-to-end automation:
  1. Fetches PT (plain text) email tasks from Asana
  2. Parses task data (brand, subject, body copy, segment, send time, category)
  3. Converts plain text body to HTML
  4. Opens Braze dashboard via Playwright
  5. Creates the campaign with full configuration:
     - Email content (subject, preheader, HTML body)
     - Target audience (segments + filters per brand)
     - Delivery schedule (Intelligent Timing or specific time)
     - Conversion events (4 per brand, 3-day deadline)
  6. Saves as draft
  7. Writes Braze campaign link back to Asana

Usage:
    # Preview what would be built (no browser launched)
    uv run python scripts/braze_automation/build_pt_campaign.py \\
      --task 1212956232276431 --dry-run

    # Build all "Ready to Code" PT tasks for a brand
    uv run python scripts/braze_automation/build_pt_campaign.py \\
      --brand BUR --dry-run

    # Actually build in Braze
    uv run python scripts/braze_automation/build_pt_campaign.py \\
      --task 1212956232276431 --no-dry-run

    # Build without confirmation prompts
    uv run python scripts/braze_automation/build_pt_campaign.py \\
      --task 1212956232276431 --no-dry-run --yes
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, date, timedelta
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

from utils.pt_text import strip_markdown_emphasis

load_dotenv(PROJECT_ROOT / ".env")

from login import (
    login,
    ensure_logged_in,
    select_workspace,
    save_session,
    create_context_with_session,
    BRAZE_DASHBOARD_URL,
    BRAND_WORKSPACE_MAP,
)
from element_utils import click_button, fill_field, wait_for_element
from utils.sale_matcher import load_sale_schedules, parse_sale_date

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

# Asana custom field GIDs (from create_braze_campaigns.py)
FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_SUBJECT_LINE = "1207522425689914"
FIELD_PRE_HEADER = "1207522425689916"
FIELD_SEGMENT = "1211927654349290"
FIELD_SEGMENT_TEXT = "1216855544683297"  # ID only — see CLAUDE.md "ID Segment (Text) field"

# ID segmentation redo (ticket 1214216873746059) — 7 new Braze segments go live
# for sends on/after this date; sends before it keep resolving through the old
# interim mapping. See _resolve_id_segment_type().
_ID_SEGMENTATION_V2_CUTOFF = "2026-08-18"


def _normalize_segment_key(raw: str) -> str:
    """Lowercase and strip everything but letters/digits, so case, dash style
    (-, –, —), spacing, and punctuation variants of a Segment (Text) value all
    collapse to the same comparison key (e.g. "Geo Segment - Engaged" and
    "geo segment engaged" both become "geosegmentengaged")."""
    return re.sub(r"[^a-z0-9]+", "", raw.strip().lower())


# Normalized Segment (Text) value -> ID audience config key, effective
# _ID_SEGMENTATION_V2_CUTOFF. full_file/engaged use a "_v2" suffix so they
# don't collide with the pre-cutoff full_file/engaged keys, which stay
# pointed at the old interim Braze segments.
_ID_SEGMENT_TEXT_KEY_MAP_V2 = {
    "fullfile": "full_file_v2",
    "allfullfile": "full_file_v2",
    "all": "full_file_v2",
    "engaged": "engaged_v2",
    "highlyengaged": "highly_engaged",
    "swatchpurchasers": "swatch_purchasers",
    "swatchnonpurchasers": "swatch_non_purchasers",
    "geosegmentengaged": "geo_engaged",
    "geosegmentunengaged": "geo_unengaged",
}
FIELD_AUDIENCE = "1207522425689896"
FIELD_SEND_TIME = "1212524397761931"
FIELD_BRAZE_LINK = "1210710306792280"
FIELD_BRAZE_CAMPAIGN_ID = "1210955430688137"
FIELD_CATEGORY = "1207522425689885"
FIELD_TRADE_BRAND = "1210233166197147"
TRADE_BRAND_GID_ID = "1210233166197148"  # "Interior Define" option

STATUS_READY_TO_CODE = "1209995669275789"

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

# Brand-specific disclaimer templates for sale periods.
# Brands with {discount}/{end_date} placeholders require a parseable discount %.
# Brands with a plain string (no placeholders) show the disclaimer for any active sale.
_SALE_DISCLAIMER_TEMPLATES: Dict[str, str] = {
    "STF": "Offers and pricing are subject to change, see site for details.",
    "CZ": "Offers and pricing are subject to change, see site for details.",
}

# HAV disclaimer text is fixed (not templated from sale name/discount %), but
# switches singular/plural depending on whether the active promo encodes more
# than one discount rule/tier (e.g. a Buy More Save More tiered offer).
# Every HAV PT sale disclaimer must also link to the full promo terms page.
_HAV_TERMS_URL = "https://havenly.com/current-promotions"
_HAV_SALE_DISCLAIMER_SINGULAR = (
    "Offer applies to select items only. Prices as marked. "
    "Total discount reflected at checkout. See complete "
    f'<a href="{_HAV_TERMS_URL}" style="color:#959596;text-decoration:underline;">'
    "Terms &amp; Conditions</a>."
)
_HAV_SALE_DISCLAIMER_PLURAL = (
    "Offers apply to select items only. Prices as marked. "
    "Total discount reflected at checkout. See complete "
    f'<a href="{_HAV_TERMS_URL}" style="color:#959596;text-decoration:underline;">'
    "Terms &amp; Conditions</a>."
)


def _hav_discount_has_multiple_rules(discount_str: str) -> bool:
    """Return True if a HAV sale discount string encodes more than one rule/tier.

    e.g. "Buy More Save More Tiered Offer: 5% off $750, 10% off $1,250, 15% off
    $2,500" has 3 tiers -> plural "Offers apply". "50% off Fulls / HIP" has a
    single rule -> singular "Offer applies".
    """
    return len(re.findall(r"\d+%", discount_str or "")) > 1


def _extract_max_discount_pct(discount_str: str) -> Optional[int]:
    """Extract the highest discount percentage from a sale discount string.

    Handles formats like "20% off sitewide", "20% off <$3K / 25% off $3K+",
    "B2C 25% off sitewide", "up to 30% off", etc.
    Returns the maximum integer percentage found, or None if none found.
    """
    if not discount_str:
        return None
    pcts = [int(m) for m in re.findall(r"(\d+)%", discount_str)]
    return max(pcts) if pcts else None


def _get_sale_disclaimer(
    brand_code: str,
    due_on: Optional[str],
    havenly_audience: Optional[str] = None,
) -> str:
    """Return formatted sale disclaimer text if the task date falls during an active sale.

    Returns empty string if no active sale found or brand has no disclaimer template.

    For templates with {discount}/{end_date} placeholders, a parseable discount % is
    required.  For plain-string templates (no placeholders), any active sale triggers
    the disclaimer regardless of whether the discount amount is specified.

    HAV is handled separately: the disclaimer text is fixed (not derived from the
    sale name/discount), switches singular/plural based on whether the promo has
    multiple discount tiers, and is matched against sale_schedules using
    *havenly_audience* ("PC" or "CONV") since HAV runs separate DPS/MP sale
    calendars. Sales without a ``havenly_audience`` set match either audience.
    """
    if not due_on:
        return ""

    from datetime import datetime as _dt
    try:
        task_date = _dt.strptime(due_on, "%Y-%m-%d")
    except ValueError:
        return ""

    try:
        sale_schedules = load_sale_schedules()
    except Exception:
        return ""

    if brand_code == "HAV":
        for sale in sale_schedules:
            if sale.get("brand") != "HAV":
                continue
            sale_audience = sale.get("havenly_audience")
            if sale_audience and havenly_audience and sale_audience != havenly_audience:
                continue
            sale_start = parse_sale_date(sale.get("start_date"))
            sale_end = parse_sale_date(sale.get("end_date")) or sale_start
            if not sale_start:
                continue
            if sale_start <= task_date <= sale_end:
                if _hav_discount_has_multiple_rules(sale.get("discount", "")):
                    return _HAV_SALE_DISCLAIMER_PLURAL
                return _HAV_SALE_DISCLAIMER_SINGULAR
        return ""

    if brand_code not in _SALE_DISCLAIMER_TEMPLATES:
        return ""

    template_str = _SALE_DISCLAIMER_TEMPLATES[brand_code]
    needs_discount = "{discount}" in template_str

    for sale in sale_schedules:
        if sale.get("brand") != brand_code:
            continue
        sale_start = parse_sale_date(sale.get("start_date"))
        sale_end = parse_sale_date(sale.get("end_date")) or sale_start
        if not sale_start:
            continue
        if sale_start <= task_date <= sale_end:
            if not needs_discount:
                return template_str
            discount = _extract_max_discount_pct(sale.get("discount", ""))
            if discount is None:
                continue
            end_date_str = str(sale.get("end_date", ""))
            try:
                end_dt = _dt.strptime(end_date_str, "%Y-%m-%d")
                end_date_fmt = f"{end_dt.month}/{end_dt.day}/{end_dt.year}"
            except ValueError:
                end_date_fmt = end_date_str
            return template_str.format(discount=discount, end_date=end_date_fmt)
    return ""


# =========================================================================
# 1.  CONFIGURATION LOADING
# =========================================================================

def load_brand_config() -> Dict[str, Any]:
    """Load brand_config.yaml."""
    config_path = PROJECT_ROOT / "data" / "brand_config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_brand_entry(brand_code: str, config: Dict, hav_variant: Optional[str] = None) -> Dict:
    """Get the config entry for a brand.

    For HAV, *hav_variant* should be ``"PC"`` or ``"CONV"``.  If not
    specified and the brand is HAV, returns ``HAV_PC`` as default.
    """
    brands = config.get("brands", {})
    if brand_code == "HAV":
        key = f"HAV_{hav_variant or 'PC'}"
    else:
        key = brand_code
    entry = brands.get(key)
    if not entry:
        raise ValueError(f"No config entry for brand key '{key}'")
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
        "name", "due_on", "completed", "notes", "html_notes",
        "custom_fields", "custom_fields.gid",
        "custom_fields.enum_value", "custom_fields.enum_value.gid",
        "custom_fields.enum_value.name",
        "custom_fields.text_value", "custom_fields.display_value",
        "assignee", "assignee.name", "assignee.gid",
    ])
    return _asana_request("GET", f"tasks/{task_gid}", params={"opt_fields": opt_fields})


def fetch_ready_to_code_pt_tasks(brand_filter: Optional[str] = None) -> List[Dict]:
    """Fetch tasks with 'Ready to Code' status whose name ends with 'PT'."""
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
        f"custom_fields.{FIELD_CHANNEL}.value": CHANNEL_OPTIONS["email"],
        "opt_fields": ",".join([
            "name", "due_on", "completed", "notes", "html_notes",
            "custom_fields", "custom_fields.gid",
            "custom_fields.enum_value", "custom_fields.enum_value.gid",
            "custom_fields.enum_value.name",
            "custom_fields.text_value", "custom_fields.display_value",
            "assignee", "assignee.name", "assignee.gid",
        ]),
        "limit": 100,
    }
    if brand_filter:
        brand_gid = BRAND_OPTIONS.get(brand_filter.upper())
        if brand_gid:
            params[f"custom_fields.{FIELD_BRAND}.value"] = brand_gid

    endpoint = f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search"
    tasks_data = _asana_request("GET", endpoint, params=params)
    if not tasks_data:
        return []

    results = []
    for task in tasks_data:
        if task.get("completed"):
            continue
        name = task.get("name", "")
        # Filter to PT (plain text) tasks
        if not name.strip().upper().endswith("PT"):
            continue
        parsed = parse_asana_task(task)
        if parsed:
            results.append(parsed)
    return results


# ---------------------------------------------------------------------------
import html as _html_module


def _extract_asana_links(html_notes: str) -> List[Dict[str, str]]:
    """Extract explicit hyperlinks from Asana html_notes before HTML stripping.

    Returns a list of {'text': anchor_text, 'url': url} for each <a href> found.
    Only external URLs (starting with 'http') are included.
    """
    if not html_notes:
        return []
    pattern = re.compile(
        r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    links: List[Dict[str, str]] = []
    seen: set = set()
    for m in pattern.finditer(html_notes):
        url = m.group(1).strip()
        anchor = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not url.startswith("http") or not anchor:
            continue
        cleaned_url = url.rstrip(".,;:!?)")
        cleaned_anchor = anchor.rstrip(".,;:!?)")
        if not cleaned_anchor:
            continue
        if cleaned_url != url or cleaned_anchor != anchor:
            logger.warning(
                f"Stripped trailing punctuation from Asana link: "
                f"URL {url!r} → {cleaned_url!r}, anchor {anchor!r} → {cleaned_anchor!r}"
            )
        normalized_url = _normalize_url(cleaned_url)
        if normalized_url != cleaned_url:
            logger.warning(f"Replaced deprecated URL {cleaned_url!r} → {normalized_url!r}")
        # Dedup by (anchor, url) pair — NOT anchor text alone. Repeated anchor
        # text pointing to different URLs is common (e.g. three "Shop now →"
        # links to Sloan / Ella / Alexander); deduping by text alone silently
        # dropped all but the first. Document order is preserved for positional
        # link application downstream.
        key = (cleaned_anchor, normalized_url)
        if key not in seen:
            links.append({"text": cleaned_anchor, "url": normalized_url})
            seen.add(key)
    return links


# Deprecated URL → replacement mapping.  Applied at link-parse time so stale
# URLs in Asana task notes are silently corrected before they reach the build.
_DEPRECATED_URLS: dict[str, str] = {
    "https://havenly.com/#package-types": "https://havenly.com/#packages-section",
    "https://www.havenly.com/#package-types": "https://havenly.com/#packages-section",
}


def _normalize_url(url: str) -> str:
    """Replace any deprecated URL with its canonical replacement."""
    return _DEPRECATED_URLS.get(url, url)


# Placeholder URL used when a link is required but no real URL was provided.
_BRAND_BASE_URLS = {
    "HAV": "https://www.havenly.com",
    "HAV_PC": "https://havenly.com/#packages-section",   # DPS (pre-converted)
    "HAV_CONV": "https://havenly.com/shop",                # Marketplace (converted)
    "TE": "https://www.theexpert.com",
}


def _get_brand_base_url(brand_code: str) -> str:
    """Return the homepage URL for a brand (used as link fallback)."""
    if brand_code in _BRAND_BASE_URLS:
        return _BRAND_BASE_URLS[brand_code]
    cfg = load_brand_config()
    url = cfg.get("sms_config", {}).get(brand_code, {}).get("base_url", "")
    return url or "https://www.havenly.com"


def _apply_link_rules(
    body_copy: str,
    asana_explicit_links: List[Dict[str, str]],
    brand_code: str = "",
) -> Tuple[str, List[Dict[str, str]]]:
    """Apply PT email link rules (CLAUDE.md §Link placement rules).

    Returns (modified_body_copy, text_links) where text_links is a list of
    {'text': anchor, 'url': url} entries to apply to HTML.  Falls back to
    the brand homepage when no explicit URL is available.
    """
    homepage = _get_brand_base_url(brand_code) if brand_code else "https://www.havenly.com"
    text_links: List[Dict[str, str]] = []

    # Rule 1: Explicit Asana hyperlinks (real URLs from the description)
    if asana_explicit_links:
        matched = [lnk for lnk in asana_explicit_links if lnk["text"] in body_copy]
        if matched:
            return (body_copy, matched)

    # Rule 1.5: bracket notation containing a URL — inline link hint from copywriter.
    # Handles any of: [URL], [link URL], [link: URL], [link to URL], [linked to URL].
    # URL may or may not have a protocol/www prefix — we add https:// when missing.
    _URL_IN_BRACKET = re.compile(
        r'https?://\S+|www\.\S+'
        r'|[\w-]+\.(?:com|net|org|io|co|design|shop|us|co\.uk|furniture|home)[/\w.\-?=%&]*',
        re.IGNORECASE,
    )
    bracket_m = re.search(r'\[([^\]]+)\]', body_copy)
    if bracket_m:
        bracket_content = bracket_m.group(1).strip()
        url_in = _URL_IN_BRACKET.search(bracket_content)
        if url_in:
            raw_url = url_in.group(0).strip()
            url = raw_url if raw_url.startswith('http') else f'https://{raw_url}'
            bracket_start = bracket_m.start()
            bracket_end = bracket_m.end()
            # Find the anchor: prefer <strong> immediately before the bracket, else last line
            pre_bracket = body_copy[:bracket_start].rstrip()
            bold_before = re.search(r'(<strong>(.*?)</strong>)\s*$', pre_bracket, re.IGNORECASE | re.DOTALL)
            if bold_before and bold_before.group(2).strip():
                # Use inner text so html_body.replace() finds it regardless of
                # whether the brand uses <b> or <strong> in the rendered HTML.
                anchor = bold_before.group(2).strip()
            else:
                last_nl = pre_bracket.rfind('\n')
                anchor = (pre_bracket[last_nl + 1:] if last_nl >= 0 else pre_bracket).strip()
            # Remove the bracket from body; strip only inline whitespace (space/tab)
            # after the bracket, not newlines — preserves paragraph breaks.
            body_copy = body_copy[:bracket_start].rstrip() + body_copy[bracket_end:].lstrip(" \t")
            body_copy = body_copy.strip()
            if anchor:
                logger.info("Bracket link rule applied: %r → %r", anchor, url)
                text_links.append({"text": anchor, "url": url})
                return (body_copy, text_links)

    # Rule 2: "anchor text: LINK" placeholder pattern
    link_anchor_m = re.search(
        r"(?m)^(.*?)\s*:\s*\bLINK\b\s*$",
        body_copy,
        re.IGNORECASE,
    )
    if link_anchor_m:
        anchor_full = link_anchor_m.group(1).strip()
        words = [w for w in anchor_full.split() if w]
        n = len(words)
        if n <= 3:
            # Arrow text becomes the full anchor — URL never appears as visible text
            arrow_text = f"{anchor_full} →"
            body_copy = body_copy[:link_anchor_m.start()] + arrow_text + body_copy[link_anchor_m.end():]
            text_links.append({"text": arrow_text, "url": homepage})
        elif n <= 6:
            new_seg = anchor_full + "."
            body_copy = body_copy[:link_anchor_m.start()] + new_seg + body_copy[link_anchor_m.end():]
            text_links.append({"text": anchor_full + ".", "url": homepage})
        else:
            # > 6 words: keep the full sentence, just replace ": LINK" with the URL.
            # _url_to_link in convert_pt_body_to_html auto-links the bare URL.
            new_seg = anchor_full + ": " + homepage
            body_copy = body_copy[:link_anchor_m.start()] + new_seg + body_copy[link_anchor_m.end():]
            # No text_link entry — URL is auto-linked
        return (body_copy, text_links)

    # Rule 2b: bare LINK placeholder (no colon-anchor pattern)
    if re.search(r"\bLINK\b", body_copy, re.IGNORECASE):
        body_copy = re.sub(r"\bLINK\b", homepage, body_copy, flags=re.IGNORECASE)
        text_links.append({"text": homepage, "url": homepage})
        return (body_copy, text_links)

    # Rule 3: "here" language
    here_m = re.search(r"\bhere\b", body_copy, re.IGNORECASE)
    if here_m:
        ls = body_copy.rfind("\n", 0, here_m.start())
        ls = 0 if ls == -1 else ls + 1
        le = body_copy.find("\n", here_m.end())
        le = len(body_copy) if le == -1 else le
        sentence = body_copy[ls:le].strip()
        if sentence:
            text_links.append({"text": sentence, "url": homepage})
            return (body_copy, text_links)

    # Rule 4: Bold text as link anchor (<strong> preserved from Asana html_notes)
    bold_m = re.search(r"(<strong>(.*?)</strong>)", body_copy, re.IGNORECASE | re.DOTALL)
    if bold_m:
        inner = bold_m.group(2).strip()
        if inner and len(inner) < 100:
            # Use inner text so html_body.replace() finds it inside <b>...</b> or <strong>...</strong>
            text_links.append({"text": inner, "url": homepage})
            return (body_copy, text_links)

    # Rule 5: No explicit signal — link the homepage directly
    text_links.append({"text": homepage, "url": homepage})
    body_copy = body_copy.rstrip() + f"\n\n{homepage}"
    return (body_copy, text_links)


def _html_notes_to_rich_text(html_notes: str) -> str:
    """Strip Asana html_notes to plain text, preserving <strong> bold markers.

    Asana html_notes wraps the description in <body> and uses <strong> for bold.
    We keep <strong>/<em> and convert <br> / <p> to newlines, stripping everything else.
    """
    if not html_notes:
        return ""
    text = html_notes
    # Preserve bold/italic markers with temp tokens. <em> was previously stripped
    # here despite the docstring/comment above claiming it's kept — confirmed
    # bug 2026-09-05 — <b>/<strong> got stash-and-restore tokens, <i>/<em> did
    # not, so italics from Asana silently vanished from every PT body.
    text = re.sub(r'<strong\b[^>]*>', '__BOLD__', text, flags=re.IGNORECASE)
    text = re.sub(r'</strong>', '__/BOLD__', text, flags=re.IGNORECASE)
    text = re.sub(r'<em\b[^>]*>', '__ITALIC__', text, flags=re.IGNORECASE)
    text = re.sub(r'</em>', '__/ITALIC__', text, flags=re.IGNORECASE)
    # Convert block-level tags to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = _html_module.unescape(text)
    # After unescaping, HTML-escaped tags like &lt;b&gt; reappear as <b> — normalize to <strong>
    # so they are treated identically to Asana's native bold (<strong>) downstream.
    # Same normalization for <i> → <em>.
    text = re.sub(r'<b\b[^>]*>', '<strong>', text, flags=re.IGNORECASE)
    text = re.sub(r'</b>', '</strong>', text, flags=re.IGNORECASE)
    text = re.sub(r'<i\b[^>]*>', '<em>', text, flags=re.IGNORECASE)
    text = re.sub(r'</i>', '</em>', text, flags=re.IGNORECASE)
    # Restore bold/italic markers
    text = text.replace('__BOLD__', '<strong>').replace('__/BOLD__', '</strong>')
    text = text.replace('__ITALIC__', '<em>').replace('__/ITALIC__', '</em>')
    # Normalise line endings
    text = re.sub(r'\r\n|\r', '\n', text)
    return text.strip()


# Copywriter-notes markers.  When one of these appears on its own line after
# the email signature + blank lines, everything from that point on is treated
# as internal notes (not email body content).
# ---------------------------------------------------------------------------
_PH_PREFIXES = re.compile(
    r"^(?:\*{0,2})(?:PH|Pre[-\s]?[Hh]eader)\s*(?:\*{0,2})\s*:\s*",
    re.IGNORECASE,
)

# A "Proposed Body Copy:" / "Body Copy:" / "Proposed Copy:" header on its own
# line introduces the actual email copy in a brief-style task.  Everything above
# it is briefing metadata (Creative Direction / Promo / LP / SL/PH) and must be
# discarded; the body starts on the next line.  Without this the header itself
# lands in the email body AND, sitting ahead of the greeting, defeats the
# greeting-dedup regex below (which only strips a greeting at the body start).
_BODY_COPY_HEADER = re.compile(
    r"^\s*(?:<strong>)?(?:\*{0,2})"
    r"(?:Proposed\s+Body\s+Copy|Body\s+Copy|Proposed\s+Copy)"
    r"(?:\*{0,2})"
    r"(?:\s*\(AI[\s-]?[Gg]enerated\))?"
    r"\s*:?\s*(?:</strong>)?\s*:?\s*$",
    re.IGNORECASE,
)

_NOTES_SECTION_HEADERS = re.compile(
    r"^(?:Overview|Notes|Details|Brief|Context|Instructions|Background|"
    r"Email Template Inspo|Template Inspo|Reference|Inspiration|"
    r"Copy Notes|Copywriter Notes|Internal Notes|Briefing|"
    r"\[AI Brief\]|\[AI Generated\]|\[AI Generated Instructions\])$",
    re.IGNORECASE,
)

# A body-copy greeting line — "Hi there,", "Hi {{${first_name} ...}}," etc.
# Used to locate where the copywriter's own copy starts.
_PT_GREETING_LINE_RE = re.compile(r"^\s*(?:Hi|Hey|Hello|Dear|Greetings)\b", re.IGNORECASE)

# Briefing-section field headers.  Unlike _NOTES_SECTION_HEADERS (which anchors
# on the whole line being a bare section word) these are prefix-style fields
# that carry their content on the same line, e.g.
# "Creative Direction: PM resend to non-openers."
#
# Nothing at or below one of these may reach the email body.  The Step 2
# backwards walk only honours a section header once it has already found a
# recognised signature followed by 3+ blank lines, so a briefing section
# separated by a single blank line — or sitting under a sign-off whose name
# line isn't recognised — used to be swept into the body wholesale.
_BRIEF_FIELD_HEADERS = re.compile(
    r"^\s*(?:"
    r"\[AI Brief\]"
    r"|Creative Direction\s*:"
    r"|Direction\s*:"
    r"|Proposed\s+Body\s+Copy\s*\(AI[\s-]?generated\)"
    r"|Proposed\s+Copy\s*\(AI[\s-]?generated\)"
    r"|SL\s*(?:/\s*PH)?\s*\(AI[\s-]?generated\)"
    r"|PH\s*\(AI[\s-]?generated\)"
    r"|SL/PH Suggestions\s*\(AI[\s-]?generated\)"
    r"|Format\s*:"
    r")",
    re.IGNORECASE,
)

# Horizontal rules (e.g. "---", "===", "***") used as section dividers
_HORIZONTAL_RULE = re.compile(r"^[-=*_]{3,}\s*$")

# Signoff phrases that can precede the name/attribution line
_SIGNOFF_PHRASE_RE = re.compile(
    r"^(?:Best|Thanks|Warmly|Cheers|Happy Shopping|Happy Decorating|Happy designing|"
    r"With gratitude|See you soon|Thank you|Talk soon|Xo|Regards|"
    r"Until next time)[,!]?\s*$",
    re.IGNORECASE,
)


def _is_signoff_attribution(line: str) -> bool:
    """Return True if *line* looks like a sign-off or attribution line.

    Matches patterns like:
      - "-The Interior Define Team", "-Lisa"      (starts with dash)
      - "The Havenly Team", "Havenly Team"         (contains "Team")
      - "Lisa at The Citizenry", "Rachel from Havenly"  (person at/from brand)
      - "Lisa", "Rachel"                           (single word, capitalized — personal name)
      - "Best,", "Thanks!", "Warmly,"              (classic sign-off phrase)

    Only called for lines that are immediately followed by 3+ blank lines, so
    false-positive risk is low even for generic patterns like single names.
    """
    if not line:
        return False

    # Starts with "-" (e.g. "-The Interior Define Team")
    if line.startswith("-") and len(line) > 1:
        return True

    # Classic sign-off phrase ("Best,", "Thanks!", etc.)
    if _SIGNOFF_PHRASE_RE.match(line):
        return True

    # Contains "Team" — catches "Havenly Team", "The Burrow Team", etc.
    if re.search(r'\bTeam\b', line, re.IGNORECASE) and len(line) < 60:
        return True

    # Person at/from Brand — "Lisa at The Citizenry", "Rachel from Havenly"
    if re.search(r'\b(?:at|from)\s+(?:The\s+)?[A-Z]', line) and len(line) < 60:
        return True

    # Short line (1–4 words) where every word starts with a capital —
    # most likely a personal name, brand name, or "The Burrow Team"-style string.
    # Exclude lines with colons, parentheses, or digits (those are notes/labels).
    if not any(ch in line for ch in (":", "(", ")", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
        words = line.replace(",", "").replace(".", "").split()
        if 1 <= len(words) <= 4 and all(w[0].isupper() for w in words if w[0].isalpha()):
            return True

    return False


def _strip_signoff(
    body: str, brand_code: str
) -> Tuple[str, Optional[str]]:
    """Strip the signoff from the end of the body if it matches brand defaults.

    Templates now include default signoffs, so we strip them from Asana body
    copy to avoid duplication.  If the body ends with a *different* signoff
    (e.g. "Thanks!" instead of the default "Best,"), we extract it so the
    caller can override the template default.

    Returns ``(cleaned_body, signoff_override)`` where *signoff_override* is
    ``None`` if the default signoff was stripped (or no signoff found), or
    the raw signoff text if a non-default signoff was detected.
    """
    global_config = load_brand_config()
    styles = global_config.get("pt_email_styles", {}).get(brand_code, {})
    default_signoff = styles.get("default_signoff", "")
    default_name = styles.get("default_signoff_name_plain", "") or styles.get(
        "default_signoff_name", ""
    )
    signoff_aliases = [
        re.sub(r"<[^>]+>", "", a).strip().lower()
        for a in styles.get("signoff_name_aliases", [])
    ]

    if not default_signoff and not default_name:
        return (body, None)

    lines = body.rstrip().split("\n")
    if len(lines) < 2:
        return (body, None)

    # Common signoff phrases to detect (brand-agnostic)
    _SIGNOFF_PHRASES = [
        "Best,", "Thanks!", "Thanks,", "Warmly,", "Cheers,",
        "Happy Shopping,", "Happy Shopping!", "Happy decorating!",
        "With gratitude,", "Happy designing,", "See you soon!",
        "Thank you,", "Talk soon,", "Xo,", "Until next time,",
    ]

    # Walk backwards to find signoff block at the end of body
    # Pattern: [optional blank lines] [name line(s)] [signoff phrase]
    trailing_blanks = 0
    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        trailing_blanks += 1
        idx -= 1

    if idx < 0:
        return (body, None)

    # Collect potential signoff lines (last 1-4 non-blank lines),
    # allowing a single blank line gap between the signoff phrase and name
    # (e.g. "Thanks for being part of Burrow,\n\nThe Burrow Team").
    candidate_lines = []
    scan_idx = idx
    blank_gap_seen = False
    while scan_idx >= max(0, idx - 5):
        stripped = lines[scan_idx].strip()
        if not stripped:
            if blank_gap_seen:
                break  # Only allow one blank gap
            # Only cross the blank gap if we haven't yet found the signoff
            # phrase.  The gap exists to reach a phrase that sits ABOVE a blank
            # line (e.g. "Thanks for being part of Burrow,\n\nThe Burrow Team").
            # If the earliest candidate is already a signoff phrase, the block is
            # complete — crossing the blank would pull a body sentence into it.
            earliest = candidate_lines[0] if candidate_lines else ""
            if _SIGNOFF_PHRASE_RE.match(earliest):
                break
            blank_gap_seen = True
            scan_idx -= 1
            continue
        candidate_lines.insert(0, stripped)
        scan_idx -= 1
        if len(candidate_lines) >= 4:
            break

    if not candidate_lines:
        return (body, None)

    # Check if the first candidate line is a signoff phrase
    first_candidate = candidate_lines[0]
    is_signoff = any(
        first_candidate.lower().rstrip() == phrase.lower()
        for phrase in _SIGNOFF_PHRASES
    )

    # Also detect signoff-like lines that end with a comma and precede a
    # brand team name (e.g. "Thanks for being part of Burrow,")
    clean_default_name_lower = re.sub(r"<[^>]+>", "", default_name).strip().lower()
    if not is_signoff and len(candidate_lines) >= 2:
        second_lower = candidate_lines[1].strip().lower()
        if first_candidate.rstrip().endswith(",") and (
            second_lower == clean_default_name_lower
            or second_lower in signoff_aliases
        ):
            is_signoff = True

    if not is_signoff:
        # Secondary check: the body ends with a bare attribution line like
        # "-The Interior Define Team" or "-Lisa". The attribution is the LAST
        # non-blank line (lines[idx]), not first_candidate (which is the earliest
        # line in the candidate window and may be a CTA line above the attribution).
        last_line = lines[idx].strip()
        if _is_signoff_attribution(last_line):
            # Strip HTML tags so <strong>The Burrow Team</strong> → "The Burrow Team"
            clean_attr = re.sub(r"<[^>]+>", "", last_line).strip()
            # Strip from the attribution line onward (plus its preceding blank lines)
            attr_start = idx
            while attr_start > 0 and not lines[attr_start - 1].strip():
                attr_start -= 1
            cleaned_body = "\n".join(lines[:attr_start]).rstrip()
            # Treat alias names as the default (don't return as override)
            if (
                clean_attr.lower() == clean_default_name_lower
                or clean_attr.lower() in signoff_aliases
            ):
                return (cleaned_body, None)
            return (cleaned_body, clean_attr)
        return (body, None)

    # We found a signoff block — check if it matches the brand default
    signoff_phrase = first_candidate
    signoff_names = candidate_lines[1:]  # remaining lines are name(s)

    # Build the default signoff text for comparison (strip HTML tags from name)
    clean_default_name = re.sub(r"<[^>]+>", "", default_name).strip()

    is_default = (
        signoff_phrase.lower().rstrip() == default_signoff.lower().rstrip()
        and (
            not signoff_names
            or signoff_names[0].lower().strip() == clean_default_name.lower().strip()
            or signoff_names[0].lower().strip() in signoff_aliases
        )
    )

    # Strip the signoff block from body
    # Find where the signoff starts (scan_idx + 1 is first signoff line)
    signoff_start = scan_idx + 1
    # Also strip any blank line immediately before the signoff
    while signoff_start > 0 and not lines[signoff_start - 1].strip():
        signoff_start -= 1

    cleaned_body = "\n".join(lines[:signoff_start]).rstrip()

    if is_default:
        # Default signoff — strip it, template will add it
        return (cleaned_body, None)
    else:
        # Non-default signoff — strip it from body but return it for override
        signoff_text = "\n".join(candidate_lines)
        return (cleaned_body, signoff_text)


def _extract_locked_signoff(
    body: str, styles: Dict
) -> Tuple[str, Optional[str]]:
    """Strip the trailing signoff block for a locked-name brand.

    Walks backwards over the contiguous run of trailing sign-off lines (a
    closing phrase and/or name/attribution lines), removes them from the body,
    and returns ``(cleaned_body, phrase)`` where *phrase* is the copywriter's
    closing phrase (e.g. ``"Warmly,"``) or ``None`` to fall back to the brand
    default.  The name lines are intentionally discarded — the render
    reconstructs the standard locked name.

    Guards against stripping a random trailing capitalised line by requiring
    the block to contain either a recognised sign-off phrase or a name that
    matches the brand default / an alias.
    """
    default_name = styles.get("default_signoff_name", "")
    clean_default_name = re.sub(r"<[^>]+>", "", default_name).strip().lower()
    aliases = [
        re.sub(r"<[^>]+>", "", a).strip().lower()
        for a in styles.get("signoff_name_aliases", [])
    ]

    lines = body.rstrip().split("\n")
    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return (body, None)

    block_start: Optional[int] = None
    i = idx
    while i >= 0:
        s = lines[i].strip()
        if not s:
            break  # a blank line ends the trailing signoff block
        low = re.sub(r"<[^>]+>", "", s).strip().lower()
        is_phrase = bool(_SIGNOFF_PHRASE_RE.match(s))
        is_name = (
            _is_signoff_attribution(s)
            or low == clean_default_name
            or low in aliases
        )
        if is_phrase or is_name:
            block_start = i
            i -= 1
            continue
        break

    if block_start is None:
        return (body, None)

    block = [lines[j].strip() for j in range(block_start, idx + 1)]
    phrase_line = next((b for b in block if _SIGNOFF_PHRASE_RE.match(b)), None)
    has_known_name = any(
        re.sub(r"<[^>]+>", "", b).strip().lower() == clean_default_name
        or re.sub(r"<[^>]+>", "", b).strip().lower() in aliases
        for b in block
    )
    if not phrase_line and not has_known_name:
        return (body, None)

    new_start = block_start
    while new_start > 0 and not lines[new_start - 1].strip():
        new_start -= 1
    cleaned = "\n".join(lines[:new_start]).rstrip()
    return (cleaned, phrase_line)


def _preprocess_body_copy(
    raw_notes: str, brand_code: str
) -> Tuple[str, Optional[str], Optional[str]]:
    """Clean Asana task notes into email body copy.

    Returns ``(body_copy, subject_line, signoff_override)`` where
    *subject_line* may be ``None`` if the notes don't contain a subject
    prefix, and *signoff_override* is ``None`` if the default brand signoff
    should be used, or raw signoff text if a non-default signoff was found.

    Processing steps:
      1. Extract subject line from "SL:", "Subject:", "Subject line:", or
         "Subject Line:" prefix at the start of the notes.
      2. Truncate after the email signature — large blocks that follow the
         sign-off (brand name + blank lines) are copywriter notes.
      3. Remove "Email Template Inspo" sections and anything below them.
      4. Strip signoff from body (templates now include default signoffs).
    """
    if not raw_notes:
        return ("", None)

    lines = raw_notes.split("\n")
    subject_line: Optional[str] = None

    # --- Step 1: Extract subject from the first non-empty line ---
    # Supported prefixes (case-insensitive): "SL:", "Subject:",
    # "Subject line:", "Subject Line:"
    _SUBJECT_PREFIXES = re.compile(
        r"^(?:\*{0,2})(?:SL|Subject(?:\s*Line)?)\s*(?:\*{0,2})\s*:\s*",
        re.IGNORECASE,
    )
    first_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped:
            first_idx = i
            break
    first_line = lines[first_idx].strip() if first_idx < len(lines) else ""
    m = _SUBJECT_PREFIXES.match(first_line)
    if m:
        # A bolded label ("**SL:**") leaves its closing marker behind — the
        # prefix pattern only consumes up to the colon.
        subject_line = strip_markdown_emphasis(first_line[m.end():])
        # Remove the subject line (and any immediately following blank line)
        lines = lines[:first_idx] + lines[first_idx + 1:]
        # Also strip a leading blank line if the prefix was followed by one
        while lines and not lines[0].strip():
            lines.pop(0)
    else:
        # Secondary scan: SL: may appear mid-notes when the task has no [AI Brief]
        # separator and notes/context sit above the subject line.
        # Pattern: ... [metadata lines] ... SL: subject \n\n Hi ...,
        # Condition: SL: is on its own line and is followed (within a few lines)
        # by a greeting, confirming the copy starts there.
        _GREETING_RE = re.compile(r"^(?:Hi|Hey|Hello)\b", re.IGNORECASE)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            m2 = _SUBJECT_PREFIXES.match(stripped)
            if m2:
                # Verify a greeting follows within the next 5 non-empty lines
                lookahead = [l.strip() for l in lines[i + 1:i + 8] if l.strip()]
                if any(_GREETING_RE.match(l) for l in lookahead[:5]):
                    subject_line = strip_markdown_emphasis(stripped[m2.end():])
                    # Discard everything before and including the SL: line
                    lines = lines[i + 1:]
                    while lines and not lines[0].strip():
                        lines.pop(0)
                    break

    # Tertiary fallback: no "SL:"/"Subject:" label anywhere in the notes.
    # Copywriters sometimes drop the subject line in as a bare first line with
    # no indicator at all — if the very first non-empty line is copy (not a
    # greeting itself) and is followed, with only blank lines in between, by
    # the greeting that opens the real body, treat that first line as the
    # subject and remove it. Without this the line stays stuck in the body
    # ahead of the greeting, and — because the body no longer starts with the
    # greeting — the later "strip the leading greeting" step never fires
    # either, so the template's own greeting and the copy's greeting both
    # render (confirmed 2026-08-31 on STF "Labor Day Event: Final Hours PM",
    # GID 1218024407555518: body led with "Final hours for 20% off" above the
    # greeting, and the built email showed the greeting twice).
    if subject_line is None:
        first_nonblank_idx = next((i for i, l in enumerate(lines) if l.strip()), None)
        if first_nonblank_idx is not None:
            first_line_stripped = lines[first_nonblank_idx].strip()
            if not _PT_GREETING_LINE_RE.match(first_line_stripped):
                greeting_idx = next(
                    (
                        i
                        for i in range(first_nonblank_idx + 1, len(lines))
                        if _PT_GREETING_LINE_RE.match(lines[i].strip())
                    ),
                    None,
                )
                if greeting_idx is not None:
                    between = [
                        l.strip() for l in lines[first_nonblank_idx + 1:greeting_idx] if l.strip()
                    ]
                    if not between:
                        subject_line = strip_markdown_emphasis(first_line_stripped)
                        logger.info(
                            "Subject line inferred from bare copy line above greeting: %s",
                            subject_line,
                        )
                        lines = lines[greeting_idx:]

    # Strip PH: / Preheader: line if it immediately follows the SL: line.
    # PT emails have no preheader; leaving this line in causes it to appear in the
    # email body.  The value is discarded (custom field is the authoritative source
    # for designed emails; PT emails ignore preheader entirely).
    if lines:
        first_ph = lines[0].strip()
        if _PH_PREFIXES.match(first_ph):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)

    # --- Step 1b: Locate the real body — copywriter's copy beats the AI draft ---
    # Brief-style tasks lead with metadata fields (Creative Direction / Promo /
    # LP / SL/PH) and introduce the AI-drafted copy under a "Proposed Body Copy:"
    # header, so by default the body is whatever sits below that header.
    #
    # But once a copywriter has written or edited copy, it goes at the TOP of the
    # description, above the briefing — leaving both versions in the task.  The
    # copywriter's version is the approved one and must win; taking the AI draft
    # would silently ship an unreviewed draft over reviewed copy.  A greeting
    # line above the header is the signal that real copy is there (briefing
    # fields are all "Label: value" lines and never start with a greeting).
    header_idx = next(
        (i for i, line in enumerate(lines) if _BODY_COPY_HEADER.match(line.strip())),
        None,
    )
    if header_idx is not None:
        greeting_idx = next(
            (
                i
                for i, line in enumerate(lines[:header_idx])
                if _PT_GREETING_LINE_RE.match(line.strip())
            ),
            None,
        )
        if greeting_idx is not None:
            # Copywriter copy sits above the header — use it, and drop the
            # header and everything below it (the superseded AI draft).
            lines = lines[greeting_idx:header_idx]
        else:
            # No copy above the header: the AI draft below it is the body.
            lines = lines[header_idx + 1:]
            while lines and not lines[0].strip():
                lines.pop(0)

    # --- Step 1c: Hard stop at any briefing-section header ---
    # Unconditional: no signature match and no blank-line run required.  Step 1b
    # has already consumed the "Proposed Body Copy" header that opens the real
    # copy, so anything matching here is a briefing field below the body.
    for i, line in enumerate(lines):
        if _BRIEF_FIELD_HEADERS.match(line):
            lines = lines[:i]
            break

    # --- Step 2: Find the end of the actual email body ---
    # Strategy: walk backwards from the end looking for the signature block.
    # The signature is the brand name (or a common sign-off) on its own line,
    # followed by 2+ blank lines, then a notes-section header or horizontal rule.
    #
    # We look for the FIRST notes-section header or horizontal rule that
    # appears after a run of 3+ blank lines (strong signal the email is done).

    body_end = len(lines)  # default: use all lines

    blank_run = 0
    past_signature = False
    last_attribution_idx: Optional[int] = None  # index of last signoff/attribution line
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            blank_run += 1
            # 2+ blank lines immediately after a signoff/attribution line = briefing
            # notes start — truncate there.  (Copywriters often separate body from
            # briefing metadata with just two blank lines, not three.)
            if blank_run >= 2 and last_attribution_idx is not None:
                body_end = last_attribution_idx + 1
                break
            # 3+ consecutive blank lines = hard end-of-body signal regardless of
            # what follows. Copywriter brief notes often have no recognized header
            # (e.g. "Final hours of the sale — urgency close; no template...").
            if blank_run >= 3:
                body_end = i - blank_run + 1  # exclude the blank run itself
                break
        else:
            # [AI Brief] / section headers are a hard truncation point regardless
            # of past_signature — even one blank line after a signoff is enough.
            is_header = _NOTES_SECTION_HEADERS.match(stripped) or _HORIZONTAL_RULE.match(stripped)
            if is_header and (past_signature or (blank_run >= 1 and last_attribution_idx is not None)):
                body_end = last_attribution_idx + 1 if last_attribution_idx is not None else i - blank_run
                break
            if past_signature and is_header:
                body_end = i - blank_run
                break
            blank_run = 0
            if _is_signoff_attribution(stripped):
                last_attribution_idx = i
                past_signature = True
            else:
                last_attribution_idx = None

    body_lines = lines[:body_end]

    # Strip trailing blank lines from the body
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    body_copy = "\n".join(body_lines).strip()

    # Strip greeting line from body — the template already includes a
    # personalised greeting ("Hi {{${first_name}}}"), so including it in the
    # body copy would duplicate it.  Remove common greeting patterns from the
    # start of the body.
    #
    # The salutation object is matched loosely (any short run of words up to
    # the terminating comma/!/newline) rather than just "there"/the Liquid
    # tag: a brief opening "Dear friend," or "Hi friends," previously slipped
    # through and stacked underneath the template's own greeting.  Kept tight
    # enough (<= ~4 words, no sentence punctuation) that a real opening
    # sentence starting with "Hi" isn't eaten.
    body_copy = re.sub(
        r"^(?:Hi|Hey|Hello|Dear|Greetings)"
        r"(?:\s+(?:\{\{.*?\}\}|\[.*?\]|[\w''\u2019-]+)){0,4}"
        r"\s*[,!:]?[ \t]*\n+",
        "",
        body_copy,
        flags=re.IGNORECASE,
    ).strip("\n")

    # --- Step 3: Strip signoff if it matches the brand's template default ---
    # Templates now include signoffs, so we strip them from the body to avoid
    # duplication.  If the body ends with a *different* signoff, we extract it
    # so the caller can override the template default.
    _styles = load_brand_config().get("pt_email_styles", {}).get(brand_code, {})
    if _styles.get("signoff_name_locked"):
        # Locked-name brands (e.g. ID): extract the entire trailing signoff
        # block wholesale — discard the copywriter's name lines and keep only
        # their closing phrase (e.g. "Warmly,").  The standard name is
        # reconstructed at render time.  More robust than _strip_signoff for
        # briefs with stacked drafts.
        body_copy, extracted_signoff = _extract_locked_signoff(body_copy, _styles)
    else:
        body_copy, extracted_signoff = _strip_signoff(body_copy, brand_code)

    return (body_copy, subject_line, extracted_signoff)


def parse_asana_task(task: Dict) -> Optional[Dict[str, Any]]:
    """Parse a raw Asana task into a structured PT campaign record."""
    task_gid = task.get("gid")
    task_name = task.get("name", "")
    due_on = task.get("due_on")  # YYYY-MM-DD
    notes = task.get("notes", "")
    html_notes = task.get("html_notes", "")

    # Brand
    brand_gid = _get_enum_value_gid(task, FIELD_BRAND)
    brand_code = BRAND_GID_TO_CODE.get(brand_gid) if brand_gid else None
    if not brand_code:
        logger.warning(f"Task {task_gid} ({task_name}): missing brand")
        return None

    # Channel
    channel_gid = _get_enum_value_gid(task, FIELD_CHANNEL)
    channel = CHANNEL_GID_TO_NAME.get(channel_gid) if channel_gid else None
    if channel != "email":
        return None

    # Subject / preheader
    subject_line = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""

    # Segment: blank or "Full File" → full_file; "Engaged File" → engaged; "Geo" → geo
    # ID prefers the new Segment (Text) field, falling back to the legacy enum
    # field when blank — see resolve_segment_type_for_task() / CLAUDE.md.
    segment_type = resolve_segment_type_for_task(task, brand_code, send_date=due_on)

    # Override: "Items In Your Design Are On Sale" always uses the IYDO segment
    if "items in your design" in task_name.lower() and "on sale" in task_name.lower():
        segment_type = "items_in_design_on_sale"

    # Send time (free text, e.g. "4pm", "7:15am", "16:00")
    send_time_raw = _get_text_value(task, FIELD_SEND_TIME) or ""

    # Category
    category = _get_enum_value_name(task, FIELD_CATEGORY) or ""

    # Existing Braze campaign ID
    braze_campaign_id = _get_text_value(task, FIELD_BRAZE_CAMPAIGN_ID)

    # Trade Brand field — "id" for Interior Define, "hb" for Havenly Brands Trade
    trade_brand = None
    if brand_code == "TRADE":
        trade_brand_gid = _get_enum_value_gid(task, FIELD_TRADE_BRAND)
        trade_brand = "id" if trade_brand_gid == TRADE_BRAND_GID_ID else "hb"

    # Body copy: prefer html_notes (preserves bold/italic from Asana) over plain notes
    asana_explicit_links = _extract_asana_links(html_notes) if html_notes else []
    rich_notes = _html_notes_to_rich_text(html_notes) if html_notes else notes.strip()
    body_copy, notes_subject, signoff_override = _preprocess_body_copy(
        rich_notes, brand_code
    )

    # Apply link rules (CLAUDE.md §Link placement rules)
    # For HAV, pass HAV_PC or HAV_CONV so the correct default link is used.
    hav_variant = None
    if brand_code == "HAV":
        name_upper = task_name.upper()
        if re.search(r'(?:^|\s)(?:MP|MKPL)\s*:', name_upper):
            hav_variant = "CONV"
        elif "CONV" in name_upper and "PRE" not in name_upper:
            hav_variant = "CONV"
        else:
            hav_variant = "PC"
    link_brand_code = f"HAV_{hav_variant}" if hav_variant else brand_code
    body_copy, text_links = _apply_link_rules(
        body_copy, asana_explicit_links, link_brand_code
    )
    if text_links:
        logger.info("Link rule applied: %d link(s) detected", len(text_links))

    # Description subject takes priority over the Asana subject field.
    if notes_subject:
        subject_line = notes_subject
        logger.info("Subject line from description (overrides field): %s", subject_line)
    elif not subject_line:
        logger.warning("No subject line found in description or Asana field")

    disclaimer = _get_sale_disclaimer(brand_code, due_on, havenly_audience=hav_variant)
    if disclaimer:
        logger.info("Sale disclaimer auto-detected for %s on %s", brand_code, due_on)

    return {
        "gid": task_gid,
        "name": task_name,
        "due_on": due_on,
        "brand": brand_code,
        "channel": channel,
        "subject_line": subject_line,
        "preheader": preheader,
        "body_copy": body_copy,
        "signoff_override": signoff_override,
        "segment_type": segment_type,
        "send_time_raw": send_time_raw,
        "category": category,
        "braze_campaign_id": braze_campaign_id,
        "trade_brand": trade_brand,
        "assignee_gid": (task.get("assignee") or {}).get("gid"),
        "disclaimer": disclaimer,
        "text_links": text_links,
    }


def _resolve_segment_type(raw: str) -> str:
    """Map Asana Segment field value to config key."""
    raw_lower = raw.strip().lower()
    if not raw_lower or raw_lower == "full file":
        return "full_file"
    if "engaged" in raw_lower:
        return "engaged"
    if "geo" in raw_lower:
        return "geo"
    # Default to full_file for unknown values
    logger.warning(f"Unknown segment type '{raw}', defaulting to full_file")
    return "full_file"


def _resolve_id_segment_type(raw: str, send_date: Optional[str] = None) -> str:
    """Map ID's Segment (Text) field value to audience config key.

    Effective _ID_SEGMENTATION_V2_CUTOFF (ticket 1214216873746059): all 7
    segments (Full File, Engaged, Highly Engaged, Swatch Purchasers, Swatch
    Non-Purchasers, Geo Segment - Engaged, Geo Segment - Unengaged) route to
    their own dedicated Braze segment. Matching is case/dash/spacing
    tolerant via _normalize_segment_key() — see _ID_SEGMENT_TEXT_KEY_MAP_V2.

    Before that date, tasks keep resolving through the old interim mapping
    (only Full File and Engaged/Highly Engaged route to real lists; everything
    else falls back to full_file) so already-scheduled sends aren't retargeted.
    """
    if send_date and send_date >= _ID_SEGMENTATION_V2_CUTOFF:
        key = _normalize_segment_key(raw)
        mapped = _ID_SEGMENT_TEXT_KEY_MAP_V2.get(key) if key else None
        if mapped:
            return mapped
        logger.warning(f"ID segment '{raw}' not recognized, defaulting to full_file")
        return "full_file_v2"

    # Legacy interim mapping — unchanged, for sends before _ID_SEGMENTATION_V2_CUTOFF
    raw_lower = raw.strip().lower()
    if not raw_lower or raw_lower == "full file":
        return "full_file"
    if raw_lower in ("engaged", "highly engaged"):
        return "engaged"
    logger.warning(f"ID segment '{raw}' has no Braze list yet, defaulting to full_file")
    return "full_file"


def _resolve_task_segment_optional(
    task: Dict, brand_code: str, send_date: Optional[str] = None
) -> Optional[str]:
    """Resolve a task's segment type, or None if nothing is set.

    ID reads the new Segment (Text) field first, falling back to the legacy
    enum Segment field when the text field is blank (transition period —
    tasks briefed before Segment (Text) existed, or left blank). Every other
    brand reads the enum field only. Returns None (not "full_file") when
    neither field is set, so callers that need to distinguish "unset" from
    "explicitly Full File" (e.g. diffing a reference campaign's audience) can.

    `send_date` (the campaign's own send date, "YYYY-MM-DD") is only consulted
    for ID, to decide whether _resolve_id_segment_type() should use the new
    7-segment mapping or the pre-cutoff interim one.
    """
    if brand_code == "ID":
        text_val = (_get_text_value(task, FIELD_SEGMENT_TEXT) or "").strip()
        if text_val:
            return _resolve_id_segment_type(text_val, send_date)
        enum_val = _get_enum_value_name(task, FIELD_SEGMENT) or ""
        return _resolve_segment_type(enum_val) if enum_val else None
    enum_val = _get_enum_value_name(task, FIELD_SEGMENT) or ""
    return _resolve_segment_type(enum_val) if enum_val else None


def resolve_segment_type_for_task(
    task: Dict, brand_code: str, send_date: Optional[str] = None
) -> str:
    """Resolve a task's desired segment type, defaulting to full_file when unset."""
    default = "full_file"
    if (
        brand_code == "ID"
        and send_date
        and send_date >= _ID_SEGMENTATION_V2_CUTOFF
    ):
        default = "full_file_v2"
    return _resolve_task_segment_optional(task, brand_code, send_date) or default


# =========================================================================
# 4.  SEND TIME RESOLUTION
# =========================================================================

SALE_KEYWORDS = [
    "sale launch", "sale announcement", "sale extension",
    "last chance", "final hours", "sale starts", "sale ends",
    "early access",
]


def parse_time_string(raw: str) -> Optional[str]:
    """Parse a free-text time string into HH:MM (24-hour) format.

    Handles: "4pm", "4:00 PM", "7:15am", "16:00", "4 PM", "7:15 AM".
    Returns None if unparseable.
    """
    raw = raw.strip().lower().replace(".", "")
    if not raw:
        return None

    # Try 24-hour format first (e.g. "16:00")
    m = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"

    # 12-hour with optional minutes (e.g. "4pm", "4:00 PM", "7:15am")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", raw)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"

    logger.warning(f"Could not parse time string: '{raw}'")
    return None


# PM (afternoon / second-send) time — 4:00 PM local across all brands.
# Source: data/lifecycle_guidelines.yaml `email_pm` (lifecycle common data set,
# column M). Used whenever a task signals an afternoon send but has no explicit
# time in the Asana "Send time" field.
PM_SEND_TIME = "16:00"


def is_pm_send(task_name: str) -> bool:
    """Return True if the task name signals an afternoon / PM send.

    A standalone "PM" token (or "afternoon") in the Asana task name is the
    team's convention for the second, afternoon send of the day — e.g.
    "4th of July Sale Final Hours - PM". When the Asana "Send time" field is
    left empty, this signal alone schedules the campaign for the PM slot
    (PM_SEND_TIME = 4:00 PM local). Matches on token boundaries so an explicit
    time like "3pm" (a single token) is NOT treated as the PM-slot convention.
    """
    tokens = re.split(r"[\s_\-]+", task_name.lower())
    return "pm" in tokens or "afternoon" in tokens


# Minimum business days of lead time before a send may use Intelligent Timing
# (STO). Below this, Braze is given a specific send time instead: STO spreads
# delivery across a rolling 24h+ window picked per user, which a last-minute
# send cannot absorb — the tail can land after the moment has passed, and for a
# same/next-day build Braze may start delivering the evening before the send
# date. Shared by the PT and designed builders and by the QA delivery check so
# all three agree on when STO is appropriate.
STO_MIN_BUSINESS_DAYS = 5


def business_days_until(send_date_str: str, from_date: Optional[date] = None) -> int:
    """Business days (Mon-Fri) between *from_date* (default today) and the send date.

    Returns 0 when the send date is that day, earlier, or unparseable.
    """
    try:
        send_date = datetime.strptime(send_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0
    start = from_date or date.today()
    if send_date <= start:
        return 0
    count = 0
    current = start
    while current < send_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def _is_sale_announcement(task_name: str, category: str) -> bool:
    """Check if this is a sale announcement / launch / extension / last chance email."""
    name_lower = task_name.lower()
    for kw in SALE_KEYWORDS:
        if kw in name_lower:
            return True
    # Also check category
    if "sale" in category.lower():
        # Only trigger for sale announcement-type emails, not all sale category
        for kw in ["launch", "announce", "extension", "last chance", "final", "early access", "starts", "ends"]:
            if kw in name_lower:
                return True
    return False


def resolve_send_time(
    task: Dict[str, Any],
    config: Dict[str, Any],
    hav_variant: Optional[str] = None,
) -> Dict[str, Any]:
    """Determine send time configuration for a PT campaign.

    Returns a dict with:
      - type: "specific" | "intelligent_timing"
      - time: "HH:MM" (only if type == "specific")
      - local_time: True/False
      - is_second_send: whether this appears to be a 2nd email of the day
    """
    send_time_raw = task.get("send_time_raw", "")
    task_name = task.get("name", "")
    category = task.get("category", "")

    # Priority 1: Asana "Send time" field is explicitly set — always honor it.
    parsed = parse_time_string(send_time_raw)
    if parsed:
        logger.info(f"Send time from Asana field: {parsed}")
        return {
            "type": "specific",
            "time": parsed,
            "local_time": True,
            "is_second_send": False,
        }

    # Priority 2: No explicit Send time, but the task name signals a PM send
    # ("... - PM", "afternoon") → 4:00 PM local. Must come before the sale /
    # HAV-CONV defaults so a PM-tagged send is not scheduled for an AM slot.
    if is_pm_send(task_name):
        logger.info("PM indicator in task name → 4:00 PM local")
        return {
            "type": "specific",
            "time": PM_SEND_TIME,
            "local_time": True,
            "is_second_send": True,
        }

    # Priority 3: Sale announcement → 7:15 AM local
    if _is_sale_announcement(task_name, category):
        logger.info("Sale announcement detected → 7:15 AM local")
        return {
            "type": "specific",
            "time": "07:15",
            "local_time": True,
            "is_second_send": False,
        }

    # Priority 4: HAV CONV sends skip Intelligent Timing — use 4:00 PM local default.
    # Converted audience is smaller and more predictable; STO adds no meaningful lift.
    if hav_variant == "CONV":
        logger.info("HAV CONV send → skipping Intelligent Timing, using 4:00 PM local")
        return {
            "type": "specific",
            "time": "16:00",
            "local_time": True,
            "is_second_send": False,
        }

    # Priority 5: Intelligent Timing, but only with enough lead time.
    # A send built a day or two out cannot absorb STO's rolling delivery window
    # (see STO_MIN_BUSINESS_DAYS) — those get a specific local time instead, the
    # same rule resolve_send_time_designed() applies to designed emails.
    bdays = business_days_until(task.get("due_on") or "")
    if bdays < STO_MIN_BUSINESS_DAYS:
        t = parse_time_string(send_time_raw) or "07:15"
        logger.info(
            f"{bdays} business days until send (< {STO_MIN_BUSINESS_DAYS}) → "
            f"specific time {t} local, not Intelligent Timing"
        )
        return {
            "type": "specific",
            "time": t,
            "local_time": True,
            "is_second_send": False,
        }

    # The fallback is the brand default (07:00) so Braze doesn't silently use
    # "most popular time to use the app" — we always want a deterministic time.
    fallback = parse_time_string(send_time_raw) or "07:00"
    logger.info(f"{bdays} business days until send → Intelligent Timing (fallback {fallback})")
    return {
        "type": "intelligent_timing",
        "time": None,
        "fallback_time": fallback,
        "local_time": True,
        "is_second_send": False,
    }


# =========================================================================
# 5.  PLAIN TEXT → HTML CONVERSION
# =========================================================================

def convert_pt_body_to_html(
    body: str,
    brand_code: str = "HAV",
    *,
    signoff_override: Optional[str] = None,
    signoff_name_extra_override: Optional[str] = None,
    disclaimer: str = "",
    is_sale: bool = False,
) -> str:
    """Convert plain text email body to production-quality HTML.

    Produces an email HTML shell matching real Braze PT campaigns, with
    MSO conditional comments, CSS resets, responsive media query,
    brand-specific font, and proper ``<p>`` tags.

    Args:
        body: Plain text email body content.
        brand_code: Brand code (HAV, CZ, ID, BUR, STF, TI, TRADE)
            for font/style lookup.
        signoff_override: Optional signoff text to replace the template
            default.  ``None`` uses the brand's default signoff.
        disclaimer: Optional legal/promo disclaimer text for sale periods.
            Empty string omits the disclaimer row.

    Returns:
        Complete HTML email string ready for Braze.
    """
    global_config = load_brand_config()
    styles = global_config.get("pt_email_styles", {}).get(brand_code, {})
    font_family = styles.get("font_family", "Arial, Sans-serif")
    font_url = styles.get("font_url")
    template_path = styles.get("template")

    if not body:
        if template_path:
            return _wrap_html_template(
                "",
                brand_code=brand_code,
                template_path=template_path,
                signoff_override=signoff_override,
                signoff_name_extra_override=signoff_name_extra_override,
                disclaimer=disclaimer,
                is_sale=is_sale,
            )
        return _wrap_html("", font_family=font_family, font_url=font_url)

    # Escape HTML entities, but preserve <strong>/<em> markers from Asana.
    # Strategy: stash <strong>/<em> tokens, escape everything, then restore.
    # <em> was previously not stashed at all despite the comment above always
    # claiming it was — confirmed bug 2026-09-05, companion to the same gap in
    # _html_notes_to_rich_text() — so any <em> that survived parsing was still
    # HTML-escaped into visible "&lt;em&gt;...&lt;/em&gt;" text here.
    _BOLD_OPEN = "\x00BOLD\x00"
    _BOLD_CLOSE = "\x00/BOLD\x00"
    _ITALIC_OPEN = "\x00ITALIC\x00"
    _ITALIC_CLOSE = "\x00/ITALIC\x00"
    text = body.replace("<strong>", _BOLD_OPEN).replace("</strong>", _BOLD_CLOSE)
    text = text.replace("<em>", _ITALIC_OPEN).replace("</em>", _ITALIC_CLOSE)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace(_BOLD_OPEN, "<strong>").replace(_BOLD_CLOSE, "</strong>")
    text = text.replace(_ITALIC_OPEN, "<em>").replace(_ITALIC_CLOSE, "</em>")

    # Convert URLs to hyperlinks (exclude trailing sentence-ending punctuation)
    url_pattern = r'(https?://(?:[^\s,;)!.]|\\.(?!\\s|$))+)'
    def _url_to_link(m: re.Match) -> str:
        url = m.group(1).rstrip(".,;:!?)")
        return f'<a href="{url}" style="text-decoration: underline; color: #1871D8;">{url}</a>'
    text = re.sub(r'(https?://[^\s,;)]+)', _url_to_link, text)

    # Normalize triple+ newlines to double; strip leading newlines so the first
    # paragraph isn't a blank spacer that appears above the greeting block.
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.lstrip('\n')

    # Split into paragraph groups on double-newline boundaries
    paragraphs = text.split("\n\n")

    html_parts: List[str] = []
    for i, para in enumerate(paragraphs):
        # Within a paragraph group, single newlines become separate <p> tags
        lines = para.split("\n")
        for j, line in enumerate(lines):
            content = line.strip() if line.strip() else "&nbsp;"
            is_last = (i == len(paragraphs) - 1 and j == len(lines) - 1)
            if is_last:
                html_parts.append(f'<p style="margin:0">{content}</p>')
            else:
                html_parts.append(
                    f'<p style="margin:0;margin-bottom:0">{content}</p>'
                )
        # Blank spacer paragraph between groups (double-newline gap)
        if i < len(paragraphs) - 1:
            html_parts.append(
                '<p style="margin:0;margin-bottom:0">&nbsp;</p>'
            )

    content_html = "".join(html_parts)

    # Route to brand-specific template if configured, else generic wrapper
    if template_path:
        return _wrap_html_template(
            content_html,
            brand_code=brand_code,
            template_path=template_path,
            signoff_override=signoff_override,
            signoff_name_extra_override=signoff_name_extra_override,
            disclaimer=disclaimer,
            is_sale=is_sale,
        )

    return _wrap_html(content_html, font_family=font_family, font_url=font_url)


def _wrap_html(
    content: str,
    *,
    font_family: str = "Arial, Sans-serif",
    font_url: Optional[str] = None,
) -> str:
    """Wrap content in production-quality 600px email HTML template.

    Matches the structure used by real Braze PT campaigns, including MSO
    conditionals for Outlook, CSS resets, responsive media query, and
    ``role="presentation"`` on tables.

    Args:
        content: Inner HTML content (already wrapped in ``<p>`` tags).
        font_family: CSS font-family string for the brand.
        font_url: URL for web font loading (behind MSO conditional), or None.
    """
    if font_url:
        font_link = (
            '<!--[if !mso]><!-->'
            f'<link href="{font_url}" rel="stylesheet" type="text/css">'
            '<!--<![endif]-->'
        )
    else:
        font_link = ""

    return (
        '<!DOCTYPE html>'
        '<html xmlns:v="urn:schemas-microsoft-com:vml"'
        ' xmlns:o="urn:schemas-microsoft-com:office:office" lang="en">'
        '<head>'
        '<title></title>'
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<!--[if mso]>\n'
        '<xml><w:WordDocument xmlns:w="urn:schemas-microsoft-com:office:word">'
        '<w:DontUseAdvancedTypographyReadingMail/></w:WordDocument>\n'
        '<o:OfficeDocumentSettings>'
        '<o:PixelsPerInch>96</o:PixelsPerInch><o:AllowPNG/>'
        '</o:OfficeDocumentSettings></xml>\n'
        '<![endif]-->'
        f'{font_link}'
        '<style>'
        '*{box-sizing:border-box}'
        'body{margin:0;padding:0}'
        'a[x-apple-data-detectors]{color:inherit!important;text-decoration:inherit!important}'
        '#MessageViewBody a{color:inherit;text-decoration:none}'
        'p{line-height:inherit}'
        '.desktop_hide,.desktop_hide table{mso-hide:all;display:none;max-height:0;overflow:hidden}'
        '.image_block img+div{display:none}'
        'sub,sup{font-size:75%;line-height:0}'
        ' @media (max-width:620px){'
        '.mobile_hide{display:none}'
        '.row-content{width:100%!important}'
        '.stack .column{width:100%;display:block}'
        '.mobile_hide{min-height:0;max-height:0;max-width:0;overflow:hidden;font-size:0}'
        '.desktop_hide,.desktop_hide table{display:table!important;max-height:none!important}'
        '}'
        '</style>'
        '<!--[if mso ]><style>'
        'sup, sub { font-size: 100% !important; } '
        'sup { mso-text-raise:10% } '
        'sub { mso-text-raise:-10% }'
        '</style> <![endif]-->'
        '</head>'
        '<body class="body" style="background-color:#fff;margin:0;padding:0;'
        '-webkit-text-size-adjust:none;text-size-adjust:none">'
        '<table class="nl-container" width="100%" border="0" cellpadding="0"'
        ' cellspacing="0" role="presentation"'
        ' style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff">'
        '<tbody><tr><td>'
        '<table class="row row-1" align="center" width="100%" border="0"'
        ' cellpadding="0" cellspacing="0" role="presentation"'
        ' style="mso-table-lspace:0;mso-table-rspace:0">'
        '<tbody><tr><td>'
        '<table class="row-content" align="center" border="0" cellpadding="0"'
        ' cellspacing="0" role="presentation"'
        ' style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;'
        'color:#000;width:600px;margin:0 auto" width="600">'
        '<tbody><tr>'
        '<td class="column column-1" width="100%"'
        ' style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;'
        'text-align:left;padding-bottom:5px;padding-top:5px;vertical-align:top">'
        '<table class="paragraph_block block-1" width="100%" border="0"'
        ' cellpadding="10" cellspacing="0" role="presentation"'
        ' style="mso-table-lspace:0;mso-table-rspace:0;word-break:break-word">'
        '<tr><td class="pad">'
        f'<div style="color:#101b24;direction:ltr;font-family:{font_family};'
        'font-size:14px;font-weight:400;letter-spacing:0;line-height:1.5;'
        'text-align:left;mso-line-height-alt:21px">'
        f'{content}'
        '</div>'
        '</td></tr>'
        '</table>'
        '</td></tr>'
        '</tbody></table>'
        '</td></tr></tbody></table>'
        '</td></tr></tbody></table>'
        '<!-- End -->'
        '</body>'
        '</html>'
    )


def _wrap_html_cz(
    content: str,
    *,
    disclaimer: str = "",
    template_path: Optional[str] = None,
) -> str:
    """Wrap content in the CZ plain-text email template.

    Loads ``components/cz_pt_template.html`` and injects body content
    and an optional disclaimer into the marked placeholder zones.

    Args:
        content: Inner HTML content (already wrapped in ``<p>`` tags).
        disclaimer: Optional legal/promo disclaimer text (plain text or
            HTML).  If empty, the disclaimer row is removed entirely.
        template_path: Relative path to template from PROJECT_ROOT.
            Falls back to ``components/cz_pt_template.html``.

    Returns:
        Complete HTML email string ready for Braze.
    """
    if template_path is None:
        template_path = "components/cz_pt_template.html"
    full_path = PROJECT_ROOT / template_path
    template = full_path.read_text(encoding="utf-8")

    # Inject body content
    template = template.replace("<!-- BODY_CONTENT -->", content)

    # Handle disclaimer: inject text or strip the entire row
    if disclaimer:
        template = template.replace("<!-- DISCLAIMER -->", f"<em>{disclaimer}</em>")
    else:
        # Remove everything between the row markers (inclusive)
        start = template.find("<!-- BEGIN_DISCLAIMER_ROW -->")
        end = template.find("<!-- END_DISCLAIMER_ROW -->")
        if start >= 0 and end >= 0:
            end += len("<!-- END_DISCLAIMER_ROW -->")
            template = template[:start] + template[end:]

    return template


def _wrap_html_template(
    content: str,
    *,
    brand_code: str = "",
    template_path: Optional[str] = None,
    signoff_override: Optional[str] = None,
    signoff_name_extra_override: Optional[str] = None,
    disclaimer: str = "",
    is_sale: bool = False,
) -> str:
    """Wrap content in a brand-specific plain-text email template.

    Generalized template loader that handles all brands.  Loads the
    template HTML file and injects body content, signoff, and an optional
    disclaimer into the marked placeholder zones.

    Placeholder markers handled:
      - ``<!-- BODY_CONTENT -->`` — replaced with body HTML
      - ``<!-- SIGNOFF -->`` — replaced with signoff HTML (default or override)
      - ``<!-- DISCLAIMER -->`` — replaced with disclaimer, or row removed
      - ``<!-- BEGIN_DISCLAIMER_ROW -->`` / ``<!-- END_DISCLAIMER_ROW -->``

    Args:
        content: Inner HTML content (already wrapped in ``<p>`` tags).
        brand_code: Brand code for signoff lookup.
        template_path: Relative path to template from PROJECT_ROOT.
        signoff_override: Raw signoff text to use instead of the brand
            default.  ``None`` uses the default from the template config.
        disclaimer: Optional legal/promo disclaimer text.  If empty, the
            disclaimer row is removed entirely.

    Returns:
        Complete HTML email string ready for Braze.
    """
    if template_path is None:
        raise ValueError("template_path is required for _wrap_html_template")
    full_path = PROJECT_ROOT / template_path
    template = full_path.read_text(encoding="utf-8")

    # Inject body content
    template = template.replace("<!-- BODY_CONTENT -->", content)

    # Build signoff HTML
    global_config = load_brand_config()
    styles = global_config.get("pt_email_styles", {}).get(brand_code, {})

    if styles.get("signoff_name_locked"):
        # Name block is locked to the brand standard (e.g. ID: "Lisa" /
        # "The Interior Define Team").  The copywriter's name lines are
        # discarded — only the closing phrase they wrote (e.g. "Warmly,") is
        # preserved.  This prevents brief typos like a bare "The Interior
        # Define" (missing "Team") from shipping verbatim.
        default_signoff = styles.get("default_signoff", "")
        default_name = styles.get("default_signoff_name", "")
        default_name_extra = (
            signoff_name_extra_override
            if signoff_name_extra_override is not None
            else styles.get("default_signoff_name_extra", "")
        )
        # Pull the leading closing-phrase line(s) from the override, stopping at
        # the first line that isn't a recognised sign-off phrase (that's where
        # the name begins).
        phrase_lines: list[str] = []
        if signoff_override:
            for line in signoff_override.strip().split("\n"):
                s = line.strip()
                if not s:
                    continue
                if _SIGNOFF_PHRASE_RE.match(s) or s.endswith(",") or s.endswith("!"):
                    phrase_lines.append(s)
                else:
                    break
        if not phrase_lines and default_signoff:
            phrase_lines = [default_signoff]

        signoff_parts = [
            f'<p style="margin:0;margin-bottom:0;">{p}</p>' for p in phrase_lines
        ]
        if default_name:
            if default_name_extra:
                signoff_parts.append(
                    f'<p style="margin:0;margin-bottom:0;">{default_name}</p>'
                )
            else:
                signoff_parts.append(f'<p style="margin:0;">{default_name}</p>')
        if default_name_extra:
            signoff_parts.append(f'<p style="margin:0;">{default_name_extra}</p>')
        signoff_html = "".join(signoff_parts)
    elif signoff_override:
        # Convert override text to HTML paragraphs.
        # If the override includes the brand team name, use the styled
        # (e.g. bold) version from config instead of plain text.
        default_name_styled = styles.get("default_signoff_name", "")
        default_name_plain = (
            styles.get("default_signoff_name_plain", "")
            or re.sub(r"<[^>]+>", "", default_name_styled).strip()
        )
        override_aliases = [
            re.sub(r"<[^>]+>", "", a).strip().lower()
            for a in styles.get("signoff_name_aliases", [])
        ]

        override_lines = signoff_override.strip().split("\n")
        signoff_parts = []
        for k, line in enumerate(override_lines):
            line_content = line.strip() if line.strip() else "&nbsp;"
            # Use styled name if this line matches the default team name or an alias
            if default_name_plain and (
                line_content.lower() == default_name_plain.lower()
                or line_content.lower() in override_aliases
            ):
                line_content = default_name_styled
            if k == len(override_lines) - 1:
                signoff_parts.append(
                    f'<p style="margin:0;">{line_content}</p>'
                )
            else:
                signoff_parts.append(
                    f'<p style="margin:0;margin-bottom:0;">{line_content}</p>'
                )
        signoff_html = "".join(signoff_parts)
    else:
        # Use brand default signoff from config
        default_signoff = styles.get("default_signoff", "")
        default_name = styles.get("default_signoff_name", "")
        default_name_extra = (
            signoff_name_extra_override
            if signoff_name_extra_override is not None
            else styles.get("default_signoff_name_extra", "")
        )

        signoff_parts = []
        if default_signoff:
            if default_name or default_name_extra:
                signoff_parts.append(
                    f'<p style="margin:0;margin-bottom:0;">{default_signoff}</p>'
                )
            else:
                signoff_parts.append(
                    f'<p style="margin:0;">{default_signoff}</p>'
                )
        if default_name:
            if default_name_extra:
                signoff_parts.append(
                    f'<p style="margin:0;margin-bottom:0;">{default_name}</p>'
                )
            else:
                signoff_parts.append(
                    f'<p style="margin:0;">{default_name}</p>'
                )
        if default_name_extra:
            signoff_parts.append(
                f'<p style="margin:0;">{default_name_extra}</p>'
            )
        signoff_html = "".join(signoff_parts)

    template = template.replace("<!-- SIGNOFF -->", signoff_html)

    # Handle disclaimer: inject text or strip the entire row
    if disclaimer:
        template = template.replace("<!-- DISCLAIMER -->", f"<em>{disclaimer}</em>")
    else:
        # Remove everything between the row markers (inclusive)
        start = template.find("<!-- BEGIN_DISCLAIMER_ROW -->")
        end = template.find("<!-- END_DISCLAIMER_ROW -->")
        if start >= 0 and end >= 0:
            end += len("<!-- END_DISCLAIMER_ROW -->")
            template = template[:start] + template[end:]

    # Handle footer content block (e.g. BW uses Braze content blocks for
    # address + unsubscribe, with separate sale vs non-sale variants)
    footer_config = styles.get("footer_content_block")
    if footer_config and "<!-- FOOTER_CONTENT_BLOCK -->" in template:
        footer_block = footer_config.get("sale" if is_sale else "non_sale", "")
        template = template.replace("<!-- FOOTER_CONTENT_BLOCK -->", footer_block)

    return template


# =========================================================================
# 6.  CAMPAIGN CONFIG BUILDER
# =========================================================================

# Brand codes used in Asana tasks that need cleaning from descriptions
_BRAND_CODES_FOR_STRIPPING = {
    "HAV", "CZ", "ID", "BUR", "BW", "STF", "SF", "TI", "TRADE",
}

# Prefixes that indicate design type in Asana task names (e.g. "PT: Sale Extended")
_DESIGN_PREFIXES = re.compile(
    r"^(?:PT|D|HTML|SMS|PUSH)\s*[-–—:]\s*", re.IGNORECASE
)

# Suffixes that indicate design type / channel in Asana task names
_DESIGN_SUFFIXES = re.compile(
    r"\s*[-–—]\s*(?:PT|D|HTML|SMS|PUSH)\s*$", re.IGNORECASE
)


def _derive_campaign_name(
    task: Dict[str, Any],
    hav_variant: Optional[str] = None,
) -> str:
    """Generate a proper campaign name from an Asana task.

    Extracts a clean description from the Asana task name and calls
    ``generate_campaign_name()`` to produce the standard format::

        P_EM_2026_02_07_ID_PT_Sip_And_Sit_Reminder

    Args:
        task: Parsed Asana task dict with keys ``name``, ``brand``, ``due_on``.
        hav_variant: "PC" or "CONV" for Havenly, None otherwise.

    Returns:
        A campaign name string following the naming convention.
    """
    from utils.campaign_name import generate_campaign_name, validate_campaign_name

    raw_name = task["name"]  # e.g. "Sip & Sit Reminder - PT"
    brand_code = task["brand"]  # e.g. "ID", "BUR", "HAV"
    due_on = task.get("due_on")  # e.g. "2026-02-07"

    if not due_on:
        logger.warning("Task %s missing due_on, using today's date", task.get("gid"))
        due_on = date.today().isoformat()

    # --- Extract description from task name ---
    # Shared with the Klaviyo PT builder so the two can't drift again; see
    # clean_task_name_for_description() in utils/campaign_name.py.
    from utils.campaign_name import clean_task_name_for_description

    desc = clean_task_name_for_description(raw_name)

    if not desc:
        desc = "Campaign"
        logger.warning(
            "Could not derive description from task name '%s', using '%s'",
            raw_name, desc,
        )

    try:
        name = generate_campaign_name(
            campaign_type="P",
            channel="EM",
            send_date=due_on,
            brand=brand_code,
            design_type="PT",
            hav_audience=hav_variant,
            description=desc,
        )
        # Surface convention violations instead of shipping them silently —
        # validate_campaign_name() was previously called by neither builder.
        valid, issues = validate_campaign_name(name)
        if not valid:
            for issue in issues:
                logger.warning("Campaign name issue (%s): %s", name, issue)
        logger.info("Generated campaign name: %s (from task: %s)", name, raw_name)
        return name
    except ValueError as e:
        # Fallback: return the raw name if generation fails
        logger.warning(
            "Campaign name generation failed (%s), using raw task name: %s",
            e, raw_name,
        )
        return raw_name


def build_campaign_config(
    task: Dict[str, Any],
    brand_config: Dict[str, Any],
    global_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a complete campaign configuration from Asana task + brand config.

    Returns a dict with everything needed to build the campaign in Braze.
    """
    brand_code = task["brand"]

    # Detect HAV variant from task name
    # "MP:" prefix → Converted (marketplace) audience → CONV
    # "DPS:" prefix → Pre-converted (design-service) audience → PC (strip DPS from campaign name)
    # Explicit "CONV" in name → CONV; everything else → PC
    hav_variant = None
    if brand_code == "HAV":
        name_upper = task["name"].upper()
        if re.search(r'(?:^|\s)(?:MP|MKPL)\s*:', name_upper):
            hav_variant = "CONV"
        elif "CONV" in name_upper and "PRE" not in name_upper:
            hav_variant = "CONV"
        else:
            hav_variant = "PC"  # includes DPS: prefix and unqualified tasks

    entry = get_brand_entry(brand_code, global_config, hav_variant)

    # Audience config
    segment_type = task["segment_type"]
    audience = entry.get("audiences", {}).get(segment_type)
    if not audience:
        logger.warning(
            f"No audience config for {brand_code}/{segment_type}, "
            f"falling back to full_file"
        )
        audience = entry.get("audiences", {}).get("full_file", {})

    # Conversion events
    conversions = entry.get("conversion_events", {})

    # Send time
    send_time = resolve_send_time(task, global_config, hav_variant=hav_variant)

    # Determine if this is a sale campaign (affects footer content block)
    is_sale = "sale" in task.get("category", "").lower()

    # HTML body
    disclaimer = task.get("disclaimer", "")
    trade_brand = task.get("trade_brand")  # "id" or "hb" for TRADE tasks, None otherwise
    signoff_name_extra_override = None
    if brand_code == "TRADE" and trade_brand:
        styles = global_config.get("pt_email_styles", {}).get("TRADE", {})
        key = "default_signoff_name_extra_id" if trade_brand == "id" else "default_signoff_name_extra"
        signoff_name_extra_override = styles.get(key)
    html_body = convert_pt_body_to_html(
        task["body_copy"],
        brand_code=brand_code,
        signoff_override=task.get("signoff_override"),
        signoff_name_extra_override=signoff_name_extra_override,
        disclaimer=disclaimer,
        is_sale=is_sale,
    )

    # Apply text-to-link mappings from task metadata.
    # Skip entries where plain_text is a bare URL — convert_pt_body_to_html's
    # _url_to_link already wrapped those as anchors, and replacing again would
    # inject a new <a> tag inside an existing href="..." attribute.
    #
    # text_links is in document order. Replace occurrences positionally with a
    # forward-only cursor so repeated anchor text (e.g. three "Shop now →" links
    # to different collections) each map to their own URL, and so we never
    # re-match the plain_text living inside an anchor we just inserted.
    link_search_start = 0
    for link_map in task.get("text_links", []):
        plain_text = link_map["text"]
        url = link_map["url"]
        if plain_text.startswith("http"):
            continue  # already auto-linked by _url_to_link
        linked_html = (
            f'<a href="{url}" style="text-decoration: underline; '
            f'color: #1871D8;">{plain_text}</a>'
        )
        idx = html_body.find(plain_text, link_search_start)
        if idx == -1:
            # Not found at/after the cursor. Fall back to the first occurrence
            # only if it isn't already inside an anchor we inserted earlier
            # (guard against corrupting an existing <a> tag).
            first = html_body.find(plain_text)
            if first == -1 or first < link_search_start:
                logger.warning(
                    "text_link anchor %r not found for URL %r — skipping",
                    plain_text, url,
                )
                continue
            idx = first
        html_body = html_body[:idx] + linked_html + html_body[idx + len(plain_text):]
        link_search_start = idx + len(linked_html)

    # Campaign name — generate from task metadata using the naming convention
    campaign_name = _derive_campaign_name(task, hav_variant)

    # UTM link templates
    # Default: select all available. Brand config can override with specific names.
    utm_templates = entry.get("utm_templates", "all")

    # Sender info — PT emails often use a personal from-name (e.g. "Lisa from Havenly")
    sender_info = entry.get("sender_info", {}).get("pt", {})
    from_name = sender_info.get("from_name_id" if trade_brand == "id" else "from_name")

    # Strip exclusion filter groups that have expired relative to the launch date.
    # An entry with expires_before: "2026-06-03" is only applied when the campaign
    # launch date is strictly before that date (i.e., through 2026-06-02).
    launch_date_str = task["due_on"] or date.today().isoformat()
    raw_exclusions = audience.get("exclusion_filter_groups", []) or []
    active_exclusions = active_exclusion_filter_groups(audience, launch_date_str)
    if len(active_exclusions) != len(raw_exclusions):
        audience = dict(audience)  # don't mutate the shared brand_config dict
        audience["exclusion_filter_groups"] = active_exclusions

    return {
        "campaign_name": campaign_name,
        "brand_code": brand_code,
        "hav_variant": hav_variant,
        "workspace": entry.get("workspace"),
        "subject": task["subject_line"],
        "preheader": task["preheader"],
        "html_body": html_body,
        "body_text": task["body_copy"],
        "audience": audience,
        "send_time": send_time,
        "launch_date": task["due_on"],
        "conversions": conversions,
        "utm_templates": utm_templates,
        "asana_gid": task["gid"],
        "from_name": from_name,
        "from_email": sender_info.get("from_email"),
        "reply_to": sender_info.get("reply_to"),
    }


# =========================================================================
# 7.  PLAYWRIGHT — BRAZE AUTOMATION
# =========================================================================

async def navigate_to_campaigns(page: Page, brand: str = None) -> bool:
    """Navigate to the Campaigns section.

    Args:
        page: Playwright page object
        brand: Brand code (HAV, CZ, BUR, etc.) — when provided, navigates
               directly to the workspace-specific campaigns URL to avoid
               landing in the wrong workspace via the generic sidebar link.
    """
    logger.info("Navigating to Campaigns...")
    await page.wait_for_timeout(2000)

    async def _wait_for_list():
        """Wait for the campaign list to actually render (async data load)."""
        try:
            await page.wait_for_selector(
                "input[placeholder*='Search' i], input[type='search']",
                state="visible",
                timeout=15000,
            )
        except Exception:
            await page.wait_for_timeout(3000)

    # Strategy 0: workspace-specific direct URL (avoids sidebar link resolving
    # to wrong workspace when multiple workspaces exist in session)
    if brand:
        from login import BRAND_WORKSPACE_DIRECT_URL
        workspace_url = BRAND_WORKSPACE_DIRECT_URL.get(brand.upper())
        if workspace_url:
            import re
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
                        await _wait_for_list()
                        return True
                except Exception as e:
                    logger.debug(f"Workspace-specific campaigns URL failed: {e}")

    # Strategy 1: sidebar link
    try:
        link = page.get_by_role("link", name="Campaigns")
        await link.wait_for(state="visible", timeout=5000)
        await link.click()
        await page.wait_for_timeout(2000)
        if "/campaigns" in page.url:
            logger.info("Navigated via sidebar link")
            await _wait_for_list()
            return True
    except Exception:
        pass

    # Strategy 2: locator
    try:
        link = page.locator("a[href*='/campaigns']").first
        await link.click(timeout=5000)
        await page.wait_for_timeout(2000)
        if "/campaigns" in page.url:
            logger.info("Navigated via href locator")
            await _wait_for_list()
            return True
    except Exception:
        pass

    # Strategy 3: direct URL
    dashboard_url = BRAZE_DASHBOARD_URL.rstrip("/")
    await page.goto(f"{dashboard_url}/engagement/campaigns", wait_until="load", timeout=15000)
    await page.wait_for_timeout(2000)
    if "/campaigns" in page.url:
        logger.info("Navigated via direct URL")
        await _wait_for_list()
        return True

    raise Exception("Could not navigate to Campaigns page")


async def start_email_campaign(page: Page) -> bool:
    """Click Create Campaign → Email."""
    logger.info("Starting email campaign creation...")
    create_btn = page.get_by_role("button", name="Create campaign")
    await create_btn.wait_for(state="visible", timeout=10000)
    await create_btn.click()
    await page.wait_for_timeout(500)

    email_btn = page.get_by_role("button", name="Email")
    await email_btn.wait_for(state="visible", timeout=5000)
    await email_btn.click()
    await page.wait_for_timeout(2000)
    logger.info("Selected Email campaign type")
    return True


async def set_campaign_name(page: Page, name: str) -> bool:
    """Set the campaign name field."""
    logger.info(f"Setting campaign name: {name}")
    name_field = page.get_by_role("textbox", name="Enter Campaign Name")
    await name_field.fill(name, timeout=5000)
    return True


async def _fill_sending_info(
    page: Page,
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Select From Name/Address and Reply-To from Braze dropdown menus.

    The Braze Sending Settings tab has dropdown selectors (not text inputs)
    for both the "From" address and the "Reply-To" address.  Each dropdown
    contains pre-configured options set up in the Braze workspace.

    This function:
      1. Clicks "Edit Sending Info" to expand the sender section.
      2. Opens the "From" dropdown, scrolls through options, and clicks the
         one whose text contains ``from_name``.
      3. Opens the "Reply-To" dropdown and selects the matching option.

    Args:
        page: Playwright page (Sending Settings tab visible).
        from_name: Display name to match in the From dropdown
            (e.g. "Rachel from the Interior Define Team").
        from_email: Sender email — used as secondary match hint if needed.
        reply_to: Reply-to email to match in the Reply-To dropdown.

    Returns:
        True if at least one field was successfully selected.
    """
    if not any([from_name, from_email, reply_to]):
        return False

    logger.info(
        "Setting sender info: from_name=%s, from_email=%s, reply_to=%s",
        from_name, from_email, reply_to,
    )

    # Click "Edit Sending Info" to expand the sender fields.
    edit_link = (
        page.get_by_role("button", name="Edit Sending Info")
        .or_(page.get_by_role("link", name="Edit Sending Info"))
        .or_(page.get_by_text("Edit Sending Info", exact=False))
    )
    try:
        await edit_link.first.click(timeout=5000)
        await page.wait_for_timeout(500)
        logger.debug("Expanded 'Edit Sending Info' section")
    except Exception as e:
        logger.warning(
            "Could not click 'Edit Sending Info' (may already be expanded): %s", e
        )

    filled = False

    # ------------------------------------------------------------------
    # Helper: select an option from a Braze dropdown by matching text.
    # Braze dropdowns are custom components — clicking the trigger opens
    # a list of <div> or <li> options.  We try several strategies to find
    # the trigger, open the list, and click the matching option.
    # ------------------------------------------------------------------
    async def _select_dropdown_option(
        field_label: str, match_text: str
    ) -> bool:
        """Open a dropdown near *field_label* and click the option
        whose visible text contains *match_text* (case-insensitive).

        Returns True on success.
        """
        logger.debug(
            "Looking for dropdown '%s', want option containing '%s'",
            field_label, match_text,
        )

        # --- Strategy 1: find the dropdown trigger via aria-label / label ---
        trigger_candidates = [
            # Braze often wraps dropdowns in a container with an aria-label
            page.locator(f"[aria-label*='{field_label}']"),
            page.get_by_label(field_label, exact=False),
            # Sometimes the label is a sibling; look for a nearby select-like element
            page.locator(f"text='{field_label}'").locator("..").locator(
                "[role='listbox'], [role='combobox'], select, [class*='dropdown'], [class*='select']"
            ),
        ]

        dropdown_opened = False
        for trigger in trigger_candidates:
            try:
                count = await trigger.count()
                if count == 0:
                    continue

                # Click the first matching element to open the dropdown
                el = trigger.first
                await el.scroll_into_view_if_needed(timeout=3000)
                await el.click(timeout=3000)
                await page.wait_for_timeout(600)
                dropdown_opened = True
                logger.debug("Opened dropdown via trigger strategy")
                break
            except Exception:
                continue

        if not dropdown_opened:
            logger.warning("Could not open dropdown for '%s'", field_label)
            # Take a debug screenshot
            try:
                ss = Path(__file__).parent / f"debug_dropdown_{field_label.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                await page.screenshot(path=str(ss))
                logger.info("Debug screenshot saved: %s", ss)
            except Exception:
                pass
            return False

        # --- Find and click the matching option ---
        # Braze dropdown options may be <div>, <li>, or <option> elements.
        # We search broadly for any visible element whose text contains our
        # match string.
        match_lower = match_text.lower()

        # Strategy A: look for listbox/menu options
        option_selectors = [
            "[role='option']",
            "[role='listbox'] > *",
            "[role='menu'] > *",
            "ul[class*='dropdown'] > li",
            "[class*='dropdown-menu'] > *",
            "[class*='select-option']",
            "[class*='option']",
        ]

        for sel in option_selectors:
            options = page.locator(sel)
            opt_count = await options.count()
            if opt_count == 0:
                continue

            for i in range(opt_count):
                opt = options.nth(i)
                try:
                    text = (await opt.text_content(timeout=1000)) or ""
                    if match_lower in text.lower():
                        await opt.scroll_into_view_if_needed(timeout=2000)
                        await opt.click(timeout=3000)
                        await page.wait_for_timeout(400)
                        logger.info(
                            "Selected '%s' option: %s",
                            field_label, text.strip()[:80],
                        )
                        return True
                except Exception:
                    continue

        # Strategy B: broad text search for visible elements
        # (catches non-standard dropdown implementations)
        all_visible = page.locator(f"text=/{re.escape(match_text)}/i")
        vis_count = await all_visible.count()
        for i in range(vis_count):
            el = all_visible.nth(i)
            try:
                if await el.is_visible(timeout=1000):
                    await el.click(timeout=3000)
                    await page.wait_for_timeout(400)
                    logger.info(
                        "Selected '%s' option via text match: '%s'",
                        field_label, match_text,
                    )
                    return True
            except Exception:
                continue

        logger.warning(
            "Could not find option containing '%s' in '%s' dropdown",
            match_text, field_label,
        )
        # Close the dropdown by pressing Escape
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        return False

    # ------------------------------------------------------------------
    # From Name + Address — dropdown selection
    # ------------------------------------------------------------------
    if from_name:
        if await _select_dropdown_option("From", from_name):
            filled = True
        else:
            # Fallback: match on from_email. This picks *a* sender with the
            # right address but not necessarily the right display name — when
            # several senders share one address (e.g. CZ's "The Citizenry" and
            # "Lisa at The Citizenry" both on info@mail.the-citizenry.com) it
            # silently selects the wrong one, which then surfaces only as a QA
            # sender mismatch. Warn loudly so the missing dropdown entry gets
            # added in Braze rather than being papered over.
            logger.warning(
                "From dropdown has no option matching %r — the sender display "
                "name may need to be added in Braze (Settings > Email Preferences). "
                "Falling back to matching on the address instead.",
                from_name,
            )
            if from_email:
                logger.info("Retrying From dropdown with email: %s", from_email)
                if await _select_dropdown_option("From", from_email):
                    filled = True

    # ------------------------------------------------------------------
    # Reply-To Address — dropdown selection
    # ------------------------------------------------------------------
    if reply_to:
        if await _select_dropdown_option("Reply-To", reply_to):
            filled = True
        else:
            # Fallback: try as a text input (some Braze configs use an input)
            logger.info("Reply-To dropdown failed, trying text input fallback")
            reply_input = (
                page.locator("[aria-label*='Reply-To'] input")
                .or_(page.locator("[aria-label*='Reply-To'] [contenteditable]"))
                .or_(page.get_by_label("Reply-To", exact=False).locator("input"))
            )
            try:
                await reply_input.first.fill(reply_to, timeout=5000)
                logger.info("Set Reply-To via text input: %s", reply_to)
                filled = True
            except Exception as e:
                logger.warning("Reply-To text input fallback also failed: %s", e)

    # Debug screenshot after setting sender info
    try:
        ss = Path(__file__).parent / f"debug_sender_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(ss))
        logger.info("Post-sender-info screenshot: %s", ss)
    except Exception:
        pass

    return filled


async def configure_email_content(
    page: Page,
    subject: str,
    preheader: str,
    html_body: str,
    utm_templates: Optional[Any] = None,
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Open HTML editor, fill subject/preheader/body, apply UTM templates, close modal.

    Args:
        page: Playwright page
        subject: Email subject line
        preheader: Email preheader text
        html_body: HTML body content
        utm_templates: Which link templates to apply.
            - None: select all available templates (default for most brands)
            - list of str: select specific template names (e.g. Havenly)
            - "all": select all available templates (explicit)
        from_name: Sender display name (e.g. "Rachel from Havenly"). If set,
            overrides the workspace default via Edit Sending Info.
        from_email: Sender email address. If set, overrides the workspace default.
        reply_to: Reply-to email address. If set, overrides the workspace default.
    """
    logger.info("Configuring email content...")

    # Open HTML editor
    html_editor_btn = page.get_by_role("button", name="HTML code editor Start from")
    await html_editor_btn.wait_for(state="visible", timeout=10000)
    await html_editor_btn.click()
    await page.wait_for_timeout(1000)

    # Fill subject in Sending Settings
    sending_tab = page.get_by_label("Sending Settings")
    await sending_tab.click(timeout=5000)
    await page.wait_for_timeout(500)

    # --- Sender info (Edit Sending Info) ---
    if from_name or from_email or reply_to:
        await _fill_sending_info(page, from_name, from_email, reply_to)

    # Subject field
    subject_field = page.locator("#sending-info-subject-input--1932011389").or_(
        page.get_by_role("textbox", name="Liquid text area").first
    )
    await subject_field.fill(subject, timeout=5000)

    # Preheader field
    if preheader:
        preheader_field = page.locator("#sending-info-preheader-input--296805365").or_(
            page.get_by_role("textbox", name="Liquid text area").nth(1)
        )
        await preheader_field.fill(preheader, timeout=5000)

        # Always check "Add whitespace after preheader" when a preheader is set.
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
                    break
            except Exception:
                continue

    # Switch to Content tab and fill HTML.
    # The sidebar nav also has aria-label="Content" (with data-route="/templates"),
    # so we explicitly exclude sidebar buttons to avoid strict-mode violation.
    content_tab = page.locator("button[aria-label='Content']:not([data-route])")
    if await content_tab.count() == 0:
        # Fallback: second element with the label (modal tab group)
        content_tab = page.get_by_label("Content").nth(1)
    await content_tab.click(timeout=5000)
    await page.wait_for_timeout(500)

    # Try Monaco API injection first
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
            logger.info(f"HTML set via Monaco API ({result['method']})")
        else:
            # Clipboard paste fallback
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
            logger.info("HTML set via editor fill()")

    # Apply UTM link templates before closing the editor
    await _configure_link_templates(page, utm_templates)

    # Close editor modal
    done_btn = page.get_by_role("button", name="Done")
    await done_btn.click(timeout=5000)
    await page.wait_for_timeout(1000)
    logger.info("Email content configured")
    return True


# ---------------------------------------------------------------------------
# BEE/DnD editor helpers — used when a pt_seed_campaign is configured
# ---------------------------------------------------------------------------

async def _inject_html_into_bee_text_block(page: Page, html_body: str) -> bool:
    """Inject HTML body into the PT text block in the open BEE editor.

    BEE uses TinyMCE internally but only syncs TinyMCE content back to its own
    block model when a text block is in active edit mode.  Calling setContent()
    on an unbound TinyMCE editor (no block selected) has no effect on Done.

    Correct flow:
      1. Double-click the text block in the BEE canvas → enters TinyMCE edit mode
         and binds TinyMCE to that block.
      2. Call tinymce.activeEditor.setContent(html) + fire('change').
      3. Click outside the block → BEE reads TinyMCE content into its JSON model.

    Fallback: clipboard paste (Ctrl+A → Ctrl+V) after double-clicking the block.
    """
    # TinyMCE receives an HTML fragment, not a full document.  Passing the full
    # <!DOCTYPE>/<html>/<head>/<body> wrapper causes TinyMCE to insert a leading
    # <p><br></p> before the first block-level element (<table>), which renders
    # as blank lines above the greeting.  Extract only the <body> inner content.
    body_match = re.search(r'<body[^>]*>(.*)</body>', html_body, re.DOTALL | re.IGNORECASE)
    tinymce_html = body_match.group(1).strip() if body_match else html_body
    html_json = json.dumps(tinymce_html)

    bee_frame = next((f for f in page.frames if "getbee.io" in f.url), None)
    if not bee_frame:
        logger.warning("BEE iframe (getbee.io) not found — cannot inject body")
        return False

    # Step 1: double-click the first paragraph in the BEE canvas to enter edit mode.
    # A single click selects the block; double-click activates TinyMCE for it.
    try:
        para = bee_frame.locator("p").first
        if await para.count() > 0:
            await para.scroll_into_view_if_needed()
            await para.dblclick()
            await page.wait_for_timeout(800)
            logger.info("Double-clicked text block in BEE canvas — TinyMCE should be active")
        else:
            # Fallback: click anywhere in the canvas body
            await bee_frame.locator("body").click()
            await page.wait_for_timeout(500)
    except Exception as e:
        logger.debug(f"BEE text block click failed: {e}")

    # Step 2: set content via TinyMCE API now that a block is in edit mode.
    try:
        result = await bee_frame.evaluate(f"""() => {{
            const html = {html_json};
            const editors = (window.tinymce && window.tinymce.editors) || [];
            const active = (window.tinymce && window.tinymce.activeEditor) || (editors[0] || null);
            if (!active) return {{ found: false, editorCount: editors.length }};
            active.setContent(html);
            active.fire('input');
            active.fire('change');
            active.undoManager && active.undoManager.add();
            return {{ found: true, editorCount: editors.length, isActive: !!window.tinymce.activeEditor }};
        }}""")
        if result.get("found"):
            logger.info(
                f"BEE body set via TinyMCE (editorCount={result.get('editorCount')}, "
                f"activeEditor={result.get('isActive')})"
            )
            # Step 3: click outside the text block so BEE syncs TinyMCE → block model.
            try:
                await bee_frame.locator("body").click(position={"x": 50, "y": 10})
                await page.wait_for_timeout(500)
            except Exception:
                pass
            return True
        logger.debug(f"TinyMCE not ready after dblclick (editorCount={result.get('editorCount')})")
    except Exception as e:
        logger.debug(f"TinyMCE setContent failed: {e}")

    # Fallback: clipboard paste after the dblclick already entered edit mode.
    try:
        await page.evaluate(f"""async () => {{
            const html = {html_json};
            await navigator.clipboard.write([
                new ClipboardItem({{
                    'text/html': new Blob([html], {{type: 'text/html'}}),
                    'text/plain': new Blob([html], {{type: 'text/plain'}}),
                }})
            ]);
        }}""")
        await page.keyboard.press("Meta+a")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Meta+v")
        await page.wait_for_timeout(500)
        # Click outside to sync
        try:
            await bee_frame.locator("body").click(position={"x": 50, "y": 10})
            await page.wait_for_timeout(500)
        except Exception:
            pass
        logger.info("BEE body injected via clipboard paste fallback")
        return True
    except Exception as e:
        logger.debug(f"Clipboard paste fallback failed: {e}")

    logger.warning("BEE HTML injection: all strategies failed — check debug screenshots")
    return False


async def configure_pt_body_in_bee(
    page: Page,
    html_body: str,
    subject: str,
    preheader: str,
    utm_templates: Optional[Any] = None,
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Configure PT email content after seed campaign duplication.

    Called from the campaign compose overview (after rename). The seed campaign
    is already in BEE/DnD format with the correct block structure.

    Steps:
    1. Open sending info panel → fill sender dropdowns + subject/preheader
    2. Open BEE editor via "Edit message" → inject HTML body into text block
    3. Close BEE editor
    4. Apply UTM link templates
    """
    logger.info("Configuring PT content in BEE editor (seed duplication path)...")

    # ------------------------------------------------------------------
    # Step 1: Open sending info panel, set sender + subject + preheader
    # ------------------------------------------------------------------
    panel_opened = False
    for btn_name in ("Edit sending info", "Edit Sending Info"):
        btn = page.get_by_role("button", name=btn_name, exact=False)
        try:
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(1000)
                logger.info(f"Opened sending info panel via '{btn_name}'")
                panel_opened = True
                break
        except Exception:
            continue

    if panel_opened:
        # Sender dropdowns (from_name, from_email, reply_to)
        if from_name or from_email or reply_to:
            await _fill_sending_info(page, from_name, from_email, reply_to)

        # Subject/preheader via Monaco editors
        async def _fill_monaco(field_fragment: str, value: str) -> bool:
            el = page.locator(f"[id*='{field_fragment}']")
            try:
                await el.wait_for(state="attached", timeout=4000)
                view_lines = el.locator(
                    "xpath=ancestor::div[contains(@class,'monaco-editor')][1]"
                    "//div[contains(@class,'view-lines')]"
                )
                if await view_lines.count() > 0:
                    await view_lines.click()
                else:
                    await el.click(force=True)
                await page.keyboard.press("Meta+a")
                await page.keyboard.type(value)
                logger.info(f"Filled '{field_fragment}'")
                return True
            except Exception as exc:
                logger.warning(f"Could not fill Monaco field '{field_fragment}': {exc}")
                return False

        if subject:
            await _fill_monaco("subject-input", subject)
        if preheader:
            await _fill_monaco("preheader-input", preheader)

        # Close panel
        for done_sel in [
            page.get_by_role("button", name="Done", exact=True),
            page.locator('[aria-label="Done"]'),
        ]:
            try:
                if await done_sel.count() > 0 and await done_sel.is_visible(timeout=2000):
                    await done_sel.click()
                    await page.wait_for_timeout(1000)
                    logger.info("Sending info panel closed")
                    break
            except Exception:
                continue
    else:
        logger.warning("Could not open sending info panel — subject/preheader/sender not set")

    # ------------------------------------------------------------------
    # Step 2: Open BEE editor and inject HTML body
    # ------------------------------------------------------------------
    opened_bee = False
    for sel in [
        page.get_by_role("button", name="Edit message"),
        page.locator("button:has-text('Edit message')"),
        page.get_by_role("link", name="Edit message"),
    ]:
        try:
            if await sel.count() > 0 and await sel.first.is_visible():
                await sel.first.click()
                await page.wait_for_timeout(5000)
                logger.info("Opened BEE editor via 'Edit message'")
                opened_bee = True
                break
        except Exception:
            continue

    if not opened_bee:
        logger.warning("Could not open BEE editor — body content not injected")
        return False

    try:
        dbg = Path(__file__).parent / f"debug_bee_pt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(dbg), full_page=True)
        logger.info(f"BEE editor open screenshot: {dbg}")
    except Exception:
        pass

    await _inject_html_into_bee_text_block(page, html_body)

    # ------------------------------------------------------------------
    # Step 3: Apply UTM link templates (must happen inside the editor
    # modal — Link Management is not accessible from the compose overview)
    # ------------------------------------------------------------------
    await _configure_link_templates(page, utm_templates)

    # ------------------------------------------------------------------
    # Step 4: Close BEE editor
    # ------------------------------------------------------------------
    for close_sel in [
        page.locator('[aria-label="Done"]'),
        page.get_by_role("button", name="Done"),
        page.locator("#email-message-composer-portal button[aria-label='Done']"),
        page.locator("#email-message-composer-portal .bcl-button-primary"),
    ]:
        try:
            if await close_sel.count() > 0:
                await close_sel.first.click(force=True)
                await page.wait_for_timeout(2000)
                logger.info("BEE editor closed")
                break
        except Exception:
            continue

    return True


async def _option_is_selected(option) -> bool:
    """True if a react-select option is already selected.

    Braze marks selected options both with data-selected="true" and with the
    bcl-select__option--is-selected class; check both so a change to either
    one doesn't silently turn this into a no-op.
    """
    try:
        if (await option.get_attribute("data-selected")) == "true":
            return True
    except Exception:
        pass
    try:
        cls = await option.get_attribute("class") or ""
        return "--is-selected" in cls
    except Exception:
        return False


async def _dismiss_blocking_modal(page: Page) -> bool:
    """Cancel any open confirmation dialog that would block later steps.

    Braze's destructive confirms ("Remove link template?") are aria-modal and
    intercept pointer events page-wide. Always take the non-destructive exit
    (Cancel), never the confirm button.
    """
    try:
        dialog = page.locator("[role='dialog'][aria-modal='true']").first
        if await dialog.count() == 0 or not await dialog.is_visible():
            return False
        title = (await dialog.inner_text()).strip().splitlines()[0]
        logger.warning(f"Dismissing blocking modal: {title!r}")
        cancel = dialog.get_by_role("button", name=re.compile("cancel", re.I)).first
        if await cancel.count() > 0:
            await cancel.click(timeout=5000)
        else:
            await page.keyboard.press("Escape")
        await page.wait_for_timeout(1000)
        return True
    except Exception as e:
        logger.warning(f"Could not dismiss blocking modal: {e}")
        return False


async def _configure_link_templates(
    page: Page,
    utm_templates: Optional[Any] = None,
) -> bool:
    """Navigate to Link Management and apply UTM link templates.

    This is called from within the email editor modal, after HTML is set.

    Args:
        page: Playwright page (inside the email editor modal)
        utm_templates: Which templates to select:
            - None or "all": select ALL available templates in the dropdown
            - list of str: select only the named templates
    """
    logger.info("Applying UTM link templates...")

    # Click "Link Management" on the left sidebar
    link_mgmt = page.get_by_text("Link Management", exact=True).first
    try:
        await link_mgmt.wait_for(state="visible", timeout=5000)
        await link_mgmt.click()
        await page.wait_for_timeout(3000)
        logger.info("Opened Link Management")
    except Exception as e:
        logger.warning(f"Could not open Link Management: {e}")
        return False

    # Open the "Select link templates" dropdown (React Select, top-right).
    # The placeholder text is "Select link templates" when nothing is selected;
    # when already selected it shows "N item(s) selected" — handle both.
    template_selected = False
    tmpl_ph = page.locator(
        ".bcl-select__placeholder:has-text('Select link templates')"
    )
    if await tmpl_ph.count() > 0:
        tmpl_ctrl = tmpl_ph.last.locator(
            "xpath=ancestor::div[contains(@class, 'bcl-select__control')]"
        )
    else:
        # Try value-container (already has a selection)
        tmpl_ctrl = page.locator(".bcl-select__control").last

    try:
        await tmpl_ctrl.click(timeout=5000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        logger.warning(f"Could not open link templates dropdown: {e} — will still check unchecked rows")
        template_selected = True  # Assume already applied; skip to checkbox pass

    if not template_selected:
        # Get all available template options
        options = page.locator(".bcl-select__option")
        opt_count = await options.count()
        if opt_count == 0:
            logger.warning("No link templates available in dropdown — will still check unchecked rows")
            await page.keyboard.press("Escape")
            template_selected = True  # Skip selection, proceed to checkbox pass

    if not template_selected:
        logger.info(f"Found {opt_count} link template(s)")

        # Determine which templates to select
        select_all = utm_templates is None or utm_templates == "all"
        specific_names = []
        if isinstance(utm_templates, list):
            specific_names = utm_templates
            select_all = False

        # Click each template option.
        #
        # This is a multi-select: clicking an option that is ALREADY selected
        # de-selects it, which makes Braze raise a "Remove link template?"
        # confirmation modal. That modal is aria-modal and swallows pointer
        # events for the rest of the session, so every later step (the second
        # template, Intelligent Timing, #entry-frequency) times out and the
        # whole build dies. Seed campaigns duplicated from the PT template
        # already carry their link templates, so this is the common case —
        # skip anything already selected instead of toggling it off.
        selected_count = 0
        already_count = 0
        for i in range(opt_count):
            option = options.nth(i)
            try:
                option_text = (await option.inner_text()).strip()
            except Exception:
                continue

            should_select = select_all or any(
                name.lower() in option_text.lower() for name in specific_names
            )
            if not should_select:
                continue

            if await _option_is_selected(option):
                already_count += 1
                logger.info(f"Link template already applied: {option_text}")
                continue

            try:
                await option.click()
                await page.wait_for_timeout(500)
                selected_count += 1
                logger.info(f"Selected link template: {option_text}")
            except Exception as e:
                logger.warning(f"Could not select template '{option_text}': {e}")

        # Close the dropdown
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(1500)

        # Defensive: if anything above still managed to trip a destructive
        # confirm modal, dismiss it now rather than letting it block the
        # remainder of the build.
        await _dismiss_blocking_modal(page)

        if selected_count == 0 and already_count == 0:
            logger.warning("No link templates were selected — will still check unchecked rows")

    # Now select all links so UTM templates apply to every link.
    # After a template is applied, the link table shows columns for each
    # UTM parameter (utm_source, utm_medium, etc.) with per-link checkboxes.
    # There are "select all" checkboxes in the header row — one per template.
    # We click all visible header checkboxes that are unchecked.
    await page.wait_for_timeout(1000)

    # Find all checkboxes in the link management table header area.
    # These are the "select all" toggles next to column headers like
    # utm_source, bzt, etc.
    header_checkboxes = page.locator(
        "thead input[type='checkbox'], "
        "th input[type='checkbox'], "
        "[role='columnheader'] input[type='checkbox']"
    )
    hc_count = await header_checkboxes.count()

    if hc_count > 0:
        for i in range(hc_count):
            cb = header_checkboxes.nth(i)
            try:
                if await cb.is_visible() and not await cb.is_checked():
                    await cb.click()
                    await page.wait_for_timeout(300)
                    logger.debug(f"Checked header checkbox {i}")
            except Exception:
                pass
        logger.info(f"Selected all links ({hc_count} select-all checkbox(es))")
    else:
        # Fallback: look for any visible unchecked checkboxes in the table area
        # The select-all checkbox might be a standalone element
        all_cbs = page.locator("input[type='checkbox']")
        cb_total = await all_cbs.count()
        checked_count = 0
        for i in range(cb_total):
            cb = all_cbs.nth(i)
            try:
                if await cb.is_visible() and not await cb.is_checked():
                    # Check if this looks like a select-all (near the top of the table)
                    box = await cb.bounding_box()
                    if box and box["y"] < 300:  # Rough heuristic for header area
                        await cb.click()
                        await page.wait_for_timeout(300)
                        checked_count += 1
            except Exception:
                pass
        if checked_count > 0:
            logger.info(f"Checked {checked_count} select-all checkbox(es) (fallback)")
        else:
            logger.warning("Could not find select-all checkboxes for link templates")

    # Final pass: check any remaining unchecked row checkboxes.
    # Liquid-variable URLs like {{ kicker.url }} are not covered by the header
    # "select all" and need their per-row checkbox clicked individually.
    await page.wait_for_timeout(500)
    all_cbs = page.locator("input[type='checkbox']")
    extra = 0
    for i in range(await all_cbs.count()):
        cb = all_cbs.nth(i)
        try:
            if await cb.is_visible() and not await cb.is_checked():
                await cb.click()
                await page.wait_for_timeout(200)
                extra += 1
        except Exception:
            pass
    if extra:
        logger.info(f"Checked {extra} additional unchecked link checkbox(es) (e.g. kicker rows)")

    return True


# -------------------------------------------------------------------------
# 7a.  TARGET AUDIENCE
# -------------------------------------------------------------------------

def active_exclusion_filter_groups(
    audience_config: Dict,
    launch_date: Optional[str] = None,
) -> List[Dict]:
    """Return only the exclusion filter groups that are still in effect.

    A brand_config entry may carry `expires_before: "YYYY-MM-DD"` to mark a
    time-boxed exclusion (e.g. a canvas test holdout). The entry applies only
    when the campaign's launch date is strictly before that date.

    `launch_date` is the campaign's own send date (ISO YYYY-MM-DD), which is the
    correct reference point — not "today". A campaign built today for a send
    three weeks out must be evaluated against the send date, and a backdated
    rebuild of a past send must reproduce what applied then. Falls back to today
    only when the caller has no send date to give.

    This is the single source of truth for the expiry rule. Every path that
    applies `exclusion_filter_groups` must go through it — the Memorial Day
    Canvas Test Group leaked into BUR HTML/CSS designed builds for ~3 months
    because `configure_target_audience()` looped the raw list instead.
    """
    raw = audience_config.get("exclusion_filter_groups", []) or []
    ref_date = launch_date or date.today().isoformat()
    active = [
        excl for excl in raw
        if not excl.get("expires_before") or ref_date < excl["expires_before"]
    ]
    for excl in raw:
        if excl not in active:
            logger.info(
                "Skipping expired exclusion %r (expires_before %s, launch date %s)",
                excl.get("name", ""), excl.get("expires_before"), ref_date,
            )
    return active


async def configure_target_audience(
    page: Page,
    audience_config: Dict,
    clear_existing: bool = False,
    launch_date: Optional[str] = None,
) -> bool:
    """Configure the target audience in the campaign builder.

    Handles three audience types:
      - segment: select a single segment by name
      - segment_with_filter: select a segment, then add filter(s)
      - all_users_with_filters: select All Users, then add segment filters

    Args:
        clear_existing: When True (seed duplication path), remove all existing
            filter rows and exclusion groups before configuring. This prevents
            the seed campaign's audience from doubling up with the new config.
        launch_date: Campaign send date (ISO YYYY-MM-DD). Used to drop
            `exclusion_filter_groups` entries whose `expires_before` has passed.
            Always pass this when known; omitting it falls back to today.
    """
    logger.info("Configuring target audience...")

    # Navigate to "Target Audiences" step (step 3 in Braze campaign builder)
    # Braze uses "Target Audiences" in the header and "Target" in the footer nav
    target_selectors = [
        page.get_by_role("button", name="Target Audiences"),
        page.get_by_role("button", name="Target"),
        page.get_by_text("Target Audiences", exact=True),
        page.locator("button:has-text('Target')"),
    ]
    for selector in target_selectors:
        try:
            await selector.wait_for(state="visible", timeout=5000)
            await selector.click()
            await page.wait_for_timeout(2000)
            logger.info("Navigated to Target Audiences step")
            break
        except Exception:
            continue

    # Remove the control group first (does NOT set variant % yet — we do that last)
    await _remove_control_group(page)

    # For seed-duplicated campaigns, wipe the existing audience config before
    # re-applying. Without this, filters and exclusion groups from the seed
    # stack on top of whatever the new campaign needs.
    if clear_existing:
        from build_designed_campaign import _clear_audience_selection
        logger.info("Clearing existing audience selection (seed duplication path)...")
        await _clear_audience_selection(page)
        await page.wait_for_timeout(500)

    audience_type = audience_config.get("type", "segment")
    segment_name = audience_config.get("segment", "")
    filters = audience_config.get("filters", [])

    if audience_type == "segment":
        await _select_segment(page, segment_name)

    elif audience_type == "all_users_with_filters":
        # Select the base segment (e.g. "All Email Subscribed", "All Users")
        await _select_segment(page, segment_name)
        # Then add filters
        for f in filters:
            await _add_audience_filter(page, f)

    elif audience_type == "segment_with_filter":
        # Select the base segment
        await _select_segment(page, segment_name)
        # Add additional filters
        for f in filters:
            await _add_audience_filter(page, f)

    # Handle exclusion filter groups (separate AND groups with "Not Included").
    # Expired time-boxed entries are dropped here — see
    # active_exclusion_filter_groups().
    for excl in active_exclusion_filter_groups(audience_config, launch_date):
        segment_name = excl.get("name", "")
        if segment_name:
            await _add_exclusion_filter_group(page, segment_name)

    # Set variant % LAST — segment picker interactions cause React re-renders that
    # revert any earlier DOM manipulation of the variant % input.
    await _set_variant1_to_100(page)

    logger.info("Target audience configured")
    return True


async def _remove_control_group(page: Page) -> bool:
    """Click 'Remove Control Group' if present.

    Braze defaults to 80% variant + 20% control. After removing the control
    group the variant stays at 80%. _set_variant1_to_100() is called separately
    at the END of configure_target_audience(), after segment selection, because
    segment picker re-renders reset any earlier DOM manipulation.
    """
    removed = False
    try:
        remove_btn = page.get_by_role("button", name="Remove Control Group")
        if await remove_btn.count() == 0:
            remove_btn = page.get_by_text("Remove Control Group", exact=False)
        if await remove_btn.count() > 0 and await remove_btn.first.is_visible():
            await remove_btn.first.click()
            await page.wait_for_timeout(1000)
            logger.info("Removed control group")
            removed = True
        else:
            logger.debug("No control group to remove (not present)")
    except Exception as e:
        logger.debug(f"Control group removal skipped: {e}")

    return removed


async def _set_variant1_to_100(page: Page) -> None:
    """Find the Variant 1 percentage input and set it to 100.

    Called AFTER segment selection so React re-renders from the segment picker
    don't revert the value before we navigate away.
    """
    try:
        # The number input for variant % has class 'sc-gVcfYu dFcXyT' and ctx='%'.
        # page.locator("input[type='number']").first is the reliable selector.
        input_el = page.locator("input[type='number']").first
        if await input_el.count() == 0 or not await input_el.is_visible(timeout=3000):
            logger.warning("Could not find Variant 1 percentage input — may still be <100%")
            return

        await input_el.scroll_into_view_if_needed()
        # fill() clears + types + dispatches React-compatible input events.
        await input_el.fill("100")
        await input_el.press("Tab")
        await page.wait_for_timeout(500)

        actual = await input_el.input_value()
        logger.info(f"Variant 1 percentage set to: {actual!r}")
    except Exception as e:
        logger.warning(f"Could not set Variant 1 to 100%: {e}")


async def _select_segment(page: Page, segment_name: str, max_retries: int = 3) -> bool:
    """Search for and select a segment in the 'Target Users By Segment' picker.

    The Braze segment picker is a React Select multi-select dropdown with
    checkboxes.  The placeholder div says 'Search Segments...' and changes
    to 'N item(s) selected' after picking.  The dropdown stays open after
    clicking an option, so we need to close it explicitly afterwards.

    If the search results don't load in time, the function clears the search
    text, closes the dropdown, and retries up to ``max_retries`` times with
    increasing wait times before giving up.

    Search strategy: Braze's segment search can break on dashes and special
    characters.  On each attempt we try progressively shorter search terms
    (full name -> up to first dash -> first two words) while always matching
    the full segment name in the results.
    """
    logger.info(f"Selecting segment: {segment_name}")

    # Build a list of search terms from shortest to longest.
    # Braze's segment search works best with short, distinctive terms.
    # Strategy: try individual words first (skipping common/generic words),
    # then progressively longer combinations, then the full name last.
    _GENERIC_WORDS = {
        "list", "send", "segment", "all", "the", "and", "or", "for",
        "new", "old", "test", "users", "email", "subscribed", "file",
    }
    words = segment_name.split()
    search_terms: List[str] = []

    # 1. Individual distinctive words (skip short/generic ones)
    for w in words:
        w_clean = w.strip(" -–—")
        if (
            len(w_clean) >= 3
            and w_clean.lower() not in _GENERIC_WORDS
            and w_clean not in search_terms
        ):
            search_terms.append(w_clean)

    # 2. First two words together (if multi-word)
    if len(words) >= 2:
        two = " ".join(words[:2])
        if two not in search_terms:
            search_terms.append(two)

    # 3. Portion before first dash (if dashes present)
    if " - " in segment_name:
        prefix = segment_name.split(" - ")[0].strip()
        if prefix and prefix not in search_terms:
            search_terms.append(prefix)

    # 4. Full name as final fallback
    if segment_name not in search_terms:
        search_terms.append(segment_name)

    logger.debug(f"Segment search terms for '{segment_name}': {search_terms}")

    # Use enough retries to try all search terms (at least max_retries)
    total_attempts = max(max_retries, len(search_terms))

    for attempt in range(1, total_attempts + 1):
        # Cycle through search terms in order
        search_term = search_terms[min(attempt - 1, len(search_terms) - 1)]

        # --- Locate the segment picker control ---
        seg_ph = page.locator(".bcl-select__placeholder:has-text('Search Segments...')")
        seg_ctrl = seg_ph.locator("xpath=ancestor::div[contains(@class, 'bcl-select__control')]")

        # Fallback: if segment was already selected, the control shows "N item selected"
        if await seg_ctrl.count() == 0:
            seg_ctrl = page.locator(".bcl-select__control:has-text('item selected')").first

        # Fallback: find by heading context
        if await seg_ctrl.count() == 0:
            heading = page.get_by_text("Target Users By Segment", exact=False).first
            seg_ctrl = heading.locator("xpath=following::div[contains(@class, 'bcl-select__control')]").first

        # --- Open the dropdown ---
        try:
            await seg_ctrl.scroll_into_view_if_needed()
            await seg_ctrl.click()
            await page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"Could not open segment picker (attempt {attempt}/{total_attempts}): {e}")
            if attempt < total_attempts:
                await page.wait_for_timeout(2000)
                continue
            return False

        # --- Clear any leftover search text from a previous attempt ---
        await page.keyboard.press("Meta+a")
        await page.wait_for_timeout(100)
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(300)

        # --- Type to search (using progressively shorter term) ---
        logger.info(
            f"Searching for segment with term '{search_term}' "
            f"(attempt {attempt}/{total_attempts})"
        )
        await page.keyboard.type(search_term)
        # Wait longer on retries to give the search results more time to load
        search_wait = 2000 + (attempt - 1) * 2000
        await page.wait_for_timeout(search_wait)

        # --- Click the matching checkbox option (exact name match only) ---
        # :has-text() is a substring match, not exact — with segments like
        # "Engaged", "Highly Engaged", and "Geo Segment - Engaged" all live at
        # once, a substring match + .first can silently click the wrong one.
        # Compare each rendered option's trimmed text for exact equality instead.
        try:
            options = page.locator(".bcl-select__option")
            await options.first.wait_for(state="visible", timeout=5000 + (attempt - 1) * 3000)
            option_count = await options.count()
            option_texts = [(await options.nth(i).inner_text()).strip() for i in range(option_count)]
            match_index = next(
                (i for i, text in enumerate(option_texts) if text == segment_name), None
            )
            if match_index is None:
                raise RuntimeError(
                    f"No exact-match option for '{segment_name}' among rendered options: {option_texts}"
                )
            await options.nth(match_index).click()
            await page.wait_for_timeout(500)
            logger.info(f"Selected segment: {segment_name}")
            # Close the segment dropdown (it stays open after selection)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)
            return True
        except Exception as e:
            logger.warning(
                f"Could not select segment '{segment_name}' "
                f"with search term '{search_term}' "
                f"(attempt {attempt}/{total_attempts}): {e}"
            )
            # Save a debug screenshot so we can see what the dropdown shows
            try:
                from datetime import datetime as _dt
                dbg_path = (
                    Path(__file__).parent
                    / f"debug_segment_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png"
                )
                await page.screenshot(path=str(dbg_path), full_page=False)
                logger.info(f"Debug screenshot saved: {dbg_path}")
            except Exception:
                pass

            # Close the dropdown before retrying
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)

            if attempt < total_attempts:
                logger.info(f"Retrying segment selection with next search term...")
                await page.wait_for_timeout(2000)

    logger.error(f"Failed to select segment '{segment_name}' after {total_attempts} attempts")
    return False


async def _add_exclusion_filter_group(page: Page, segment_name: str) -> bool:
    """Add segment_name to Braze's Exclusion group section on the Target Audiences step.

    Braze has two distinct audience exclusion mechanisms:
      - Filter group with "Not Included" comparison (old approach, fragile)
      - Dedicated "Exclusion group" section (native, correct approach)

    This function uses the Exclusion group section. After inclusion filters have
    been added to the first Filter group via .first, the Exclusion group's
    "Search filter..." placeholder is the last one on the page.

    Two scenarios:
      - Duplicated campaign: Exclusion group section persists from ref → reuse it
      - New campaign: only Filter group exists → click "+ Add exclusion group" first
    """
    logger.info(f"Adding to Exclusion group: '{segment_name}'")

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(500)

    # Check how many "Search filter..." placeholders exist.
    # After inclusion filters are added with .first, any remaining placeholder(s)
    # belong to the Exclusion group section (or stale filter group containers).
    # If only 1 exists (only the Filter group), we need to create the Exclusion group.
    filter_ph = page.locator(".bcl-select__placeholder:has-text('Search filter...')")
    ph_count = await filter_ph.count()

    if ph_count < 2:
        # No Exclusion group section present yet — click "+ Add exclusion group"
        add_excl_selectors = [
            page.get_by_role("button", name="Add exclusion group"),
            page.get_by_text("Add exclusion group", exact=False),
            page.locator("button:has-text('Add exclusion group')"),
            page.locator("a:has-text('Add exclusion group')"),
            page.locator("span:has-text('Add exclusion group')"),
        ]
        clicked = False
        for sel in add_excl_selectors:
            try:
                await sel.wait_for(state="visible", timeout=3000)
                await sel.scroll_into_view_if_needed()
                await sel.click()
                await page.wait_for_timeout(1500)
                clicked = True
                logger.info("Clicked '+ Add exclusion group'")
                break
            except Exception as e:
                logger.debug(f"Add exclusion group selector failed: {e}")

        if not clicked:
            logger.warning("Could not find '+ Add exclusion group' button — skipping")
            return False

    # Use the LAST "Search filter..." placeholder — this is the Exclusion group's input.
    # (Inclusion filters used .first so they stayed in the Filter group section.)
    seg_mem_selected = False
    for attempt in range(3):
        filter_ph = page.locator(".bcl-select__placeholder:has-text('Search filter...')")
        if await filter_ph.count() == 0:
            logger.debug(f"No 'Search filter...' found (attempt {attempt+1})")
            await page.wait_for_timeout(1000)
            continue

        filter_ctrl = filter_ph.last.locator(
            "xpath=ancestor::div[contains(@class, 'bcl-select__control')]"
        )
        await filter_ctrl.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)

        try:
            await filter_ctrl.click(timeout=3000)
        except Exception:
            await filter_ctrl.click(force=True)
        await page.wait_for_timeout(1500)

        menu = page.locator(".bcl-select__menu")
        if await menu.count() == 0:
            logger.debug(f"Filter dropdown didn't open (attempt {attempt+1})")
            await page.mouse.click(400, 200)
            await page.wait_for_timeout(1000)
            continue

        await page.keyboard.type("Segment Membership")
        await page.wait_for_timeout(2000)

        try:
            seg_mem_opt = page.locator(
                ".bcl-select__option:has-text('Segment Membership')"
            ).first
            await seg_mem_opt.wait_for(state="visible", timeout=5000)
            await seg_mem_opt.click()
            await page.wait_for_timeout(1500)
            seg_mem_selected = True
            logger.debug("Selected 'Segment Membership' in Exclusion group")
            break
        except Exception as e:
            logger.debug(f"Attempt {attempt+1}: {e}")
            await page.mouse.click(400, 200)
            await page.wait_for_timeout(1000)

    if not seg_mem_selected:
        logger.warning("Could not select 'Segment Membership' for Exclusion group")
        return False

    # Select the segment. Comparison stays "Included" — inside the Exclusion group
    # section, "Included in segment X" means "user is in X → excluded from campaign".
    select_ph = page.locator(".bcl-select__placeholder:has-text('Select...')")
    if await select_ph.count() == 0:
        logger.warning(f"No 'Select...' dropdown for exclusion segment '{segment_name}'")
        return False

    seg_ctrl = select_ph.last.locator(
        "xpath=ancestor::div[contains(@class, 'bcl-select__control')]"
    )
    await seg_ctrl.scroll_into_view_if_needed()
    await seg_ctrl.click(force=True)
    await page.wait_for_timeout(800)

    await page.keyboard.type(segment_name)
    await page.wait_for_timeout(2000)

    try:
        seg_opt = page.locator(
            f".bcl-select__option:has-text('{segment_name}')"
        ).first
        await seg_opt.wait_for(state="visible", timeout=5000)
        await seg_opt.click()
        await page.wait_for_timeout(1000)
        logger.info(f"Exclusion group: added '{segment_name}'")
        return True
    except Exception:
        pass

    try:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)
        logger.info(f"Exclusion group: added '{segment_name}' (via Enter)")
        return True
    except Exception as e:
        logger.warning(f"Could not select segment '{segment_name}' for Exclusion group: {e}")
        return False


async def _add_audience_filter(page: Page, filter_config: Dict) -> bool:
    """Add a single segment-membership filter using the Braze filter picker.

    The Braze filter flow is:
      1. Click the last 'Search filter...' React Select in the filter group.
      2. Type 'Segment Membership' and select the matching option.
      3. A new row appears with 'Comparison' (Included) and 'Segment' (Select...).
      4. Click the 'Segment' dropdown and pick the specific segment.

    Each subsequent filter gets an OR row automatically within the same
    filter group.

    filter_config:
      type: "segment" or "filter"
      name: segment/filter name
      op: "or" or "and" (default "and")
    """
    filter_name = filter_config.get("name", "")
    filter_op = filter_config.get("op", "and")
    logger.info(f"Adding filter: {filter_name} ({filter_op})")

    # Dismiss any open dropdown or popup before starting
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)

    # --- Step 1: Click the FIRST "Search filter..." dropdown ---
    # Always use .first so inclusion filters land in the main (top) filter group.
    # Using .last would target any stale second filter group left over from a
    # reference campaign that wasn't fully cleared, putting inclusions in the
    # wrong (exclusion) group.
    # Retry up to 3 times. IMPORTANT: do NOT press Escape after a failed
    # attempt — that can remove the empty filter row from the DOM.
    seg_mem_selected = False
    for attempt in range(3):
        filter_ph = page.locator(".bcl-select__placeholder:has-text('Search filter...')")
        ph_count = await filter_ph.count()
        if ph_count == 0:
            # The empty filter row may have been removed. Try clicking in a
            # neutral area, then wait for it to reappear.
            logger.debug(f"No 'Search filter...' row found (attempt {attempt+1}), clicking neutral area...")
            try:
                heading = page.get_by_text("Additional Filters", exact=False).first
                await heading.click()
            except Exception:
                await page.mouse.click(400, 200)
            await page.wait_for_timeout(1500)
            # Check again
            filter_ph = page.locator(".bcl-select__placeholder:has-text('Search filter...')")
            if await filter_ph.count() == 0:
                logger.warning(f"No 'Search filter...' dropdown found for filter '{filter_name}'")
                return False

        filter_ctrl = filter_ph.first.locator(
            "xpath=ancestor::div[contains(@class, 'bcl-select__control')]"
        )
        # Scroll the control fully into view and give the page time to settle
        await filter_ctrl.scroll_into_view_if_needed()
        await page.wait_for_timeout(1000)

        # Click to open the dropdown — try regular click first, then force
        try:
            await filter_ctrl.click(timeout=3000)
        except Exception:
            await filter_ctrl.click(force=True)
        await page.wait_for_timeout(1500)

        # Verify the menu opened
        menu = page.locator(".bcl-select__menu")
        if await menu.count() == 0:
            logger.debug(f"Filter dropdown didn't open (attempt {attempt+1}), retrying...")
            # Click away to neutral area instead of Escape (Escape removes the row)
            try:
                heading = page.get_by_text("Additional Filters", exact=False).first
                await heading.click()
            except Exception:
                await page.mouse.click(400, 200)
            await page.wait_for_timeout(1000)
            continue

        # --- Step 2: Type "Segment Membership" and select it ---
        await page.keyboard.type("Segment Membership")
        await page.wait_for_timeout(2000)

        try:
            seg_mem_opt = page.locator(
                ".bcl-select__option:has-text('Segment Membership')"
            ).first
            await seg_mem_opt.wait_for(state="visible", timeout=5000)
            await seg_mem_opt.scroll_into_view_if_needed()
            await seg_mem_opt.click()
            await page.wait_for_timeout(1500)
            logger.debug(f"Selected 'Segment Membership' filter type for '{filter_name}'")
            seg_mem_selected = True
            break
        except Exception as e:
            logger.debug(f"Attempt {attempt+1} failed to select 'Segment Membership': {e}")
            # Click away instead of Escape
            try:
                heading = page.get_by_text("Additional Filters", exact=False).first
                await heading.click()
            except Exception:
                await page.mouse.click(400, 200)
            await page.wait_for_timeout(1000)

    if not seg_mem_selected:
        logger.warning(f"Could not select 'Segment Membership' for filter '{filter_name}'")
        return False

    # --- Step 3: Click the 'Segment' (Select...) dropdown and pick the segment ---
    # After selecting "Segment Membership", a row appears with
    # [Comparison: Included] [Segment: Select...]
    # The "Select..." is the last one with that placeholder on the page.
    select_ph = page.locator(".bcl-select__placeholder:has-text('Select...')")
    if await select_ph.count() == 0:
        logger.warning(f"No 'Select...' dropdown found for segment '{filter_name}'")
        return False

    seg_ctrl = select_ph.last.locator(
        "xpath=ancestor::div[contains(@class, 'bcl-select__control')]"
    )
    await seg_ctrl.scroll_into_view_if_needed()
    await seg_ctrl.click(force=True)
    await page.wait_for_timeout(800)

    # Type the segment name to search
    await page.keyboard.type(filter_name)
    await page.wait_for_timeout(2000)

    # Select the matching option
    try:
        seg_opt = page.locator(
            f".bcl-select__option:has-text('{filter_name}')"
        ).first
        await seg_opt.wait_for(state="visible", timeout=5000)
        await seg_opt.click()
        await page.wait_for_timeout(1000)
        logger.info(f"Added segment filter: {filter_name}")
        return True
    except Exception:
        pass

    # Fallback: try Enter to accept
    try:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)
        logger.info(f"Added segment filter: {filter_name} (via Enter)")
        return True
    except Exception as e:
        logger.warning(f"Could not select segment '{filter_name}' in filter: {e}")
        await page.keyboard.press("Escape")
        return False


# -------------------------------------------------------------------------
# 7b.  DELIVERY SCHEDULE
# -------------------------------------------------------------------------

def _convert_24h_to_12h(time_24h: str) -> str:
    """Convert HH:MM (24h) to H:MM am/pm string for Braze time pickers."""
    h, m = int(time_24h.split(":")[0]), int(time_24h.split(":")[1])
    period = "pm" if h >= 12 else "am"
    hour_12 = h % 12 or 12
    return f"{hour_12}:{m:02d} {period}"


async def _set_it_fallback_time(page: Page, fallback_time_24h: str) -> bool:
    """Select 'a specific custom fallback time' radio and fill the time value.

    Braze shows two sub-options under Intelligent Timing:
      • "most popular time to use the app"  ← wrong default
      • "a specific custom fallback time"   ← always use this
    """
    # Step 1: click the specific-fallback radio
    radio_clicked = False
    for radio_sel in [
        page.get_by_text("a specific custom fallback time", exact=False),
        page.get_by_label("a specific custom fallback time", exact=False),
        page.get_by_text("specific custom fallback", exact=False),
        page.get_by_text("custom fallback time", exact=False),
    ]:
        try:
            if await radio_sel.count() > 0 and await radio_sel.is_visible(timeout=3000):
                await radio_sel.click()
                await page.wait_for_timeout(500)
                logger.info("Selected 'specific custom fallback time' radio")
                radio_clicked = True
                break
        except Exception:
            continue
    if not radio_clicked:
        logger.warning("Could not find 'specific custom fallback time' radio — fallback time may not be set")
        return False

    await page.wait_for_timeout(800)

    # Step 2: fill the time using the Braze scroll-picker (same approach as designed builder)
    h, m = int(fallback_time_24h.split(":")[0]), int(fallback_time_24h.split(":")[1])
    hour_str = str(h % 12 or 12)
    min_str = str(m)
    period = "pm" if h >= 12 else "am"

    # Find and click the fallback time input to open the picker
    fallback_input = None
    try:
        label = page.get_by_text("a specific custom fallback time", exact=False).first
        fallback_input = label.locator("xpath=following::input[1]")
        if await fallback_input.count() == 0:
            fallback_input = None
    except Exception:
        pass

    if not fallback_input:
        for sel in [
            page.get_by_placeholder("h:mm am").last,
            page.locator("input[placeholder*='h:mm']").last,
        ]:
            try:
                if await sel.count() > 0:
                    fallback_input = sel
                    break
            except Exception:
                continue

    if fallback_input:
        await fallback_input.scroll_into_view_if_needed()
        await fallback_input.click()
        await page.wait_for_timeout(1500)

        # Debug screenshot to confirm picker is open and see its structure.
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _dbg = str(Path(__file__).resolve().parent.parent / f"debug_it_picker_{_ts}.png")
        try:
            await page.screenshot(path=_dbg, full_page=False)
            logger.info(f"IT fallback picker debug screenshot: {_dbg}")
        except Exception:
            pass

        # The Braze fallback time picker is a slot-machine style picker: the full
        # hour/minute/period lists exist in the DOM simultaneously, each inside a
        # scrollable column that clips to a small visible window via CSS overflow.
        # Clicking an item outside that visible window closes the whole picker.
        #
        # Two earlier approaches both failed here, confirmed live 2026-08-27:
        #   1. Guessing the window's position as a fixed offset below the input
        #      ("input top" .. "input top + 280") — wrong whenever Braze renders
        #      the picker ABOVE the input instead of below it (more room above
        #      than below near the bottom of the page). A borderline item got
        #      treated as clickable when it was actually past the real panel's
        #      edge; that click closed the picker, and everything after it
        #      "succeeded" against a picker that no longer existed.
        #   2. Inferring the visible window from sibling items' bounding rects —
        #      wrong because a CSS `overflow: hidden` clip does NOT change a
        #      clipped child's own getBoundingClientRect(); an item can report a
        #      perfectly normal position while being entirely invisible.
        #
        # Fix: find the actual scrollable ancestor element for the column (the
        # one whose computed overflow clips it, with scrollHeight > clientHeight)
        # and set its scrollTop directly to center the target row — no guessing,
        # no iterative wheel nudges, no reliance on any other element's rect.
        input_rect = await fallback_input.evaluate(
            "el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }"
        )
        picker_cx_est = input_rect["x"] + input_rect["w"] / 2
        logger.info(f"IT picker: input at y≈{input_rect['y']:.0f}, cx≈{picker_cx_est:.0f}")

        async def _scroll_col_to(target_text: str, col_name: str, col_cx: float) -> bool:
            """Scroll target_text's column so it's centered in its clipping container, then click."""
            padded = target_text.zfill(2) if target_text.isdigit() else None
            targets_to_try = [target_text, padded, target_text.upper()] if padded else [target_text, target_text.upper()]
            targets_to_try = list(dict.fromkeys(t for t in targets_to_try if t))  # dedupe

            for tv in targets_to_try:
                result = await page.evaluate(f"""() => {{
                    const tv = "{tv}";
                    const colCx = {col_cx};
                    const colXTolerance = 80;  // only consider elements within 80px of the column center

                    function findScrollAncestor(el) {{
                        let a = el.parentElement;
                        for (let i = 0; i < 8 && a; i++) {{
                            const cs = getComputedStyle(a);
                            const clips = cs.overflowY === 'hidden' || cs.overflowY === 'scroll' || cs.overflowY === 'auto';
                            if (clips && a.scrollHeight > a.clientHeight + 2) return a;
                            a = a.parentElement;
                        }}
                        return null;
                    }}

                    const items = [...document.querySelectorAll('span, li')].filter(el => {{
                        if (el.children.length !== 0) return false;
                        const t = el.textContent.trim();
                        if (!/^([0-9]{{1,2}}|am|pm|AM|PM)$/.test(t)) return false;
                        const r = el.getBoundingClientRect();
                        if (r.width <= 0 || r.height <= 0) return false;
                        const cx = r.x + r.width / 2;
                        return Math.abs(cx - colCx) <= colXTolerance;
                    }});
                    if (items.length === 0) return {{ error: 'no_column_items' }};

                    const target = items.find(el => el.textContent.trim() === tv);
                    if (!target) return {{ error: 'target_not_in_column' }};

                    const container = findScrollAncestor(target);
                    if (!container) {{
                        // No clipping ancestor at all — this column (e.g. am/pm, only
                        // 2 rows) never needs scrolling, so whatever's currently
                        // rendered is already fully visible. Use the viewport itself
                        // as the safety window instead of erroring out.
                        const r = target.getBoundingClientRect();
                        return {{
                            x: r.x + r.width / 2,
                            y: r.y + r.height / 2,
                            containerTop: 0,
                            containerBottom: window.innerHeight,
                        }};
                    }}

                    const contRect = container.getBoundingClientRect();
                    const targRect = target.getBoundingClientRect();
                    const delta = (targRect.top + targRect.height / 2) - (contRect.top + contRect.height / 2);
                    container.scrollTop += delta;

                    const targRectAfter = target.getBoundingClientRect();
                    const contRectAfter = container.getBoundingClientRect();
                    return {{
                        x: targRectAfter.x + targRectAfter.width / 2,
                        y: targRectAfter.y + targRectAfter.height / 2,
                        containerTop: contRectAfter.top,
                        containerBottom: contRectAfter.bottom,
                    }};
                }}""")
                if result.get("error"):
                    logger.warning(f"IT picker: {col_name} item {tv!r} — {result['error']}")
                    continue

                margin = 6
                if result["y"] < result["containerTop"] + margin or result["y"] > result["containerBottom"] - margin:
                    # Centering should have made this comfortably in-bounds; if it
                    # didn't (e.g. row taller than expected), don't risk the click.
                    logger.warning(
                        f"IT picker: {col_name} item {tv!r} not centered after scroll "
                        f"(y={result['y']:.0f}, container {result['containerTop']:.0f}-{result['containerBottom']:.0f})"
                    )
                    continue

                await page.mouse.click(result["x"], result["y"])
                await page.wait_for_timeout(300)
                logger.info(f"IT fallback picker: clicked {col_name} ({tv!r}) at ({result['x']:.0f},{result['y']:.0f})")
                return True

            logger.warning(f"IT picker: could not set {col_name} to '{target_text}'")
            return False

        # Click order: hour → minute → period. We use separate x positions for each
        # column but rely on re-querying after scrolls, so the column cx doesn't need
        # to be exact — just roughly in the right column.
        hour_ok = await _scroll_col_to(hour_str, "hour",   picker_cx_est - 80)
        min_ok = await _scroll_col_to(min_str,  "minute", picker_cx_est)
        period_ok = await _scroll_col_to(period,   "period", picker_cx_est + 80)

        await page.keyboard.press("Tab")
        await page.wait_for_timeout(400)

        if not (hour_ok and min_ok and period_ok):
            logger.error(
                f"IT fallback time NOT fully set — hour_ok={hour_ok} min_ok={min_ok} period_ok={period_ok} "
                f"(intended {_convert_24h_to_12h(fallback_time_24h)}); Braze's default likely remains in place"
            )
            return False

        # Verify: read the input back and confirm it actually reflects what we set,
        # rather than trusting the per-column click results alone.
        try:
            actual_value = (await fallback_input.input_value()).strip().lower()
        except Exception:
            actual_value = None
        expected_value = _convert_24h_to_12h(fallback_time_24h).strip().lower()
        if actual_value and actual_value != expected_value:
            logger.error(
                f"IT fallback time mismatch after fill: expected {expected_value!r}, "
                f"input shows {actual_value!r}"
            )
            return False

        logger.info(f"IT fallback time set to {_convert_24h_to_12h(fallback_time_24h)}")
        return True

    logger.warning("Could not find fallback time input to fill")
    return False


async def configure_delivery(
    page: Page,
    send_time_config: Dict,
    launch_date: str,
    skip_tz_checkbox: bool = False,
) -> bool:
    """Configure the Delivery step of the campaign builder.

    Args:
        page: Playwright page
        send_time_config: from resolve_send_time()
        launch_date: YYYY-MM-DD string
    """
    logger.info("Configuring delivery schedule...")

    # Navigate to "Schedule Delivery" step (step 2 in Braze campaign builder)
    # Braze uses "Schedule Delivery" in the header and "Schedule" in the footer nav
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

    # Debug screenshot after navigating to delivery step
    try:
        _ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        _dbg = str(__import__("pathlib").Path(__file__).parent.parent.parent / f"debug_delivery_{_ts}.png")
        await page.screenshot(path=_dbg, full_page=False)
        logger.info(f"Delivery step debug screenshot: {_dbg}")
    except Exception:
        pass

    # ---- Scheduling option (radio buttons: immediate / scheduled / optimal) ----
    time_type = send_time_config.get("type", "intelligent_timing")

    if time_type == "intelligent_timing":
        # Select the "Intelligent Timing" radio button — try multiple selectors
        it_clicked = False
        for it_sel in [
            page.get_by_text("Intelligent Timing", exact=True),
            page.get_by_text("Intelligent Timing", exact=False),
            page.get_by_text("Intelligent timing", exact=False),
            page.get_by_text("Send at an optimal time", exact=False),
            page.get_by_text("Optimal Time", exact=False),
            page.locator("label").filter(has_text="Intelligent"),
            page.locator("input[type='radio'] + label").filter(has_text="Intelligent"),
        ]:
            try:
                if await it_sel.count() > 0 and await it_sel.first.is_visible(timeout=5000):
                    await it_sel.first.scroll_into_view_if_needed()
                    await it_sel.first.click()
                    await page.wait_for_timeout(1000)
                    logger.info("Selected Intelligent Timing")
                    it_clicked = True
                    break
            except Exception:
                continue
        if not it_clicked:
            logger.warning("Could not find Intelligent Timing option — taking debug screenshot")

    else:
        # Select "Send at a designated time" radio
        designated = page.get_by_text("Send at a designated time", exact=True)
        await designated.scroll_into_view_if_needed()
        await designated.click()
        await page.wait_for_timeout(1000)
        logger.info("Selected 'Send at a designated time'")

    # ---- Entry Frequency: select "Once" from custom dropdown ----
    await _set_entry_frequency(page, launch_date, send_time_config)

    # ---- IT fallback time — set AFTER entry frequency ----
    # Entry frequency sets a Start Time input that can interfere with the
    # fallback time picker if we set them in the wrong order.
    if time_type == "intelligent_timing":
        fallback_time = send_time_config.get("fallback_time")
        if fallback_time:
            fb_ok = await _set_it_fallback_time(page, fallback_time)
            if not fb_ok:
                logger.error(
                    f"Intelligent Timing fallback time could not be confirmed as {fallback_time!r} — "
                    f"verify the Delivery step in Braze before this campaign launches"
                )
        else:
            logger.warning("IT selected but no fallback_time in config — leaving as default")

    # ---- Local time zone checkbox ----
    if skip_tz_checkbox:
        logger.debug("Skipping local time zone checkbox (skip_tz_checkbox=True)")
    else:
        try:
            tz_label = page.get_by_text("Enter users into this Campaign in their local time zone", exact=False)
            await tz_label.scroll_into_view_if_needed()
            tz_checkbox = page.locator("input[type='checkbox']").filter(
                has=page.locator(".. >> text=local time zone")
            )
            # If we can't find via filter, try the nearby checkbox
            if await tz_checkbox.count() == 0:
                tz_checkbox = tz_label.locator("xpath=preceding-sibling::input[@type='checkbox'] | ancestor::label//input[@type='checkbox']")
            if await tz_checkbox.count() > 0 and not await tz_checkbox.is_checked():
                await tz_checkbox.check()
                logger.info("Checked local time zone checkbox")
            else:
                # Click the label itself (often toggles the checkbox)
                await tz_label.click()
                logger.info("Clicked local time zone label")
        except Exception as e:
            logger.warning(f"Could not set local time zone: {e}")

    logger.info("Delivery configured")
    return True


async def _set_entry_frequency(
    page: Page,
    launch_date: str,
    send_time_config: Dict,
) -> bool:
    """Set Entry Frequency to 'Once' and fill Start Time + On date.

    The Braze UI has:
      - Entry Frequency: a custom select dropdown (id='entry-frequency')
        with options: Once, Daily, Weekly, Monthly
      - After selecting 'Once': two inputs appear:
        - Start Time: text input, placeholder 'h:mm am' (12-hour format)
        - On date: text input, placeholder 'yyyy/mm/dd', aria-label='Select Date'
    """
    logger.info("Setting Entry Frequency to 'Once'...")

    # Click the Entry Frequency dropdown (custom React select with id='entry-frequency')
    entry_freq = page.locator("#entry-frequency")
    await entry_freq.scroll_into_view_if_needed()
    await entry_freq.click()
    await page.wait_for_timeout(1000)

    # Select "Once" from the dropdown options
    once_option = page.get_by_role("option", name="Once")
    if await once_option.count() == 0:
        once_option = page.get_by_text("Once", exact=True)
    await once_option.first.click()
    await page.wait_for_timeout(1500)
    logger.info("Selected 'Once' from Entry Frequency")

    # ---- Fill Start Time ----
    # Set for Intelligent Timing too, using its fallback time. Braze keeps a
    # default start time in the field (it is the campaign's entry time, not the
    # per-user send time), and leaving it untouched is how a send ends up
    # starting at an arbitrary hour like 02:00 instead of the intended morning.
    specific_time = send_time_config.get("time") or send_time_config.get("fallback_time")
    if specific_time:
        time_12h = _convert_24h_to_12h(specific_time)
        time_input = page.get_by_placeholder("h:mm am")
        if await time_input.count() == 0:
            time_input = page.locator("input[placeholder*='h:mm']")
        if await time_input.count() > 0:
            await time_input.scroll_into_view_if_needed()
            await time_input.click()
            await time_input.fill(time_12h)
            await page.wait_for_timeout(500)
            logger.info(f"Set Start Time: {time_12h}")
        else:
            logger.warning("Could not find Start Time input")

    # ---- Fill On date ----
    if launch_date:
        # Convert YYYY-MM-DD to yyyy/mm/dd
        date_formatted = launch_date.replace("-", "/")
        date_input = page.get_by_placeholder("yyyy/mm/dd")
        if await date_input.count() == 0:
            date_input = page.locator("input[aria-label='Select Date']")
        if await date_input.count() > 0:
            await date_input.scroll_into_view_if_needed()
            await date_input.click()
            await page.wait_for_timeout(300)
            # Select all existing text and replace with keyboard input
            # (fill() alone doesn't always register with React date pickers)
            await page.keyboard.press("Meta+A")
            await page.wait_for_timeout(200)
            await page.keyboard.type(date_formatted)
            await page.wait_for_timeout(500)
            # Close any date picker popup
            await date_input.press("Escape")
            await page.wait_for_timeout(500)
            # Verify the value was set
            actual_val = await date_input.input_value()
            if actual_val == date_formatted:
                logger.info(f"Set On date: {date_formatted}")
            else:
                logger.warning(f"On date mismatch: expected '{date_formatted}', got '{actual_val}' — retrying")
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

    return True


def _convert_24h_to_12h(time_24: str) -> str:
    """Convert 'HH:MM' 24-hour format to 'h:mm am/pm' 12-hour format.

    Examples: '16:00' -> '4:00 pm', '07:15' -> '7:15 am', '00:00' -> '12:00 am'
    """
    h, m = int(time_24.split(":")[0]), int(time_24.split(":")[1])
    period = "am" if h < 12 else "pm"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {period}"


# -------------------------------------------------------------------------
# 7c.  CONVERSION EVENTS
# -------------------------------------------------------------------------

# Built-in Braze conversion event types (available as direct dropdown options).
# Everything else is a custom event requiring "Performs Custom Event" + event name.
BUILTIN_CONVERSION_EVENTS = {
    "start session": "Starts Session",
    "starts session": "Starts Session",
    "makes purchase": "Makes Purchase",
    "makes a purchase": "Makes Purchase",
}


def _is_builtin_event(event_name: str) -> Tuple[bool, str]:
    """Check if an event name maps to a Braze built-in conversion event type.

    Returns (is_builtin, braze_ui_label).
    """
    normalized = event_name.strip().lower()
    braze_label = BUILTIN_CONVERSION_EVENTS.get(normalized)
    if braze_label:
        return True, braze_label
    return False, event_name


async def configure_conversions(page: Page, conversions: Dict) -> bool:
    """Configure 4 conversion events (A-D) with 3-day deadline.

    Braze UI uses React Select custom dropdowns (class ``bcl-select``) for
    the "Conversion event type" field.  Built-in types like "Starts Session"
    and "Makes Purchase" are direct options; everything else requires
    selecting "Performs Custom Event" and then filling the custom event name
    in a second React Select that appears.

    Args:
        page: Playwright page
        conversions: Dict with keys A, B, C, D each containing
                     {event: str, deadline_days: int}
    """
    if not conversions:
        logger.warning("No conversion events configured")
        return True

    logger.info("Configuring conversion events...")

    # Navigate to "Assign Conversions" step (step 4)
    conv_nav_selectors = [
        page.get_by_role("button", name="Assign Conversions"),
        page.get_by_role("button", name="Assign"),
        page.get_by_text("Assign Conversions", exact=True),
        page.locator("button:has-text('Assign')"),
    ]
    for selector in conv_nav_selectors:
        try:
            await selector.wait_for(state="visible", timeout=5000)
            await selector.click()
            await page.wait_for_timeout(2000)
            logger.info("Navigated to Assign Conversions step")
            break
        except Exception:
            continue

    # ------------------------------------------------------------------
    # Check whether all 4 slots are already filled (seed duplication path).
    # If they are, read the current event labels and compare to config.
    # Skip reconfiguration if they match; clear + readd if they differ.
    # ------------------------------------------------------------------
    add_btn = page.get_by_role("button", name="Add Conversion Event")
    all_slots_filled = False
    try:
        if await add_btn.count() > 0 and await add_btn.first.is_disabled():
            all_slots_filled = True
    except Exception:
        pass

    if all_slots_filled:
        # Read the currently selected event type labels from all 4 slots.
        # Braze renders each selected value in a .bcl-select__single-value span.
        current_labels = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.bcl-select__single-value'))
                .map(el => el.textContent.trim())
                .filter(t => t.length > 0);
        }""")

        # Build the expected label list in slot order (A-D).
        expected_labels = []
        for slot in ["A", "B", "C", "D"]:
            ev = conversions.get(slot, {})
            is_b, label = _is_builtin_event(ev.get("event", ""))
            expected_labels.append(label if is_b else "Performs Custom Event")

        logger.info(f"Conversions — current: {current_labels} | expected: {expected_labels}")

        if current_labels[:4] == expected_labels:
            logger.info("Conversion events already correct — skipping reconfiguration")
            return True

        # Mismatch — all 4 slots are pre-filled so we can't use "Add Conversion
        # Event". Instead, just change the type on each existing slot in-place.
        # _select_conversion_event_type selects by index so no add/remove needed.
        logger.info("Conversion events mismatch — reconfiguring existing slots in-place")

    # Configure each conversion event (A through D)
    for idx, slot in enumerate(["A", "B", "C", "D"]):
        event_config = conversions.get(slot)
        if not event_config:
            continue

        event_name = event_config.get("event", "")
        deadline = event_config.get("deadline_days", 3)
        is_builtin, braze_label = _is_builtin_event(event_name)

        if is_builtin:
            logger.info(f"Conversion {slot}: {braze_label} (built-in, {deadline}d)")
        else:
            logger.info(f"Conversion {slot}: Performs Custom Event → '{event_name}' ({deadline}d)")

        # For B, C, D: click "Add Conversion Event" to create the slot —
        # but skip this if all 4 slots are already present (seed path).
        if slot != "A" and not all_slots_filled:
            try:
                await add_btn.scroll_into_view_if_needed()
                await add_btn.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Added conversion event slot {slot}")
            except Exception as e:
                logger.warning(f"Could not add conversion slot {slot}: {e}")
                continue

        # ---- Select event type via React Select ----
        # Each conversion section has a "Conversion event type" label followed
        # by a React Select.  We find the Nth label and its sibling select.
        await _select_conversion_event_type(page, idx, slot, is_builtin, braze_label, event_name)

        # ---- Deadline is pre-set to 3 days by default; verify/set ----
        await _set_conversion_deadline(page, idx, slot, deadline)

    logger.info("Conversion events configured")
    return True


async def _select_conversion_event_type(
    page: Page,
    idx: int,
    slot: str,
    is_builtin: bool,
    braze_label: str,
    custom_event_name: str,
) -> bool:
    """Select conversion event type from a React Select dropdown.

    The Braze "Conversion event type" is a ``bcl-select`` (React Select)
    component.  Each conversion section has one.  We locate the correct
    section by finding the Nth ``Conversion event type`` label and then
    interacting with its React Select container.
    """
    # Find all "Conversion event type" labels on the page.
    # The idx-th one corresponds to our slot.
    type_labels = page.get_by_text("Conversion event type", exact=True)
    label_count = await type_labels.count()
    if idx >= label_count:
        logger.warning(f"Conversion {slot}: only {label_count} type labels found, need index {idx}")
        return False

    target_label = type_labels.nth(idx)
    await target_label.scroll_into_view_if_needed()

    # The React Select is a sibling of the label inside a shared container.
    # Navigate: label -> parent container -> find the bcl-select__control div
    # Strategy: find the React Select input (class bcl-select__input) that is
    # near/after the label.
    # All the conversion event type React Select inputs on the page:
    all_react_inputs = page.locator(".bcl-select__input input")
    # We need the one for "Conversion event type" (not "Apps and websites targeted"
    # or "Days"). Each conversion section has multiple React Selects.
    # The layout per section is: [event type select] [apps select] [days select]
    # So for section idx, the event type select input is at index idx*3
    # But let's use a more robust approach: find the select control that's a
    # descendant of the same parent as the label.

    # Robust: click the React Select control div that follows the target label
    # The label and the select are siblings inside a container div
    try:
        # Use the label to locate the parent, then find the React Select within it
        container = target_label.locator("xpath=ancestor::div[contains(@class, 'FieldLabel')]/..")
        select_control = container.locator(".bcl-select__control").first
        await select_control.scroll_into_view_if_needed()
        await select_control.click()
        await page.wait_for_timeout(1000)
        logger.debug(f"Conversion {slot}: opened event type dropdown via container")
    except Exception:
        # Fallback: click on the React Select input near the label
        try:
            # Each section has: event_type_select, apps_select, deadline_num, days_select
            # The event_type selects are at indices 0, 3, 6, 9 of all bcl-select controls
            all_controls = page.locator(".bcl-select__control")
            # Filter: find controls that currently show "Starts Session" or are in event type position
            # For section idx, try clicking the control right after the label
            target_control = all_controls.nth(idx * 3)
            await target_control.scroll_into_view_if_needed()
            await target_control.click()
            await page.wait_for_timeout(1000)
            logger.debug(f"Conversion {slot}: opened dropdown via index {idx * 3}")
        except Exception as e:
            logger.warning(f"Conversion {slot}: could not open event type dropdown: {e}")
            return False

    # Now the dropdown menu is open — select the correct option
    event_type_label = braze_label if is_builtin else "Performs Custom Event"

    # Type to search (React Select supports type-to-filter)
    try:
        focused_input = page.locator(".bcl-select__input input:focus, .bcl-select__input input[aria-expanded='true']").first
        if await focused_input.count() == 0:
            # Find the active/focused input
            focused_input = page.locator("input:focus").first
        await focused_input.fill(event_type_label[:15])  # Type partial to trigger search
        await page.wait_for_timeout(800)
    except Exception:
        logger.debug(f"Conversion {slot}: could not type in search, trying direct click")

    # Click the matching option from the dropdown
    try:
        option = page.locator(f".bcl-select__option:has-text('{event_type_label}')").first
        await option.wait_for(state="visible", timeout=5000)
        await option.click()
        await page.wait_for_timeout(1000)
        logger.info(f"Conversion {slot}: selected '{event_type_label}'")
    except Exception:
        # Fallback: try role-based option
        try:
            option = page.get_by_role("option", name=event_type_label)
            await option.first.click(timeout=5000)
            await page.wait_for_timeout(1000)
            logger.info(f"Conversion {slot}: selected '{event_type_label}' via role")
        except Exception as e:
            logger.warning(f"Conversion {slot}: could not select '{event_type_label}': {e}")
            # Press Escape to close any open dropdown
            await page.keyboard.press("Escape")
            return False

    # ---- If custom event, fill in the custom event name ----
    if not is_builtin:
        await _fill_custom_event_name(page, idx, slot, custom_event_name)

    return True


async def _fill_custom_event_name(page: Page, idx: int, slot: str, event_name: str) -> bool:
    """Fill the custom event name after 'Performs Custom Event' is selected.

    A new React Select appears for "Custom event name".  We find it within
    the same conversion section and type/select the event name.
    """
    logger.info(f"Conversion {slot}: entering custom event name '{event_name}'")
    await page.wait_for_timeout(1000)  # Wait for the new select to appear

    # The "Custom event name" React Select appears after selecting
    # "Performs Custom Event".  It's the next bcl-select in the section.
    # Find all custom event name labels
    custom_labels = page.get_by_text("Custom event name", exact=True)
    if await custom_labels.count() == 0:
        custom_labels = page.get_by_text("Custom event name", exact=False)

    custom_label_count = await custom_labels.count()
    if custom_label_count == 0:
        logger.warning(f"Conversion {slot}: no 'Custom event name' field found")
        return False

    # Use the last "Custom event name" label (the one for the most recently added event)
    target_label = custom_labels.last
    await target_label.scroll_into_view_if_needed()

    # Find and click the React Select near this label
    try:
        container = target_label.locator("xpath=ancestor::div[contains(@class, 'FieldLabel')]/..")
        select_control = container.locator(".bcl-select__control").first
        await select_control.click()
        await page.wait_for_timeout(500)
    except Exception:
        # Fallback: click the nearest bcl-select__control after the label
        try:
            select_control = target_label.locator("xpath=following::div[contains(@class, 'bcl-select__control')]").first
            await select_control.click()
            await page.wait_for_timeout(500)
        except Exception as e:
            logger.warning(f"Conversion {slot}: could not open custom event dropdown: {e}")
            return False

    # Type the event name to search
    try:
        focused = page.locator("input:focus").first
        await focused.fill(event_name)
        await page.wait_for_timeout(1500)  # Wait for autocomplete results
    except Exception:
        logger.warning(f"Conversion {slot}: could not type custom event name")
        return False

    # Select the matching result
    try:
        option = page.locator(f".bcl-select__option:has-text('{event_name}')").first
        await option.wait_for(state="visible", timeout=5000)
        await option.click()
        await page.wait_for_timeout(500)
        logger.info(f"Conversion {slot}: selected custom event '{event_name}'")
        return True
    except Exception:
        try:
            option = page.get_by_role("option", name=event_name)
            await option.first.click(timeout=5000)
            logger.info(f"Conversion {slot}: selected custom event '{event_name}' via role")
            return True
        except Exception:
            # If no exact match found, press Enter to accept the typed value
            try:
                await page.keyboard.press("Enter")
                logger.info(f"Conversion {slot}: pressed Enter for '{event_name}'")
                return True
            except Exception as e:
                logger.warning(f"Conversion {slot}: could not select custom event: {e}")
                return False


async def _set_conversion_deadline(page: Page, idx: int, slot: str, deadline_days: int) -> bool:
    """Set the conversion deadline for the idx-th conversion event.

    The deadline input is a number input (type='number') with a default of 3.
    Each conversion section has one.
    """
    # Find all deadline number inputs on the page
    deadline_inputs = page.locator("input[type='number'][placeholder*='value']")
    if await deadline_inputs.count() == 0:
        deadline_inputs = page.locator("input[type='number']")

    count = await deadline_inputs.count()
    if idx < count:
        try:
            target = deadline_inputs.nth(idx)
            await target.scroll_into_view_if_needed()
            current_val = await target.input_value()
            if current_val != str(deadline_days):
                await target.triple_click()  # Select existing value
                await target.fill(str(deadline_days))
            logger.info(f"Conversion {slot}: deadline = {deadline_days} days")
            return True
        except Exception as e:
            logger.debug(f"Conversion {slot}: deadline set error: {e}")

    # Default is already 3 days, which matches our requirement
    logger.info(f"Conversion {slot}: deadline assumed {deadline_days} days (default)")
    return True


# -------------------------------------------------------------------------
# 7d.  SAVE & SCREENSHOT
# -------------------------------------------------------------------------

async def save_as_draft(page: Page, dry_run: bool = True) -> bool:
    """Save the campaign as a draft."""
    if dry_run:
        logger.info("DRY RUN — would save as draft here")
        return True

    logger.info("Saving campaign as draft...")
    # Button label varies by Braze version: "Save Draft" or "Save as Draft"
    save_btn = None
    for btn_name in ("Save Draft", "Save as Draft"):
        candidate = page.get_by_role("button", name=btn_name, exact=True)
        try:
            await candidate.wait_for(state="visible", timeout=3000)
            save_btn = candidate
            break
        except Exception:
            continue
    if save_btn is None:
        raise Exception("Could not find Save Draft button")
    await save_btn.click()

    try:
        await page.get_by_text("Save completed").wait_for(state="visible", timeout=10000)
        logger.info("Campaign saved as draft")
    except PlaywrightTimeout:
        logger.warning("Save confirmation not detected, but may have succeeded")

    return True


async def capture_screenshot(page: Page, campaign_name: str) -> Optional[str]:
    """Take a full-page screenshot for verification."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^\w\-]', '_', campaign_name)[:50]
    path = Path(__file__).parent / f"screenshot_{safe_name}_{timestamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    logger.info(f"Screenshot saved: {path}")
    return str(path)


def get_campaign_url_from_page(page_url: str) -> Optional[str]:
    """Extract the Braze campaign URL from the current page URL."""
    # After saving, the URL typically contains the campaign ID
    if "/campaigns/" in page_url:
        return page_url
    return None


# =========================================================================
# 8.  ASANA WRITEBACK
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


# =========================================================================
# 9.  MAIN ORCHESTRATOR
# =========================================================================

async def build_single_campaign(
    task: Dict[str, Any],
    global_config: Dict[str, Any],
    dry_run: bool = True,
    auto_confirm: bool = False,
    headless: bool = True,
    skip_asana_writeback: bool = False,
    skip_qa: bool = False,
    skip_comment: bool = False,
) -> Dict[str, Any]:
    """Build a single PT campaign in Braze from an Asana task.

    Returns a result dict with status, errors, screenshot path, etc.
    skip_comment: when True, suppress the internal Asana comment (caller posts its own).
    """
    result = {
        "success": False,
        "task_gid": task["gid"],
        "task_name": task["name"],
        "brand": task["brand"],
        "dry_run": dry_run,
        "errors": [],
        "screenshot": None,
        "braze_url": None,
    }

    try:
        # Build the full config
        config = build_campaign_config(task, None, global_config)

        # Missing-subject flag — confirmed asymmetry 2026-09-05: the Klaviyo PT
        # builder (create_klaviyo_email.py) has always posted a "⚠️ subject
        # line is missing" Asana comment when it can't find one anywhere; this
        # builder only ever logged a warning (parse_asana_task(), never
        # surfaced to a human) and shipped the campaign with a blank subject.
        # Folded into the same `warnings` list the HTML-QA check below
        # populates, so it rides the same @-mention comment as those.
        result["warnings"] = []
        if not config.get("subject"):
            result["warnings"].append(
                "Subject line is missing — please add it before scheduling."
            )

        # Print summary
        print("\n" + "=" * 60)
        print("CAMPAIGN BUILD SUMMARY")
        print("=" * 60)
        print(f"  Task:        {config['campaign_name']}")
        print(f"  Brand:       {config['brand_code']}", end="")
        if config.get("hav_variant"):
            print(f" ({config['hav_variant']})", end="")
        print()
        print(f"  Workspace:   {config['workspace']}")
        print(f"  Subject:     {config['subject'] or '(empty — needs manual entry)'}")
        print(f"  Preheader:   {config['preheader'] or '(none)'}")
        print(f"  Body:        {len(config['body_text'])} chars")
        _bk = f"{config['brand_code']}_{config['hav_variant']}" if config.get("hav_variant") else config["brand_code"]
        _sn = (global_config.get("pt_seed_campaigns") or {}).get(_bk)
        print(f"  Editor:      {'BEE/DnD (seed: ' + _sn + ')' if _sn else 'HTML code editor (no seed)'}")
        print(f"  Audience:    {config['audience'].get('type')} — {config['audience'].get('segment')}")
        if config["audience"].get("filters"):
            for f in config["audience"]["filters"]:
                print(f"    + filter: {f.get('name')} ({f.get('op', 'and')})")
        print(f"  Send time:   {config['send_time']['type']}", end="")
        if config["send_time"].get("time"):
            print(f" @ {config['send_time']['time']} local", end="")
        print()
        print(f"  Launch date: {config['launch_date']}")
        # Sender info
        if config.get("from_name") or config.get("from_email"):
            print(f"  From Name:   {config.get('from_name', '(default)')}")
            print(f"  From Email:  {config.get('from_email', '(default)')}")
            print(f"  Reply-To:    {config.get('reply_to', '(default)')}")
        else:
            print(f"  Sender info: (workspace default)")
        utm = config.get("utm_templates", "all")
        if isinstance(utm, list):
            print(f"  UTM templates: {', '.join(utm)}")
        else:
            print(f"  UTM templates: select all available")
        print(f"  Conversions:")
        for slot in ["A", "B", "C", "D"]:
            ev = config["conversions"].get(slot, {})
            ev_name = ev.get("event", "N/A")
            is_builtin, label = _is_builtin_event(ev_name)
            if is_builtin:
                print(f"    {slot}: {label} (built-in, {ev.get('deadline_days', 3)}d)")
            else:
                print(f"    {slot}: Performs Custom Event → '{ev_name}' ({ev.get('deadline_days', 3)}d)")
        print("=" * 60)

        # --- HTML QA checks ---
        if skip_qa:
            print("\n  (HTML QA checks skipped via --skip-qa)")
        else:
            try:
                from validate_html import validate_html as _validate_html

                qa_errors, qa_warnings = _validate_html(
                    html_content=config["html_body"],
                    brand=config["brand_code"],
                    channel="email",
                    subscription_group="Marketing",
                )

                if qa_warnings:
                    print(f"\n  QA WARNINGS ({len(qa_warnings)}):")
                    for w in qa_warnings:
                        print(f"    WARN: {w}")
                    # Extend, don't overwrite — the missing-subject warning (if
                    # any) was already added to this list above.
                    result["warnings"].extend(qa_warnings)

                if qa_errors:
                    print(f"\n  QA ERRORS ({len(qa_errors)}):")
                    for e in qa_errors:
                        print(f"    ERROR: {e}")
                    print(
                        "\n  HTML QA failed — fix the errors above before building."
                    )
                    result["errors"] = qa_errors
                    return result
            except ImportError:
                logger.debug("validate_html not available, skipping HTML QA")

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

                # Select workspace
                brand_for_workspace = config["brand_code"]
                if brand_for_workspace == "TRADE":
                    brand_for_workspace = "ID"
                await select_workspace(page, brand_for_workspace)

                # Navigate to campaigns — pass brand to use workspace-specific URL (prevents drift)
                await navigate_to_campaigns(page, brand=brand_for_workspace)

                # Determine brand key (e.g. "HAV_PC", "BUR") for seed lookup
                hav_variant = config.get("hav_variant")
                _brand_key = (
                    f"{config['brand_code']}_{hav_variant}"
                    if hav_variant
                    else config["brand_code"]
                )
                _seed_name = (global_config.get("pt_seed_campaigns") or {}).get(_brand_key)

                if _seed_name:
                    # --- BEE/DnD path: duplicate seed campaign ---
                    logger.info(f"PT seed campaign found for {_brand_key}: '{_seed_name}'")
                    from build_designed_campaign import (
                        search_and_duplicate_email_campaign as _dup_campaign,
                    )
                    duped = await _dup_campaign(page, _seed_name, brand=brand_for_workspace)
                    if not duped:
                        raise RuntimeError(
                            f"Failed to duplicate PT seed campaign '{_seed_name}' for {_brand_key}"
                        )
                    await set_campaign_name(page, config["campaign_name"])

                    # Step 1: Compose — sender info, subject, preheader, BEE body injection
                    await configure_pt_body_in_bee(
                        page,
                        config["html_body"],
                        config["subject"],
                        config["preheader"],
                        utm_templates=config.get("utm_templates", "all"),
                        from_name=config.get("from_name"),
                        from_email=config.get("from_email"),
                        reply_to=config.get("reply_to"),
                    )
                else:
                    # --- HTML editor path (legacy / no seed configured) ---
                    logger.info(
                        f"No PT seed campaign for {_brand_key} — using HTML code editor"
                    )
                    await start_email_campaign(page)
                    await set_campaign_name(page, config["campaign_name"])

                    # Step 1: Compose — email content + UTM link templates + sender info
                    await configure_email_content(
                        page,
                        config["subject"],
                        config["preheader"],
                        config["html_body"],
                        utm_templates=config.get("utm_templates", "all"),
                        from_name=config.get("from_name"),
                        from_email=config.get("from_email"),
                        reply_to=config.get("reply_to"),
                    )

                # Step 2: Schedule Delivery
                await configure_delivery(page, config["send_time"], config["launch_date"])

                # Step 3: Target Audiences
                await configure_target_audience(
                    page, config["audience"], clear_existing=bool(_seed_name)
                )

                # Step 4: Assign Conversions
                await configure_conversions(page, config["conversions"])

                # Screenshot before saving
                screenshot_path = await capture_screenshot(page, config["campaign_name"])
                result["screenshot"] = screenshot_path

                # Save as draft
                await save_as_draft(page, dry_run=False)

                # Get campaign URL
                braze_url = get_campaign_url_from_page(page.url)
                result["braze_url"] = braze_url

                result["success"] = True
                logger.info("Campaign built successfully")

            except Exception as e:
                logger.error(f"Campaign build failed: {e}")
                result["errors"].append(str(e))

                # Error screenshot — always try, log failures
                try:
                    err_path = Path(__file__).parent / f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    await page.screenshot(path=str(err_path), full_page=True)
                    result["error_screenshot"] = str(err_path)
                    logger.info(f"Error screenshot saved: {err_path}")
                except Exception as ss_err:
                    logger.warning(f"Could not save error screenshot: {ss_err}")

            finally:
                await browser.close()

        # Write back to Asana (unless skipped)
        if result["success"] and result.get("braze_url"):
            if skip_asana_writeback:
                logger.info("Skipping Asana writeback (--skip-asana)")
            else:
                if update_asana_with_braze_link(task["gid"], result["braze_url"]):
                    logger.info("Asana task updated with Braze link")
                else:
                    logger.warning("Failed to update Asana task with Braze link")

                # Post @-mention comment (suppressed when caller posts its own)
                if not skip_comment:
                    try:
                        from orchestrate_sms import post_campaign_created_comment
                        orchestrator_config = global_config.get("orchestrator", {})
                        build_warnings = result.get("warnings", [])
                        warning_suffix = ""
                        if build_warnings:
                            warning_suffix = "\n\n⚠ Links to review:\n" + "\n".join(
                                f"  • {w}" for w in build_warnings
                            )
                        patched_orchestrator = {
                            **orchestrator_config,
                            "comment_template": (
                                "this email campaign has been automatically created in {platform} "
                                "and is ready for review and scheduling.\n\n"
                                "Campaign link: {braze_url}"
                                + warning_suffix
                            ),
                        }
                        post_campaign_created_comment(
                            task_gid=task["gid"],
                            braze_url=result["braze_url"],
                            brand_code=task["brand"],
                            orchestrator_config=patched_orchestrator,
                            assignee_gid=task.get("assignee_gid"),
                        )
                        logger.info("Asana comment posted with @-mentions")
                    except Exception as e:
                        logger.warning(f"Could not post Asana comment: {e}")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        result["errors"].append(str(e))

    return result


# =========================================================================
# 10.  CLI ENTRY POINT
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Build plain text email campaigns in Braze from Asana tasks."
    )
    parser.add_argument(
        "--task", type=str,
        help="Asana task GID to process (fetches full task details)",
    )
    parser.add_argument(
        "--brand", type=str,
        help="Filter to one brand (HAV, CZ, ID, BUR, STF, TI)",
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
        "--no-headless", action="store_false", dest="headless",
        help="Show browser window (default: headless)",
    )
    parser.set_defaults(headless=True)
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--skip-asana", action="store_true",
        help="Skip writing Braze campaign link back to Asana task",
    )
    parser.add_argument(
        "--skip-qa", action="store_true",
        help="Skip HTML QA checks (use for testing only)",
    )
    parser.add_argument(
        "--link-text", action="append", nargs=2, metavar=("TEXT", "URL"),
        help="Link a text phrase to a URL in the email body (repeatable). "
             'Example: --link-text "Presidents Day Sale" "https://burrow.com"',
    )
    parser.add_argument(
        "--disclaimer", type=str, default="",
        help="Sale disclaimer / legal text for the footer disclaimer row. "
             "Only shown for templates with a disclaimer row.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    dry_run = not args.no_dry_run

    # Load brand config
    global_config = load_brand_config()

    # Determine which tasks to process
    tasks_to_process = []

    if args.task:
        # Fetch a single task by GID
        logger.info(f"Fetching Asana task {args.task}...")
        raw_task = fetch_task_by_gid(args.task)
        if not raw_task:
            print(f"Error: Could not fetch task {args.task}")
            sys.exit(1)
        parsed = parse_asana_task(raw_task)
        if not parsed:
            print(f"Error: Task {args.task} could not be parsed (missing brand/channel?)")
            sys.exit(1)
        tasks_to_process = [parsed]
    else:
        # Fetch all "Ready to Code" PT tasks
        brand_filter = args.brand.upper() if args.brand else None
        logger.info("Scanning Asana for 'Ready to Code' PT tasks...")
        tasks_to_process = fetch_ready_to_code_pt_tasks(brand_filter)

    # Inject text-link mappings into each task
    if args.link_text:
        text_links = [{"text": t, "url": u} for t, u in args.link_text]
        for task in tasks_to_process:
            task["text_links"] = text_links

    # Inject disclaimer text into each task
    if args.disclaimer:
        for task in tasks_to_process:
            task["disclaimer"] = args.disclaimer

    if not tasks_to_process:
        print("No PT tasks found to process.")
        return

    print(f"\nFound {len(tasks_to_process)} PT task(s) to process.\n")

    # Process each task
    results = []
    for i, task in enumerate(tasks_to_process, 1):
        print(f"\n[{i}/{len(tasks_to_process)}] {task['brand']}: {task['name']}")

        if task.get("braze_campaign_id"):
            print(f"  Skipping — already has Braze campaign ID: {task['braze_campaign_id']}")
            continue

        result = asyncio.run(
            build_single_campaign(
                task=task,
                global_config=global_config,
                dry_run=dry_run,
                auto_confirm=args.yes,
                headless=args.headless,
                skip_asana_writeback=args.skip_asana,
                skip_qa=args.skip_qa,
            )
        )
        results.append(result)

    # Summary
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
    print("=" * 60)


if __name__ == "__main__":
    main()
