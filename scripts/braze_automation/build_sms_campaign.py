#!/usr/bin/env python3
"""
Build SMS campaigns in Braze from Asana tasks.

End-to-end automation using a *duplicate-based* workflow:
  1. Fetches SMS tasks from Asana (Channel = SMS, Status = "Ready to Code")
  2. Parses SMS copy — prefers the "Copy" custom field; falls back to
     task description (notes field) when the Copy field is empty
  3. Appends brand-specific UTM parameters to links
  4. Opens Braze dashboard via Playwright
  5. Finds the most recent SMS campaign for the same brand and duplicates it
  6. Edits: campaign name, SMS body, delivery date/time
     (audience and conversion events carry over from the duplicate)
  7. Verifies audience segment and removes extra filters if needed
  8. Saves as draft
  9. Writes Braze campaign link back to Asana

Falls back to creating from scratch if no existing SMS campaign is found
for the brand.

Usage:
    # Preview what would be built (no browser launched)
    uv run python scripts/braze_automation/build_sms_campaign.py \\
      --task 1213104067064266 --dry-run

    # Build all "Ready to Code" SMS tasks for a brand
    uv run python scripts/braze_automation/build_sms_campaign.py \\
      --brand BUR --dry-run

    # Actually build in Braze
    uv run python scripts/braze_automation/build_sms_campaign.py \\
      --task 1213104067064266 --no-dry-run

    # Build without confirmation prompts
    uv run python scripts/braze_automation/build_sms_campaign.py \\
      --task 1213104067064266 --no-dry-run --yes
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
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs, urljoin

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
)
from element_utils import click_button, fill_field, wait_for_element

# Reuse Playwright helpers from build_pt_campaign for audience, delivery, conversions
from build_pt_campaign import (
    configure_target_audience,
    configure_delivery,
    configure_conversions,
    resolve_send_time,
    parse_time_string,
    save_as_draft,
    capture_screenshot,
    get_campaign_url_from_page,
    navigate_to_campaigns,
    _is_builtin_event,
    _convert_24h_to_12h,
)

# Reuse Playwright helpers from build_push_campaign for duplicate-based flow
from build_push_campaign import (
    navigate_to_campaigns_list,
    _set_status_filter,
    _enter_search_query,
    _duplicate_row,
    wait_for_campaign_editor,
)

from utils.campaign_name import generate_campaign_name

# Brand code mapping: YAML brand code → campaign naming convention code
# Some brands use different codes in YAML (BUR) vs campaign names (BW)
_BRAND_TO_NAME_CODE = {
    "BUR": "BW",
    "STF": "SF",
    "HAV": "HAV",
    "CZ": "CZ",
    "ID": "ID",
    "TI": "TI",
    "TRADE": "TRADE",
}

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

# Asana custom field GIDs (shared with create_braze_campaigns.py / build_pt_campaign.py)
FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_SUBJECT_LINE = "1207522425689914"
FIELD_PRE_HEADER = "1207522425689916"
FIELD_SEGMENT = "1211927654349290"
FIELD_AUDIENCE = "1207522425689896"
FIELD_SEND_TIME = "1212524397761931"
FIELD_BRAZE_LINK = "1210710306792280"
FIELD_BRAZE_CAMPAIGN_ID = "1210955430688137"
FIELD_CATEGORY = "1207522425689888"
FIELD_COPY = "1209982215611013"

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
    "TE": "1213380147938608",
}
BRAND_GID_TO_CODE = {v: k for k, v in BRAND_OPTIONS.items()}

CHANNEL_OPTIONS = {
    "email": "1207562370794989",
    "sms": "1207562370794990",
    "push": "1207562370794991",
}
CHANNEL_GID_TO_NAME = {v: k for k, v in CHANNEL_OPTIONS.items()}

# Instruction-line patterns to filter out when extracting SMS copy
_INSTRUCTION_PATTERNS = [
    r"^pick\s*up\b",
    r"^use\s+copy\b",
    r"^reference\b",
    r"^see\s+email\b",
    r"^note:",
    # "FYI:" / "FYI," / "FYI -" is an editorial aside to the builder. A bare
    # "FYI ..." is not: real SMS copy opens with it ("FYI your nearest Interior
    # Define Studio is ready...") and the bare \b form silently swallowed that
    # whole message, leaving the task with "No SMS copy found in task notes".
    # Delimiter-anchored like its ^note: neighbour.
    r"^fyi\s*[:,–—-]",
    r"^pull\s+copy\b",
    r"create\s+an?\s+sms",
    r"use\s+for\s+the\s+email",
    r"use\s+(?:the\s+)?email\s+copy",
    r"adapt\s+(?:the\s+)?email",
    r"same\s+copy\s+as",
    r"^filter\s+out\b",
    r"^exclude\b",
    # Campaign name lines (e.g. "P_SMS_2026_03_13_CZ_Bedding") — reference only, not copy
    r"^[A-Z]+_(?:EM|SMS|PUSH)_\d{4}_\d{2}_\d{2}_",
    r"\bholdout\b",
    r"^frequency\s+test",
    # Landing page / metadata lines
    r"^lp:\s*https?://",
    # SMS Copy section headers and char count lines
    r"^sms\s+copy\b",
    r"^\(~?\d+\s*chars?\)",
    # Context / editorial notes
    r"^mirrors\s+the\b",
    r"sends\s+day\s+before",
]


# =========================================================================
# 1.  CONFIGURATION LOADING
# =========================================================================

def load_brand_config() -> Dict[str, Any]:
    """Load brand_config.yaml."""
    config_path = PROJECT_ROOT / "data" / "brand_config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _brand_link_paths_from_yaml(yaml_path: Path) -> list[dict]:
    """Build a link_paths list from a brand links YAML (e.g. stf_links.yaml).

    Each entry in the yaml with a ``keywords`` field becomes one link_paths
    entry.  Entries without keywords (e.g. Homepage with a catch-all keyword
    in ``categories``) are included as-is.
    """
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    entries = []
    for section in data.values():
        if not isinstance(section, list):
            continue
        for item in section:
            keywords = item.get("keywords")
            if not keywords:
                continue
            parsed = urlparse(item["url"])
            entries.append({"keywords": keywords, "path": parsed.path})
    return entries


def get_sms_config(brand_code: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Get SMS-specific config for a brand from brand_config.yaml.

    Returns the entry from sms_config.<brand_code>.  For brands that have a
    dedicated links YAML (currently STF, BUR, CZ), the link_paths are loaded
    from that file instead of brand_config.yaml so both SMS and email
    briefing share one source of truth.
    Raises ValueError if no SMS config exists for the brand.
    """
    sms_configs = config.get("sms_config", {})
    entry = sms_configs.get(brand_code)
    if not entry:
        raise ValueError(
            f"No SMS config for brand '{brand_code}'. "
            f"Available: {sorted(sms_configs.keys())}"
        )
    entry = dict(entry)  # shallow copy so we don't mutate the cached config

    # Override link_paths from a brand-specific YAML when one exists.
    brand_yaml_map = {
        "STF": PROJECT_ROOT / "data" / "stf_links.yaml",
        "BUR": PROJECT_ROOT / "data" / "bur_links.yaml",
        "CZ": PROJECT_ROOT / "data" / "cz_links.yaml",
    }
    yaml_path = brand_yaml_map.get(brand_code)
    if yaml_path and yaml_path.exists():
        entry["link_paths"] = _brand_link_paths_from_yaml(yaml_path)

    return entry


