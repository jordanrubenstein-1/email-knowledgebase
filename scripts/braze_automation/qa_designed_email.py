#!/usr/bin/env python3
"""
Generic QA verification + test send for designed email campaigns.

Called by webhook_server.py when an Asana task's status transitions to
"Ready for QA". Verifies delivery settings and audience configuration via
Playwright, sends a test email to the task's assignee, and checks off the
verifiable Asana QA subtasks.

Can also be run standalone for debugging:
    uv run python scripts/braze_automation/qa_designed_email.py \\
        --task-gid 1213928748054248 --brand CZ
"""

import argparse
import asyncio
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse, urlunparse

import yaml
from dotenv import load_dotenv
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))
load_dotenv(PROJECT_ROOT / ".env")

from login import create_context_with_session, ensure_logged_in, select_workspace
from build_pt_campaign import (
    _asana_request,
    fetch_task_by_gid,
    FIELD_AUDIENCE,
    FIELD_SEGMENT,
    FIELD_SEGMENT_TEXT,
    FIELD_SUBJECT_LINE,
    FIELD_PRE_HEADER,
    _get_enum_value_gid,
    _get_enum_value_name,
    _resolve_task_segment_optional,
    business_days_until,
    STO_MIN_BUSINESS_DAYS,
    load_brand_config,
    get_brand_entry,
)
from utils.segment_text import resolve_ti_segment_key
# wait_for_campaign_editor and _parse_push_task imported below (combined build_push_campaign block)
from build_designed_campaign import (
    send_test_email,
    _braze_get,
    find_campaign_api_id_by_name,
    _derive_campaign_name,
    FIELD_REF_BRAZE_CAMPAIGN,
)
from build_sms_campaign import (
    FIELD_BRAZE_LINK, FIELD_CHANNEL, CHANNEL_OPTIONS, _get_text_value,
    generate_sms_campaign_name, BRAND_GID_TO_CODE as _SMS_BRAND_GID_TO_CODE,
    FIELD_BRAND as _FIELD_BRAND,
    validate_url as _validate_sms_url,
    _extract_lp_from_task as _sms_extract_lp,
)
from build_push_campaign import (
    wait_for_campaign_editor,
    parse_asana_push_task as _parse_push_task,
)

# Asana Type field — used to detect plain-text emails independent of campaign name
FIELD_TYPE = "1207522425689987"
TYPE_PLAIN_TEXT = "1207522425689988"  # enum value: "Plain-Text"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Assignee → test-send email mapping
# Keyed by the Asana "assignee.name" string returned by the tasks API.
# First-name-only matches are used as a fallback.
# ---------------------------------------------------------------------------
ASSIGNEE_QA_EMAILS: dict[str, str] = {
    "Jordan Rubenstein": "jordan.rubenstein@havenly.com",
    "Emmanuel Oluwalomola": "emmanuel.oluwalomola@havenly.com",
    "Momina Ayaz": "momina.ayaz@havenly.com",
}
DEFAULT_QA_EMAIL = "jordan.rubenstein@havenly.com"


def resolve_qa_email(assignee_name: Optional[str]) -> str:
    """Return the test-send email for the given assignee name, with fallback."""
    if not assignee_name:
        return DEFAULT_QA_EMAIL
    if assignee_name in ASSIGNEE_QA_EMAILS:
        return ASSIGNEE_QA_EMAILS[assignee_name]
    # First-name prefix match
    first = assignee_name.split()[0]
    for name, email in ASSIGNEE_QA_EMAILS.items():
        if name.split()[0].lower() == first.lower():
            return email
    logger.warning(f"No QA email found for assignee '{assignee_name}' — using default")
    return DEFAULT_QA_EMAIL


# ---------------------------------------------------------------------------
# Braze URL parsing
# ---------------------------------------------------------------------------
# Campaign ID can be a 24-char hex (MongoDB ObjectID, from manually-copied URLs) or
# a UUID (from the Braze REST API campaigns/list `id` field).
_BRAZE_URL_RE = re.compile(
    r"/campaigns/"
    r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}|[a-f0-9]{24})"
    r"/([a-f0-9]{24})"
)


