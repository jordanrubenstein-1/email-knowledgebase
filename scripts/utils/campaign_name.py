"""Campaign naming convention utilities.

Generates, validates, and parses Braze campaign names following the standard
naming convention:

    [TYPE]_[CHANNEL]_[YYYY]_[MM]_[DD]_[BRAND]_[DESIGN]_[HAV_AUDIENCE?]_[CONTENT_TYPE?]_Description[_SUFFIX?]

Examples:
    P_EM_2026_02_10_HAV_PC_PF_Summer_Sale_Reminder
    P_EM_2026_01_29_CZ_D_Winter_Retreat_Sale_Last_Chance
    P_SMS_2026_01_29_BW_Sale_Final_Hours
    OT_EM_2026_02_01_ID_D_Order_Confirmation
    P_EM_2026_01_29_ALL_TRADE_PT_Appreciation_Week_Teaser

Reference: https://docs.google.com/spreadsheets/d/10GQdM8YUfQQuCOvgk7fvzHvyswdrxM5e6j0Qii8g4Lk
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants — maps human-readable label → naming code
# ---------------------------------------------------------------------------

VALID_TYPES: dict[str, str] = {
    "Promotional": "P",
    "Transactional": "OT",
    "CX": "CX",
    "Waitlist": "WTL",
    "Segmented": "SEG",
}

VALID_CHANNELS: dict[str, str] = {
    "Email": "EM",
    "SMS": "SMS",
    "Push": "PUSH",
}

VALID_BRANDS: dict[str, str] = {
    "The Citizenry": "CZ",
    "St Frank": "SF",
    "Interior Define": "ID",
    "Havenly": "HAV",
    "The Inside": "TI",
    "The Expert": "TE",
    "Burrow": "BW",
    "Trade": "TRADE",
}

VALID_DESIGNS: dict[str, str] = {
    "Designed": "D",
    "HTML": "H",
    "Plain-Text": "PT",
}

VALID_HAV_AUDIENCES: dict[str, str] = {
    "Pre-Converted": "PC",
    "Converted": "CONV",
}

VALID_CONTENT_TYPES: dict[str, str] = {
    "Back in Stock": "BIS",
    "Color Story": "CLR",
    "Coming Soon": "CS",
    "Get the Look": "GTL",
    "Product Feature": "PF",
    "Ready to Ship": "RTS",
    "User Generated Content": "UGC",
    "At Risk": "At_Risk",
    "Cart Abandon": "Cart_Abandon",
    "Category Browse Abandon": "Category_Browse",
    "Delivery Confirmation": "Delivery_Confirmation",
    "Order Confirmation": "Order_Confirmation",
    "Out for Delivery": "Out_for_Delivery",
    "Post Purchase": "Post_Purchase",
    "Price Drop": "Price_Drop",
    "Product Browse Abandon": "Product_Browse",
    "Shipping Confirmation": "Shipping_Confirmation",
    "Waitlist": "Waitlist",
}

# Reverse lookups: code → label
_TYPE_CODES: dict[str, str] = {v: k for k, v in VALID_TYPES.items()}
_CHANNEL_CODES: dict[str, str] = {v: k for k, v in VALID_CHANNELS.items()}
_BRAND_CODES: dict[str, str] = {v: k for k, v in VALID_BRANDS.items()}
_DESIGN_CODES: dict[str, str] = {v: k for k, v in VALID_DESIGNS.items()}
_HAV_AUDIENCE_CODES: dict[str, str] = {v: k for k, v in VALID_HAV_AUDIENCES.items()}
_CONTENT_TYPE_CODES: dict[str, str] = {v: k for k, v in VALID_CONTENT_TYPES.items()}

# Sets of all valid codes (uppercase) for quick membership checks
_ALL_TYPE_CODES = {v.upper() for v in VALID_TYPES.values()}
_ALL_CHANNEL_CODES = {v.upper() for v in VALID_CHANNELS.values()}
_ALL_BRAND_CODES = {v.upper() for v in VALID_BRANDS.values()} | {"ALL"}
_ALL_DESIGN_CODES = {v.upper() for v in VALID_DESIGNS.values()}
_ALL_HAV_AUDIENCE_CODES = {v.upper() for v in VALID_HAV_AUDIENCES.values()}
_ALL_CONTENT_TYPE_CODES = {v.upper() for v in VALID_CONTENT_TYPES.values()}

# Multi-brand / trade patterns (these appear before or after brand code)
_TRADE_PATTERNS = {"TRADE", "ALL_TRADE", "TRADE_ALL", "ALL"}

# Known suffixes that appear at the end of campaign names
KNOWN_SUFFIXES = {"PM", "AM", "EA", "RETAIL", "UPDATED", "SMS", "RESEND", "OOPS"}


# ---------------------------------------------------------------------------
# Name generation
# ---------------------------------------------------------------------------

# Prefixes/suffixes in Asana task names that encode design type or channel
# rather than describing the send: "PT: Sale Extended", "Sale Reminder - PT".
_DESIGN_PREFIXES = re.compile(r"^(?:PT|D|HTML|SMS|PUSH)\s*[-–—:]\s*", re.IGNORECASE)
_DESIGN_SUFFIXES = re.compile(r"\s*[-–—]\s*(?:PT|D|HTML|SMS|PUSH)\s*$", re.IGNORECASE)

_BRAND_CODES_FOR_STRIPPING = {
    "HAV", "CZ", "ID", "BUR", "BW", "STF", "SF", "TI", "TE", "TRADE",
}


# GA4 misclassifies sessions from campaigns whose name contains "Shop" as
# Organic Shopping rather than Email, which breaks attribution in the marketing
# dashboards.  The rule has been documented for a while but was enforced
# nowhere in code, so names like ..._PT_Shop_The_Sale_Reminder shipped.
#
# Phrase-level rewrites first (they read naturally), then a bare-word fallback.
_SHOP_PHRASE_REWRITES: list[tuple[str, str]] = [
    (r"\bShop\s+by\s+Category\b", "Browse by Category"),
    (r"\bShop\s+by\s+Room\b", "Browse by Room"),
    (r"\bShop\s+the\s+Edit\b", "The Edit"),
    (r"\bShop\s+the\s+Look\b", "Get the Look"),
    (r"\bShop\s+the\s+Sale\b", "Explore the Sale"),
    (r"\bShop\s+All\b", "Browse All"),
    (r"\bShop\s+Now\b", "Explore Now"),
    (r"\bShop\s+the\b", "Explore the"),
    (r"\bShop\s+Early\s+Access\b", "Early Access"),
    (r"\bShopping\s+Guide\b", "Buying Guide"),
]

_SHOP_WORD_RE = re.compile(r"\bShop(?:ping|s|ped)?\b", re.IGNORECASE)


def contains_shop(name: str) -> bool:
    """True if *name* contains "Shop" in any form (see the GA4 rule above).

    Underscores are treated as separators so a fully-formed campaign name
    ("..._PT_Shop_The_Sale") matches — "_" is a word character, so a bare
    \\bShop\\b never matches inside an underscore-delimited name.
    """
    if not name:
        return False
    return bool(_SHOP_WORD_RE.search(name.replace("_", " ")))


def strip_shop_from_description(desc: str) -> str:
    """Rewrite "Shop" out of a campaign-name description segment.

    Applies the documented phrase rewrites, then drops any remaining bare
    "Shop"/"Shopping" word.  Returns *desc* unchanged when it contains no
    "Shop" at all.
    """
    if not desc or not contains_shop(desc):
        return desc
    out = desc
    for pattern, replacement in _SHOP_PHRASE_REWRITES:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    if contains_shop(out):
        out = _SHOP_WORD_RE.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def clean_task_name_for_description(raw_name: str) -> str:
    """Reduce an Asana task name to the description segment of a campaign name.

    Shared by the Braze PT builder (``_derive_campaign_name``) and the Klaviyo
    PT builder (``_generate_campaign_name``), which previously had two very
    different implementations: the Klaviyo one stripped only a leading
    "PT:"-style prefix, so "Labor Day Event Reminder PT Resend" kept its inner
    PT (the design code is already a segment of the name, giving
    ``..._TI_PT_..._PT_Resend``) and "Sale Reminder - PT" kept a literal hyphen,
    which the naming convention forbids.

    Returns "" when nothing survives; the caller decides the fallback.
    """
    desc = (raw_name or "").strip()

    # HAV audience prefixes — these map to the CONV/PC segment, not the description.
    desc = re.sub(
        r"^(?:DPS\s+and\s+MP|MKPL|MP|DPS)\s*:\s*", "", desc, flags=re.IGNORECASE
    ).strip()

    # " | Channel (Type)" suffixes: "Reminder | Email (PT)", "Sale | SMS".
    desc = re.sub(
        r"\s*\|\s*(?:Email|SMS|Push)(?:\s*\([^)]*\))?\s*$", "", desc, flags=re.IGNORECASE
    ).strip()

    # Design-type prefix/suffix.
    desc = _DESIGN_PREFIXES.sub("", desc).strip()
    desc = _DESIGN_SUFFIXES.sub("", desc).strip()

    # Brand code as a separated prefix or suffix.
    for code in _BRAND_CODES_FOR_STRIPPING:
        desc = re.sub(rf"^{re.escape(code)}\s*[-–—:]\s*", "", desc, flags=re.IGNORECASE)
        desc = re.sub(rf"\s*[-–—]\s*{re.escape(code)}\s*$", "", desc, flags=re.IGNORECASE)

    # Special characters — the convention allows only alphanumerics, spaces and
    # underscores, so punctuation is dropped and separators collapsed.
    desc = desc.replace("&", "And").replace("+", "And")
    desc = re.sub(r"[^\w\s-]", "", desc)
    desc = re.sub(r"[\s-]+", " ", desc).strip()

    # Design-type words anywhere in the remainder — they duplicate the design
    # code already encoded as its own segment.
    desc = re.sub(r"\s+(?:PT|D|HTML)\s*$", "", desc, flags=re.IGNORECASE).strip()
    desc = re.sub(r"^(?:PT|D|HTML)\s+", "", desc, flags=re.IGNORECASE).strip()
    desc = re.sub(r"\b(?:PT|HTML)\b", "", desc, flags=re.IGNORECASE).strip()

    # "Send" as a scheduling qualifier ("PM Send" -> "PM").
    desc = re.sub(r"\bSend\b", "", desc, flags=re.IGNORECASE).strip()

    desc = strip_shop_from_description(desc)

    return re.sub(r"\s{2,}", " ", desc).strip()


def generate_campaign_name(
    campaign_type: str,
    channel: str,
    send_date: str | date,
    brand: str,
    description: str,
    design_type: str | None = None,
    hav_audience: str | None = None,
    content_type: str | None = None,
    suffix: str | None = None,
) -> str:
    """Assemble a campaign name following the naming convention.

    Args:
        campaign_type: Campaign type code or label (e.g. "P", "Promotional").
        channel: Channel code or label (e.g. "EM", "Email").
        send_date: Send date as "YYYY-MM-DD" string or date object.
        brand: Brand code or label (e.g. "CZ", "The Citizenry").
        description: Campaign description in Title Case (underscores or spaces).
        design_type: Design type code or label (e.g. "D", "Designed"). Optional
            for SMS campaigns.
        hav_audience: Havenly audience code or label (e.g. "PC", "Pre-Converted").
            Only used for HAV brand.
        content_type: Content type code or label (e.g. "PF", "Product Feature").
        suffix: Optional suffix (e.g. "PM", "AM", "EA").

    Returns:
        Fully-formed campaign name string.

    Raises:
        ValueError: If required components are invalid.
    """
    # Resolve codes from labels if needed
    type_code = _resolve_code(campaign_type, VALID_TYPES, "campaign type")
    channel_code = _resolve_code(channel, VALID_CHANNELS, "channel")
    brand_code = _resolve_brand(brand)

    # Format date
    if isinstance(send_date, date):
        date_str = send_date.strftime("%Y_%m_%d")
    else:
        # Accept YYYY-MM-DD or YYYY_MM_DD
        date_str = send_date.replace("-", "_")
    # Validate date format
    if not re.match(r"^\d{4}_\d{2}_\d{2}$", date_str):
        raise ValueError(
            f"Invalid date format: {send_date!r}. Expected YYYY-MM-DD or YYYY_MM_DD."
        )

    # Build the name parts
    parts: list[str] = [type_code, channel_code, date_str, brand_code]

    # HAV audience comes before design type: P_EM_YYYY_MM_DD_HAV_PC_PT_...
    if hav_audience:
        if brand_code != "HAV":
            raise ValueError(
                f"hav_audience is only valid for HAV brand, got brand={brand_code!r}."
            )
        aud_code = _resolve_code(hav_audience, VALID_HAV_AUDIENCES, "HAV audience")
        parts.append(aud_code)

    # Design type (optional for SMS, required for email)
    if design_type:
        design_code = _resolve_code(design_type, VALID_DESIGNS, "design type")
        parts.append(design_code)
    elif channel_code == "EM":
        raise ValueError("design_type is required for email campaigns (D, H, or PT).")

    # Content type
    if content_type:
        ct_code = _resolve_code(content_type, VALID_CONTENT_TYPES, "content type")
        parts.append(ct_code)

    # Description — convert spaces to underscores, ensure Title_Case
    desc = _format_description(description)
    parts.append(desc)

    # Suffix
    if suffix:
        parts.append(suffix.strip("_"))

    return "_".join(parts)


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

def validate_campaign_name(name: str) -> tuple[bool, list[str]]:
    """Validate a campaign name against the naming convention.

    Returns:
        Tuple of (is_valid, list_of_issues). If is_valid is True the list
        is empty; otherwise it contains human-readable issue descriptions.
    """
    issues: list[str] = []

    if not name or not name.strip():
        return False, ["Campaign name is empty."]

    parts = name.split("_")

    # --- Campaign type ---
    idx = 0
    type_code = parts[idx].upper()
    if type_code not in _ALL_TYPE_CODES:
        issues.append(
            f"Unknown campaign type '{parts[idx]}'. "
            f"Expected one of: {', '.join(sorted(_ALL_TYPE_CODES))}."
        )
    idx += 1

    if idx >= len(parts):
        issues.append("Name too short — missing channel after campaign type.")
        return False, issues

    # --- Channel ---
    channel_code = parts[idx].upper()
    if channel_code not in _ALL_CHANNEL_CODES:
        issues.append(
            f"Unknown channel '{parts[idx]}'. "
            f"Expected one of: {', '.join(sorted(_ALL_CHANNEL_CODES))}."
        )
    idx += 1

    # --- Date (YYYY_MM_DD = 3 parts) ---
    if idx + 2 >= len(parts):
        issues.append("Name too short — missing date components (YYYY_MM_DD).")
        return False, issues

    date_str = f"{parts[idx]}_{parts[idx+1]}_{parts[idx+2]}"
    if not re.match(r"^\d{4}_\d{2}_\d{2}$", date_str):
        issues.append(
            f"Invalid date '{date_str}'. Expected YYYY_MM_DD format."
        )
    else:
        # Validate it's a real date
        try:
            datetime.strptime(date_str, "%Y_%m_%d")
        except ValueError:
            issues.append(f"Date '{date_str}' is not a valid calendar date.")
    idx += 3

    if idx >= len(parts):
        issues.append("Name too short — missing brand after date.")
        return False, issues

    # --- Brand (may be multi-part: ALL_TRADE, TRADE_ALL, etc.) ---
    brand_code, brand_parts_consumed = _extract_brand(parts, idx)
    if brand_code is None:
        issues.append(
            f"Unknown brand '{parts[idx]}' at position {idx}. "
            f"Expected one of: {', '.join(sorted(_ALL_BRAND_CODES))}."
        )
        brand_parts_consumed = 1  # skip one and keep going
    idx += brand_parts_consumed

    # Remaining parts are design type, audience, content type, description, suffix
    # We do best-effort matching but don't require strict positional adherence
    # since descriptions are free-form.

    # --- "Shop" rule (GA4 attribution) ---
    if contains_shop(name):
        issues.append(
            'Name contains "Shop" — GA4 misclassifies these sessions as '
            "Organic Shopping instead of Email. Rephrase (e.g. "
            '"Shop the Sale" -> "Explore the Sale").'
        )

    return (len(issues) == 0, issues)


# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------

def parse_campaign_name(name: str) -> dict[str, Any]:
    """Parse a campaign name into its component parts.

    Returns a dict with keys: campaign_type, channel, date, brand,
    design_type, hav_audience, content_type, description, suffix.
    Missing components are None.
    """
    result: dict[str, Any] = {
        "campaign_type": None,
        "channel": None,
        "date": None,
        "brand": None,
        "design_type": None,
        "hav_audience": None,
        "content_type": None,
        "description": None,
        "suffix": None,
        "raw": name,
    }

    if not name:
        return result

    parts = name.split("_")
    idx = 0

    # Campaign type
    if idx < len(parts) and parts[idx].upper() in _ALL_TYPE_CODES:
        result["campaign_type"] = parts[idx].upper()
        idx += 1
    else:
        return result

    # Channel
    if idx < len(parts) and parts[idx].upper() in _ALL_CHANNEL_CODES:
        result["channel"] = parts[idx].upper()
        idx += 1
    else:
        return result

    # Date (YYYY_MM_DD)
    if idx + 2 < len(parts):
        date_str = f"{parts[idx]}_{parts[idx+1]}_{parts[idx+2]}"
        if re.match(r"^\d{4}_\d{2}_\d{2}$", date_str):
            result["date"] = date_str
            idx += 3
        else:
            return result
    else:
        return result

    # Brand (may consume 1-2 parts for TRADE_ALL, ALL_TRADE, etc.)
    if idx < len(parts):
        brand_code, consumed = _extract_brand(parts, idx)
        if brand_code:
            result["brand"] = brand_code
            idx += consumed
        else:
            # Unrecognized brand — treat rest as description
            result["description"] = "_".join(parts[idx:])
            return result

    # Remaining parts: try to identify design_type, hav_audience, content_type
    # then treat the rest as description + suffix.
    remaining = parts[idx:]
    desc_start = 0

    # Design type
    if desc_start < len(remaining) and remaining[desc_start].upper() in _ALL_DESIGN_CODES:
        result["design_type"] = remaining[desc_start].upper()
        desc_start += 1

    # HAV audience (only if brand is HAV)
    if (
        desc_start < len(remaining)
        and result["brand"] in ("HAV", "HAVENLY")
        and remaining[desc_start].upper() in _ALL_HAV_AUDIENCE_CODES
    ):
        result["hav_audience"] = remaining[desc_start].upper()
        desc_start += 1

    # Content type (check for multi-word content types first like Cart_Abandon)
    if desc_start < len(remaining):
        # Try two-word content type
        if desc_start + 1 < len(remaining):
            two_word = f"{remaining[desc_start]}_{remaining[desc_start+1]}"
            if two_word in _ALL_CONTENT_TYPE_CODES:
                result["content_type"] = two_word
                desc_start += 2
        # Try single-word content type
        if result["content_type"] is None and remaining[desc_start].upper() in _ALL_CONTENT_TYPE_CODES:
            result["content_type"] = remaining[desc_start].upper()
            desc_start += 1

    # Everything else is description (possibly with suffix at the end)
    if desc_start < len(remaining):
        desc_parts = remaining[desc_start:]

        # Check if last part is a known suffix
        if len(desc_parts) > 1 and desc_parts[-1].upper() in KNOWN_SUFFIXES:
            result["suffix"] = desc_parts[-1]
            desc_parts = desc_parts[:-1]

        result["description"] = "_".join(desc_parts) if desc_parts else None

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_code(
    value: str, label_to_code: dict[str, str], field_name: str
) -> str:
    """Resolve a value that may be a code or a human-readable label."""
    upper = value.upper().strip()
    codes = {v.upper(): v for v in label_to_code.values()}

    # Direct code match
    if upper in codes:
        return codes[upper]

    # Label match (case-insensitive)
    for label, code in label_to_code.items():
        if label.upper() == upper:
            return code

    valid = ", ".join(f"{k} ({v})" for k, v in label_to_code.items())
    raise ValueError(f"Invalid {field_name}: {value!r}. Valid options: {valid}.")



# Alternate brand codes used in Asana/YAML that differ from naming convention
_ALTERNATE_BRAND_CODES: dict[str, str] = {
    "BUR": "BW",   # Burrow: YAML uses BUR, naming convention uses BW
    "STF": "SF",   # St Frank: YAML uses STF, naming convention uses SF
}


def _resolve_brand(brand: str) -> str:
    """Resolve a brand value to its code, handling multi-brand patterns."""
    upper = brand.upper().strip()

    # Direct code matches
    codes = {v.upper(): v for v in VALID_BRANDS.values()}
    if upper in codes:
        return codes[upper]
    if upper == "ALL":
        return "ALL"

    # Alternate code mappings (e.g. BUR -> BW, STF -> SF)
    if upper in _ALTERNATE_BRAND_CODES:
        return _ALTERNATE_BRAND_CODES[upper]

    # Multi-brand patterns
    for pattern in ("ALL_TRADE", "TRADE_ALL"):
        if upper == pattern:
            return pattern

    # Label match
    for label, code in VALID_BRANDS.items():
        if label.upper() == upper:
            return code

    valid = ", ".join(f"{k} ({v})" for k, v in VALID_BRANDS.items())
    raise ValueError(f"Invalid brand: {brand!r}. Valid options: {valid}, ALL.")


def _extract_brand(parts: list[str], idx: int) -> tuple[str | None, int]:
    """Extract brand code from parts, handling multi-part brands.

    Returns (brand_code, number_of_parts_consumed).
    """
    if idx >= len(parts):
        return None, 0

    current = parts[idx].upper()

    # Two-part brand patterns: ALL_TRADE, TRADE_ALL
    if idx + 1 < len(parts):
        two_part = f"{current}_{parts[idx + 1].upper()}"
        if two_part in _TRADE_PATTERNS:
            return two_part, 2

    # Single-part brand
    if current in _ALL_BRAND_CODES:
        return current, 1

    return None, 0


def _format_description(description: str) -> str:
    """Format a description string for use in a campaign name.

    Strips punctuation that is invalid in Braze campaign names (colons, commas,
    em dashes, en dashes, parentheses, etc.), converts spaces to underscores,
    and applies Title_Case to each word.
    """
    # Strip "If Needed" scheduling qualifier (case-insensitive) before processing
    desc = re.sub(r'\bif\s+needed\b', '', description, flags=re.IGNORECASE).strip()
    # Strip "Engaged" audience qualifier — signals segment selection, not campaign content
    desc = re.sub(r'\bengaged\b', '', desc, flags=re.IGNORECASE).strip()
    # Strip HAV audience prefixes — DPS/MP/MKPL are task name prefixes that map to PC/CONV,
    # which are already encoded in the campaign name. Handle combined forms first (e.g.
    # "DPS and MP") to avoid leaving a dangling "and". Colon/dash after prefix is optional.
    desc = re.sub(r'\bDPS\s+and\s+(?:MP|MKPL)\b\s*[:\-]?\s*', '', desc, flags=re.IGNORECASE).strip()
    desc = re.sub(r'\b(?:DPS|MKPL|MP)\b\s*[:\-]?\s*', '', desc, flags=re.IGNORECASE).strip()
    # Strip channel words — redundant since the channel is already encoded in P_SMS_/P_PUSH_/P_EM_
    desc = re.sub(r'\b(?:sms|push|email)\b\s*[:\-]?\s*', '', desc, flags=re.IGNORECASE).strip()
    # Strip parenthesized content entirely (e.g. "(May 29)", "(If Needed)") — content
    # inside parens is scheduling/context metadata, not part of the campaign name
    desc = re.sub(r'\s*\([^)]*\)', '', desc).strip()
    # Strip invalid punctuation: colons, commas, em/en dashes, remaining brackets,
    # quotes, exclamation/question marks, pipes, slashes, ampersands, etc.
    desc = re.sub(r'[:\,\—\–\(\)\[\]\{\}\'\"!?|/\\&;]', '', desc)
    # Collapse multiple spaces left by removals
    desc = re.sub(r'\s{2,}', ' ', desc).strip()
    # Replace spaces with underscores
    desc = desc.replace(" ", "_")

    # Apply Title Case to each word (split on underscore)
    words = desc.split("_")
    title_words = []
    for word in words:
        if not word:
            continue
        # Preserve all-caps acronyms (e.g. BFCM, EOY, UGC)
        if word.isupper() and len(word) > 1:
            title_words.append(word)
        else:
            title_words.append(word[0].upper() + word[1:] if len(word) > 1 else word.upper())
    return "_".join(title_words)