def get_brand_entry(brand_code: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Get the email/general config entry for a brand (for conversion events, workspace, etc.)."""
    brands = config.get("brands", {})
    entry = brands.get(brand_code)
    if not entry:
        raise ValueError(f"No config entry for brand '{brand_code}'")
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


def fetch_ready_to_code_sms_tasks(brand_filter: Optional[str] = None) -> List[Dict]:
    """Fetch tasks with 'Ready to Code' status and Channel = SMS."""
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
        f"custom_fields.{FIELD_CHANNEL}.value": CHANNEL_OPTIONS["sms"],
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
        parsed = parse_asana_task(task)
        if parsed:
            results.append(parsed)
    return results


def _resolve_segment_type(raw: str) -> str:
    """Map Asana Segment field value to config key.

    Mirrors the logic in build_pt_campaign.py for consistency.
    """
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


def parse_asana_task(task: Dict) -> Optional[Dict[str, Any]]:
    """Parse a raw Asana task into a structured SMS campaign record."""
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

    # Channel — must be SMS
    channel_gid = _get_enum_value_gid(task, FIELD_CHANNEL)
    channel = CHANNEL_GID_TO_NAME.get(channel_gid) if channel_gid else None
    if channel != "sms":
        return None

    # Send time (free text, e.g. "3pm", "3:00 PM", "15:00")
    send_time_raw = _get_text_value(task, FIELD_SEND_TIME) or ""

    # Category
    category = _get_enum_value_name(task, FIELD_CATEGORY) or ""

    # Segment (e.g. "Full File", "Engaged", "Geo")
    segment_raw = _get_enum_value_name(task, FIELD_SEGMENT) or ""

    # Existing Braze campaign ID
    braze_campaign_id = _get_text_value(task, FIELD_BRAZE_CAMPAIGN_ID)

    # Existing Braze link (written by automation after a successful build)
    braze_link = _get_text_value(task, FIELD_BRAZE_LINK)

    # Copy custom field (SMS body text — preferred over task notes/description)
    copy_field = _get_text_value(task, FIELD_COPY) or ""

    # Assignee
    assignee_raw = task.get("assignee") or {}
    assignee_gid = assignee_raw.get("gid")
    assignee_name = assignee_raw.get("name", "")

    # Extract the LP URL from html_notes (standard 5-field brief) or plain notes.
    # Stored so build_campaign_config can pass it directly to extract_sms_copy,
    # guaranteeing the exact brief URL is used instead of keyword-resolved guesses.
    lp_url = _extract_lp_from_task(notes.strip(), html_notes)

    return {
        "gid": task_gid,
        "name": task_name,
        "due_on": due_on,
        "brand": brand_code,
        "channel": "sms",
        "notes": notes.strip(),
        "html_notes": html_notes,
        "copy_field": copy_field.strip(),
        "lp_url": lp_url,
        "send_time_raw": send_time_raw,
        "category": category,
        "segment_raw": segment_raw,
        "braze_campaign_id": braze_campaign_id,
        "braze_link": braze_link,
        "assignee_gid": assignee_gid,
        "assignee_name": assignee_name,
    }


# =========================================================================
# 4.  CAMPAIGN NAME GENERATION
# =========================================================================

def generate_sms_campaign_name(task_name: str, brand_code: str, due_on: str) -> str:
    """Generate a proper campaign name from an Asana task name.

    Transforms Asana task names like "Pet Friendly SMS" into campaign names
    like "P_SMS_2026_02_10_BW_Pet_Friendly" following the naming convention.

    Args:
        task_name: Raw Asana task name (e.g. "Pet Friendly SMS").
        brand_code: Internal brand code (e.g. "BUR").
        due_on: Due date as YYYY-MM-DD string.

    Returns:
        Properly formatted campaign name.
    """
    # Get the naming convention brand code (BUR → BW, STF → SF, etc.)
    name_brand = _BRAND_TO_NAME_CODE.get(brand_code, brand_code)

    # Clean the task name to extract the description
    description = task_name.strip()

    # Strip channel words anywhere in the description — redundant since P_SMS_ already encodes channel
    description = re.sub(r'\b(?:SMS|Push|Email)\b\s*[:\-]?\s*', '', description, flags=re.IGNORECASE).strip()

    # Strip leading brand name if present (e.g. "Burrow Pet Friendly" → "Pet Friendly")
    brand_names = {
        "BUR": ["Burrow", "BUR", "BW"],
        "CZ": ["The Citizenry", "Citizenry", "CZ"],
        "ID": ["Interior Define", "ID"],
        "STF": ["St. Frank", "St Frank", "STF", "SF"],
        "TI": ["The Inside", "TI"],
        "HAV": ["Havenly", "HAV"],
        "TRADE": ["Trade", "TRADE"],
    }
    for name_variant in brand_names.get(brand_code, []):
        pattern = rf'^{re.escape(name_variant)}\s*[:\-]?\s*'
        description = re.sub(pattern, '', description, flags=re.IGNORECASE)

    # Strip em dashes and their surrounding spaces
    description = description.replace(" — ", " ").replace("—", " ")

    # Replace ampersands with "And" (campaign names should not contain &)
    description = description.replace(" & ", " And ").replace("&", " And ")

    # Clean up extra spaces
    description = " ".join(description.split())

    if not description:
        description = "SMS Campaign"

    try:
        campaign_name = generate_campaign_name(
            campaign_type="P",
            channel="SMS",
            send_date=due_on,
            brand=name_brand,
            description=description,
        )
    except ValueError as e:
        # Fallback: build manually if the utility fails
        logger.warning(f"generate_campaign_name failed: {e}, building manually")
        date_str = due_on.replace("-", "_")
        desc_parts = description.replace(" ", "_").split("_")
        desc_formatted = "_".join(
            w[0].upper() + w[1:] if len(w) > 1 else w.upper()
            for w in desc_parts if w
        )
        campaign_name = f"P_SMS_{date_str}_{name_brand}_{desc_formatted}"

    return campaign_name


# =========================================================================
# 5.  SMS COPY EXTRACTION
# =========================================================================

def _is_instruction_line(line: str) -> bool:
    """Return True if the line looks like an editorial instruction, not SMS copy."""
    stripped = line.strip().lower()
    if not stripped:
        return True  # blank lines are not copy
    # A line containing a URL or LINK placeholder is always copy, regardless of
    # how it starts — e.g. "FYI the sale is live. Shop now: LINK" is copy.
    if re.search(r'https?://|\bLINK\b|\[link\]', line.strip(), re.IGNORECASE):
        return False
    for pattern in _INSTRUCTION_PATTERNS:
        if re.search(pattern, stripped):
            return True
    return False


def _extract_lp_from_task(notes: str, html_notes: str = "") -> Optional[str]:
    """Extract the LP URL from the Asana task description.

    Checks html_notes first (standard 5-field brief ``<strong>LP:</strong> URL``
    pattern), then falls back to a plain ``LP: URL`` prefix line in notes.
    Returns the first URL found, or None.
    """
    # Check html_notes — standard 5-field brief format uses <li><strong>LP:</strong> URL</li>
    if html_notes:
        # Strip all HTML tags to get plain text, then scan for LP: URL
        plain = re.sub(r"<[^>]+>", " ", html_notes)
        for line in plain.splitlines():
            m = re.match(r"\s*LP\s*:\s*(https?://\S+)", line, re.IGNORECASE)
            if m:
                return m.group(1).rstrip(".,;)")

    # Check plain notes for an LP: prefix line — stop at [AI Brief] so AI-generated
    # URLs in the brief section never override the keyword-resolved landing page.
    if notes:
        for line in notes.splitlines():
            if line.strip() == "[AI Brief]":
                break
            m = re.match(r"^LP\s*:\s*(https?://\S+)", line.strip(), re.IGNORECASE)
            if m:
                return m.group(1).rstrip(".,;)")

    return None


# Shared with the Klaviyo SMS builder (scripts/create_klaviyo_sms.py) — see
# scripts/utils/sms_grammar.py, the single source of truth for both.
from utils.sms_grammar import SMS_URL_PATTERN, SMS_URL_STRIP_RE, check_copy_grammar  # noqa: E402,F401


def extract_sms_copy(
    notes: str,
    brand: str,
    sms_config: Dict[str, Any],
    explicit_lp: Optional[str] = None,
    task_title: Optional[str] = None,
) -> Tuple[str, bool]:
    """Extract SMS copy from Asana task notes.

    The task description may contain a mix of actual SMS copy and editorial
    instructions (e.g. "Pick up copy we use for the email to create an SMS").

    Strategy:
      1. Split into lines, filter out instruction lines.
      2. Among remaining lines, prefer the line containing a URL or ending
         with LINK.
      3. If no line has a URL or LINK, join all non-instruction lines as the
         copy and append a smart-resolved link with UTMs.
      4. Replace bare ``LINK`` placeholder with smart-resolved URL + UTMs.
      5. Append UTMs to existing URLs that don't already have them.

    Args:
        notes: Raw task description text.
        brand: Brand code (BUR, CZ, ID, etc.).
        sms_config: SMS config entry from brand_config.yaml.
        task_title: Optional Asana task name, passed through to
            ``resolve_landing_page`` as a fallback/tiebreak signal only.

    Returns:
        Tuple of (processed_copy_with_utms, link_was_auto_appended).
        ``link_was_auto_appended`` is True when the copy didn't have its own
        URL — we inferred one from content and appended it. The user should
        verify the URL is correct before launching.
    """
    if not notes:
        return "", True

    # Extract explicit LP URL from raw notes before filtering — stop at [AI Brief]
    # so AI-generated URLs in the brief section never override keyword resolution.
    explicit_lp_url: Optional[str] = None
    for raw_line in notes.strip().splitlines():
        if raw_line.strip() == "[AI Brief]":
            break
        lp_match = re.match(r'^lp:\s*(https?://\S+)', raw_line.strip(), re.IGNORECASE)
        if lp_match:
            explicit_lp_url = lp_match.group(1).rstrip('.,;)')
            break

    # Only process the first paragraph — content after the first blank line is
    # copywriter notes or metadata, not part of the intended SMS copy.
    first_para_lines: List[str] = []
    for line in notes.strip().splitlines():
        if not line.strip():
            if first_para_lines:
                break  # end of first paragraph
        else:
            first_para_lines.append(line)

    candidate_lines: List[str] = []
    for line in first_para_lines:
        stripped = line.strip()
        if _is_instruction_line(stripped):
            continue
        candidate_lines.append(stripped)

    if not candidate_lines:
        logger.warning("No SMS copy found in task notes (all lines were instructions)")
        return "", True

    # Prefer lines that contain a URL or a LINK placeholder (bare or bracketed)
    url_lines = [l for l in candidate_lines if re.search(r'https?://', l)]
    # Collect all link-placeholder lines (both [link] and bare LINK) in document order.
    # DO NOT prefer one format over the other — copywriters use bare LINK, AI drafts often
    # use [link]. The first occurrence in the description is always the preferred copy.
    link_placeholder_lines = [
        l for l in candidate_lines
        if re.search(r'\[link\]', l, re.IGNORECASE) or l.strip().upper().endswith("LINK")
    ]

    if url_lines:
        # Copy already has a URL — validate then append UTMs
        raw_copy = url_lines[0]
        for found_url in re.findall(r'https?://[^\s,;)]+', raw_copy):
            validate_url(found_url)
        processed = _append_utms_to_urls(raw_copy, brand, sms_config)
        return processed, False
    elif link_placeholder_lines:
        # Copy has a LINK placeholder (bare or [link]) — replace with a real URL.
        # Priority: explicit_lp arg (from task html_notes/notes LP field) >
        #           explicit_lp_url (LP: prefix line found inside the notes text) >
        #           smart keyword resolution (last resort — always validate).
        raw_copy = link_placeholder_lines[0]
        copy = re.sub(r'\s*\[?link\]?\s*$', '', raw_copy, flags=re.IGNORECASE).rstrip()
        lp_url_valid = True
        if explicit_lp:
            landing_url = explicit_lp
            logger.info(f"Using LP from Asana task brief: {landing_url}")
            lp_url_valid = validate_url(landing_url)
            if not lp_url_valid:
                logger.error(
                    "LP URL from Asana task brief is broken or redirects to homepage: %s  "
                    "Update the Asana task with the correct URL before launching.",
                    landing_url,
                )
        elif explicit_lp_url:
            landing_url = explicit_lp_url
            logger.info(f"Using explicit LP URL from notes: {landing_url}")
            lp_url_valid = validate_url(landing_url)
            if not lp_url_valid:
                logger.error(
                    "Explicit LP URL from notes is broken or redirects to homepage: %s  "
                    "Update the Asana task with the correct URL before launching.",
                    landing_url,
                )
        else:
            landing_url = resolve_landing_page(copy, brand, sms_config, task_title=task_title)
            lp_url_valid = validate_url(landing_url)
            if not lp_url_valid:
                logger.error(
                    "Smart-resolved URL is broken or redirects to homepage: %s  "
                    "Add an explicit LP field to the Asana task before launching.",
                    landing_url,
                )
        utm_url = build_sms_url(landing_url, brand, sms_config)
        # link_was_auto_appended signals "verify before launching" in the summary.
        # Always True here (we replaced a placeholder), and also True when LP validation failed.
        link_needs_verify = True
        # If copy already ends with ':', append URL directly (no extra period)
        if copy.endswith(":"):
            return f"{copy} {utm_url}", link_needs_verify
        # Use period before link when copy already contains a colon (e.g. brand prefix "Brand: copy")
        if ":" in copy:
            copy = copy.rstrip(".")
            return f"{copy}. {utm_url}", link_needs_verify
        else:
            copy = copy.rstrip(".")
            return f"{copy}: {utm_url}", link_needs_verify
    else:
        # No URL or LINK in the copy — the message text has no link signal.
        # Priority: explicit_lp from task brief > keyword resolution.
        raw_copy = " ".join(candidate_lines)
        if explicit_lp:
            landing_url = explicit_lp
            logger.info(f"Using LP from Asana task brief (no LINK placeholder): {landing_url}")
            lp_url_valid = validate_url(landing_url)
            if not lp_url_valid:
                logger.error(
                    "LP URL from Asana task brief is broken or redirects to homepage: %s  "
                    "Update the Asana task with the correct URL before launching.",
                    landing_url,
                )
        elif explicit_lp_url:
            landing_url = explicit_lp_url
            logger.info(f"Using explicit LP URL from notes (no LINK placeholder): {landing_url}")
            validate_url(landing_url)
        else:
            landing_url = resolve_landing_page(raw_copy, brand, sms_config, task_title=task_title)
            lp_url_valid = validate_url(landing_url)
            if not lp_url_valid:
                logger.error(
                    "Smart-resolved URL is broken or redirects to homepage: %s  "
                    "Add an explicit LP field to the Asana task before launching.",
                    landing_url,
                )
        utm_url = build_sms_url(landing_url, brand, sms_config)
        # Use colon before link only if copy doesn't already contain one
        if raw_copy.endswith(":"):
            return f"{raw_copy} {utm_url}", True
        elif ":" in raw_copy:
            raw_copy = raw_copy.rstrip(".")
            return f"{raw_copy}. {utm_url}", True
        else:
            raw_copy = raw_copy.rstrip(".")
            return f"{raw_copy}: {utm_url}", True


# =========================================================================
# 5.  SMART LINK RESOLUTION
# =========================================================================

def _score_link_paths(text: str, link_paths: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    """Score every link_paths entry by how many of its keywords appear in text.

    Longer keyword matches are more specific and score higher (summed, not maxed).
    """
    text_lower = text.lower()
    scored = []
    for entry in link_paths:
        score = 0
        for kw in entry.get("keywords", []):
            if kw.lower() in text_lower:
                score += len(kw)
        scored.append((score, entry))
    return scored


def resolve_landing_page(
    copy_text: str,
    brand: str,
    sms_config: Dict[str, Any],
    task_title: Optional[str] = None,
) -> str:
    """Infer the best landing page URL from SMS copy content.

    Uses keyword matching against the brand's ``link_paths`` config to find
    a relevant collection/category page instead of defaulting to the homepage.

    The task title (e.g. "SMS: Back in Stock") is a secondary signal only —
    it never outranks a real keyword match in the copy text itself, since the
    copy is more specific and task titles get stripped of most identifying
    words per the Task Naming rules. The title is only consulted when (1) the
    copy matches nothing at all, or (2) multiple entries tie on the copy
    score, to break the tie.

    Args:
        copy_text: The SMS copy text (without LINK placeholder).
        brand: Brand code.
        sms_config: SMS config entry (must contain ``base_url``,
            may contain ``link_paths``).
        task_title: Optional Asana task name — fallback/tiebreak signal only.

    Returns:
        Full URL (e.g. ``https://burrow.com/collections/pet-friendly``).
    """
    base_url = sms_config["base_url"].rstrip("/")
    link_paths = sms_config.get("link_paths", [])

    if not link_paths:
        logger.info(f"No link_paths configured for {brand}, using homepage")
        return base_url

    copy_scores = _score_link_paths(copy_text, link_paths)
    best_score = max((s for s, _ in copy_scores), default=0)
    candidates = [e for s, e in copy_scores if s == best_score and s > 0]
    source = "copy"

    if best_score == 0 and task_title:
        # Copy has no keyword signal at all — fall back to the task title entirely.
        title_scores = _score_link_paths(task_title, link_paths)
        best_score = max((s for s, _ in title_scores), default=0)
        candidates = [e for s, e in title_scores if s == best_score and s > 0]
        source = "title, no copy match"
    elif len(candidates) > 1 and task_title:
        # Copy scored a tie between multiple entries — use the title to break it,
        # but only among the already-tied candidates (title can't promote a
        # non-winning copy entry over the copy's own top score).
        tied_ids = {id(e) for e in candidates}
        title_scores = _score_link_paths(task_title, link_paths)
        title_among_tied = [(s, e) for s, e in title_scores if id(e) in tied_ids]
        title_best = max((s for s, _ in title_among_tied), default=0)
        if title_best > 0:
            candidates = [e for s, e in title_among_tied if s == title_best]
            source = "copy tie, broken by title"

    if not candidates:
        logger.info(f"No keyword match for link resolution, using homepage: {base_url}")
        return base_url

    winner = candidates[0]
    best_url = winner.get("url")  # full URL override (takes precedence over path)
    best_path = winner.get("path", "/")

    if best_url:
        logger.info(f"Smart link resolved (full URL): {best_url} (score={best_score}, source={source})")
        return best_url

    if best_path and best_path != "/":
        resolved = f"{base_url}{best_path}"
        logger.info(f"Smart link resolved: {resolved} (score={best_score}, source={source})")
        return resolved

    # Fallback to homepage
    logger.info(f"No keyword match for link resolution, using homepage: {base_url}")
    return base_url


# =========================================================================
# 5b. UTM BUILDER
# =========================================================================

# Shared with the Klaviyo SMS builder (scripts/create_klaviyo_sms.py) — see
# scripts/utils/url_validation.py, the single source of truth for both. Wrapped
# here only to keep routing messages through this module's `logger` (same
# format as before) rather than the shared module's plain-print default.
from utils.url_validation import validate_url as _shared_validate_url  # noqa: E402


def validate_url(url: str) -> bool:
    return _shared_validate_url(url, on_error=logger.error, on_warning=logger.warning)


def build_sms_url(base_url: str, brand: str, sms_config: Dict[str, Any]) -> str:
    """Build a URL with brand-specific SMS UTM parameters.

    Args:
        base_url: The base URL (e.g. https://burrow.com/collections/rugs).
        brand: Brand code.
        sms_config: SMS config entry from brand_config.yaml.

    Returns:
        URL with UTM parameters appended.
    """
    parsed = urlparse(base_url)

    # Build UTM params
    utm_params = {
        "utm_source": sms_config["utm_source"],
        "utm_medium": sms_config.get("utm_medium", "sms"),
        "utm_campaign": "{{campaign.${name}}}",
    }
    if sms_config.get("include_userid", False):
        utm_params["userid"] = "{{${user_id}}}"
    if sms_config.get("include_bzt", False):
        utm_params["bzt"] = "{{${email_address} | base64_encode | url_param_escape}}"
    # Brand-specific extra params (e.g. bzt, em, fn, ln for BUR)
    for key, val in sms_config.get("extra_params", {}).items():
        utm_params[key] = val

    # Preserve existing query params and add UTMs
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    # Flatten single-value lists from parse_qs
    flat_params = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
    flat_params.update(utm_params)

    # Rebuild the URL
    new_query = "&".join(f"{k}={v}" for k, v in flat_params.items())
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))
    return new_url


def _append_utms_to_urls(copy: str, brand: str, sms_config: Dict[str, Any]) -> str:
    """Find URLs in SMS copy and append UTM parameters to each.

    Only processes URLs that don't already have utm_source.
    """
    url_pattern = re.compile(r'(https?://[^\s,;)]+)')

    def _add_utms(match: re.Match) -> str:
        url = match.group(1)
        # Skip only if UTMs are fully present — including bzt when required.
        # A URL with utm_source but missing bzt still needs build_sms_url.
        if "utm_source" in url:
            bzt_required = sms_config.get("include_bzt", False)
            if not bzt_required or "bzt=" in url:
                return url
        return build_sms_url(url, brand, sms_config)

    return url_pattern.sub(_add_utms, copy)


# =========================================================================
# 6.  SEND TIME RESOLUTION (SMS-specific)
# =========================================================================

def resolve_sms_send_time(
    task: Dict[str, Any],
    sms_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Determine send time for an SMS campaign.

    Priority:
      1. Asana "Send time" field (if explicitly set)
      2. SMS default from config (3:00 PM for all brands)

    Returns a dict compatible with configure_delivery():
      - type: "specific"
      - time: "HH:MM"
      - local_time: True
      - is_second_send: False
    """
    send_time_raw = task.get("send_time_raw", "")

    # Priority 1: Asana "Send time" field
    parsed = parse_time_string(send_time_raw)
    if parsed:
        logger.info(f"SMS send time from Asana field: {parsed}")
        return {
            "type": "specific",
            "time": parsed,
            "local_time": True,
            "is_second_send": False,
        }

    # Priority 2: SMS default from config
    default_time = sms_config.get("send_time", "15:00")
    logger.info(f"SMS send time using config default: {default_time}")
    return {
        "type": "specific",
        "time": default_time,
        "local_time": True,
        "is_second_send": False,
    }


# =========================================================================
# 7.  CAMPAIGN CONFIG BUILDER
# =========================================================================

def build_campaign_config(
    task: Dict[str, Any],
    global_config: Dict[str, Any],
    landing_url_override: Optional[str] = None,
    copy_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a complete SMS campaign configuration from Asana task + brand config.

    Args:
        task: Parsed Asana task dict.
        global_config: Full brand_config.yaml contents.
        landing_url_override: If provided, use this URL instead of the
            smart-resolved landing page (UTMs are still appended).
        copy_override: If provided, use this exact text as the SMS body
            instead of parsing it from the Asana task notes. UTMs are still
            appended if no URL is present in the text.

    Returns a dict with everything needed to build the campaign in Braze.
    """
    brand_code = task["brand"]

    # Get SMS-specific config
    sms_cfg = get_sms_config(brand_code, global_config)

    # Get general brand entry (for conversion events, workspace)
    brand_entry = get_brand_entry(brand_code, global_config)

    # LP URL extracted from the task brief (html_notes LP: field or plain notes LP: line).
    # Passed as explicit_lp so extract_sms_copy uses the exact brief URL instead of
    # falling back to keyword-based smart resolution.
    task_lp = task.get("lp_url")
    if task_lp:
        logger.info(f"LP from Asana task brief: {task_lp}")

    # Extract SMS copy: --copy CLI flag > "Copy" custom field > task notes
    if copy_override:
        sms_body, needs_url = extract_sms_copy(copy_override, brand_code, sms_cfg, explicit_lp=task_lp, task_title=task["name"])
        logger.info("SMS copy sourced from --copy CLI override")
    else:
        copy_source = task.get("copy_field", "").strip()
        if copy_source:
            sms_body, needs_url = extract_sms_copy(copy_source, brand_code, sms_cfg, explicit_lp=task_lp, task_title=task["name"])
            logger.info("SMS copy sourced from Asana 'Copy' custom field")
        else:
            sms_body, needs_url = extract_sms_copy(task["notes"], brand_code, sms_cfg, explicit_lp=task_lp, task_title=task["name"])
            logger.info("SMS copy sourced from task description (notes field)")

    # Grammar check on the final copy text (before URL for cleaner context)
    copy_for_grammar = SMS_URL_STRIP_RE.sub(' ', sms_body).strip()
    grammar_warnings = check_copy_grammar(copy_for_grammar)
    if grammar_warnings:
        logger.warning("Grammar issues detected in SMS copy: %s", grammar_warnings)

    # Override the auto-resolved landing URL if --landing-url was provided.
    # This replaces the entire URL (including UTMs) in the SMS body.
    if landing_url_override and needs_url:
        override_with_utms = build_sms_url(landing_url_override, brand_code, sms_cfg)
        # The body was built as "<copy> <auto_url>"; replace the auto URL
        # with the override URL.
        url_pattern = re.compile(r'https?://[^\s]+$')
        sms_body = url_pattern.sub(override_with_utms, sms_body)
        logger.info(f"Landing URL overridden to: {landing_url_override}")

    # Audience — use SMS segment, with optional filter from Asana Segment field.
    # Most SMS campaigns use just the standard SMS segment. When the Asana
    # Segment field is "Geo", we keep the SMS segment as the base but add
    # the geo filter from the email brand config on top.
    segment_type = _resolve_segment_type(task.get("segment_raw", ""))
    if segment_type == "geo":
        geo_audience = brand_entry.get("audiences", {}).get("geo", {})
        geo_filters = geo_audience.get("filters", [])
        if geo_filters:
            audience = {
                "type": "segment_with_filter",
                "segment": sms_cfg["segment"],
                "filters": geo_filters,
            }
            logger.info(
                f"SMS audience: {sms_cfg['segment']} + geo filters "
                f"{[f.get('name') for f in geo_filters]}"
            )
        else:
            logger.warning(
                f"Segment type is 'geo' but no geo audience config for {brand_code}; "
                f"using plain SMS segment"
            )
            audience = {
                "type": "segment",
                "segment": sms_cfg["segment"],
            }
    else:
        audience = {
            "type": "segment",
            "segment": sms_cfg["segment"],
        }

    # Conversion events (same as email)
    conversions = brand_entry.get("conversion_events", {})

    # Send time
    send_time = resolve_sms_send_time(task, sms_cfg)

    # Campaign name — generate from Asana task name following convention
    # P_SMS_YYYY_MM_DD_BRAND_Description (e.g. P_SMS_2026_02_10_BW_Pet_Friendly)
    campaign_name = generate_sms_campaign_name(
        task_name=task["name"],
        brand_code=brand_code,
        due_on=task["due_on"],
    )
    logger.info(f"Generated campaign name: {campaign_name} (from '{task['name']}')")

    return {
        "campaign_name": campaign_name,
        "brand_code": brand_code,
        "workspace": brand_entry.get("workspace"),
        "sms_body": sms_body,
        "needs_url_resolution": needs_url,
        "grammar_warnings": grammar_warnings,
        "audience": audience,
        "_segment_type": segment_type,
        "send_time": send_time,
        "launch_date": task["due_on"],
        "conversions": conversions,
        "asana_gid": task["gid"],
    }


# =========================================================================
# 8.  PLAYWRIGHT — SMS CAMPAIGN AUTOMATION
# =========================================================================

async def start_sms_campaign(page: Page) -> bool:
    """Click Create Campaign -> SMS in the Braze dashboard."""
    logger.info("Starting SMS campaign creation...")
    create_btn = page.get_by_role("button", name="Create campaign")
    await create_btn.wait_for(state="visible", timeout=10000)
    await create_btn.click()
    await page.wait_for_timeout(500)

    sms_btn = page.get_by_role("button", name="SMS")
    await sms_btn.wait_for(state="visible", timeout=5000)
    await sms_btn.click()
    await page.wait_for_timeout(2000)
    logger.info("Selected SMS campaign type")
    return True


async def set_campaign_name(page: Page, name: str) -> bool:
    """Set the campaign name field."""
    logger.info(f"Setting campaign name: {name}")
    name_field = page.get_by_role("textbox", name="Enter Campaign Name")
    await name_field.fill(name, timeout=5000)
    return True


async def _scoped_sms_monaco_op(
    page: Page, container_selector: str, body: Optional[str] = None
) -> Dict[str, Any]:
    """Read or set the SMS body on the Monaco editor scoped to the compose modal.

    Finds the modal container via ``container_selector``, then the Monaco editor
    instance whose DOM node lives inside that container — so we never target a
    different Monaco editor elsewhere on the page. When ``body`` is provided the
    value is set; the editor's current value is always returned so the caller can
    verify the write actually landed.

    The compose modal can render more than one Monaco-backed editor at once (e.g.
    the Message body plus an Assets/Media caption or link-preview field). Taking
    the first ``.monaco-editor`` node in DOM order — the previous behavior — can
    silently target the wrong one; this is the same class of bug documented in
    CLAUDE.md for the CZ designed-email builder ("Monaco editor must be scoped to
    the portal in edit mode"), and is the leading suspect for an ID SMS send
    (2026-07) where the Message field was correct but a stale/mismatched draft
    ended up in Assets/Media. When multiple editors are found, we prefer the one
    whose nearest labeled ancestor text references the message body and does not
    reference Assets/Media, and fall back to the first node (old behavior)
    whenever that signal is absent or ambiguous — so the common single-editor
    case is completely unchanged.

    Returns ``{"found": bool, "value": str|None}``.
    """
    import json as _json

    sel_json = _json.dumps(container_selector)
    body_json = _json.dumps(body if body is not None else "")
    do_set = "true" if body is not None else "false"
    return await page.evaluate(
        f"""
        (() => {{
            const sel = {sel_json};
            const doSet = {do_set};
            const content = {body_json};
            const containers = Array.from(document.querySelectorAll(sel));
            const container = containers.find(e => e.querySelector('.monaco-editor'));
            if (!container) return {{ found: false, value: null }};

            const monacoNodes = Array.from(container.querySelectorAll('.monaco-editor'));
            let bestNode = monacoNodes[0] || null;
            if (monacoNodes.length > 1) {{
                // Walk a few ancestors up from each editor node looking for label
                // text that confirms (or rules out) that this is the message body
                // editor. +1 = looks like the message editor, -1 = looks like an
                // Assets/Media editor, 0 = no signal either way.
                const scoreNode = (node) => {{
                    let el = node;
                    for (let hops = 0; hops < 6 && el; hops++, el = el.parentElement) {{
                        const text = (el.innerText || '').toLowerCase();
                        if (!text) continue;
                        const mentionsMedia = text.includes('media') || text.includes('asset');
                        const mentionsMessage = text.includes('message') || text.includes('sms body') || text.includes('body copy');
                        if (mentionsMedia && !mentionsMessage) return -1;
                        if (mentionsMessage && !mentionsMedia) return 1;
                    }}
                    return 0;
                }};
                const scored = monacoNodes.map(n => ({{ n, s: scoreNode(n) }}));
                const positive = scored.find(x => x.s > 0);
                if (positive) {{
                    bestNode = positive.n;
                }} else {{
                    const hasNegative = scored.some(x => x.s < 0);
                    const firstNonNegative = scored.find(x => x.s >= 0);
                    if (hasNegative && firstNonNegative) bestNode = firstNonNegative.n;
                }}
            }}
            if (!bestNode) return {{ found: false, value: null }};

            const editors = (window.monaco && window.monaco.editor
                && window.monaco.editor.getEditors)
                ? window.monaco.editor.getEditors() : [];
            const target = editors.find(ed => {{
                const node = ed.getDomNode && ed.getDomNode();
                return node && (bestNode.contains(node) || node.contains(bestNode) || node === bestNode);
            }});
            if (!target) return {{ found: false, value: null }};
            if (doSet) target.setValue(content);
            return {{ found: true, value: target.getValue() }};
        }})()
        """
    )


async def configure_sms_content(page: Page, body: str) -> bool:
    """Fill the SMS body text in the campaign compose step.

    The Braze SMS compose step uses a Monaco code editor (same component as
    the email HTML editor). After opening the editor, the body is written into
    the editor scoped to the compose modal, then read back and verified. If the
    write doesn't land it is retried once.

    Returns True if the body was written AND verified to match ``body``.
    Returns False if it could not be verified — the caller does NOT abort in
    that case; it proceeds with the build and surfaces a copy warning on the
    task, since a false negative should never block an otherwise-good campaign.
    """
    logger.info("Configuring SMS content...")
    import json as _json

    # --- Step 1: Open the SMS editor ---
    # Click the variant card / edit area to open the compose modal.
    # IMPORTANT: We must confirm the modal is open before attempting Monaco
    # injection. If we proceed without the modal open, we may target a Monaco
    # instance elsewhere on the page (e.g. the campaign name field) and
    # silently overwrite the wrong editor — leaving the SMS body unchanged
    # from the duplicated campaign.
    #
    # The two fallback selectors below (a bare "Edit" button, a generic
    # variant-card match) are loose by design — loose enough that they could
    # also match an "Edit" control belonging to a different editable section
    # (e.g. Assets/Media) that happens to expose the same affordance. Before
    # clicking a fallback match we check its own visible text and its closest
    # card-like ancestor's text, and skip any candidate that reads as
    # Assets/Media rather than Message — this is the leading suspect for an ID
    # SMS send (2026-07) where a stale/mismatched draft ended up in
    # Assets/Media while Message held the correct copy. The exact "Edit
    # message" accessible-name match is trusted as-is since it isn't a guess,
    # so the common working path is unaffected.
    async def _reads_as_media_not_message(locator) -> bool:
        try:
            own_text = (await locator.inner_text(timeout=500)).strip().lower()
        except Exception:
            own_text = ""
        texts = [own_text]
        try:
            ancestor = locator.locator(
                "xpath=ancestor::*[contains(@class,'variant') or contains(@class,'card') "
                "or contains(@class,'panel') or self::section][1]"
            )
            texts.append((await ancestor.inner_text(timeout=500)).strip().lower())
        except Exception:
            pass
        combined = " ".join(texts)
        mentions_media = "media" in combined or "asset" in combined
        mentions_message = "message" in combined or "sms" in combined or "body" in combined
        return mentions_media and not mentions_message

    edit_selectors = [
        (page.get_by_role("button", name="Edit message"), False),
        (page.locator("button:has-text('Edit')"), True),
        (page.locator(".message-variant, .variant-card, [class*='variant']"), True),
    ]

    editor_opened = False
    for selector, guarded in edit_selectors:
        try:
            count = await selector.count()
        except Exception:
            continue
        for i in range(min(count, 5)):
            candidate = selector.nth(i)
            try:
                if not await candidate.is_visible():
                    continue
                if guarded and await _reads_as_media_not_message(candidate):
                    logger.info(
                        "Skipping an Edit control that reads as Assets/Media, not Message"
                    )
                    continue
                await candidate.click()
                await page.wait_for_timeout(2000)
                editor_opened = True
                logger.info("Opened SMS editor")
                break
            except Exception:
                continue
        if editor_opened:
            break

    if not editor_opened:
        logger.error(
            "Could not open SMS editor modal — cannot safely inject body text. "
            "Aborting to avoid overwriting the wrong Monaco editor."
        )
        return False

    # --- Step 2: Locate the SMS compose modal and write into its Monaco editor ---
    # We MUST scope the write to the editor inside the compose modal. Writing to
    # an unscoped ".monaco-editor" or the "last" editor can silently target a
    # different Monaco instance (e.g. a hidden email HTML editor or the campaign
    # name field), leaving the SMS body unchanged from the duplicated source
    # campaign. Every write is followed by a read-back; if the body cannot be
    # verified we return False so build_single_campaign aborts instead of saving
    # stale copy. (This is exactly the failure that shipped a source campaign's
    # copy to a live send — see CLAUDE.md on Monaco/React scoping.)
    container_selectors = [
        "[role='dialog']",
        "[class*='modal']",
        "[class*='drawer']",
        "[class*='slide-over']",
        "[class*='compose']",
    ]
    modal_selector = None
    for sel in container_selectors:
        if await page.locator(f"{sel} .monaco-editor").count() > 0:
            modal_selector = sel
            logger.info(f"SMS compose modal scoped via: {sel!r}")
            break

    body_json = _json.dumps(body)

    def _norm(s: Optional[str]) -> str:
        return re.sub(r"\s+", " ", s or "").strip()

    body_filled = False

    if modal_selector is not None:
        monaco_editor = page.locator(f"{modal_selector} .monaco-editor").first

        # Write the body, read it back, and retry once if it did not land.
        # Two write methods per round:
        #   1. Clipboard paste — fires the DOM input events Braze's React-controlled
        #      Monaco listens to, so the value persists into React state (a bare
        #      setValue can update the Monaco model but leave React state — and thus
        #      the saved body — unchanged).
        #   2. Scoped Monaco setValue as a backstop.
        MAX_WRITE_ROUNDS = 2
        for attempt in range(1, MAX_WRITE_ROUNDS + 1):
            # Method 1 — clipboard paste into the scoped editor
            try:
                await page.evaluate(f"navigator.clipboard.writeText({body_json})")
                await monaco_editor.click()
                await page.wait_for_timeout(200)
                await page.keyboard.press("Meta+a")
                await page.wait_for_timeout(100)
                await page.keyboard.press("Meta+v")
                await page.wait_for_timeout(600)
                read = await _scoped_sms_monaco_op(page, modal_selector)
                if read.get("found") and _norm(read.get("value")) == _norm(body):
                    body_filled = True
                    logger.info(f"SMS body set via clipboard paste and verified (attempt {attempt})")
                    break
            except Exception as e:
                logger.debug(f"Clipboard paste attempt {attempt} failed: {e}")

            # Method 2 — scoped Monaco setValue, then read back to confirm
            res = await _scoped_sms_monaco_op(page, modal_selector, body)
            if res.get("found") and _norm(res.get("value")) == _norm(body):
                body_filled = True
                logger.info(f"SMS body set via scoped Monaco setValue and verified (attempt {attempt})")
                break
            if not res.get("found"):
                logger.error(
                    "Could not locate the Monaco editor inside the SMS compose "
                    "modal — retrying will not help."
                )
                break
            if attempt < MAX_WRITE_ROUNDS:
                logger.warning(f"SMS body write not verified on attempt {attempt} — retrying...")
    else:
        logger.warning(
            "No Monaco editor found inside a recognized SMS compose modal "
            "container — will try the textarea fallback."
        )

    # --- Step 3: Fallback to textarea / contenteditable (verified) ---
    if not body_filled:
        textarea_selectors = [
            page.locator("textarea[placeholder*='message']"),
            page.locator("textarea[aria-label*='message']"),
            page.get_by_role("textbox", name=re.compile(r"message|sms|body", re.IGNORECASE)),
        ]
        for selector in textarea_selectors:
            try:
                if await selector.count() > 0 and await selector.first.is_visible():
                    await selector.first.fill(body, timeout=5000)
                    await page.wait_for_timeout(300)
                    try:
                        actual = await selector.first.input_value()
                    except Exception:
                        actual = None
                    if actual is None or _norm(actual) == _norm(body):
                        body_filled = True
                        logger.info("SMS body filled via textarea")
                        break
            except Exception:
                continue

    # --- Step 4: Close the editor modal (always, so the build can proceed) ---
    try:
        done_btn = page.get_by_role("button", name="Done")
        if await done_btn.count() > 0 and await done_btn.first.is_visible():
            await done_btn.first.click()
            await page.wait_for_timeout(1000)
            logger.info("Closed SMS editor")
    except Exception:
        pass  # No Done button visible — editor may be inline

    # Return the verification status. We do NOT abort on failure: the caller
    # proceeds with the build (writes the Braze link, flips the task to Ready
    # for QA) and surfaces a copy warning for a human to reconcile.
    if body_filled:
        logger.info("SMS content configured and verified")
    else:
        logger.warning(
            "SMS body could not be verified after retries — proceeding with the "
            "build; the campaign may still hold the duplicated source campaign's "
            "copy. A copy warning will be posted to the task."
        )
    return body_filled


# =========================================================================
# 8b. PLAYWRIGHT — DUPLICATE-BASED SMS CAMPAIGN AUTOMATION
# =========================================================================

async def _find_sms_row(page: Page, brand_name_code: str) -> Optional[Any]:
    """Scan the current campaign list rows for an SMS campaign matching the brand.

    Args:
        page: Playwright page (should be on the campaigns list).
        brand_name_code: Brand code as used in campaign names (e.g. "BW", "CZ").

    Returns:
        The matching Playwright row locator, or None.
    """
    rows = page.locator("tr, [role='row']")
    row_count = await rows.count()
    logger.info(f"Found {row_count} rows in the campaign list")

    for i in range(row_count):
        row = rows.nth(i)
        row_text = (await row.text_content() or "").strip()

        # Must be an SMS row (Braze shows "SMS" as channel type)
        if "SMS" not in row_text:
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

        logger.debug(f"Row {i} SMS campaign name: {name}")

        # Check the NAME for the correct brand code at a token boundary.
        # Campaign names follow: P_SMS_YYYY_MM_DD_BRAND_...
        if brand_name_code:
            if f"_{brand_name_code}_" not in name:
                logger.debug(f"  Skipping — does not match brand {brand_name_code}")
                continue

        logger.info(f"Found {brand_name_code} SMS campaign to duplicate: {name}")
        return row

    return None


async def search_and_duplicate_sms_campaign(
    page: Page, search_term: str, brand_name_code: str
) -> bool:
    """Search for an SMS campaign matching the brand and duplicate it.

    Tries Status: Active first, then Idle, then Stopped (sent One-Time
    campaigns move to Idle after their send completes).

    Args:
        page: Playwright page (should be on the campaigns list).
        search_term: Search query to narrow the list (e.g. "P_SMS").
        brand_name_code: Brand code as used in campaign names (e.g. "BW").

    Returns:
        True if a campaign was successfully duplicated.
    """
    for status in ("Active", "Idle", "Stopped"):
        logger.info(
            f"Searching for {brand_name_code} SMS campaign to duplicate "
            f"(Status: {status})..."
        )

        await _set_status_filter(page, status)
        await _enter_search_query(page, search_term)

        # Debug screenshot
        try:
            debug_path = (
                Path(__file__).parent
                / f"debug_sms_search_{status.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
            await page.screenshot(path=str(debug_path), full_page=True)
            logger.info(f"SMS search results screenshot ({status}): {debug_path}")
        except Exception:
            pass

        target_row = await _find_sms_row(page, brand_name_code)

        if target_row:
            return await _duplicate_row(page, target_row)

        logger.info(
            f"No {brand_name_code} SMS campaign found under Status: {status}"
        )

    logger.warning(
        f"No SMS campaign with _{brand_name_code}_ in its name "
        f"found under Active, Idle, or Stopped status"
    )
    return False


async def duplicate_sms_campaign(page: Page, brand_code: str) -> bool:
    """Find the most recent SMS campaign for a brand and duplicate it.

    Navigates to the campaigns list, searches for recent SMS campaigns
    matching the brand, picks the first (most recent) match, and
    duplicates it via the row action menu.

    This ensures we always duplicate from a recent, known-good SMS
    campaign with the correct audience, conversion events, and delivery
    settings.

    Args:
        page: Playwright page.
        brand_code: Internal brand code (e.g. "BUR", "CZ").

    Returns:
        True if a campaign was successfully duplicated.
    """
    brand_name_code = _BRAND_TO_NAME_CODE.get(brand_code, brand_code)
    logger.info(
        f"Finding most recent {brand_code} ({brand_name_code}) SMS campaign to duplicate..."
    )

    # Navigate to campaigns list — use workspace-specific URL to prevent drift
    await navigate_to_campaigns(page, brand=brand_code)

    # Search for SMS campaigns matching the brand.
    # Use "P_SMS" as search term to surface all SMS campaigns, then
    # let the row-level filtering (in search_and_duplicate_sms_campaign)
    # pick the first row with the correct brand code.
    search_term = "P_SMS"

    return await search_and_duplicate_sms_campaign(page, search_term, brand_name_code)


# =========================================================================
# 8c. PLAYWRIGHT — AUDIENCE VERIFICATION & CLEANUP (DUPLICATE FLOW)
# =========================================================================

async def _has_audience_filters(page: Page) -> bool:
    """Check whether the Target Audiences step has additional filters beyond the base segment."""
    filter_indicators = [
        page.locator("text='Segment Membership'"),
        page.locator("[class*='filter-row']"),
        page.locator("[class*='filterRow']"),
        page.locator("[class*='filter-group']"),
        page.locator("[class*='FilterRow']"),
    ]

    for indicator in filter_indicators:
        try:
            if await indicator.count() > 0 and await indicator.first.is_visible():
                logger.info("Found audience filter indicator")
                return True
        except Exception:
            continue

    return False


async def _remove_audience_filters(
    page: Page,
    preserve_segment: Optional[str] = None,
) -> int:
    """Remove additional audience filters from the Target Audiences step,
    preserving any filter that matches the expected SMS segment.

    Braze shows filter entries inside a "Filter group" container under
    "Additional Filters".  Each filter row has a grip handle on the left
    and remove/trash icons that appear on hover.

    The source campaign may use the SMS segment as a Segment Membership
    filter (instead of the base segment dropdown).  When ``preserve_segment``
    is provided, any Segment Membership filter whose row text contains that
    segment name will be **kept** — only other filters are removed.

    Strategy:
      1. Find "Segment Membership" pill entries.
      2. For each, check if the row text contains ``preserve_segment`` — skip if so.
      3. Hover over the row to reveal hidden action buttons.
      4. Click the revealed remove/trash button.

    Returns the number of filters removed.
    """
    removed = 0
    preserved = 0

    # Check if there are any "Segment Membership" filter entries
    filter_text = page.locator("text='Segment Membership'")
    filter_count = 0
    try:
        filter_count = await filter_text.count()
    except Exception:
        pass

    if filter_count == 0:
        logger.info("No additional audience filters found to remove")
        return 0

    logger.info(f"Found {filter_count} audience filter entry/entries to evaluate")

    # Remove from last to first to avoid index shifting issues.
    for idx in range(filter_count - 1, -1, -1):
        try:
            entry = filter_text.nth(idx)

            # --- Check if this filter matches the segment we want to KEEP ---
            if preserve_segment:
                # Walk up to the filter row to get the full text (includes
                # "Segment Membership | Included | <segment name>")
                row_text = ""
                for level in range(1, 8):
                    try:
                        ancestor = entry.locator(f"xpath=ancestor::*[{level}]")
                        row_text = (await ancestor.text_content() or "").strip()
                        # Stop when we have enough text to check
                        if preserve_segment in row_text:
                            break
                    except Exception:
                        continue

                if preserve_segment in row_text:
                    preserved += 1
                    logger.info(
                        f"Preserving Segment Membership filter: "
                        f"contains expected segment '{preserve_segment}'"
                    )
                    continue  # Skip this filter — it's the audience we want

            # --- Strategy 1: Hover over the filter row to reveal hidden buttons ---
            # Walk up the DOM to find the filter row container, then hover it.
            for ancestor_level in range(1, 8):
                try:
                    container = entry.locator(f"xpath=ancestor::*[{ancestor_level}]")
                    # Hover to reveal hidden action buttons
                    await container.hover()
                    await page.wait_for_timeout(500)

                    # Look for remove/trash buttons that appeared after hover
                    remove_btns = container.locator(
                        "button[aria-label*='remove' i], "
                        "button[aria-label*='delete' i], "
                        "button[aria-label*='trash' i], "
                        "button[class*='remove'], "
                        "button[class*='delete'], "
                        "button:has(svg[class*='trash']), "
                        "button:has(svg[class*='close']), "
                        "button:has(svg[class*='remove']), "
                        "button:has(svg[class*='delete'])"
                    )
                    if await remove_btns.count() > 0 and await remove_btns.first.is_visible():
                        await remove_btns.first.click()
                        await page.wait_for_timeout(1000)
                        removed += 1
                        logger.info(f"Removed audience filter #{removed} (hover-reveal at level {ancestor_level})")
                        break
                except Exception:
                    continue

            if removed > idx:
                continue  # Successfully removed, move to next

            # --- Strategy 2: Try the grip handle area ---
            # The grip (⠿ icon) is typically a sibling of the filter pills.
            # Hovering it may reveal a trash icon next to it.
            try:
                grip = entry.locator("xpath=ancestor::*[2]").locator(
                    "svg, [class*='grip'], [class*='drag'], [class*='handle']"
                ).first
                if await grip.count() > 0:
                    await grip.hover()
                    await page.wait_for_timeout(500)
                    # Now look for trash buttons near the grip
                    grip_parent = grip.locator("xpath=..")
                    trash = grip_parent.locator(
                        "button, [role='button']"
                    ).filter(has=page.locator("svg"))
                    if await trash.count() > 0 and await trash.first.is_visible():
                        await trash.first.click()
                        await page.wait_for_timeout(1000)
                        removed += 1
                        logger.info(f"Removed audience filter #{removed} (grip hover)")
                        continue
            except Exception:
                pass

            # --- Strategy 3: Try the filter group header edit/delete ---
            try:
                group_header = page.locator("text='Filter group'").first
                if await group_header.count() > 0:
                    await group_header.hover()
                    await page.wait_for_timeout(500)
                    header_parent = group_header.locator("xpath=ancestor::*[2]")
                    header_btns = header_parent.locator(
                        "button, [role='button']"
                    ).filter(has=page.locator("svg"))
                    btn_count = await header_btns.count()
                    # Try each button — one might be delete/remove
                    for btn_idx in range(btn_count):
                        btn = header_btns.nth(btn_idx)
                        aria = await btn.get_attribute("aria-label") or ""
                        if any(kw in aria.lower() for kw in ("delete", "remove", "trash")):
                            await btn.click()
                            await page.wait_for_timeout(1000)
                            removed += 1
                            logger.info(f"Removed filter group (header button)")
                            break
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Failed to remove filter at index {idx}: {e}")

    if preserved > 0:
        logger.info(
            f"Preserved {preserved} filter(s) matching expected segment "
            f"'{preserve_segment}'"
        )

    if removed > 0:
        logger.info(f"Removed {removed} audience filter(s) total")
        # Post-cleanup screenshot
        try:
            debug_path = (
                Path(__file__).parent
                / f"debug_sms_audience_cleaned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
            await page.screenshot(path=str(debug_path), full_page=True)
            logger.info(f"Post-cleanup audience screenshot: {debug_path}")
        except Exception:
            pass
    elif filter_count > 0 and preserved == 0:
        logger.warning(
            f"Detected {filter_count} filter(s) but could not remove them — "
            f"please verify the audience manually"
        )

    return removed


async def _check_audience_configured(page: Page, expected_segment: str) -> bool:
    """Check whether the audience is actually configured after cleanup.

    Looks for two things:
      1. The base "Target Users By Segment" dropdown shows a selected segment
         (not just "Search Segments...").
      2. OR the "Audience Summary" text still contains the expected segment.

    Returns True if the audience appears to be properly configured.
    """
    # Check 1: Base segment dropdown has a selection
    segment_picker = page.locator(
        "[class*='segment'] [class*='select'], "
        "[class*='multiValue'], "
        "[class*='multi-value']"
    )
    try:
        if await segment_picker.count() > 0:
            picker_text = (await segment_picker.first.text_content() or "").strip()
            if picker_text and "Search Segments" not in picker_text:
                logger.info(f"Base segment is selected: {picker_text}")
                return True
    except Exception:
        pass

    # Check 2: See if the segment picker placeholder still says "Search Segments..."
    # (meaning nothing is selected in the base segment)
    placeholder = page.get_by_text("Search Segments...", exact=True)
    try:
        base_empty = await placeholder.count() > 0 and await placeholder.first.is_visible()
    except Exception:
        base_empty = True

    # Check 3: Audience Summary still mentions the expected segment
    # (This can be stale in the UI, so also verify via Segment Membership filters)
    page_text = await page.text_content("body") or ""

    # Look for an active Segment Membership filter containing the expected segment
    filter_text = page.locator("text='Segment Membership'")
    has_segment_filter = False
    try:
        for i in range(await filter_text.count()):
            entry = filter_text.nth(i)
            for level in range(1, 8):
                try:
                    ancestor = entry.locator(f"xpath=ancestor::*[{level}]")
                    row_text = (await ancestor.text_content() or "").strip()
                    if expected_segment in row_text:
                        has_segment_filter = True
                        break
                except Exception:
                    continue
            if has_segment_filter:
                break
    except Exception:
        pass

    if has_segment_filter:
        logger.info(
            f"Audience configured via Segment Membership filter: "
            f"{expected_segment}"
        )
        return True

    if not base_empty:
        # Something is selected in the base segment (but we couldn't read it)
        logger.info("Base segment appears to have a selection")
        return True

    # Neither base segment nor filter — audience is likely gone
    logger.warning(
        f"Audience appears unconfigured: base segment is empty and "
        f"no Segment Membership filter found for '{expected_segment}'"
    )
    return False


async def verify_and_clean_sms_audience(
    page: Page,
    expected_segment: str,
    segment_type: str = "full_file",
    geo_filters: Optional[List[Dict]] = None,
) -> bool:
    """Verify the duplicated campaign's audience and remove unwanted filters.

    When duplicating an SMS campaign, the audience (segment + any filters)
    carries over from the source.  This function:
      1. Navigates to the Target Audiences step
      2. Verifies the expected SMS segment is present (either as base segment
         or as a Segment Membership filter)
      3. If segment_type is ``full_file`` — removes extra filters while
         **preserving** any filter that matches the expected SMS segment
      4. After cleanup, verifies the audience is still configured; if it
         was accidentally removed or missing, falls back to
         ``configure_target_audience`` to re-add it from scratch
      5. If segment_type is ``geo`` and geo filters are missing — falls
         back to ``configure_target_audience`` to add them

    Args:
        page: Playwright page.
        expected_segment: Expected SMS segment name
            (e.g. "SMS Master List - Double Opt In").
        segment_type: "full_file" (default) or "geo".
        geo_filters: Geo filter config dicts (used when segment_type is "geo"
            and the duplicated campaign is missing geo filters).

    Returns:
        True if the segment was verified correctly.
    """
    logger.info(f"Verifying SMS audience: {expected_segment} (type={segment_type})")

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

    # Debug screenshot (before cleanup)
    try:
        debug_path = (
            Path(__file__).parent
            / f"debug_sms_audience_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        await page.screenshot(path=str(debug_path), full_page=True)
        logger.info(f"SMS audience screenshot: {debug_path}")
    except Exception:
        pass

    # Check for the expected segment in page text
    page_text = await page.text_content("body") or ""
    segment_ok = expected_segment in page_text
    if segment_ok:
        logger.info(f"Target segment verified: {expected_segment}")
    else:
        logger.warning(
            f"Expected segment '{expected_segment}' not found on Target "
            f"Audiences page. The duplicated campaign may have the wrong "
            f"audience — please verify manually."
        )

    # --- Handle filters based on segment_type ---
    if segment_type == "full_file":
        # Standard SMS campaign — remove extra filters but PRESERVE the
        # expected SMS segment (which may be configured as a Segment
        # Membership filter rather than the base segment).
        removed = await _remove_audience_filters(
            page, preserve_segment=expected_segment
        )
        if removed > 0:
            logger.info(f"Cleaned {removed} extra filter(s) for full_file audience")

    elif segment_type == "geo":
        # Geo SMS campaign — should have geo filters.
        has_filters = await _has_audience_filters(page)
        if has_filters:
            logger.info("Geo filters appear to be present from duplicated campaign")
        elif geo_filters:
            # Geo filters missing — fall back to full audience configuration
            logger.info(
                "Geo segment type but no filters found — falling back to "
                "configure_target_audience to add geo filters"
            )
            audience_config = {
                "type": "segment_with_filter",
                "segment": expected_segment,
                "filters": geo_filters,
            }
            await configure_target_audience(page, audience_config)
        else:
            logger.warning(
                "Geo segment type requested but no geo filter config available "
                "— using duplicated audience as-is"
            )

    # --- Post-cleanup verification ---
    # Verify the audience is still configured.  If the base segment is empty
    # AND no Segment Membership filter matches the expected segment, the
    # audience was lost — fall back to configure_target_audience.
    audience_ok = await _check_audience_configured(page, expected_segment)
    if not audience_ok:
        logger.warning(
            f"Audience lost after cleanup — re-adding via "
            f"configure_target_audience: {expected_segment}"
        )
        audience_config = {
            "type": "segment",
            "segment": expected_segment,
        }
        # Add geo filters if this is a geo campaign
        if segment_type == "geo" and geo_filters:
            audience_config["type"] = "segment_with_filter"
            audience_config["filters"] = geo_filters

        await configure_target_audience(page, audience_config)

        # Verify again after re-configuration
        await page.wait_for_timeout(2000)
        audience_ok = await _check_audience_configured(page, expected_segment)
        if audience_ok:
            logger.info("Audience successfully re-configured")
        else:
            logger.error(
                f"Could not configure audience '{expected_segment}' — "
                f"please verify manually"
            )

    return segment_ok and audience_ok


# =========================================================================
# 8d. PLAYWRIGHT — DELIVERY DATE UPDATE (DUPLICATE FLOW)
# =========================================================================

async def update_sms_delivery_date(
    page: Page, launch_date: str, send_time_config: Dict[str, Any]
) -> bool:
    """Update the delivery date and time on a duplicated SMS campaign.

    Since we duplicated the campaign, the scheduling type (Once) and local
    time zone settings carry over.  We only need to update the date and
    confirm/set the time.

    Args:
        page: Playwright page.
        launch_date: Date string as YYYY-MM-DD.
        send_time_config: Send time dict with ``time`` key (HH:MM format).

    Returns:
        True on success.
    """
    logger.info("Updating SMS delivery schedule...")

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

    # --- Confirm/update Start Time ---
    send_time = send_time_config.get("time", "15:00")
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

    # --- Verify local time zone is checked ---
    # The checkbox should carry over from the duplicate, but verify it.
    try:
        local_tz_label = page.get_by_text("local time zone", exact=False)
        if await local_tz_label.count() > 0:
            local_tz_checkbox = local_tz_label.locator(
                "xpath=preceding-sibling::input[@type='checkbox'] | "
                "ancestor::label/input[@type='checkbox']"
            )
            if await local_tz_checkbox.count() > 0:
                is_checked = await local_tz_checkbox.first.is_checked()
                if is_checked:
                    logger.info("Local time zone checkbox is checked")
                else:
                    logger.warning("Local time zone checkbox is NOT checked — checking it")
                    await local_tz_checkbox.first.check()
                    await page.wait_for_timeout(500)
            else:
                logger.debug("Could not find local time zone checkbox element")
        else:
            logger.debug("Could not find local time zone label — assuming it carried over")
    except Exception:
        logger.debug("Could not verify local time zone checkbox")

    logger.info("SMS delivery schedule updated")
    return True


# =========================================================================
# 9.  ASANA WRITEBACK
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


def update_asana_task_status(task_gid: str, status_gid: str) -> bool:
    """Update the Task Status enum custom field on an Asana task."""
    payload = {
        "data": {
            "custom_fields": {
                FIELD_TASK_STATUS: status_gid,
            }
        }
    }
    result = _asana_request("PUT", f"tasks/{task_gid}", json_data=payload)
    return result is not None


# =========================================================================
# 10.  MAIN ORCHESTRATOR
# =========================================================================

async def build_single_campaign(
    task: Dict[str, Any],
    global_config: Dict[str, Any],
    dry_run: bool = True,
    auto_confirm: bool = False,
    headless: bool = True,
    skip_writeback: bool = False,
    landing_url_override: Optional[str] = None,
    copy_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single SMS campaign in Braze from an Asana task.

    Uses a duplicate-based workflow when a recent SMS campaign for the same
    brand exists (faster — skips conversion event setup), falling back to
    creating from scratch if no source campaign is found.

    Returns a result dict with status, errors, screenshot path, etc.
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
        config = build_campaign_config(task, global_config, landing_url_override, copy_override)

        # Print summary
        print("\n" + "=" * 60)
        print("SMS CAMPAIGN BUILD SUMMARY")
        print("=" * 60)
        print(f"  Asana task:  {task['name']}")
        print(f"  Braze name:  {config['campaign_name']}")
        print(f"  Brand:       {config['brand_code']}")
        print(f"  Workspace:   {config['workspace']}")
        print(f"  Build mode:  Duplicate (with create-from-scratch fallback)")

        # Wrap long SMS body for display
        body_display = config["sms_body"]
        if len(body_display) > 100:
            body_display = body_display[:97] + "..."
        print(f"  SMS Body:    {body_display}")
        print(f"  Full length: {len(config['sms_body'])} chars")

        if config["needs_url_resolution"]:
            print(f"  ** NOTE:     Link was auto-appended (inferred from copy content).")
            print(f"               Verify the URL is correct before launching.")

        print(f"  Audience:    {config['audience'].get('type')} — {config['audience']['segment']}")
        if config["audience"].get("filters"):
            for f in config["audience"]["filters"]:
                print(f"    + filter: {f.get('name')} ({f.get('op', 'and')})")
        print(f"  Send time:   {config['send_time']['type']}", end="")
        if config["send_time"].get("time"):
            print(f" @ {config['send_time']['time']} local", end="")
        print()
        print(f"  Launch date: {config['launch_date']}")
        print(f"  Conversions: (carried over from source campaign / configured per brand)")
        for slot in ["A", "B", "C", "D"]:
            ev = config["conversions"].get(slot, {})
            ev_name = ev.get("event", "N/A")
            is_builtin, label = _is_builtin_event(ev_name)
            if is_builtin:
                print(f"    {slot}: {label} (built-in, {ev.get('deadline_days', 3)}d)")
            else:
                print(f"    {slot}: Performs Custom Event -> '{ev_name}' ({ev.get('deadline_days', 3)}d)")
        if config.get("grammar_warnings"):
            print(f"\n  ** GRAMMAR:  {len(config['grammar_warnings'])} issue(s) detected in copy:")
            for w in config["grammar_warnings"]:
                print(f"               - {w}")
        print("=" * 60)

        if not config["sms_body"]:
            print("\n  ERROR: No SMS copy found in task notes. Cannot build campaign.")
            result["errors"].append("No SMS copy found in task notes")
            return result

        # --- SMS UTM QA checks ---
        try:
            from validate_html import validate_sms as _validate_sms

            _sms_cfg = get_sms_config(config["brand_code"], global_config)
            qa_errors, qa_warnings = _validate_sms(
                sms_body=config["sms_body"],
                brand=config["brand_code"],
                require_bzt=_sms_cfg.get("include_bzt", False),
            )

            if qa_warnings:
                print(f"\n  QA WARNINGS ({len(qa_warnings)}):")
                for w in qa_warnings:
                    print(f"    WARN: {w}")

            if qa_errors:
                print(f"\n  QA ERRORS ({len(qa_errors)}):")
                for e in qa_errors:
                    print(f"    ERROR: {e}")
        except ImportError:
            pass  # validate_html not available, skip

        if dry_run:
            print("\nDRY RUN — no changes will be made.")
            print(f"\n  Full SMS body:\n  {config['sms_body']}")
            result["success"] = True
            return result

        # Confirm before proceeding
        if not auto_confirm:
            print(f"\n  Full SMS body:\n  {config['sms_body']}")
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
                    brand_for_workspace = "HAV"
                await select_workspace(page, brand_for_workspace)

                # --- Try duplicate-based flow first ---
                duplicated = await duplicate_sms_campaign(page, config["brand_code"])

                if duplicated:
                    # -------------------------------------------------------
                    # DUPLICATE FLOW — audience + conversions carry over
                    # -------------------------------------------------------
                    logger.info("Using duplicate-based flow")

                    await wait_for_campaign_editor(page)
                    await set_campaign_name(page, config["campaign_name"])

                    # Step 1: Edit SMS body (scoped write + read-back verification).
                    # On failure we do NOT abort — the build proceeds and a copy
                    # warning is surfaced so a human reconciles the copy in Braze.
                    copy_verified = await configure_sms_content(page, config["sms_body"])
                    if not copy_verified:
                        result.setdefault("copy_warnings", []).append(
                            "SMS body could not be verified against the Asana brief after "
                            "retries — the campaign may still contain copy from the duplicated "
                            "source campaign. Verify the SMS copy in Braze before dispatching."
                        )
                        logger.warning(
                            "SMS body not verified — continuing build with a copy warning."
                        )

                    # Step 2: Update delivery date/time (schedule type carries over)
                    await update_sms_delivery_date(
                        page, config["launch_date"], config["send_time"]
                    )

                    # Step 3: Verify audience and clean up extra filters
                    segment_ok = await verify_and_clean_sms_audience(
                        page,
                        expected_segment=config["audience"]["segment"],
                        segment_type=config["_segment_type"],
                        geo_filters=config["audience"].get("filters"),
                    )
                    if not segment_ok:
                        result["errors"].append(
                            f"Segment mismatch — expected '{config['audience']['segment']}'. "
                            f"Please verify the Target Audiences manually."
                        )

                    # Conversions: SKIP — carried over from duplicated campaign
                    logger.info("Conversions carried over from source campaign (skipped)")

                else:
                    # -------------------------------------------------------
                    # FALLBACK — create from scratch (full configuration)
                    # -------------------------------------------------------
                    logger.info(
                        "No source SMS campaign found for brand "
                        f"'{config['brand_code']}' — falling back to "
                        "create-from-scratch flow"
                    )

                    await navigate_to_campaigns(page, brand=config["brand_code"])

                    # Create new SMS campaign
                    await start_sms_campaign(page)
                    await set_campaign_name(page, config["campaign_name"])

                    # Step 1: Compose — SMS body (scoped write + read-back verification)
                    copy_verified = await configure_sms_content(page, config["sms_body"])
                    if not copy_verified:
                        result.setdefault("copy_warnings", []).append(
                            "SMS body could not be verified against the Asana brief after "
                            "retries — verify the SMS copy in Braze before dispatching."
                        )
                        logger.warning(
                            "SMS body not verified — continuing build with a copy warning."
                        )

                    # Step 2: Schedule Delivery (full setup)
                    await configure_delivery(
                        page, config["send_time"], config["launch_date"]
                    )

                    # Step 3: Target Audiences (full segment search + filters)
                    await configure_target_audience(
                        page, config["audience"], launch_date=config["launch_date"]
                    )

                    # Step 4: Assign Conversions (full setup — 4 events)
                    await configure_conversions(page, config["conversions"])

                # --- Common final steps (both paths) ---

                # Screenshot before saving
                screenshot_path = await capture_screenshot(page, config["campaign_name"])
                result["screenshot"] = screenshot_path

                # Save as draft
                await save_as_draft(page, dry_run=False)

                # Get campaign URL
                braze_url = get_campaign_url_from_page(page.url)
                result["braze_url"] = braze_url

                result["success"] = True
                result["grammar_warnings"] = config.get("grammar_warnings", [])
                result["copy_warnings"] = result.get("copy_warnings", [])
                build_mode = "duplicate" if duplicated else "from-scratch"
                logger.info(f"SMS campaign built successfully ({build_mode})")

            except Exception as e:
                logger.error(f"SMS campaign build failed: {e}")
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

        # Write back to Asana
        if skip_writeback:
            logger.info("Skipping Asana writeback (--skip-writeback)")
        elif result["success"] and result.get("braze_url"):
            if update_asana_with_braze_link(task["gid"], result["braze_url"]):
                logger.info("Asana task updated with Braze link")
            else:
                logger.warning("Failed to update Asana task")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        result["errors"].append(str(e))

    return result


# =========================================================================
# 11.  CLI ENTRY POINT
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Build SMS campaigns in Braze from Asana tasks."
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
        "--skip-writeback", action="store_true",
        help="Skip writing Braze link back to Asana (useful for testing)",
    )
    parser.add_argument(
        "--landing-url", type=str, default=None,
        help="Override the auto-resolved landing page URL (UTMs still appended). "
             "Only used with --task for a single task.",
    )
    parser.add_argument(
        "--copy", type=str, default=None,
        help="Override SMS body text instead of parsing from Asana notes. "
             "UTMs are still appended. Only used with --task for a single task.",
    )
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
        # Fetch all "Ready to Code" SMS tasks
        brand_filter = args.brand.upper() if args.brand else None
        logger.info("Scanning Asana for 'Ready to Code' SMS tasks...")
        tasks_to_process = fetch_ready_to_code_sms_tasks(brand_filter)

    if not tasks_to_process:
        print("No SMS tasks found to process.")
        return

    print(f"\nFound {len(tasks_to_process)} SMS task(s) to process.\n")

    # Process each task
    results = []
    for i, task in enumerate(tasks_to_process, 1):
        print(f"\n[{i}/{len(tasks_to_process)}] {task['brand']}: {task['name']}")

        if task.get("braze_campaign_id") or task.get("braze_link"):
            existing = task.get("braze_campaign_id") or task.get("braze_link")
            print(f"  Skipping — already built: {existing}")
            continue

        result = asyncio.run(
            build_single_campaign(
                task=task,
                global_config=global_config,
                dry_run=dry_run,
                auto_confirm=args.yes,
                headless=args.headless,
                skip_writeback=args.skip_writeback,
                landing_url_override=args.landing_url,
                copy_override=args.copy,
            )
        )
        results.append(result)

        # Post-build Asana updates (non-dry-run only)
        if not dry_run and result.get("success") and result.get("braze_url"):
            status_ok = update_asana_task_status(task["gid"], STATUS_READY_FOR_QA)
            if status_ok:
                print(f"  Status updated to 'Ready for QA'.")
            else:
                print(f"  WARNING: Failed to update task status to Ready for QA.")
            braze_url = result["braze_url"]
            comment_ok = _asana_request(
                "POST",
                f"tasks/{task['gid']}/stories",
                json_data={
                    "data": {
                        "text": (
                            f"This SMS campaign has been automatically created in Braze "
                            f"and is ready for review and scheduling.\n\n"
                            f"Campaign link: {braze_url}"
                        ),
                        "is_pinned": False,
                    }
                },
            )
            if comment_ok:
                print(f"  Asana comment posted.")
            else:
                print(f"  WARNING: Failed to post Asana comment.")

            # Post a separate grammar warning comment if issues were detected
            grammar_warnings = result.get("grammar_warnings", [])
            if grammar_warnings:
                issues_text = "\n".join(f"  • {w}" for w in grammar_warnings)
                grammar_comment_ok = _asana_request(
                    "POST",
                    f"tasks/{task['gid']}/stories",
                    json_data={
                        "data": {
                            "text": (
                                f"⚠️ Grammar check flagged {len(grammar_warnings)} issue(s) "
                                f"in the SMS copy — please review before dispatching:\n\n"
                                f"{issues_text}\n\n"
                                f"The campaign was still built; update the copy in Braze if needed."
                            ),
                            "is_pinned": False,
                        }
                    },
                )
                if grammar_comment_ok:
                    print(f"  Grammar warning comment posted ({len(grammar_warnings)} issue(s)).")
                else:
                    print(f"  WARNING: Failed to post grammar warning comment.")

            # Post a copy-verification warning if the SMS body could not be
            # confirmed to match the brief (campaign was still built + linked).
            copy_warnings = result.get("copy_warnings", [])
            if copy_warnings:
                issues_text = "\n".join(f"  • {w}" for w in copy_warnings)
                copy_comment_ok = _asana_request(
                    "POST",
                    f"tasks/{task['gid']}/stories",
                    json_data={
                        "data": {
                            "text": (
                                f"⚠️ SMS copy could not be automatically verified — please "
                                f"confirm the SMS body in Braze matches the brief before "
                                f"dispatching:\n\n{issues_text}"
                            ),
                            "is_pinned": False,
                        }
                    },
                )
                if copy_comment_ok:
                    print(f"  Copy warning comment posted ({len(copy_warnings)} issue(s)).")
                else:
                    print(f"  WARNING: Failed to post copy warning comment.")

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