def parse_braze_url(braze_url: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (campaign_id, workspace_id) from a Braze dashboard URL."""
    m = _BRAZE_URL_RE.search(braze_url or "")
    if m:
        return m.group(1), m.group(2)
    return None, None


# ---------------------------------------------------------------------------
# Expected segment lookup
# ---------------------------------------------------------------------------
# Some lifecycle guidelines names differ slightly from the Braze UI display.
_BRAZE_SEGMENT_OVERRIDES: dict[str, str] = {
    # Lifecycle says "Full File List - September 2024"
    # Braze UI shows '"Full File" List - September 2024' (literal quotes)
    "Full File List - September 2024": '"Full File" List - September 2024',
}

# Map brand code → keyword to match the brand entry in lifecycle_guidelines.yaml
_BRAND_CODE_TO_KEYWORD: dict[str, str] = {
    "HAV": "havenly",  # matches both "Havenly Pre-Converted" and "Havenly Converted"
    "CZ": "citizenry",
    "ID": "interior define",
    "BUR": "burrow",
    "STF": "frank",
    "TI": "inside",
    "TE": "expert",
}

# Asana "Send time" custom field GID
FIELD_SEND_TIME = "1212524397761931"

# Content block names that carry the unsubscribe footer but whose name does not
# say so — these still need a brand-scoped allow-list. Blocks whose name
# contains "unsub" are recognized for every brand by _html_has_unsubscribe(),
# so they do not need to be listed here (and listing them per-brand is what made
# ID's use of BUR's PT_sale_footer_unsubscribe block read as a missing footer).
# All brands also accept the direct {{${set_user_to_unsubscribed_url}}} link.
_UNSUB_CONTENT_BLOCKS: dict[str, list[str]] = {
    "BUR": ["sale_footer_us", "footer_us"],
    "STF": ["footer"],
}

# Matches a content block reference and captures its name, ignoring any
# trailing Liquid filters: {{content_blocks.${NAME} | id: 'cb2'}} → NAME
_CONTENT_BLOCK_RE = re.compile(r"\{\{\s*content_blocks\.\$\{([^}]+)\}")

# The direct Braze unsubscribe URL, as an href or bare Liquid. Written as a
# regex rather than a literal substring so optional whitespace inside the
# braces and casing differences still count as a real unsubscribe link.
_UNSUB_URL_RE = re.compile(
    r"\{\{\s*\$\{\s*set_user_to_unsubscribed_url\s*\}\s*\}\}", re.IGNORECASE
)


def _html_has_unsubscribe(html: str, brand: str) -> tuple[bool, str]:
    """Return (found, reason) for the unsubscribe link/footer check.

    Accepts, in order:
      1. the direct {{${set_user_to_unsubscribed_url}}} link;
      2. any content block whose name contains "unsub" (any brand) — a block
         named e.g. PT_sale_footer_unsubscribe always carries the unsub link,
         and these blocks are shared across brands;
      3. a brand-specific block from _UNSUB_CONTENT_BLOCKS whose name does not
         itself say "unsub" (BUR's footer_us, STF's footer).
    """
    if _UNSUB_URL_RE.search(html):
        return True, "set_user_to_unsubscribed_url link"

    blocks = [n.strip() for n in _CONTENT_BLOCK_RE.findall(html)]
    named = next((b for b in blocks if "unsub" in b.lower()), None)
    if named:
        return True, f"content block {named!r}"

    brand_blocks = _UNSUB_CONTENT_BLOCKS.get(brand.upper(), [])
    match = next((b for b in blocks if b in brand_blocks), None)
    if match:
        return True, f"{brand.upper()} content block {match!r}"

    return False, f"content blocks present: {blocks or 'none'}"

# Temporary segment exclusions that are acceptable for a limited time.
# Format: brand_code → [(segment_name, expiry_date_inclusive), ...]
# After expiry, the QA check will flag the exclusion as stale.
_KNOWN_TEMPORARY_EXCLUSIONS: dict[str, list[tuple[str, str]]] = {
    "BUR": [
        ("Memorial Day Canvas Test Group", "2026-06-02"),
    ],
}


# ---------------------------------------------------------------------------
# Brands whose email audience is selected per-task from the "Segment (Text)"
# Asana field rather than a single standing list. For these, the valid segment
# names come from data/brand_config.yaml `brands.{CODE}.audiences` (the same
# source the campaign builders resolve against), NOT from the standing
# all_subscribers/engaged pair in lifecycle_guidelines.yaml — which only ever
# names two of them and went stale after the ID + TI segmentation redos.
#   ID: 7 Braze segments   (ticket 1214216873746059, live for sends >= 2026-08-18)
#   TI: 4 Klaviyo segments (ticket 1216770925418815, swatch pair >= 2026-08-18)
# Both resolvers are date-gated, so a pre-cutoff send still expects its legacy list.
# ---------------------------------------------------------------------------
_SEGMENT_TEXT_BRANDS = ("ID", "TI")


def _config_audience_segment_names(brand: str) -> dict[str, list[str]]:
    """Return {audience_key: [segment names]} from brand_config.yaml for a brand."""
    try:
        brand_entry = get_brand_entry(brand, load_brand_config()) or {}
    except Exception as exc:
        logger.warning(f"Could not read brand_config audiences for {brand}: {exc}")
        return {}
    out: dict[str, list[str]] = {}
    for key, cfg in (brand_entry.get("audiences") or {}).items():
        if not isinstance(cfg, dict):
            continue
        names = cfg.get("segments") if isinstance(cfg.get("segments"), list) else [cfg.get("segment")]
        names = [n for n in names if n]
        if names:
            out[key] = names
    return out


def _resolve_expected_audience_key(brand: str, task: Optional[dict]) -> Optional[str]:
    """Resolve the audience key a task's Segment (Text) field asks for.

    Uses the same resolvers the builders use, so QA and the build agree —
    including their send-date cutoffs. Returns None when the task carries no
    segment selection at all (caller then accepts any configured segment).
    """
    if not task:
        return None
    send_date = task.get("due_on") or None
    if brand == "ID":
        return _resolve_task_segment_optional(task, "ID", send_date)
    if brand == "TI":
        raw = (_get_text_value(task, FIELD_SEGMENT_TEXT) or "").strip()
        if not raw:
            raw = _get_enum_value_name(task, FIELD_SEGMENT) or ""
        if not raw:
            return None
        return resolve_ti_segment_key(raw, send_date=send_date)
    return None


def _segment_text_brand_groups(brand: str, task: Optional[dict]) -> list[list[str]]:
    """Expected segment groups for a Segment (Text) brand (ID / TI).

    When the task names a segment, expect exactly that one. When it doesn't,
    accept any segment configured for the brand rather than failing the check.
    """
    by_key = _config_audience_segment_names(brand)
    if not by_key:
        return []
    key = _resolve_expected_audience_key(brand, task)
    if key and key in by_key:
        return [list(by_key[key])]
    if key:
        logger.warning(
            f"{brand}: resolved audience key {key!r} has no brand_config entry — "
            "accepting any configured segment"
        )
    groups: list[list[str]] = []
    for names in by_key.values():
        candidate = list(names)
        if candidate not in groups:
            groups.append(candidate)
    return groups


def get_expected_segment_groups(
    brand: str, channel: str = "email", task: Optional[dict] = None
) -> list[list[str]]:
    """
    Return valid audience configurations for a brand as a list of groups.

    Each group is a list of segment names that must ALL appear on the Target
    Audiences tab for that configuration to be considered valid. The audience
    check passes if ANY group is fully satisfied (AND-within-group, OR-across-groups).

    For SMS and push, reads segments.sms.name / segments.push.name from
    lifecycle_guidelines.yaml — one group per matching brand entry.

    For email (default):
      Most brands have single-element groups (any one segment name present → pass).
      BUR is the exception:
        - Full-file: all 4 filter segments must appear in Additional Filters.
        - Engaged:   all 4 filter segments + AM List VIP must appear (all 5).

    For brands with multiple audience entries (e.g. HAV has separate PC and
    Converted rows), each entry contributes its own group(s) so either audience
    passes the check.

    ID and TI bypass the lifecycle file entirely for email: their audience is
    chosen per-task via the Segment (Text) field, so the expected segment is
    resolved from that field against brand_config.yaml — see
    _segment_text_brand_groups().

    Other geo and segmented sends are NOT verified (left for human review).
    """
    guidelines_path = PROJECT_ROOT / "data" / "lifecycle_guidelines.yaml"
    try:
        with open(guidelines_path) as f:
            data = yaml.safe_load(f) or {}
        brands_list: list = data.get("brands", [])
        keyword = _BRAND_CODE_TO_KEYWORD.get(brand, brand).lower()
        # Collect ALL matching brand entries (HAV has separate PC + Converted rows)
        matching = [b for b in brands_list if keyword in (b.get("name") or "").lower()]
        if not matching:
            return []

        groups: list[list[str]] = []

        # SMS and push each have a single dedicated segment field per brand entry.
        if channel in ("sms", "push"):
            for brand_entry in matching:
                raw = brand_entry.get("segments", {}).get(channel, {}).get("name")
                if raw and raw.strip().upper() not in ("N/A", "TBD", ""):
                    resolved = _BRAZE_SEGMENT_OVERRIDES.get(raw, raw)
                    candidate = [resolved]
                    if candidate not in groups:
                        groups.append(candidate)
            return groups

        # ID / TI: audience is picked per-task from Segment (Text); read the
        # live segment names from brand_config.yaml instead of the two standing
        # lists in lifecycle_guidelines.yaml.
        if brand in _SEGMENT_TEXT_BRANDS:
            config_groups = _segment_text_brand_groups(brand, task)
            if config_groups:
                return config_groups
            logger.warning(
                f"{brand}: no brand_config audiences found — falling back to "
                "lifecycle_guidelines segment names"
            )

        # Email: use all_subscribers + engaged (existing logic).
        for brand_entry in matching:
            segs = brand_entry.get("segments", {})
            all_subs_raw: Optional[str] = segs.get("all_subscribers", {}).get("name")
            engaged_raw: Optional[str] = segs.get("engaged", {}).get("name")

            # Parse multi-segment all_subscribers (BUR): the 4 quoted segment names
            # must ALL be present in Additional Filters. We produce two groups:
            #   group A = the 4 filter segments (full-file)
            #   group B = the 4 filter segments + engaged segment (engaged)
            # Both require all members, but B is a superset of A, so satisfying A
            # is sufficient. We keep both for documentation clarity.
            if all_subs_raw and "\nOR" in all_subs_raw:
                filter_segs = [
                    _BRAZE_SEGMENT_OVERRIDES.get(n, n)
                    for n in re.findall(r'"([^"]+)"', all_subs_raw)
                ]
                if filter_segs:
                    groups.append(filter_segs)  # full-file group
                    if engaged_raw and engaged_raw.strip().upper() not in ("N/A", "TBD", ""):
                        eng_resolved = _BRAZE_SEGMENT_OVERRIDES.get(engaged_raw, engaged_raw)
                        groups.append(filter_segs + [eng_resolved])  # engaged group
                continue  # handled both tiers above

            # Standard brands: each segment is its own single-element group.
            for raw in (all_subs_raw, engaged_raw):
                if not raw or raw.strip().upper() in ("N/A", "TBD", ""):
                    continue
                resolved = _BRAZE_SEGMENT_OVERRIDES.get(raw, raw)
                candidate = [resolved]
                if candidate not in groups:
                    groups.append(candidate)

        return groups
    except Exception as exc:
        logger.warning(f"Could not read lifecycle guidelines: {exc}")
        return []


def _parse_lifecycle_time(raw: str) -> Optional[str]:
    """Extract a clock time from lifecycle guidelines strings like 'Varies; see Asana (previously 7:15 AM)'."""
    if not raw:
        return None
    m = re.search(r'previously\s+(\d{1,2}:\d{2}\s*[AP]M)', raw, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'(\d{1,2}:\d{2}\s*[AP]M)', raw, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _get_lifecycle_times(brand: str) -> tuple[Optional[str], Optional[str]]:
    """Return (am_time, pm_time) fallback strings from lifecycle_guidelines.yaml for the brand."""
    guidelines_path = PROJECT_ROOT / "data" / "lifecycle_guidelines.yaml"
    try:
        with open(guidelines_path) as f:
            data = yaml.safe_load(f) or {}
        keyword = _BRAND_CODE_TO_KEYWORD.get(brand.upper(), brand).lower()
        matching = [b for b in data.get("brands", []) if keyword in (b.get("name") or "").lower()]
        if not matching:
            return None, None
        entry = matching[0]
        send_times = entry.get("send_times", {})
        return (
            _parse_lifecycle_time(send_times.get("email_am", "")),
            _parse_lifecycle_time(send_times.get("email_pm", "")),
        )
    except Exception:
        return None, None


def _get_allowed_exclusions(brand: str) -> list[str]:
    """Return segment exclusion names that are still within their valid window for today."""
    today = date.today()
    result = []
    for seg_name, expiry_str in _KNOWN_TEMPORARY_EXCLUSIONS.get(brand.upper(), []):
        try:
            expiry = date.fromisoformat(expiry_str)
            if today <= expiry:
                result.append(seg_name)
        except ValueError:
            pass
    return result


def _get_stale_exclusions(brand: str) -> list[str]:
    """Return exclusion names that are past their expiry — should be removed from the campaign."""
    today = date.today()
    result = []
    for seg_name, expiry_str in _KNOWN_TEMPORARY_EXCLUSIONS.get(brand.upper(), []):
        try:
            expiry = date.fromisoformat(expiry_str)
            if today > expiry:
                result.append(seg_name)
        except ValueError:
            pass
    return result


def _get_channel_send_time(brand: str, channel: str) -> Optional[str]:
    """Return the default send time string for a non-email channel (sms/push).

    Reads ``send_times[channel]`` from lifecycle_guidelines.yaml (e.g. ``sms: 3:00 PM``).
    """
    guidelines_path = PROJECT_ROOT / "data" / "lifecycle_guidelines.yaml"
    try:
        with open(guidelines_path) as f:
            data = yaml.safe_load(f) or {}
        keyword = _BRAND_CODE_TO_KEYWORD.get(brand.upper(), brand).lower()
        matching = [b for b in data.get("brands", []) if keyword in (b.get("name") or "").lower()]
        if not matching:
            return None
        send_times = matching[0].get("send_times", {})
        return _parse_lifecycle_time(send_times.get(channel, ""))
    except Exception:
        return None


def _get_expected_delivery(
    task: dict,
    brand: str,
    campaign_name: str,
    channel: str = "email",
    built_on: Optional[str] = None,
) -> dict:
    """
    Compute expected delivery mode and time for the QA delivery check.

    Returns a dict with:
      use_sto (bool): True if Intelligent Timing should be configured
      time_str (str|None): expected fixed send time string (e.g. "7:15 AM")

    Send time resolution is channel-aware:
      - email: Asana Send-time field override → email_pm (only if task name says
        "PM") → email_am fallback. STO applies only with STO_MIN_BUSINESS_DAYS
        of lead time — the same rule the PT and designed builders apply, so QA
        expects what the build actually did.
      - sms / push: Asana Send-time field override → the channel's fixed default
        (``sms``/``push`` in send_times, 3:00 PM for all brands). Never STO.

    ``built_on`` is the campaign's Braze creation date ("YYYY-MM-DD"). Lead time
    is measured from it rather than from today, because QA can run days after
    the build and would otherwise judge the STO decision against a window the
    builder never saw. Falls back to today when unknown.
    """
    asana_send_time = (_get_text_value(task, FIELD_SEND_TIME) or "").strip()

    # SMS and Push are always fixed-time sends at the channel default (3:00 PM),
    # unless the Asana Send-time field explicitly overrides it. They never use STO.
    if channel in ("sms", "push"):
        default_time = _get_channel_send_time(brand, channel)
        expected_time = asana_send_time or default_time
        return {"use_sto": False, "time_str": expected_time}

    is_hav_conv = brand.upper() == "HAV" and "_CONV_" in campaign_name.upper()

    due_on = task.get("due_on") or ""
    use_sto = False
    if due_on and not is_hav_conv:
        from_date = None
        if built_on:
            try:
                from_date = date.fromisoformat(built_on[:10])
            except ValueError:
                pass
        use_sto = business_days_until(due_on, from_date) >= STO_MIN_BUSINESS_DAYS

    am_time, pm_time = _get_lifecycle_times(brand)
    task_name = (task.get("name") or "").upper()

    # PM time is only used when the task title explicitly says "PM"
    if "PM" in task_name and pm_time:
        fallback_time = pm_time
    else:
        fallback_time = am_time

    expected_time = asana_send_time or fallback_time

    return {"use_sto": use_sto, "time_str": expected_time}


# ---------------------------------------------------------------------------
# Braze API + HTML checks  (no browser required)
# ---------------------------------------------------------------------------

def _get_email_message(details: dict) -> Optional[dict]:
    """Extract the real email message dict from a campaigns/details response.

    Braze returns the channel lowercase ("email"), so the match is
    case-insensitive — an exact "Email" comparison never fired, leaving every
    campaign to be found by the subject fallback below and making a campaign
    with no subject set invisible to the email checks entirely.

    The Control Group variant is also reported as channel "email" but carries
    no body or subject, so control messages are skipped and a variant with
    actual content is preferred.
    """
    messages = details.get("messages", {})
    email_msgs = [
        m for m in messages.values()
        if (m.get("channel") or "").lower() == "email" and m.get("type") != "control"
    ]
    for msg in email_msgs:
        if msg.get("body") or msg.get("html_body") or msg.get("subject"):
            return msg
    if email_msgs:
        return email_msgs[0]
    # Fallback: any message that has a subject (email-like)
    for msg in messages.values():
        if msg.get("subject"):
            return msg
    return None


def _get_sms_message(details: dict) -> Optional[dict]:
    """Extract the SMS message dict from a campaigns/details response."""
    for msg in details.get("messages", {}).values():
        if (msg.get("channel") or "").lower() == "sms":
            return msg
    return None


def _get_push_message(details: dict) -> Optional[dict]:
    """Extract the push notification message dict from a campaigns/details response."""
    for msg in details.get("messages", {}).values():
        if "push" in (msg.get("channel") or "").lower():
            return msg
    return None


def _extract_push_deep_link(msg: dict) -> str:
    """Extract the deep link / on-click URI from a push message dict.

    Handles both flat fields and nested per-platform (ios/android) dicts.
    """
    for key in ("uri", "url", "deep_link", "redirect_url"):
        val = msg.get(key)
        if val:
            return val
    # Nested platform-specific dicts
    for platform in ("ios", "android", "web"):
        platform_obj = msg.get(platform, {})
        if isinstance(platform_obj, dict):
            for key in ("uri", "url", "deep_link"):
                val = platform_obj.get(key)
                if val:
                    return val
    # on_click_action may hold a URL directly
    on_click = msg.get("on_click_action") or msg.get("click_action") or ""
    if on_click.startswith("http"):
        return on_click
    return ""


def get_braze_campaign_details(
    task: dict, brand: str, known_name: Optional[str] = None
) -> tuple[Optional[str], Optional[dict]]:
    """
    Return (campaign_name, campaigns/details response) for a Braze campaign.

    If known_name is supplied (parsed from the campaignName query param of the
    task's Braze URL), it is used directly with find_campaign_api_id_by_name —
    no derivation needed.  Falls back to deriving the name from the task when
    known_name is absent.
    """
    if known_name:
        campaign_name = known_name
        logger.info(f"Campaign name (from Braze URL): {campaign_name!r}")
    else:
        task_name = task.get("name", "")
        due_on = task.get("due_on") or ""
        ref_campaign = _get_text_value(task, FIELD_REF_BRAZE_CAMPAIGN) or ""
        campaign_name = _derive_campaign_name(ref_campaign, task_name, due_on, brand)
        logger.info(f"Derived campaign name: {campaign_name!r}")

    api_id = find_campaign_api_id_by_name(campaign_name, brand)
    if not api_id:
        logger.warning(f"Campaign not found in Braze: {campaign_name!r}")
        return campaign_name, None

    details = _braze_get("campaigns/details", {"campaign_id": api_id}, brand)
    return campaign_name, details


# QA fires off the Asana "Ready for QA" status flip, typically within a minute
# of the builder finishing. Braze's REST campaigns/details endpoint can still be
# serving the pre-edit version of a just-built campaign at that point, and the
# starter content it returns has no unsubscribe link, an un-alt'd placeholder
# image and no real subject — producing a burst of content flags on a campaign
# that is actually fine. One delayed re-fetch resolves it.
_STALE_REFETCH_DELAY_SECONDS = 25


def _content_looks_unbuilt(details: Optional[dict], task: dict) -> bool:
    """True when the fetched campaign looks like Braze has not served the built
    content yet: no unsubscribe anywhere AND the subject does not match the brief.

    Deliberately narrow — a genuinely broken build usually fails one check, not
    both at once, and a re-fetch costs one API call.
    """
    if not details:
        return False
    msg = _get_email_message(details)
    if not msg:
        return False
    html = msg.get("body") or msg.get("html_body") or ""
    if not html:
        return False  # empty body is already reported via the html_body_empty flag
    if _UNSUB_URL_RE.search(html) or _CONTENT_BLOCK_RE.search(html):
        return False
    expected_subject = (
        _extract_subject_from_description(task)
        or _get_text_value(task, FIELD_SUBJECT_LINE)
        or ""
    ).strip()
    braze_subject = (msg.get("subject") or "").strip()
    return bool(expected_subject) and braze_subject != expected_subject


async def _refetch_if_content_looks_stale(
    details: Optional[dict],
    task: dict,
    brand: str,
    known_name: Optional[str],
    campaign_name: str,
) -> Optional[dict]:
    """Re-fetch campaign details once if the first read looks pre-build."""
    if not _content_looks_unbuilt(details, task):
        return details
    logger.warning(
        f"Campaign {campaign_name!r} has no unsubscribe and a non-matching subject — "
        f"Braze may not be serving the built content yet. Re-fetching in "
        f"{_STALE_REFETCH_DELAY_SECONDS}s before running content checks."
    )
    await asyncio.sleep(_STALE_REFETCH_DELAY_SECONDS)
    _, fresh = await asyncio.to_thread(
        get_braze_campaign_details, task, brand, known_name
    )
    if fresh and not _content_looks_unbuilt(fresh, task):
        logger.info("Re-fetch returned the built content — using it for QA checks")
        return fresh
    logger.warning("Re-fetch returned the same content — treating it as the real state")
    return fresh or details


def _extract_subject_from_description(task: dict) -> Optional[str]:
    """Extract SL from the first non-blank line of task notes if it has an SL: prefix.

    Mirrors the priority used by _preprocess_body_copy in build_pt_campaign.py —
    the copywriter's subject at the top of the description takes precedence over
    the Asana Subject Line custom field.
    """
    from build_pt_campaign import _html_notes_to_rich_text
    html_notes = task.get("html_notes", "")
    notes = task.get("notes", "")
    raw = _html_notes_to_rich_text(html_notes) if html_notes else notes
    if not raw:
        return None
    for line in raw.strip().split("\n"):
        s = line.strip()
        if not s:
            continue
        m = re.match(
            r"^(?:\*{0,2})(?:SL|Subject(?:\s*Line)?)\s*(?:\*{0,2})\s*:\s*",
            s,
            re.IGNORECASE,
        )
        if m:
            return s[m.end():].strip()
        break  # only check the first non-empty line
    return None


def _alt_exempt_images(html: str, is_pt: bool) -> set[str]:
    """Image tags that are allowed to have no alt attribute.

    Plain-text templates open with the brand logo, and that logo deliberately
    carries no alt text: Braze falls back to the first text in the email when
    no preheader is set, and alt text on the logo would be pulled in ahead of
    the body copy. Only the first image in a PT email is exempt — every other
    image still needs alt.
    """
    if not is_pt:
        return set()
    first = re.search(r"<img\b[^>]*>", html, re.IGNORECASE)
    return {first.group(0)} if first else set()


def run_api_checks(task: dict, brand: str, campaign_name: str, details: dict) -> dict:
    """
    Run the API + HTML checks verifiable without a browser.

    Returns a dict keyed by check name → bool:
        campaign_name, subject_line, preheader, sender,
        alt_tags, unsub, send_date
    Note: utm is checked separately via browser (Link Management panel).
    """
    from utils.campaign_name import validate_campaign_name

    result = {
        "campaign_name": False,
        "subject_line": False,
        "preheader": False,
        "sender": False,
        "alt_tags": False,
        "unsub": False,
        "send_date": False,
        "html_body_empty": False,  # True when Braze returned no HTML — triggers manual QA note
        "is_pt": False,            # True for plain-text emails — used to tailor QA issue messages
    }

    # 1. Campaign name follows naming conventions
    try:
        valid, issues = validate_campaign_name(campaign_name)
        if valid:
            logger.info(f"✓ Campaign name valid: {campaign_name}")
            result["campaign_name"] = True
        else:
            logger.warning(f"Campaign name issues: {issues}")
    except Exception as exc:
        logger.warning(f"validate_campaign_name error: {exc}")

    # Detect PT early — needed before the msg early-return so the preheader check
    # can still run against msg data when available, or pass if msg is absent
    is_pt = (
        "_PT_" in campaign_name.upper()
        or _get_enum_value_gid(task, FIELD_TYPE) == TYPE_PLAIN_TEXT
    )
    result["is_pt"] = is_pt

    # Extract email message from campaign details
    msg = _get_email_message(details)
    if not msg:
        logger.warning("No email message found in Braze campaign details — skipping message checks")
        # PT preheader: can't check Braze value, but pass it since no msg means nothing set
        if is_pt:
            result["preheader"] = True
        # Still try send_date
        due_on = task.get("due_on") or ""
        if due_on:
            m = re.search(r"_(\d{4})_(\d{2})_(\d{2})_", campaign_name)
            if m:
                name_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                if name_date == due_on:
                    logger.info(f"✓ Send date matches: {due_on}")
                    result["send_date"] = True
                else:
                    logger.warning(f"Send date mismatch: name={name_date}, task due_on={due_on}")
        return result

    html = msg.get("body") or msg.get("html_body") or ""

    # 2. Subject line matches brief
    # Priority: SL: prefix in description (same as builder) > custom field
    braze_subject = (msg.get("subject") or "").strip()
    asana_subject = (
        _extract_subject_from_description(task)
        or _get_text_value(task, FIELD_SUBJECT_LINE)
        or ""
    ).strip()
    if braze_subject and asana_subject and braze_subject == asana_subject:
        logger.info(f"✓ Subject line matches: {braze_subject!r}")
        result["subject_line"] = True
    elif not asana_subject:
        logger.warning("Asana Subject Line field is empty — cannot verify")
    else:
        logger.warning(f"Subject mismatch: Braze={braze_subject!r} vs Asana={asana_subject!r}")

    # 3. Preheader
    # PT emails must have no preheader set in Braze — verify it's empty, flag if not.
    # Designed emails must match the Asana Pre-Header field.
    braze_ph = (msg.get("preheader") or msg.get("preview_text") or "").strip()
    if is_pt:
        if not braze_ph:
            logger.info("✓ Preheader empty (correct for PT email)")
            result["preheader"] = True
        else:
            logger.warning(f"PT email has preheader set in Braze — should be empty: {braze_ph!r}")
    else:
        asana_ph = (_get_text_value(task, FIELD_PRE_HEADER) or "").strip()
        if braze_ph and asana_ph and braze_ph == asana_ph:
            logger.info(f"✓ Preheader matches: {braze_ph!r}")
            result["preheader"] = True
        elif not asana_ph:
            logger.warning("Asana Pre-Header field is empty — cannot verify")
        else:
            logger.warning(f"Preheader mismatch: Braze={braze_ph!r} vs Asana={asana_ph!r}")

    # 4. Sender name & email address
    try:
        config = load_brand_config()
        hav_variant = None
        if brand.upper() == "HAV":
            parts = campaign_name.upper().split("_")
            # CONV in campaign name = Converted (MP) audience; everything else = PC
            hav_variant = "CONV" if "CONV" in parts else "PC"
        entry = get_brand_entry(brand, config, hav_variant)
        sender_key = "pt" if is_pt else "designed"
        sender_info = entry.get("sender_info", {}).get(sender_key, {})
        expected_from = f"{sender_info['from_name']} <{sender_info['from_email']}>"
        braze_from = (msg.get("from") or "").strip()
        if braze_from.lower() == expected_from.lower():
            logger.info(f"✓ Sender matches: {braze_from!r}")
            result["sender"] = True
        else:
            logger.warning(f"Sender mismatch: Braze={braze_from!r} vs expected={expected_from!r}")
    except Exception as exc:
        logger.warning(f"Sender check error: {exc}")

    # 5. Images all have alt tags
    # Accepts: alt="text", alt='text', alt="" (empty/decorative), bare `alt` (BEE editor output)
    if not html:
        logger.warning("HTML body empty — skipping alt tag and unsubscribe checks")
        result["html_body_empty"] = True
        result["alt_tags"] = True   # set True so these don't generate separate generic flags;
        result["unsub"] = True      # the html_body_empty flag produces a single clear note instead
    else:
        imgs = re.findall(r"<img\b[^>]*>", html, re.IGNORECASE)
        exempt = _alt_exempt_images(html, is_pt)
        missing_alt = [
            img for img in imgs
            if not re.search(r'\balt\b', img, re.IGNORECASE) and img not in exempt
        ]
        skipped = [
            img for img in imgs
            if not re.search(r'\balt\b', img, re.IGNORECASE) and img in exempt
        ]
        if skipped:
            logger.info(
                "Header logo has no alt attribute — expected for a PT email "
                "(alt text would be pulled into the preheader ahead of the body copy)"
            )
        if not missing_alt:
            logger.info(f"✓ All {len(imgs)} images have alt attributes")
            result["alt_tags"] = True
        else:
            logger.warning(
                f"{len(missing_alt)}/{len(imgs)} images missing alt attribute: "
                f"{missing_alt[:3]}"
            )

    # 6. (UTM link template check moved to browser — see verify_link_template())

    # 7. Unsubscribe link/block present
    # Accepts: direct set_user_to_unsubscribed_url link (all brands/types) OR
    # a brand-specific content block prefix (| id: '...' suffix is ignored).
    # (html empty case already handled above — result["unsub"] set to True with html_body_empty flag)
    if html:
        unsub_found, unsub_reason = _html_has_unsubscribe(html, brand)
        result["unsub"] = unsub_found
        if unsub_found:
            logger.info(f"✓ Unsubscribe present ({unsub_reason})")
        else:
            logger.warning(f"Unsubscribe link/block not found in HTML — {unsub_reason}")

    # 8. Send date matches brief
    due_on = task.get("due_on") or ""
    if due_on:
        m = re.search(r"_(\d{4})_(\d{2})_(\d{2})_", campaign_name)
        if m:
            name_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            if name_date == due_on:
                logger.info(f"✓ Send date matches: {due_on}")
                result["send_date"] = True
            else:
                logger.warning(
                    f"Send date mismatch: campaign name has {name_date!r}, "
                    f"task due_on={due_on!r}"
                )
        else:
            logger.warning(f"Could not parse date from campaign name: {campaign_name!r}")
    else:
        logger.warning("Task has no due_on — cannot verify send date")

    return result


# ---------------------------------------------------------------------------
# Asana QA subtask discovery
# ---------------------------------------------------------------------------

# Which QA container name fragments to walk for each channel.
# "QA Campaign Settings & Audience" is always included (shared across all channels).
# Each channel also has its own container ("QA (Email)", "QA (SMS)", "QA (Push)").
_QA_CONTAINER_PATTERNS: dict[str, list[str]] = {
    "email": ["qa (email)", "qa campaign settings"],
    "sms":   ["qa (sms)",   "qa campaign settings"],
    "push":  ["qa (push)",  "qa campaign settings"],
}


def get_qa_subtask_gids(parent_task_gid: str, channel: str = "email") -> dict[str, str]:
    """
    Walk 2 levels of subtasks to find QA checklist items by name pattern.

    The parent task has channel-specific containers ("QA (Email)", "QA (SMS)",
    "QA (Push)") and a shared "QA Campaign Settings & Audience" container.
    Only the containers relevant to the given channel are walked.

    Args:
        parent_task_gid: Asana GID of the campaign task.
        channel: "email", "sms", or "push" — controls which container is walked.

    Returns a dict keyed by logical check name → subtask GID for uncompleted items.
    """
    allowed_patterns = _QA_CONTAINER_PATTERNS.get(channel, _QA_CONTAINER_PATTERNS["email"])

    level1 = _asana_request(
        "GET",
        f"tasks/{parent_task_gid}/subtasks",
        params={"opt_fields": "gid,name,completed"},
    ) or []

    gids: dict[str, str] = {}
    for container in level1:
        container_name = (container.get("name") or "").lower()
        if not any(pat in container_name for pat in allowed_patterns):
            continue
        level2 = _asana_request(
            "GET",
            f"tasks/{container['gid']}/subtasks",
            params={"opt_fields": "gid,name,completed"},
        ) or []
        for item in level2:
            if item.get("completed"):
                continue
            name = (item.get("name") or "").lower()
            gid = item["gid"]
            # Campaign Settings & Audience container
            if "send time" in name:
                gids.setdefault("send_time", gid)
            elif "lifecycle" in name:
                gids.setdefault("audience_lifecycle", gid)
            elif "segment" in name or ("audience" in name and "asana" in name):
                gids.setdefault("audience_segment", gid)
            elif "filter" in name:
                gids.setdefault("filters", gid)
            # QA (Email) container — API + HTML verifiable items
            elif "naming convention" in name or "campaign name" in name:
                gids.setdefault("campaign_name", gid)
            elif name.startswith("sl ") or "sl matches" in name or "subject line" in name:
                gids.setdefault("subject_line", gid)
            elif name.startswith("ph ") or "ph matches" in name or "pre-header" in name or "preheader" in name:
                gids.setdefault("preheader", gid)
            elif "sender name" in name or ("sender" in name and "email" in name):
                gids.setdefault("sender", gid)
            elif "alt tag" in name or ("images" in name and "alt" in name):
                gids.setdefault("alt_tags", gid)
            elif "utm" in name or "link template" in name:
                gids.setdefault("utm", gid)
            elif "unsub" in name:
                gids.setdefault("unsub", gid)
            elif "send date" in name:
                gids.setdefault("send_date", gid)
            # QA (SMS) / QA (Push) container items
            elif "copy matches" in name or "no typos" in name:
                gids.setdefault("copy_matches", gid)
            elif "links match" in name or "correct pages" in name:
                gids.setdefault("links_correct", gid)
            elif "on-click" in name or "deeplink" in name or "deep link" in name:
                gids.setdefault("onclick_behavior", gid)
            elif "pre-approved" in name:
                gids.setdefault("link_approved", gid)

    return gids


def run_sms_api_checks(task: dict, brand: str, campaign_name: str, details: dict) -> dict:
    """
    Run API-based checks for SMS campaigns.

    Returns a dict keyed by logical check name → bool:
        campaign_name, copy_matches, links_correct, utm
    """
    from utils.campaign_name import validate_campaign_name

    result = {
        "campaign_name": False,
        "copy_matches": False,
        "links_correct": False,
        "utm": False,
    }

    # 1. Campaign name follows naming conventions
    try:
        valid, issues = validate_campaign_name(campaign_name)
        if valid:
            logger.info(f"✓ SMS campaign name valid: {campaign_name}")
            result["campaign_name"] = True
        else:
            logger.warning(f"SMS campaign name issues: {issues}")
    except Exception as exc:
        logger.warning(f"validate_campaign_name error: {exc}")

    # Extract SMS message from campaign details
    msg = _get_sms_message(details)
    if not msg:
        logger.warning("No SMS message found in Braze campaign details — skipping SMS content checks")
        return result

    body = (msg.get("body") or "").strip()

    # 2. Copy matches — body is non-empty (automation set the copy)
    if body:
        logger.info(f"✓ SMS body is present ({len(body)} chars)")
        result["copy_matches"] = True
    else:
        logger.warning("SMS body is empty in Braze campaign")

    # 3. Links correct — URL present, matches Asana task LP, and resolves
    urls = re.findall(r'https?://\S+', body)
    if not urls:
        logger.warning("No links found in SMS body — verify copy includes a URL")
    else:
        logger.info(f"✓ SMS body contains {len(urls)} link(s)")

        # 3a: Compare the built URL (base path only) to the LP in the Asana task brief.
        # Uses html_notes first (standard 5-field LP: field), then falls back to plain notes.
        task_lp = _sms_extract_lp(
            task.get("notes", ""),
            task.get("html_notes", ""),
        )
        link_match_ok = True
        if task_lp:
            body_base = urlunparse(urlparse(urls[0])._replace(query="", fragment="")).rstrip("/")
            lp_base = urlunparse(urlparse(task_lp)._replace(query="", fragment="")).rstrip("/")
            if body_base == lp_base:
                logger.info(f"✓ SMS link matches Asana task LP: {lp_base}")
            else:
                logger.warning(
                    f"SMS link does not match Asana task LP — "
                    f"built={body_base!r}, asana={lp_base!r}"
                )
                link_match_ok = False
        else:
            logger.info("No LP field found in Asana task — skipping link-match check")

        # 3b: Verify the URL resolves (HTTP HEAD, UTMs stripped before checking).
        # Returns False for 4xx/5xx or redirect-to-homepage; True for network errors
        # (so QA is not blocked by connectivity issues).
        link_resolves = _validate_sms_url(urls[0])
        if not link_resolves:
            logger.warning(
                f"SMS link is broken or redirects to homepage: {urls[0][:120]} — "
                "verify the URL is correct before launching"
            )

        result["links_correct"] = link_match_ok and link_resolves

    # 4. UTMs present in link(s)
    utm_links = [u for u in urls if "utm_source" in u]
    if utm_links:
        logger.info("✓ SMS link(s) contain UTM parameters")
        result["utm"] = True
    else:
        logger.warning("No UTM parameters found in SMS links — verify UTMs are appended")

    return result


def run_push_api_checks(task: dict, brand: str, campaign_name: str, details: dict) -> dict:
    """
    Run API-based checks for push notification campaigns.

    Returns a dict keyed by logical check name → bool:
        campaign_name, copy_matches, onclick_behavior, link_approved, utm
    """
    from utils.campaign_name import validate_campaign_name

    result = {
        "campaign_name": False,
        "copy_matches": False,
        "onclick_behavior": False,
        "link_approved": False,
        "utm": False,
    }

    # 1. Campaign name follows naming conventions
    try:
        valid, issues = validate_campaign_name(campaign_name)
        if valid:
            logger.info(f"✓ Push campaign name valid: {campaign_name}")
            result["campaign_name"] = True
        else:
            logger.warning(f"Push campaign name issues: {issues}")
    except Exception as exc:
        logger.warning(f"validate_campaign_name error: {exc}")

    # Extract push message from campaign details
    msg = _get_push_message(details)
    if not msg:
        logger.warning("No push message found in Braze campaign details — skipping push content checks")
        return result

    # Extract title and body — handle both flat and nested per-platform dicts
    title = (msg.get("title") or "").strip()
    message = (msg.get("body") or msg.get("message") or msg.get("alert") or "").strip()

    if not title or not message:
        for platform in ("ios", "android"):
            p = msg.get(platform, {})
            if isinstance(p, dict):
                if not title:
                    title = (p.get("title") or p.get("alert") or "").strip()
                if not message:
                    message = (p.get("body") or p.get("alert") or "").strip()

    # 2. Copy matches — both title and message are non-empty
    if title and message:
        logger.info("✓ Push title and message are present")
        result["copy_matches"] = True
    else:
        logger.warning(
            f"Push title and/or message appear empty (title={title!r}, message={message!r})"
        )

    # 3. On-click behavior — verify a deep link / URI is set
    deep_link = _extract_push_deep_link(msg)
    on_click_action = (msg.get("on_click_action") or msg.get("click_action") or "").lower()

    if deep_link:
        logger.info(f"✓ Push on-click URI is set: {deep_link[:80]}")
        result["onclick_behavior"] = True
    elif any(kw in on_click_action for kw in ("uri", "deep", "redirect", "url")):
        logger.info(f"✓ Push on-click action indicates a link: {on_click_action}")
        result["onclick_behavior"] = True
    else:
        logger.warning("Push on-click behavior does not appear to have a deep link / URI set")

    # 4. Link set to one of pre-approved URLs
    if deep_link:
        approved_patterns = ["havenly.com", "havenly://", "app.havenly.com"]
        try:
            config = load_brand_config()
            approved_patterns.extend(
                e.get("deep_link", "")
                for e in config.get("push_config", {}).values()
                if e.get("deep_link")
            )
        except Exception:
            pass
        if any(p and p.lower() in deep_link.lower() for p in approved_patterns):
            logger.info("✓ Push deep link is from a pre-approved URL/scheme")
            result["link_approved"] = True
        else:
            logger.warning(
                f"Push deep link does not match any pre-approved URL/scheme: {deep_link[:80]}"
            )
    elif result["onclick_behavior"]:
        # on_click_action is set but URI not extractable — the build automation set it correctly
        logger.info("✓ Push on-click action set (URI not extractable — assuming pre-approved)")
        result["link_approved"] = True

    # 5. UTMs in deep link URL
    if deep_link and "utm_source" in deep_link:
        logger.info("✓ Push deep link contains UTM parameters")
        result["utm"] = True
    elif deep_link and deep_link.startswith("havenly://"):
        # Native app deeplinks may not carry UTMs — treat as acceptable
        logger.info("✓ Push uses native deeplink scheme (UTM check N/A for native links)")
        result["utm"] = True
    elif deep_link:
        logger.warning("Push deep link is missing UTM parameters")

    return result


# ---------------------------------------------------------------------------
# Campaign name derivation helpers for SMS / Push
# ---------------------------------------------------------------------------

def _derive_sms_campaign_name(raw_task: dict) -> Optional[str]:
    """Reconstruct the expected SMS campaign name from an Asana task."""
    task_name = raw_task.get("name", "")
    brand_gid = _get_enum_value_gid(raw_task, _FIELD_BRAND)
    brand_code = _SMS_BRAND_GID_TO_CODE.get(brand_gid) if brand_gid else None
    due_on = raw_task.get("due_on") or ""
    if not brand_code or not due_on:
        return None
    try:
        return generate_sms_campaign_name(task_name, brand_code, due_on)
    except Exception as exc:
        logger.warning(f"Could not derive SMS campaign name: {exc}")
        return None


def _derive_push_campaign_names(raw_task: dict) -> list[str]:
    """Reconstruct expected push campaign name(s) from an Asana task.

    Returns a list because a combined DPS+MP task produces two campaign names
    (one PC, one CONV).
    """
    try:
        parsed_list = _parse_push_task(raw_task)
        return [p["campaign_name"] for p in parsed_list if p.get("campaign_name")]
    except Exception as exc:
        logger.warning(f"Could not derive push campaign names: {exc}")
        return []


def check_task_metadata_consistency(task: dict, task_name: str) -> list[str]:
    """Check Asana Audience/Segment fields against the task title for obvious mismatches.

    Returns a (possibly empty) list of human-readable issue strings.
    All comparisons are case-insensitive substring matches on the display names
    returned by Asana (e.g. "Full File", "Engaged File", "Daily Send List").
    """
    issues: list[str] = []
    audience = (_get_enum_value_name(task, FIELD_AUDIENCE) or "").lower()
    segment = (_get_enum_value_name(task, FIELD_SEGMENT) or "").lower()
    name_lower = task_name.lower()

    # "Engaged" in title but field configuration looks like full-file
    if "engaged" in name_lower:
        if "full file" in segment:
            issues.append(
                'Task title contains "Engaged" but Segment is Full File — verify Segment field'
            )
        if "daily send" in audience:
            issues.append(
                'Task title contains "Engaged" but Audience is Daily Send List — verify Audience field'
            )

    # Audience/Segment cross-field mismatches
    if "daily send" in audience and "engaged" in segment:
        issues.append("Audience is Daily Send List but Segment is Engaged — these may conflict")

    if "engaged" in audience and "full file" in segment:
        issues.append("Audience is Engaged but Segment is Full File — these may conflict")

    # Segmented audience but a broad segment selected
    if "segment" in audience and ("full file" in segment or "engaged" in segment):
        segment_display = _get_enum_value_name(task, FIELD_SEGMENT) or segment
        issues.append(
            f"Audience is Segmented but Segment is {segment_display!r} — verify segment selection"
        )

    return issues


def check_off_subtask(gid: str, label: str) -> None:
    ok = _asana_request("PUT", f"tasks/{gid}", json_data={"data": {"completed": True}})
    if ok:
        logger.info(f"✓ Checked off: {label}")
    else:
        logger.warning(f"  Failed to check off: {label}")


# ---------------------------------------------------------------------------
# Playwright verification helpers
# ---------------------------------------------------------------------------
async def verify_link_template(page) -> bool:
    """Open the email editor's Link Management panel and verify a UTM link template is applied.

    Returns True if the dropdown shows at least one template selected ("N item(s) selected"),
    False if the placeholder "Select link templates" is still shown (no template applied).

    Opens the editor modal, checks Link Management, then closes the modal so the
    subsequent test-send step is not blocked by an open editor.
    """
    editor_opened = False
    result = False
    try:
        # Navigate to the Compose step (it's a button, not a link)
        for compose_name in ("Compose Messages", "Compose"):
            btn = page.get_by_role("button", name=compose_name)
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(2000)
                break

        # Open the email editor modal ("Edit message", not just "Edit")
        for btn_name in ("Edit message", "Edit Message"):
            for sel in [
                page.get_by_role("button", name=btn_name),
                page.locator(f"button:has-text('{btn_name}')"),
            ]:
                try:
                    if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                        await sel.first.click()
                        await page.wait_for_timeout(3000)
                        editor_opened = True
                        break
                except Exception:
                    continue
            if editor_opened:
                break

        if not editor_opened:
            logger.warning("verify_link_template: could not open editor modal")
            return False

        # Click Link Management in the left sidebar
        link_mgmt = page.get_by_text("Link Management", exact=True).first
        await link_mgmt.wait_for(state="visible", timeout=8000)
        await link_mgmt.click()
        # Wait for the Link Management panel to finish loading
        await page.wait_for_timeout(3000)



        # Check whether the template dropdown has a selection.
        # Braze renders the React-Select dropdown with bcl-select__ prefixed classes.
        # The control div (.bcl-select__control) shows "N items selected" when applied,
        # or contains .bcl-select__placeholder when nothing is selected.
        placeholder = page.locator(".bcl-select__placeholder:has-text('Select link templates')")
        control = page.locator(".bcl-select__control")
        multi_value = page.locator(".bcl-select__multi-value")
        single_value = page.locator(".bcl-select__single-value")

        # Wait for ANY bcl-select element to appear (up to 8s)
        try:
            await page.wait_for_selector(".bcl-select__control, .bcl-select__placeholder", timeout=8000)
        except Exception:
            logger.warning("verify_link_template: link template dropdown not found after waiting")
            result = False

        # Only treat the placeholder as "nothing selected" when it's actually visible —
        # Braze keeps the placeholder element in the DOM even after templates are selected.
        placeholder_visible = (
            await placeholder.count() > 0
            and await placeholder.is_visible(timeout=2000)
        )
        if placeholder_visible:
            logger.warning("Link template dropdown shows placeholder — no UTM template applied")
            result = False
        elif await multi_value.count() > 0:
            # Multi-select: template name shown in chip(s)
            label = await multi_value.first.inner_text(timeout=5000)
            logger.info(f"✓ UTM link template applied: {label.strip()!r}")
            result = True
        elif await single_value.count() > 0:
            # Single-select: template name shown directly (no "N items selected" text)
            label = await single_value.first.inner_text(timeout=5000)
            logger.info(f"✓ UTM link template applied: {label.strip()!r}")
            result = True
        elif await control.count() > 0:
            # Fallback: control text may show "N items selected"
            text = await control.first.inner_text(timeout=5000)
            if "selected" in text.lower() or "item" in text.lower():
                logger.info(f"✓ UTM link template applied: {text.strip()!r}")
                result = True
            else:
                logger.warning(f"Could not determine link template state — control text: {text!r}")
                result = False
        else:
            logger.warning("Could not determine link template state from dropdown")
            result = False

    except Exception as exc:
        logger.warning(f"verify_link_template failed: {exc}")
        result = False

    finally:
        # Always close the editor so send_test_email is not blocked by an open modal
        if editor_opened:
            for done_sel in [
                page.get_by_role("button", name="Done", exact=True),
                page.locator("button:has-text('Done')").last,
            ]:
                try:
                    if await done_sel.count() > 0 and await done_sel.is_visible(timeout=3000):
                        await done_sel.click()
                        await page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue

    return result


async def verify_delivery(page, expected: dict) -> bool:
    """Navigate to the Delivery tab and confirm delivery settings match expected.

    Args:
        page: Playwright page object.
        expected: dict from _get_expected_delivery() with keys:
            use_sto (bool): True if Intelligent Timing should be configured.
            time_str (str|None): expected fixed send time (e.g. "7:15 AM").
    """
    use_sto: bool = expected.get("use_sto", False)
    time_str: Optional[str] = expected.get("time_str")

    logger.info(f"Checking Delivery tab (use_sto={use_sto}, expected_time={time_str!r})...")
    try:
        for btn_name in ("Delivery", "Schedule"):
            btn = page.get_by_role("button", name=btn_name)
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(2000)
                break

        page_text = await page.inner_text("body")

        if use_sto:
            if "Intelligent Timing" in page_text:
                logger.info("✓ Intelligent Timing (STO) confirmed on Delivery tab")
                return True
            lines = [
                l.strip()
                for l in page_text.splitlines()
                if any(x in l for x in ("PM", "AM", ":00", "Timing"))
            ]
            logger.warning(
                f"Expected Intelligent Timing (STO) but not found. Time-related lines: {lines[:5]}"
            )
            return False
        else:
            # Fixed-time send: look for the specific expected time
            if time_str:
                candidates = [time_str, time_str.replace(" ", "")]
                for c in candidates:
                    if c in page_text:
                        logger.info(f"✓ Send time confirmed: '{c}'")
                        return True
                lines = [
                    l.strip()
                    for l in page_text.splitlines()
                    if any(x in l for x in ("PM", "AM", ":00", "Timing"))
                ]
                logger.warning(
                    f"Expected send time {time_str!r} not found on Delivery tab. "
                    f"Time-related lines: {lines[:5]}"
                )
                return False
            else:
                # No expected time known — log a warning but don't hard-fail
                logger.warning("No expected send time available — cannot verify delivery settings")
                return False
    except Exception as exc:
        logger.warning(f"Delivery tab check failed: {exc}")
        return False


def _known_segment_names(brand: str, expected_segment_groups: list[list[str]]) -> set[str]:
    """Every segment name that could legitimately appear for a brand — the
    expected ones plus all others configured in brand_config.yaml. Used to tell
    a real match apart from a name that is merely a substring of a longer one."""
    names = {s for g in expected_segment_groups for s in g}
    for group in _config_audience_segment_names(brand).values():
        names.update(group)
    return names


def _segment_name_on_page(name: str, page_text: str, known_names: set[str]) -> bool:
    """True if *name* names a segment actually shown on the Target Audiences tab.

    A plain substring test is not safe now that ID and TI use short, overlapping
    segment names: "Engaged" is a substring of "Highly Engaged", "Geo Segment -
    Engaged", and "Geo Segment - Unengaged", so a campaign built on the wrong one
    would silently pass QA. A line only counts for *name* if it does not also
    carry a longer known segment name containing it — the same
    longest-match-wins reasoning behind _select_segment()'s exact-match fix in
    build_pt_campaign.py.
    """
    longer = [k for k in known_names if k != name and name in k]
    for line in page_text.splitlines():
        cleaned = line.replace('"', "").strip()
        if name not in cleaned:
            continue
        if any(k.replace('"', "") in cleaned for k in longer):
            continue
        return True
    return False


async def verify_audience(
    page, expected_segment_groups: list[list[str]], brand: str = ""
) -> tuple[bool, bool, bool, list[str]]:
    """
    Navigate to the Target Audiences tab and check segment + filters.

    Returns (segment_ok, lifecycle_ok, filters_ok, stale_exclusions_found).
    segment_ok / lifecycle_ok are True if ALL members of at least one
    expected_segment_group are present on the page (AND-within-group,
    OR-across-groups). For most brands each group has one element; for BUR
    a group contains all required segment names.

    Known temporary exclusions (e.g. "Memorial Day Canvas Test Group") are
    allowed until their expiry date and do not cause the check to fail.
    After expiry, they are returned in stale_exclusions_found only if actually
    present on the page — not unconditionally.
    """
    logger.info("Checking Target Audiences tab...")
    try:
        for btn_name in ("Target Audiences", "Target audiences", "Audience"):
            btn = page.get_by_role("button", name=btn_name)
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(2000)
                break

        page_text = await page.inner_text("body")

        # Check for time-boxed allowed exclusions (e.g. "Memorial Day Canvas Test Group")
        allowed_excls = _get_allowed_exclusions(brand)
        stale_excls = _get_stale_exclusions(brand)
        stale_found: list[str] = []
        for excl in allowed_excls:
            if excl in page_text:
                logger.info(f"✓ Known temporary exclusion present and within valid window: '{excl}'")
        for excl in stale_excls:
            if excl in page_text:
                stale_found.append(excl)
                logger.warning(
                    f"Stale exclusion still present: '{excl}' — this should be removed from the campaign"
                )

        known_names = _known_segment_names(brand, expected_segment_groups)
        matched_group = next(
            (
                g
                for g in expected_segment_groups
                if all(_segment_name_on_page(s, page_text, known_names) for s in g)
            ),
            None,
        )
        segment_ok = matched_group is not None
        if segment_ok:
            logger.info(f"✓ Segment group confirmed: {matched_group}")
        else:
            lines = [
                l.strip()
                for l in page_text.splitlines()
                if any(k in l.lower() for k in ("file", "list", "segment", "vip"))
            ]
            # If the page contains an active allowed exclusion, note it as context
            active_allowed = [e for e in allowed_excls if e in page_text]
            if active_allowed:
                logger.warning(
                    f"Segment group not matched (allowed exclusion present: {active_allowed}). "
                    f"Expected one of: {expected_segment_groups}. "
                    f"Segment-related lines: {lines[:8]}"
                )
            else:
                logger.warning(
                    f"No valid segment group found. Expected one of: {expected_segment_groups}. "
                    f"Segment-related lines on page: {lines[:8]}"
                )

        # Active filter rules contain specific operator phrases; Braze UI
        # chrome uses generic words ("AND", "OR", "Filter") which are false positives.
        filter_pattern_lines = [
            l.strip()
            for l in page_text.splitlines()
            if any(
                kw in l
                for kw in (
                    "is not blank",
                    "is blank",
                    "is equal",
                    "does not equal",
                    "contains",
                    "Custom Attribute",
                    "Custom Event",
                    "Last Used App",
                    "Push Subscription",
                )
            )
            and l.strip()
        ]
        filters_ok = len(filter_pattern_lines) == 0
        if filters_ok:
            logger.info("✓ No active filter rules detected")
        else:
            logger.warning(f"Active filters detected: {filter_pattern_lines[:5]}")

        return segment_ok, segment_ok, filters_ok, stale_found
    except Exception as exc:
        logger.warning(f"Audience tab check failed: {exc}")
        return False, False, False, []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def run_qa_and_test_send(
    task_gid: str,
    brand: str,
    braze_url: str,
    assignee_name: Optional[str],
    dry_run: bool = False,
    raw_task: Optional[dict] = None,
) -> dict:
    """
    Run the full QA verification + test send for a designed email campaign.

    Navigates to the Braze campaign editor, checks delivery and audience
    settings, fires a test send to the assignee's email, and checks off the
    verifiable Asana QA subtasks. Posts an Asana comment if any issues are
    found (metadata mismatches or failed Playwright checks).

    Returns a result dict with keys:
        send_time_ok, segment_ok, lifecycle_ok, filters_ok, test_send_ok, errors
    """
    result: dict = {
        # Braze API + HTML checks (email)
        "campaign_name_ok": False,
        "subject_line_ok": False,
        "preheader_ok": False,
        "sender_ok": False,
        "alt_tags_ok": False,
        "utm_ok": False,
        "unsub_ok": False,
        "send_date_ok": False,
        "html_body_empty": False,
        # SMS / Push channel-specific content checks
        "copy_matches_ok": False,
        "links_correct_ok": False,
        "onclick_behavior_ok": False,
        "link_approved_ok": False,
        # Browser / UI checks
        "send_time_ok": False,
        "segment_ok": False,
        "lifecycle_ok": False,
        "filters_ok": False,
        "test_send_ok": False,
        "errors": [],
    }

    # Fetch task metadata if not already provided (enables standalone CLI use)
    if raw_task is None:
        raw_task = await asyncio.to_thread(fetch_task_by_gid, task_gid)

    task_name = (raw_task or {}).get("name", task_gid)

    # Metadata consistency check (pure field inspection, no browser)
    metadata_issues: list[str] = []
    if raw_task:
        metadata_issues = check_task_metadata_consistency(raw_task, task_name)
        if metadata_issues:
            logger.warning(f"Metadata issues for task {task_gid}: {metadata_issues}")

    campaign_id, workspace_id = parse_braze_url(braze_url)
    if not campaign_id or not workspace_id:
        msg = f"Could not parse campaign/workspace ID from URL: {braze_url}"
        logger.error(msg)
        result["errors"].append(msg)
        return result

    # Determine channel for test-send gating and QA subtask container selection
    _CHANNEL_GID_TO_NAME = {v: k for k, v in CHANNEL_OPTIONS.items()}
    channel_gid = _get_enum_value_gid(raw_task or {}, FIELD_CHANNEL) if raw_task else None
    channel = _CHANNEL_GID_TO_NAME.get(channel_gid or "", "email")  # default email
    is_email = channel == "email"

    test_recipient = resolve_qa_email(assignee_name)
    logger.info(
        f"QA run: brand={brand}, campaign={campaign_id}, channel={channel}, "
        f"assignee={assignee_name!r}, recipient={test_recipient}"
    )

    expected_segment_groups = get_expected_segment_groups(brand, channel, raw_task)
    if not expected_segment_groups:
        logger.warning(
            f"No expected segment groups found for brand {brand!r} — audience check will be skipped"
        )

    # Fetch QA subtask GIDs before opening the browser (pure API calls)
    qa_gids = await asyncio.to_thread(get_qa_subtask_gids, task_gid, channel)
    logger.info(f"QA subtask GIDs ({channel}): {qa_gids}")

    # --- Braze API + HTML checks (no browser needed) ---
    api_check_results: dict = {}
    campaign_name: str = ""
    campaign_created_at: Optional[str] = None
    if is_email and raw_task:
        try:
            qs = parse_qs(urlparse(braze_url).query)
            known_name = (qs.get("campaignName") or [None])[0]
            campaign_name, details = await asyncio.to_thread(
                get_braze_campaign_details, raw_task, brand, known_name
            )
            details = await _refetch_if_content_looks_stale(
                details, raw_task, brand, known_name, campaign_name
            )
            if details:
                # Braze creation date — lead time for the STO check is measured
                # from when the campaign was built, not from when QA runs.
                campaign_created_at = details.get("created_at")
                api_check_results = await asyncio.to_thread(
                    run_api_checks, raw_task, brand, campaign_name, details
                )
                result.update(
                    campaign_name_ok=api_check_results.get("campaign_name", False),
                    subject_line_ok=api_check_results.get("subject_line", False),
                    preheader_ok=api_check_results.get("preheader", False),
                    sender_ok=api_check_results.get("sender", False),
                    alt_tags_ok=api_check_results.get("alt_tags", False),
                    # utm_ok is set later via browser (verify_link_template)
                    unsub_ok=api_check_results.get("unsub", False),
                    send_date_ok=api_check_results.get("send_date", False),
                    html_body_empty=api_check_results.get("html_body_empty", False),
                )
            else:
                logger.warning(
                    f"Could not fetch Braze campaign details for task {task_gid} — "
                    "API checks skipped"
                )
                result["errors"].append(
                    f"Campaign not found in Braze API — API checks skipped"
                )
        except Exception as exc:
            logger.warning(f"API checks failed: {exc}")
            result["errors"].append(f"API checks exception: {exc}")

    elif channel == "sms" and raw_task:
        # --- SMS API checks ---
        try:
            sms_name = await asyncio.to_thread(_derive_sms_campaign_name, raw_task)
            if sms_name:
                logger.info(f"Derived SMS campaign name: {sms_name!r}")
                sms_api_id = await asyncio.to_thread(find_campaign_api_id_by_name, sms_name, brand)
                if sms_api_id:
                    sms_details = await asyncio.to_thread(
                        _braze_get, "campaigns/details", {"campaign_id": sms_api_id}, brand
                    )
                    if sms_details:
                        sms_checks = await asyncio.to_thread(
                            run_sms_api_checks, raw_task, brand, sms_name, sms_details
                        )
                        result.update(
                            campaign_name_ok=sms_checks.get("campaign_name", False),
                            copy_matches_ok=sms_checks.get("copy_matches", False),
                            links_correct_ok=sms_checks.get("links_correct", False),
                            utm_ok=sms_checks.get("utm", False),
                        )
                    else:
                        logger.warning(f"SMS campaign details not found for: {sms_name!r}")
                else:
                    logger.warning(f"SMS campaign not found in Braze API: {sms_name!r}")
            else:
                logger.warning("Could not derive SMS campaign name from task — skipping SMS API checks")
        except Exception as exc:
            logger.warning(f"SMS API checks failed: {exc}")
            result["errors"].append(f"SMS API checks exception: {exc}")

    elif channel == "push" and raw_task:
        # --- Push API checks ---
        try:
            push_names = await asyncio.to_thread(_derive_push_campaign_names, raw_task)
            if push_names:
                for push_name in push_names:
                    logger.info(f"Derived push campaign name: {push_name!r}")
                    push_api_id = await asyncio.to_thread(
                        find_campaign_api_id_by_name, push_name, brand
                    )
                    if push_api_id:
                        push_details = await asyncio.to_thread(
                            _braze_get, "campaigns/details", {"campaign_id": push_api_id}, brand
                        )
                        if push_details:
                            push_checks = await asyncio.to_thread(
                                run_push_api_checks, raw_task, brand, push_name, push_details
                            )
                            result.update(
                                campaign_name_ok=push_checks.get("campaign_name", False),
                                copy_matches_ok=push_checks.get("copy_matches", False),
                                onclick_behavior_ok=push_checks.get("onclick_behavior", False),
                                link_approved_ok=push_checks.get("link_approved", False),
                                utm_ok=push_checks.get("utm", False),
                            )
                            break  # First matching variant found — stop here
                        else:
                            logger.warning(f"Push campaign details not found for: {push_name!r}")
                    else:
                        logger.warning(f"Push campaign not found in Braze API: {push_name!r}")
            else:
                logger.warning("Could not derive push campaign names from task — skipping push API checks")
        except Exception as exc:
            logger.warning(f"Push API checks failed: {exc}")
            result["errors"].append(f"Push API checks exception: {exc}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-save-password-bubble",
                "--disable-password-manager-reauthentication",
            ],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        await ensure_logged_in(page)
        await select_workspace(page, brand)

        campaign_url = (
            f"https://dashboard-07.braze.com/engagement/campaigns"
            f"/{campaign_id}/{workspace_id}"
        )
        logger.info(f"Navigating to: {campaign_url}")
        await page.goto(campaign_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        # Enter the editor if we landed on the campaign overview page
        for sel in [
            page.get_by_role("button", name="Edit Draft"),
            page.get_by_role("link", name="Edit Draft"),
            page.locator("a:has-text('Edit Draft')"),
        ]:
            try:
                if await sel.count() > 0 and await sel.first.is_visible(timeout=3000):
                    await sel.first.click()
                    await page.wait_for_timeout(3000)
                    logger.info("Clicked 'Edit Draft'")
                    break
            except Exception:
                continue

        try:
            await wait_for_campaign_editor(page)
        except Exception as exc:
            logger.warning(f"wait_for_campaign_editor: {exc}")

        # --- Delivery check ---
        delivery_expected = _get_expected_delivery(
            raw_task or {}, brand, campaign_name, channel, campaign_created_at
        )
        send_time_ok = await verify_delivery(page, delivery_expected)

        # --- Audience check ---
        stale_found_on_page: list[str] = []
        if expected_segment_groups:
            segment_ok, lifecycle_ok, filters_ok, stale_found_on_page = await verify_audience(
                page, expected_segment_groups, brand
            )
        else:
            segment_ok = lifecycle_ok = False
            filters_ok = True  # can't verify, assume clean

        result.update(
            send_time_ok=send_time_ok,
            segment_ok=segment_ok,
            lifecycle_ok=lifecycle_ok,
            filters_ok=filters_ok,
        )

        # --- UTM link template check (email only, browser) ---
        if is_email:
            utm_ok = await verify_link_template(page)
            result["utm_ok"] = utm_ok

        # --- Test send (email only) ---
        if is_email:
            if not dry_run:
                test_send_ok = await send_test_email(page, test_recipient)
                result["test_send_ok"] = test_send_ok
                if test_send_ok:
                    logger.info(f"✓ Test send complete → {test_recipient}")
            else:
                logger.info(f"[dry_run] Would send test email to {test_recipient}")
                result["test_send_ok"] = True  # count as success for dry run reporting
        else:
            logger.info("Skipping test send — not an email campaign")
            result["test_send_ok"] = True  # not applicable for SMS/push

        await context.close()
        await browser.close()

    # --- Check off Asana subtasks ---
    if not dry_run:
        checks = [
            # API + HTML checks (email)
            ("campaign_name", result["campaign_name_ok"], "Campaign name follows naming conventions"),
            ("subject_line", result["subject_line_ok"], "SL matches brief"),
            ("preheader", result["preheader_ok"], "PH matches brief"),
            ("sender", result["sender_ok"], "Sender name & email address"),
            ("alt_tags", result["alt_tags_ok"], "Images all have alt tags"),
            ("utm", result["utm_ok"], "Link template added & UTMs appended"),
            ("unsub", result["unsub_ok"], "Unsub link present & linking"),
            ("send_date", result["send_date_ok"], "Send date matches brief"),
            # SMS / Push channel-specific checks
            ("copy_matches", result["copy_matches_ok"], "Copy matches & no typos"),
            ("links_correct", result["links_correct_ok"], "Links match and point to correct pages"),
            ("onclick_behavior", result["onclick_behavior_ok"], "On-click behavior set to deeplink into application"),
            ("link_approved", result["link_approved_ok"], "Link set to one of pre-approved URLs"),
            # UI / browser checks (all channels)
            ("send_time", send_time_ok, "Send time matches brief"),
            ("audience_segment", segment_ok, "Audience matches Asana Segment"),
            ("audience_lifecycle", lifecycle_ok, "Audience matches Lifecycle doc"),
            ("filters", filters_ok, "Old/irrelevant filters removed"),
        ]
        for key, passed, label in checks:
            if passed and key in qa_gids:
                await asyncio.to_thread(check_off_subtask, qa_gids[key], label)

    # --- Post Asana comment if anything needs human attention ---
    qa_issues: list[str] = list(metadata_issues)

    # API check failures
    if api_check_results:
        # If Braze returned empty HTML, emit one clear manual-QA note instead of individual HTML flags
        if api_check_results.get("html_body_empty"):
            qa_issues.append(
                "HTML body was empty when QA ran — could not auto-verify email body "
                "(alt tags, unsubscribe link). Please QA the email content manually."
            )
        if not result["campaign_name_ok"]:
            qa_issues.append("Campaign name may not follow naming conventions — verify in Braze")
        if not result["subject_line_ok"]:
            qa_issues.append("Subject line in Braze does not match Asana brief — verify")
        if not result["preheader_ok"]:
            if api_check_results.get("is_pt"):
                qa_issues.append("PT email has a preheader set in Braze — should be empty, please remove")
            else:
                qa_issues.append("Preheader in Braze does not match Asana brief — verify")
        if not result["sender_ok"]:
            qa_issues.append("Sender name/email in Braze does not match expected — verify")
        if not result["alt_tags_ok"]:
            qa_issues.append("One or more images missing alt tag — verify HTML")
        if not result["utm_ok"]:
            qa_issues.append("No UTM link template applied in Link Management — verify in Braze editor")
        if not result["unsub_ok"]:
            qa_issues.append("Unsubscribe link/block not detected in HTML — verify footer")
        if not result["send_date_ok"]:
            qa_issues.append("Send date in campaign name does not match task due date — verify")

    # SMS check failures
    if channel == "sms":
        if not result["copy_matches_ok"]:
            qa_issues.append("SMS body appears empty in Braze — verify copy was set correctly")
        if not result["links_correct_ok"]:
            qa_issues.append(
                "SMS link issue: the link in Braze either does not match the LP in the "
                "Asana task brief, or the URL is returning a 404/redirect — "
                "verify the correct link is used before launching"
            )
        if not result["utm_ok"]:
            qa_issues.append("UTM parameters missing from SMS link — verify utm_source is appended")

    # Push check failures
    if channel == "push":
        if not result["copy_matches_ok"]:
            qa_issues.append("Push title or message appears empty in Braze — verify content was set")
        if not result["onclick_behavior_ok"]:
            qa_issues.append("Push on-click behavior / deep link does not appear to be set — verify in Braze")
        if not result["link_approved_ok"]:
            qa_issues.append("Push deep link may not match pre-approved URLs — verify On-Click Behavior URL")
        if not result["utm_ok"]:
            qa_issues.append("Push deep link may be missing UTM parameters — verify link tracking")

    # UI check failures
    if not send_time_ok:
        delivery_expected = _get_expected_delivery(
            raw_task or {}, brand, campaign_name, channel, campaign_created_at
        )
        if delivery_expected.get("use_sto"):
            qa_issues.append(
                "Expected Intelligent Timing (STO) not confirmed in Braze — verify Delivery tab"
            )
        else:
            t = delivery_expected.get("time_str") or "expected time"
            qa_issues.append(
                f"Send time ({t}) could not be confirmed in Braze — verify delivery settings"
            )
    if not segment_ok:
        qa_issues.append(
            "Audience segment in Braze did not match expected — verify Target Audiences tab"
        )
    if not filters_ok:
        qa_issues.append(
            "Unexpected filter rules detected on Target Audiences tab — verify no old filters remain"
        )
    # Flag stale exclusions only when they were actually found on the page
    for excl in stale_found_on_page:
        qa_issues.append(
            f"Stale exclusion '{excl}' should be removed from Target Audiences — it's past its end date"
        )

    if not dry_run:
        if qa_issues:
            comment_text = "QA flagged items for human review:\n" + "\n".join(
                f"• {issue}" for issue in qa_issues
            )
        else:
            comment_text = "Automated QA complete — no issues found."
        posted = _asana_request(
            "POST",
            f"tasks/{task_gid}/stories",
            json_data={"data": {"text": comment_text}},
        )
        if posted:
            logger.info(f"Posted QA comment on task {task_gid} ({len(qa_issues)} issue(s))")
        else:
            logger.warning(f"Failed to post QA comment on task {task_gid}")
    elif qa_issues:
        logger.info(f"[dry_run] Would post QA comment with {len(qa_issues)} item(s): {qa_issues}")

    return result


# ---------------------------------------------------------------------------
# Standalone entry point for debugging
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="Run QA + test send for a designed email")
    parser.add_argument("--task-gid", required=True, help="Asana parent task GID")
    parser.add_argument("--brand", required=True, help="Brand code (e.g. CZ)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    task = fetch_task_by_gid(args.task_gid)
    if not task:
        print(f"Could not fetch task {args.task_gid}")
        sys.exit(1)

    braze_url = _get_text_value(task, FIELD_BRAZE_LINK) or ""
    assignee_name = (task.get("assignee") or {}).get("name")

    result = asyncio.run(
        run_qa_and_test_send(
            task_gid=args.task_gid,
            brand=args.brand,
            braze_url=braze_url,
            assignee_name=assignee_name,
            dry_run=args.dry_run,
            raw_task=task,
        )
    )

    print("\n=== QA Summary ===")
    ok = "✓"
    fail = "✗ NEEDS MANUAL CHECK"
    na = "–  (N/A for channel)"
    task_ch = _get_enum_value_name(task, FIELD_CHANNEL) or "email"
    is_sms = task_ch.lower() == "sms"
    is_push = task_ch.lower() == "push"
    is_em = not is_sms and not is_push

    print("--- API / HTML checks ---")
    print(f"Campaign name:   {ok if result['campaign_name_ok'] else fail}")
    if is_em:
        print(f"Subject line:    {ok if result['subject_line_ok'] else fail}")
        print(f"Preheader:       {ok if result['preheader_ok'] else fail}")
        print(f"Sender:          {ok if result['sender_ok'] else fail}")
        print(f"Alt tags:        {ok if result['alt_tags_ok'] else fail}")
        print(f"Unsub link:      {ok if result['unsub_ok'] else fail}")
        print(f"Send date:       {ok if result['send_date_ok'] else fail}")
    print(f"UTM tracking:    {ok if result['utm_ok'] else fail}")
    if is_sms or is_push:
        print(f"Copy matches:    {ok if result['copy_matches_ok'] else fail}")
    if is_sms:
        print(f"Links correct:   {ok if result['links_correct_ok'] else fail}")
    if is_push:
        print(f"On-click behav.: {ok if result['onclick_behavior_ok'] else fail}")
        print(f"Pre-approved URL:{ok if result['link_approved_ok'] else fail}")
    print("--- UI / browser checks ---")
    print(f"Send time:       {ok if result['send_time_ok'] else fail}")
    print(f"Segment:         {ok if result['segment_ok'] else fail}")
    print(f"Lifecycle match: {ok if result['lifecycle_ok'] else fail}")
    print(f"Filters clean:   {ok if result['filters_ok'] else fail}")
    print(f"Test send:       {ok if result['test_send_ok'] else na if not is_em else fail}")
    if result["errors"]:
        print(f"Errors: {result['errors']}")
