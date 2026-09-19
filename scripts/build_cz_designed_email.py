#!/usr/bin/env python3
"""
Build a CZ designed (image-based) email campaign in Braze using a hybrid approach:

  1. Download images from Google Drive (or a local folder)
  2. Upload images to Braze media library → get CDN URLs
  3. Assemble the email HTML from those CDN URLs
  4. Write the HTML as an email template via Braze Templates API
  5. Create the campaign via Playwright, inject HTML, configure settings, save draft
  6. Write the Braze campaign link back to the Asana task, tag assignee with QA instructions

This builder is for purely image-based CZ emails where the designer provides
all slices as image files. It does NOT use the DnD editor.

Usage:
    # From Google Drive folder (images pulled automatically)
    uv run python scripts/build_cz_designed_email.py \\
      --task-gid 1213928738006165 \\
      --drive-url "https://drive.google.com/drive/folders/1WkirCD3jsqhKFFqakiz4r34-K-yp9Cj0"

    # From local images folder
    uv run python scripts/build_cz_designed_email.py \\
      --task-gid 1213928738006165 \\
      --images-dir /path/to/images

    # Dry run — build HTML, create template, but skip Playwright + Asana writeback
    uv run python scripts/build_cz_designed_email.py \\
      --task-gid 1213928738006165 \\
      --drive-url "..." \\
      --dry-run
"""

import argparse
import asyncio
import html as _html_module
import logging
import os
import re
import sys
import tempfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

from braze_automation.login import (
    create_context_with_session,
    login,
    save_session,
    BRAND_WORKSPACE_DIRECT_URL,
)
from braze_automation.build_pt_campaign import (
    navigate_to_campaigns,
    start_email_campaign,
    set_campaign_name,
    configure_target_audience,
    configure_delivery,
    configure_conversions,
    save_as_draft,
    get_campaign_url_from_page,
    update_asana_with_braze_link,
    load_brand_config,
    get_brand_entry,
    parse_time_string,
    _asana_request,
    _get_text_value,
    fetch_task_by_gid,
    _option_is_selected,
    _dismiss_blocking_modal,
    FIELD_BRAZE_LINK,
    FIELD_SUBJECT_LINE,
    FIELD_PRE_HEADER,
    ASANA_BASE_URL,
)
from utils.sale_matcher import load_sale_schedules, parse_sale_date
from braze_automation.build_designed_campaign import (
    upload_to_media_library_rest,
    resolve_send_time_designed,
    MediaFileTooLargeError,
    set_subject_preheader,
    _derive_campaign_name,
)
from braze_automation.create_campaign import (
    select_html_editor,
    fill_sending_settings,
    close_editor_modal,
)
from utils.drive_client import (
    extract_drive_folder_id,
    extract_drive_file_id,
    _get_drive_service,
    _mime_to_ext,
    download_image,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BRAND = "CZ"

# Designer Asana GIDs (for oversize-image notifications)
BRAND_DESIGNER_GID: Dict[str, str] = {
    "BUR": "1207632413980689",  # Gillian Johnson
    "BW":  "1207632413980689",  # Gillian Johnson (alias)
    "ID":  "1209370443409899",  # Kenzie Elliott
    "HAV": "1212143940022284",  # Ally Azar
    "CZ":  "1209197946923755",  # Maria Maddocks
    "STF": "1211760270906757",  # Anya Sirker
    "SF":  "1211760270906757",  # Anya Sirker (alias)
}

# Asana field GIDs
FIELD_TASK_STATUS = "1209982215610993"
FIELD_SEND_TIME = "1212524397761931"
FIELD_SEGMENT = "1211927654349290"
STATUS_READY_FOR_QA = "1213535128306988"

_FOOTER_BLOCKS = """\
{{content_blocks.${Havenly_Footer_1} | id: 'cb2'}}
{{content_blocks.${Havenly_Footer_2} | id: 'cb3'}}
{{content_blocks.${Havenly_Footer_3} | id: 'cb11'}}"""

_DISCLAIMER_HTML = (
    '<p style="color:#9D9D9D;font-size:11px;font-style:italic;'
    'text-align:center;margin:8px 0 0 0;">'
    "Offers and pricing are subject to change, see site for details.</p>"
)

_UNSUB_BLOCK = "{{content_blocks.${unsub_block} | id: 'cb6'}}"

# Sale disclaimer sentence shared across brands (matches build_pt_campaign.py).
_SALE_DISCLAIMER_TEXT = "Offers and pricing are subject to change, see site for details."

# Homepage fallback link per brand — used for a slice when the brief supplies no link.
_BRAND_FALLBACK_LINK: Dict[str, str] = {
    "CZ": "https://www.the-citizenry.com/",
    "STF": "https://www.stfrank.com/",
    "BUR": "https://burrow.com/",
}

# Display name per brand — used for generic alt text (e.g. logo-only slices).
_BRAND_DISPLAY_NAME: Dict[str, str] = {
    "CZ": "The Citizenry",
    "STF": "St. Frank",
    "BUR": "Burrow",
}


def _has_active_sale(send_date: str, brand: str = BRAND) -> bool:
    """Return True if `brand` has an active sale on send_date (YYYY-MM-DD)."""
    if not send_date:
        return False
    try:
        from datetime import datetime as _dt
        task_dt = _dt.strptime(send_date, "%Y-%m-%d")
        for sale in load_sale_schedules():
            if sale.get("brand") != brand.upper():
                continue
            start = parse_sale_date(sale.get("start_date"))
            end = parse_sale_date(sale.get("end_date")) or start
            if start and start <= task_dt <= end:
                return True
    except Exception:
        pass
    return False


def _cz_footer_html(has_category_blocks: bool, include_disclaimer: bool = False) -> str:
    """CZ footer: assembled from Braze content blocks (CZ workspace only)."""
    main_block = "CZ_Main_Footer_Without_Categories" if has_category_blocks else "CZ_Main_Footer"
    parts = [
        f"{{{{content_blocks.${{{main_block}}} | id: 'cb16'}}}}",
        _FOOTER_BLOCKS,
    ]
    if include_disclaimer:
        parts.append(_DISCLAIMER_HTML)
    parts.append(_UNSUB_BLOCK)
    return "\n".join(parts)


def _stf_footer_html(include_disclaimer: bool = False, send_date: str = "") -> str:
    """STF footer: inline HTML (St. Frank's Braze workspace has no *_Main_Footer blocks).

    Mirrors the footer used by live STF designed campaigns — copyright + Denver
    address + unsubscribe via the {{${set_user_to_unsubscribed_url}}} personalization tag.
    """
    year = send_date[:4] if len(send_date) >= 4 and send_date[:4].isdigit() else "2026"
    disclaimer_line = (
        f"        <p><em>{_SALE_DISCLAIMER_TEXT}</em></p>\n" if include_disclaimer else ""
    )
    return (
        '<table class="html_block" width="100%" border="0" cellpadding="0" cellspacing="0" '
        'role="presentation" style="mso-table-lspace:0;mso-table-rspace:0"><tr>'
        '<td class="pad"><div style="font-family:Open Sans,Arial,Sans-serif;text-align:center" '
        'align="center"><table style="width: 100%; text-align: center;">\n'
        "  <tbody>\n"
        "    <tr>\n"
        '      <td style="color: #9D9D9D;font-size: 10px;line-height: 12px;'
        'padding-bottom: 20px;text-align: center;">\n'
        "        <br />\n"
        f"{disclaimer_line}"
        f"        <p><em>Copyright © {year}, St Frank, All rights reserved.</em></p>\n"
        "        <p><em>3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209</p>\n"
        "        <p><em>If you are no longer interested in receiving emails from us you can </em>"
        '<a href="{{${set_user_to_unsubscribed_url}}}" style="color: rgb(157, 157, 157);">'
        "Unsubscribe</a></p>\n"
        "      </td>\n"
        "    </tr>\n"
        "  </tbody>\n"
        "</table></div></td></tr></table>"
    )


def _bur_footer_html(include_disclaimer: bool = False) -> str:
    """BUR footer: assembled from Braze content blocks (Burrow workspace).

    Burrow's workspace carries the sale-vs-non-sale distinction directly in the
    content block itself — `sale_footer_us` during an active sale, `footer_us`
    otherwise (confirmed from live BW designed campaigns) — so no separate inline
    disclaimer paragraph is appended, unlike CZ's `_DISCLAIMER_HTML`.
    """
    block_name = "sale_footer_us" if include_disclaimer else "footer_us"
    return f"{{{{content_blocks.${{{block_name}}} | id: 'cb12'}}}}"


def _footer_html(
    brand: str,
    has_category_blocks: bool,
    include_disclaimer: bool = False,
    send_date: str = "",
) -> str:
    """Return the footer HTML/Liquid for `brand`.

    CZ and BUR assemble the footer from Braze content blocks (each workspace has
    its own block names); STF uses an inline footer (its workspace lacks any
    *_Main_Footer / Havenly_Footer / unsub_block content blocks). `has_category_blocks`
    only affects CZ (STF and BUR have no such variant).
    """
    brand_upper = brand.upper()
    if brand_upper == "STF":
        return _stf_footer_html(include_disclaimer=include_disclaimer, send_date=send_date)
    if brand_upper == "BUR":
        return _bur_footer_html(include_disclaimer=include_disclaimer)
    return _cz_footer_html(has_category_blocks, include_disclaimer=include_disclaimer)


# ---------------------------------------------------------------------------
# Phase 1: Image acquisition from Google Drive
# ---------------------------------------------------------------------------

# Slice-filename classification.
#   - "Slice N" / "slice N" (case-insensitive, optional space)  → designer convention
#   - digit-prefixed legacy names ("1_hero.jpg", "2 product.png")
# A file that is neither — or a full-email preview named with a send date such as
# "7.20 Wallpaper.png" (month.day, a digit-period-digit pattern) — is NOT a slice
# and must be excluded from both the media-library upload and the assembled HTML.
_SLICE_NAME_RE   = re.compile(r"^\s*slice\s*(\d+)", re.IGNORECASE)
_DIGIT_PREFIX_RE = re.compile(r"^\s*(\d+)")
_DATE_IN_NAME_RE = re.compile(r"\d\.\d")  # send-date preview signature, e.g. "7.20"


def _slice_sort_key(name: str) -> int:
    """Numeric sort key for a slice filename.

    Handles the "Slice N"/"slice N" convention (so "Slice 2" sorts before
    "Slice 10", unlike a plain alphabetical sort) and the legacy digit-prefix
    convention. Non-slice files sort last (999).
    """
    m = _SLICE_NAME_RE.match(name)
    if m:
        return int(m.group(1))
    m = _DIGIT_PREFIX_RE.match(name)
    if m:
        return int(m.group(1))
    return 999


def _is_slice_filename(name: str) -> bool:
    """True if a root image is an email slice (vs a full-email preview/mockup).

    Accepts "Slice N"/"slice N" and legacy digit-prefixed names ("1_hero.jpg").
    Rejects date-named previews like "7.20 Wallpaper.png" — designers commonly
    export the full-email mockup with the send date (month.day) in the name.
    """
    if _SLICE_NAME_RE.match(name):
        return True
    stem = Path(name).stem
    if _DIGIT_PREFIX_RE.match(name) and not _DATE_IN_NAME_RE.search(stem):
        return True
    return False


def _list_drive_subfolder(service, parent_folder_id: str, subfolder_name: str) -> Optional[str]:
    """Return the Drive folder ID of a named subfolder, or None."""
    q = (
        f"'{parent_folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{subfolder_name}' "
        f"and trashed = false"
    )
    result = service.files().list(q=q, fields="files(id,name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    return None


def _list_images_in_folder(service, folder_id: str) -> List[Dict]:
    """Return image files in a Drive folder, sorted by name."""
    q = (
        f"'{folder_id}' in parents "
        f"and mimeType contains 'image/' "
        f"and trashed = false"
    )
    result = service.files().list(
        q=q,
        fields="files(id,name,mimeType)",
        orderBy="name",
    ).execute()
    return result.get("files", [])


def _download_drive_file(service, file_id: str, name: str, dest_dir: Path) -> Path:
    """Download a Drive file to dest_dir, preserving its name."""
    from googleapiclient.http import MediaIoBaseDownload
    import io

    meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    ext = Path(meta["name"]).suffix or _mime_to_ext(meta.get("mimeType", ""))
    dest = dest_dir / name
    if not dest.suffix:
        dest = dest_dir / (name + ext)

    request = service.files().get_media(fileId=file_id)
    buf = open(dest, "wb")
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.close()
    logger.info(f"Downloaded {name} → {dest}")
    return dest


def download_images_from_drive(drive_url: str, dest_dir: Path) -> Dict[str, Path]:
    """Download root images + category blocks from a Google Drive folder or single file.

    Accepts either a folder URL (/drive/folders/…) or a single file URL (/file/d/…).
    Returns a dict mapping filename → local Path.
    """
    folder_id = extract_drive_folder_id(drive_url)
    if not folder_id:
        # Try single-file URL
        file_id = extract_drive_file_id(drive_url)
        if not file_id:
            raise ValueError(f"Could not extract folder ID from Drive URL: {drive_url}")
        service = _get_drive_service()
        if service is None:
            raise RuntimeError(
                "Google Drive credentials not configured — "
                "set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, "
                "GOOGLE_DRIVE_REFRESH_TOKEN in .env"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Use filename from Drive metadata; prefix with "1_" so it sorts as slice 1
        meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
        name = meta.get("name", "1_slice.jpg")
        if not name.startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
            name = "1_" + name
        local = _download_drive_file(service, file_id, name, dest_dir)
        return {name: local}

    service = _get_drive_service()
    if service is None:
        raise RuntimeError(
            "Google Drive credentials not configured — "
            "set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, "
            "GOOGLE_DRIVE_REFRESH_TOKEN in .env"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    cat_dir = dest_dir / "category blocks"
    cat_dir.mkdir(exist_ok=True)

    result: Dict[str, Path] = {}

    # Root images — skip non-slice files (e.g. full-email preview mockups like
    # "7.20 Wallpaper.png") so they are never uploaded to Braze or placed in the HTML.
    root_files = _list_images_in_folder(service, folder_id)
    for f in root_files:
        if not _is_slice_filename(f["name"]):
            logger.info(f"Skipping non-slice file: {f['name']}")
            continue
        local = _download_drive_file(service, f["id"], f["name"], dest_dir)
        result[f["name"]] = local

    # Single-image fallback.
    #
    # Designers routinely name a one-slice email after the send date rather
    # than "1.gif" — e.g. "8.19-EA-Last-Chance.gif" — which _is_slice_filename()
    # rejects as a decimal date stamp, emptying the folder and aborting the
    # build over a filename.
    #
    # With exactly one image in the root there is no slice ORDER to get wrong,
    # so accept it as slice 1, normalising to the "1_" prefix the single-file
    # branch above already uses. Deliberately NOT extended to 2+ unmatched
    # files: there the ordering is unknowable, and the skip above exists to
    # keep full-email preview mockups out of the HTML — a risk that only
    # applies when a real slice set is present alongside them.
    if not result and len(root_files) == 1:
        lone = root_files[0]
        norm = "1_" + lone["name"]
        logger.warning(
            f"Single unrecognized image {lone['name']!r} in Drive folder — "
            f"treating it as slice 1 ({norm})"
        )
        result[norm] = _download_drive_file(service, lone["id"], norm, dest_dir)

    # "category blocks" subfolder
    cat_folder_id = _list_drive_subfolder(service, folder_id, "category blocks")
    if cat_folder_id:
        cat_files = _list_images_in_folder(service, cat_folder_id)
        for f in cat_files:
            local = _download_drive_file(service, f["id"], f["name"], cat_dir)
            result[f["name"]] = local
    else:
        logger.warning("No 'category blocks' subfolder found in Drive folder")

    return result


# Retry policy when a Drive folder listing comes back with zero images.
# Designers sometimes finish uploading slice assets seconds after moving a task
# to Ready to Code, and Google Drive's files().list can lag a few minutes behind
# a just-created (especially large) file. Confirmed 2026-07-20: a CZ task's gif
# was created 2 min before the build kicked off and kept changing for 8 more
# minutes afterward — the build's first (only) Drive query found zero images and
# silently shipped a text-only email with no error surfaced anywhere.
DRIVE_IMAGE_RETRY_DELAYS_SEC = [120, 120]  # 2 retries, 2 min apart (~4 min total)


async def download_images_from_drive_with_retry(
    drive_url: str,
    dest_dir: Path,
    retry_delays: List[int] = DRIVE_IMAGE_RETRY_DELAYS_SEC,
) -> Dict[str, Path]:
    """download_images_from_drive, retrying with a delay if it finds zero images.

    Raises whatever download_images_from_drive raises on the final attempt if
    every attempt errors out. Returns an empty dict (not an exception) if Drive
    keeps returning zero images after all retries — callers must check for that.
    """
    local_images = download_images_from_drive(drive_url, dest_dir)
    for attempt, delay in enumerate(retry_delays, start=1):
        if local_images:
            return local_images
        logger.warning(
            f"No images found in Drive folder (attempt {attempt}/{len(retry_delays) + 1}) — "
            f"retrying in {delay}s in case the upload is still finishing"
        )
        await asyncio.sleep(delay)
        local_images = download_images_from_drive(drive_url, dest_dir)

    if not local_images:
        logger.warning(
            f"Still no images found in Drive folder after {len(retry_delays)} retries"
        )
    return local_images


def load_images_from_dir(images_dir: Path) -> Dict[str, Path]:
    """Build filename → Path mapping from a local images directory.

    Looks for root images and a 'category blocks' subfolder.
    """
    result: Dict[str, Path] = {}
    for p in images_dir.iterdir():
        if p.is_file() and p.suffix.lower() in (".png", ".gif", ".jpg", ".jpeg", ".webp"):
            # Skip reference/preview files (e.g. "7.20 Wallpaper.png"); keep only
            # "Slice N" or legacy digit-prefixed slice images.
            if not _is_slice_filename(p.name):
                logger.debug(f"Skipping non-slice file: {p.name}")
                continue
            result[p.name] = p
    cat_dir = images_dir / "category blocks"
    if cat_dir.is_dir():
        for p in cat_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".png", ".gif", ".jpg", ".jpeg", ".webp"):
                if not p.name[0].isdigit():
                    logger.debug(f"Skipping non-slice file: {p.name}")
                    continue
                result[p.name] = p
    return result


# ---------------------------------------------------------------------------
# Phase 1.5: Dynamic image config discovery from task notes
# ---------------------------------------------------------------------------

def _strip_html(html_notes: str) -> str:
    """Strip HTML tags and return plain text.

    Block/list tags (<li>, <br>, <p>) are converted to newlines so that
    field-level regex patterns (e.g. ``[^\\n\\r]+``) stop at field boundaries
    rather than running on into the next field's content.
    """
    # Replace block/list tags with newline before stripping remaining tags
    text = re.sub(r'<(?:li|br|p|/ul|/ol)[^>]*>', '\n', html_notes or '', flags=re.IGNORECASE)

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: List[str] = []
        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    stripper = _Stripper()
    stripper.feed(text)
    # Join without extra spaces since newlines are now explicit
    return "".join(stripper.parts)


def _parse_slice_links(html_notes: str, brand: str = BRAND) -> List[str]:
    """Extract ordered Link: URLs from task html_notes.

    Skips kicker slices (which have no image and no link).
    Normalizes 'homepage' (or any unresolved/non-http value) → the brand's homepage,
    via `_BRAND_FALLBACK_LINK` (defaults to CZ's homepage if `brand` is unrecognized).

    Prefers href attributes over anchor text — when a Link: field uses an anchor tag
    like <a href="https://...">https://short.url</a>, the href is the canonical URL.
    """
    fallback_link = _BRAND_FALLBACK_LINK.get(brand.upper(), "https://www.the-citizenry.com/")
    # Split on slice headers before stripping HTML so we can read hrefs
    blocks_html = re.split(r'Slice\s+\d+\s+[—–\-]+\s*', html_notes)[1:]

    normalized: List[str] = []
    for block_html in blocks_html:
        block_plain = _strip_html(block_html)
        if re.search(r'\[content block', block_plain, re.IGNORECASE):
            continue

        # Priority 1: href attribute from a Link: anchor tag
        m_href = re.search(
            r'Link:\s*<a[^>]+href=["\']([^"\']+)["\']',
            block_html,
            re.IGNORECASE,
        )
        if m_href:
            url = m_href.group(1).rstrip(".,;)")
        else:
            # Priority 2: plain text URL after "Link:"
            m = re.search(r"Link:\s*(\S+)", block_plain)
            if m:
                url = m.group(1).rstrip(".,;)")
            else:
                # Priority 3: any bare <a href> anchor in the block (no "Link:" prefix)
                m_bare_href = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', block_html, re.IGNORECASE)
                if m_bare_href:
                    url = m_bare_href.group(1).rstrip(".,;)")
                else:
                    # Priority 4: bare https:// URL in plain text
                    m_bare = re.search(r'https?://\S+', block_plain)
                    if not m_bare:
                        continue
                    url = m_bare.group(0).rstrip(".,;)")

        if url.lower() in ("homepage", "home", "homepage."):
            normalized.append(fallback_link)
        elif url.startswith("http"):
            normalized.append(url)
        else:
            normalized.append(fallback_link)

    return normalized


def _parse_slice_alts(html_notes: str, brand: str = BRAND) -> List[str]:
    """Extract short alt text for each image slice from task html_notes.

    Priority per slice (text visible in the image):
    0. Sale banner / Sale link farm header → promo text (sale name/discount)
    1. CTA: / Hero CTA: value if ≤ 4 words → use as-is
    2. CTA exists but > 4 words → shortest CTA across all non-kicker slices
    3. HED: field  → use verbatim (hero / editorial slices)
    4. Name: field → use verbatim (product slices)
    5. No CTA/HED/Name → truncated slice name (max 4 words)

    Logo-only slices (slice name contains "logo" AND no CTA/HED/Name) → "{brand} logo"
    (brand display name from `_BRAND_DISPLAY_NAME`, e.g. "The Citizenry logo", "Burrow logo").
    Kicker slices ([content block]) → skipped entirely.
    """
    _MAX = 4  # preferred word cap for CTA fallback
    brand_display_name = _BRAND_DISPLAY_NAME.get(brand.upper(), "The Citizenry")

    plain = _strip_html(html_notes)
    blocks = re.split(r'Slice\s+\d+\s+[—–\-]+\s*', plain)[1:]

    # Extract promo text for sale banner / sale link farm alt text
    promo_match = re.search(r'\bPromo:\s*([^\n\r]+)', plain)
    promo_text = promo_match.group(1).strip() if promo_match else ""

    # First pass: collect all CTA texts from non-kicker slices (newlines now preserved,
    # so [^\n\r]+ stops at the field boundary correctly)
    cta_texts: List[str] = []
    for block in blocks:
        if re.search(r'\[content block', block, re.IGNORECASE):
            continue
        m = re.search(r'(?:Hero\s+)?CTA:\s*([^\n\r]+)', block)
        if m:
            text = m.group(1).strip()
            # Strip trailing field-separator suffixes: "/ Link:..." or "/ HED:..." etc.
            # These appear when all fields are on one line (e.g. "CTA: Shop 25% Off / Link:URL")
            text = re.sub(r'\s*/\s*\S.*$', '', text).strip(' "')
            if text:
                cta_texts.append(text)

    # Default = shortest CTA (most likely to be the generic action phrase)
    default_cta = min(cta_texts, key=len) if cta_texts else ""

    alts: List[str] = []
    for block in blocks:
        if re.search(r'\[content block', block, re.IGNORECASE):
            continue
        slice_name_match = re.match(r'([^\n\r]+)', block.strip())
        slice_name = slice_name_match.group(1).strip() if slice_name_match else ""

        # Priority 0: Sale banner and Sale link farm header → use promo text (sale name/discount),
        # not the email topic CTA which would be wrong context for these structural sale slices.
        if re.search(r'\bsale\s+banner\b', slice_name, re.IGNORECASE):
            alts.append(promo_text or "Sale")
            continue
        if re.search(r'\bsale\s+link\s+farm\b', slice_name, re.IGNORECASE):
            alts.append(promo_text or "Sale")
            continue

        # Priority 1: CTA / Hero CTA field — describes the linked content concisely
        m = re.search(r'(?:Hero\s+)?CTA:\s*([^\n\r]+)', block)
        if m:
            text = m.group(1).strip()
            text = re.sub(r'\s*/\s*\S.*$', '', text).strip(' "')
            if len(text.split()) <= _MAX:
                alts.append(text)
            else:
                alts.append(default_cta or " ".join(text.split()[:_MAX]))
            continue

        # Priority 2: HED field → text displayed on the hero/editorial image
        m = re.search(r'\bHED:\s*([^\n\r]+)', block)
        if m:
            alts.append(m.group(1).strip())
            continue

        # Priority 3: Name field → product name displayed on product image
        m = re.search(r'\bName:\s*([^\n\r]+)', block)
        if m:
            alts.append(m.group(1).strip())
            continue

        # Logo-only slice (no CTA, HED, or Name above)
        if re.search(r'\blogo\b', slice_name, re.IGNORECASE):
            alts.append(f"{brand_display_name} logo")
            continue

        # Priority 4: inline "Category Link: URL" format (e.g. "Rugs Link: https://...")
        # Extract the category name before "Link:" as the alt text.
        m = re.match(r'(.+?)\s+Link:\s*https?://', slice_name)
        if m:
            alts.append(m.group(1).strip())
            continue

        # Fallback: shortest CTA, or truncated slice name
        if default_cta:
            alts.append(default_cta)
        else:
            words = slice_name.split()
            alts.append(" ".join(words[:_MAX]))

    return alts


def _parse_kickers(html_notes: str) -> List[str]:
    """Extract kicker_id values from task html_notes.

    Prefers explicit 'kicker_id: <value>' tags. Falls back to inferring the
    ID from the first meaningful word following the '[content block...]' marker
    (e.g. a bare "YMAL" or "Swatches" line becomes kicker_id "ymal"/"swatches").
    """
    plain = _strip_html(html_notes)
    blocks = re.split(r'Slice\s+\d+\s+[—–\-]+\s*', plain)[1:]
    _STOP = {'content', 'block', 'needed', 'no', 'slice', 'kicker', 'the', 'and', 'for', 'a'}

    kicker_ids: List[str] = []
    for block in blocks:
        if not re.search(r'\[content block', block, re.IGNORECASE):
            continue
        # Explicit tag wins
        m = re.search(r'kicker_id:\s*([\w-]+)', block, re.IGNORECASE)
        if m:
            kid = m.group(1).lower()
            logger.info(f"Kicker '{kid}' found (explicit)")
            kicker_ids.append(kid)
            continue
        # Parenthetical ID: "(content block new-arrivals-in-stock-1)"
        m = re.search(r'\(content\s+block\s+([\w][\w-]*)\)', block, re.IGNORECASE)
        if m:
            kid = m.group(1).lower()
            logger.info(f"Kicker '{kid}' found (parenthetical)")
            kicker_ids.append(kid)
            continue
        # Infer from first meaningful word after the [content block...] marker
        parts = re.split(r'\[content\s+block[^\]]*\]', block, maxsplit=1)
        rest = parts[1] if len(parts) > 1 else ""
        words = re.findall(r'\b[A-Za-z][A-Za-z]+\b', rest)
        for word in words:
            if word.lower() not in _STOP:
                kid = word.lower()
                logger.info(f"Kicker '{kid}' found (inferred)")
                kicker_ids.append(kid)
                break

    return kicker_ids


def _parse_slice_layouts(html_notes: str) -> Optional[List[str]]:
    """Extract layout hints for image slices from slice names in task html_notes.

    Detects '50/50 left' → 'left' and '50/50 right' → 'right' in the slice header line.
    Kicker slices ([content block]) are skipped, same as _parse_slice_links.

    Returns a list aligned with image slices (one entry per non-kicker slice),
    or None if no 50/50 hints are found (falls back to pixel-width detection).
    """
    plain = _strip_html(html_notes)
    blocks = re.split(r'Slice\s+\d+\s+[—–\-]+\s*', plain)[1:]

    layouts: List[str] = []
    found_hint = False
    for block in blocks:
        if re.search(r'\[content block', block, re.IGNORECASE):
            continue
        slice_name_match = re.match(r'([^\n\r]+)', block.strip())
        slice_name = slice_name_match.group(1).strip() if slice_name_match else ""
        if re.search(r'50\s*/\s*50\s+left', slice_name, re.IGNORECASE):
            layouts.append("left")
            found_hint = True
        elif re.search(r'50\s*/\s*50\s+right', slice_name, re.IGNORECASE):
            layouts.append("right")
            found_hint = True
        else:
            layouts.append("full")

    return layouts if found_hint else None


def _parse_footer_variant(html_notes: str) -> Optional[bool]:
    """Return True to force CZ_Main_Footer_Without_Categories, False to force CZ_Main_Footer.

    Reads a 'Footer: without categories' or 'Footer: with categories' line from
    the task body copy. Returns None when no explicit footer line is present
    (caller falls back to Drive-folder detection).
    """
    plain = _strip_html(html_notes)
    m = re.search(r'Footer:\s*(.+)', plain, re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip().lower()
    if "without" in value:
        return True
    if "with" in value:
        return False
    return None


def _get_cf_enum_name(task: dict, field_gid: str) -> Optional[str]:
    """Return the enum value name for a custom field on a task."""
    for cf in (task.get("custom_fields") or []):
        if cf.get("gid") == field_gid:
            ev = cf.get("enum_value") or {}
            return ev.get("name") or None
    return None


def _image_width(path: Path) -> int:
    """Return pixel width of an image file, or 0 on error."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.width
    except Exception:
        return 0


def discover_image_configs(
    local_images: Dict[str, Path],
    links: List[str],
    alts: Optional[List[str]] = None,
    layouts: Optional[List[str]] = None,
    brand: str = BRAND,
) -> List[Tuple]:
    """Build a flat ordered image spec list from discovered images + parsed links.

    Images are sorted numerically by filename. Layout is determined per-image:
    - If pixel width ≤ 65% of max width → always 50/50 (small images are a reliable
      signal of a half-width asset, regardless of what the brief says)
    - If pixel width > 65% of max width → check brief hint first ('left'/'right'/'full');
      fall back to full-width if no hint (large images can still be used in 50/50 pairs,
      so we trust the brief over pixel detection in that case)

    Consecutive left+right entries are rendered as a 50/50 pair.
    An orphaned left (no matching right) or right (no preceding left) falls back to full-width.

    Args:
        alts: Optional list of alt texts parsed from the Asana brief.
        layouts: Optional list of layout hints from the Asana brief ('full', 'left', 'right'),
                 indexed in image-sort order. Consulted only for large images (> 65% of max width).

    Returns:
        list of (filename, link, alt, layout) where layout is "full", "left", or "right"
    """
    all_files = sorted(local_images.keys(), key=_slice_sort_key)

    widths = {f: _image_width(local_images[f]) for f in all_files}
    max_width = max(widths.values(), default=900)
    half_threshold = max_width * 0.65

    fallback = _BRAND_FALLBACK_LINK.get(brand.upper(), "https://www.the-citizenry.com/")
    link_iter = iter(links + [fallback] * 100)
    alt_iter = iter((alts or []) + [""] * 100)
    layout_iter = iter(layouts + ["full"] * 100) if layouts else None

    specs: List[Tuple] = []
    pending_left: Optional[Tuple] = None  # (filename, link, alt)

    if layout_iter is not None:
        logger.info(f"Brief-specified layout hints: {layouts} (small images still override)")
    else:
        logger.info("No brief layout hints — using pixel-width detection only")

    for filename in all_files:
        link = next(link_iter)
        provided_alt = next(alt_iter)
        if provided_alt:
            alt = provided_alt
        else:
            stem = Path(filename).stem
            alt = stem.replace("-", " ").replace("_", " ").title()

        is_small = widths[filename] <= half_threshold

        if is_small:
            # Small pixel width is a reliable half-width signal — always 50/50
            # regardless of brief hint. Consume the hint slot if present.
            if layout_iter is not None:
                next(layout_iter)
            logger.info(f"{filename}: small ({widths[filename]}px ≤ {half_threshold:.0f}px threshold) → 50/50")
            if pending_left is None:
                pending_left = (filename, link, alt)
            else:
                specs.append((*pending_left, "left"))
                specs.append((filename, link, alt, "right"))
                pending_left = None
        else:
            # Large image — consult brief hint if available, else default full-width
            hint = next(layout_iter) if layout_iter is not None else "full"
            logger.info(f"{filename}: large ({widths[filename]}px) → hint='{hint}'")
            if hint == "left":
                if pending_left:
                    # Previous left was orphaned — flush as full-width
                    specs.append((*pending_left, "full"))
                pending_left = (filename, link, alt)
            elif hint == "right":
                if pending_left:
                    specs.append((*pending_left, "left"))
                    specs.append((filename, link, alt, "right"))
                    pending_left = None
                else:
                    # Orphaned right — render full-width
                    specs.append((filename, link, alt, "full"))
            else:  # "full" (explicit or default)
                if pending_left:
                    # Orphaned small left — flush as full-width
                    specs.append((*pending_left, "full"))
                    pending_left = None
                specs.append((filename, link, alt, "full"))

    if pending_left:
        specs.append((*pending_left, "full"))

    widths_summary = ", ".join(f"{f}={widths[f]}px" for f in all_files)
    logger.info(f"Image widths: {widths_summary}")
    return specs


# ---------------------------------------------------------------------------
# Phase 2: Braze media library upload
# ---------------------------------------------------------------------------

def upload_images(
    local_images: Dict[str, Path],
    brand: str = BRAND,
) -> Tuple[Dict[str, str], List["MediaFileTooLargeError"]]:
    """Upload images to Braze media library.

    Returns:
        cdn_urls: filename → CDN URL for successfully uploaded images
        oversize_errors: MediaFileTooLargeError for each file that exceeded 5 MB.
            These files are excluded from cdn_urls; the caller is responsible for
            notifying the designer and still building the campaign with a placeholder.
    """
    cdn_urls: Dict[str, str] = {}
    oversize_errors: List[MediaFileTooLargeError] = []
    for name, path in local_images.items():
        logger.info(f"Uploading {name} to Braze media library...")
        try:
            url = upload_to_media_library_rest(str(path), brand)
        except MediaFileTooLargeError as exc:
            logger.warning(str(exc))
            oversize_errors.append(exc)
            continue
        if url:
            cdn_urls[name] = url
            logger.info(f"  → {url[:80]}")
        else:
            logger.error(f"  Upload FAILED for {name}")
    return cdn_urls, oversize_errors


# ---------------------------------------------------------------------------
# Phase 3: HTML assembly
# ---------------------------------------------------------------------------

def _full_width_image(url: str, link: str, alt: str) -> str:
    return (
        f'<tr><td style="padding:0;line-height:0;">'
        f'<a href="{link}" style="display:block;" target="_blank">'
        f'<img src="{url}" width="600" alt="{alt}" '
        f'style="display:block;width:100%;height:auto;border:0;">'
        f'</a></td></tr>\n'
    )


def _half_pair(
    url_l: str, link_l: str, alt_l: str,
    url_r: str, link_r: str, alt_r: str,
) -> str:
    """50/50 image pair that stays 50/50 on mobile.

    Uses real <td> table cells (not display:inline-block divs) for both
    halves, so it renders correctly in every client including Gmail's iOS
    app, which unreliably honors inline-block + percentage width on divs
    and was silently collapsing this module to full-width stacking (bug
    confirmed 2026-08-26 on iPhone 17 Pro Max + iPhone 16, Gmail app only —
    Apple Mail and Gmail Android were unaffected). Table-cell layout needs
    no Outlook-specific fallback — it's already MSO-safe.

    Cell width is percentage-based (width:50%, capped at max-width:300px),
    matching the original div version's sizing — NOT a fixed width:300px.
    The outer content table is deliberately fluid (width:100%;max-width:600px,
    no @media block), so it can render narrower than 600px in plenty of
    real contexts (a narrower desktop reading pane, Braze's own preview,
    some mobile clients). Two hard-pixel 300px cells (600px total) don't
    shrink with a narrower parent and overflow/squeeze — confirmed 2026-08-26
    when a first attempt using width:300px/width="300" broke rendering on
    desktop and Android Gmail, which had been fine before. Percentage cells
    always sum to exactly 100% of whatever the parent actually renders at.

    The two cells sit inside a NESTED <table>, itself inside one <td> of the
    outer content table — every other row in the document (_full_width_image,
    footer, kickers) is a single <td> with no colspan, so a bare 2-cell <tr>
    dropped directly into the outer table breaks its column model: rows
    disagree on column count, and browsers resolve that inconsistently
    (single-cell rows shrink to "column 1"'s width, the second column's width
    is guessed differently per client) — confirmed 2026-08-26 when a second
    attempt using a bare <tr> with two outer-table <td>s left the whole email
    too narrow except for the 50/50 rows, with the pair's own left/right
    cells sized unevenly on mobile. Nesting an inner 2-column table inside a
    single outer <td> keeps the outer table single-column throughout (matching
    every other row, no changes needed elsewhere) while the inner table's
    own two-column layout is fully isolated and unambiguous.
    """
    def cell(url: str, link: str, alt: str) -> str:
        return (
            '      <td width="50%" valign="top" '
            'style="padding:0;line-height:0;font-size:0;width:50%;max-width:300px;">\n'
            f'        <a href="{link}" style="display:block;" target="_blank">'
            f'<img src="{url}" width="300" alt="{alt}" '
            f'style="display:block;width:100%;max-width:300px;height:auto;border:0;"></a>\n'
            '      </td>\n'
        )
    return (
        '<tr><td style="padding:0;line-height:0;font-size:0;">\n'
        '  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;">\n'
        '    <tr>\n'
        + cell(url_l, link_l, alt_l)
        + cell(url_r, link_r, alt_r)
        + '    </tr>\n'
        '  </table>\n'
        '</td></tr>\n'
    )


def build_email_html(
    cdn_urls: Dict[str, str],
    image_specs: List[Tuple],
    has_category_blocks: bool = False,
    kickers: Optional[List[str]] = None,
    send_date: str = "",
    brand: str = BRAND,
) -> str:
    """Assemble the full email HTML from CDN image URLs and a flat image spec list.

    image_specs: list of (filename, link, alt, layout) where layout is
                 "full", "left", or "right". Produced by discover_image_configs().
    has_category_blocks: True if the Drive folder contained a "category blocks" subfolder;
                         selects CZ_Main_Footer_Without_Categories instead of CZ_Main_Footer.
    kickers: Optional list of Braze content block names to insert before the footer.
    send_date: ISO date string (YYYY-MM-DD). Used to determine whether to include the
               sale disclaimer. Omit for non-sale sends.
    """
    include_disclaimer = _has_active_sale(send_date, brand)
    if include_disclaimer:
        logger.info(f"Active {brand} sale detected for {send_date} — including sale disclaimer in footer")
    else:
        logger.info(f"No active {brand} sale for {send_date} — disclaimer omitted from footer")
    rows: List[Tuple[str, str]] = []
    slice_num = 0
    pending_left: Optional[Tuple[str, str, str, str]] = None  # (url, link, alt, filename)

    for filename, link, alt, layout in image_specs:
        url = cdn_urls.get(filename)
        if not url:
            logger.warning(f"No CDN URL for: {filename} — inserting placeholder")
            # Keep the slice in the HTML so the slot is visible during QA.
            # src="" is intentionally empty; the designer must supply a replacement asset.
            url = ""

        if layout == "full":
            if pending_left:
                p_url, p_link, p_alt, p_fn = pending_left
                slice_num += 1
                rows.append((f"Slice {slice_num}: {p_fn} — {p_alt}", _full_width_image(p_url, p_link, p_alt)))
                pending_left = None
            slice_num += 1
            rows.append((
                f"Slice {slice_num}: {filename} — {alt}",
                _full_width_image(url, link, alt),
            ))

        elif layout == "left":
            if pending_left:
                p_url, p_link, p_alt, p_fn = pending_left
                slice_num += 1
                rows.append((f"Slice {slice_num}: {p_fn} — {p_alt}", _full_width_image(p_url, p_link, p_alt)))
            pending_left = (url, link, alt, filename)

        elif layout == "right":
            if pending_left:
                p_url, p_link, p_alt, p_fn = pending_left
                slice_num += 1
                rows.append((
                    f"Slice {slice_num}: {p_fn} ({p_alt}) | {filename} ({alt}) — 50/50",
                    _half_pair(p_url, p_link, p_alt, url, link, alt),
                ))
                pending_left = None
            else:
                slice_num += 1
                rows.append((f"Slice {slice_num}: {filename} — {alt}", _full_width_image(url, link, alt)))

    if pending_left:
        p_url, p_link, p_alt, p_fn = pending_left
        slice_num += 1
        rows.append((f"Slice {slice_num}: {p_fn} — {p_alt}", _full_width_image(p_url, p_link, p_alt)))

    # Kicker content blocks.
    # When there's an active sale the last image slice is the sale link farm header —
    # kickers must appear BEFORE it (per brief ordering), not after all images.
    sale_link_farm_row = None
    if kickers and include_disclaimer and len(rows) >= 2:
        sale_link_farm_row = rows.pop()

    # _DIRECT_BLOCKS: kickers that bypass the kicker_id variable entirely (different CB).
    # _KICKER_BLOCK_NAMES: kickers that still assign kicker_id but use a non-default CB
    #   (e.g. 50/50 layout uses kicker-5050 instead of the default single-column kicker).
    _DIRECT_BLOCKS: dict = {
        "ymal": "product_recs",
    }
    # Maps kicker_id → (content_block_name, liquid_variable_name).
    # kicker-5050 uses kicker_5050 (not kicker_id) as its Liquid variable.
    _KICKER_BLOCK_CONFIGS: dict = {
        "new-arrivals-in-stock-1": ("kicker-5050", "kicker_5050"),
    }
    for i, kicker_id in enumerate(kickers or []):
        cb_name = _DIRECT_BLOCKS.get(kicker_id)
        if cb_name:
            liquid = f"{{{{content_blocks.${{{cb_name}}} | id: 'cb{8 + i}'}}}}"
        else:
            cb_block, cb_var = _KICKER_BLOCK_CONFIGS.get(kicker_id, ("kicker", "kicker_id"))
            liquid = (
                f"{{% assign {cb_var} = \"{kicker_id}\" %}}\n"
                f"{{{{content_blocks.${{{cb_block}}} | id: 'cb{8 + i}'}}}}"
            )
        rows.append((
            f"Kicker: {kicker_id}",
            f'<tr><td style="padding:0;">\n{liquid}\n</td></tr>\n',
        ))

    # Re-append sale link farm image after kickers (preserves brief ordering)
    if sale_link_farm_row:
        rows.append(sale_link_farm_row)

    # Footer HTML block (raw Liquid — Braze renders at send time)
    rows.append((
        "Footer: content blocks + disclaimer",
        '<tr><td style="padding:0;">\n' + _footer_html(brand, has_category_blocks, include_disclaimer=include_disclaimer, send_date=send_date) + '\n</td></tr>\n',
    ))

    body_rows = "".join(f"          <!-- {comment} -->\n{html}" for comment, html in rows)

    return f"""\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <!--[if !mso]><!-->
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <!--<![endif]-->
  <title></title>
  <!--[if mso]>
  <noscript>
    <xml><o:OfficeDocumentSettings>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings></xml>
  </noscript>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#ffffff;">
    <tr>
      <td align="center" style="padding:0;">
        <!--[if mso]><table width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;">
{body_rows}        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Phase 4: Braze Templates API
# ---------------------------------------------------------------------------

def create_braze_template(
    html: str,
    subject: str,
    preheader: str,
    template_name: str,
    dry_run: bool = False,
    brand: str = BRAND,
) -> Optional[str]:
    """POST to /templates/email/create and return the template ID."""
    if dry_run:
        logger.info("DRY RUN — skipping template API call")
        return None

    brand_upper = brand.upper()
    api_key = os.environ.get(f"BRAZE_API_KEY_{brand_upper}") or os.environ.get("BRAZE_API_KEY")
    base_url = (
        os.environ.get(f"BRAZE_BASE_URL_{brand_upper}")
        or os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")
    ).rstrip("/")

    if not api_key:
        raise RuntimeError(f"BRAZE_API_KEY_{brand_upper} not set in .env")

    payload = {
        "template_name": template_name,
        "subject": subject,
        "preheader": preheader,
        "body": html,
    }
    resp = requests.post(
        f"{base_url}/templates/email/create",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Template API error {resp.status_code}: {resp.text[:400]}")
        return None

    data = resp.json()
    template_id = data.get("email_template_id") or data.get("id")
    logger.info(f"Template created: {template_id}")
    return template_id


# ---------------------------------------------------------------------------
# Phase 5: Playwright campaign creation
# ---------------------------------------------------------------------------

async def _inject_html(page, html: str) -> None:
    """Inject HTML into the Monaco editor that's already visible.

    Does NOT click any tab — caller must ensure the Content/editor tab is active.
    Tries Monaco JS API first (instant), then clipboard paste, then textarea fill.

    In edit mode the compose step has subject/preheader Monaco editors in the DOM
    alongside the HTML body Monaco editor inside the portal. Scoping to the portal
    (#email-message-composer-portal) ensures we target the HTML body editor, not the
    subject field.
    """
    import json as _json
    html_json = _json.dumps(html)

    # Scope to the portal when in edit mode; fall back to page-wide search for new builds.
    # NOTE: window.monaco.editor.getEditors()/getModels() return EVERY Monaco
    # instance on the page (subject/preheader editors included), not just the
    # ones inside the portal — a Playwright locator scoped to the portal only
    # gates *whether* we attempt JS injection, it does not scope the JS itself.
    # We must filter editors/models by DOM containment inside the portal,
    # otherwise index [0] can silently grab the subject editor and overwrite
    # it with the full HTML body (confirmed 2026-07-22 on a CZ Back in Stock
    # rebuild — subject field ended up containing the entire HTML document).
    portal = page.locator("#email-message-composer-portal")
    portal_scoped = await portal.count() > 0
    if portal_scoped:
        monaco_editor = portal.locator(".monaco-editor")
        logger.info("Scoping Monaco lookup to #email-message-composer-portal")
    else:
        monaco_editor = page.locator(".monaco-editor")

    if await monaco_editor.count() > 0:
        result = await page.evaluate(f"""
            (() => {{
                const content = {html_json};
                const portalEl = {"document.querySelector('#email-message-composer-portal')" if portal_scoped else "null"};
                const inPortal = (node) => !portalEl || (node && portalEl.contains(node));
                try {{
                    const editors = window.monaco?.editor?.getEditors?.() || [];
                    const scoped = editors.filter(ed => inPortal(ed.getDomNode?.()));
                    const pick = scoped.length ? scoped : (portalEl ? [] : editors);
                    if (pick.length) {{ pick[0].setValue(content); return 'getEditors'; }}
                }} catch(e) {{}}
                try {{
                    const models = window.monaco?.editor?.getModels?.() || [];
                    if (!portalEl && models.length) {{ models[0].setValue(content); return 'getModels'; }}
                }} catch(e) {{}}
                try {{
                    const nodes = portalEl
                        ? portalEl.querySelectorAll('.monaco-editor')
                        : document.querySelectorAll('.monaco-editor');
                    for (const el of nodes) {{
                        for (const prop of ['__monacoEditor__', '_editor', 'monacoEditor']) {{
                            if (el[prop]?.setValue) {{ el[prop].setValue(content); return 'DOM.' + prop; }}
                        }}
                    }}
                }} catch(e) {{}}
                return null;
            }})()
        """)
        if result:
            logger.info(f"HTML injected via Monaco ({result})")
            return

        # Clipboard paste fallback
        try:
            await page.evaluate(f"navigator.clipboard.writeText({html_json})")
            await monaco_editor.first.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Meta+v")
            await page.wait_for_timeout(500)
            logger.info("HTML injected via clipboard paste")
            return
        except Exception as e:
            logger.warning(f"Clipboard paste failed: {e}")

    # Textarea fallback
    textarea = page.locator("textarea").first
    if await textarea.count() > 0:
        await textarea.fill(html)
        logger.info("HTML injected via textarea")
        return

    logger.warning("Could not inject HTML — no Monaco editor or textarea found")


async def _apply_utm_template(page, utm_templates: Optional[Any] = "all") -> None:
    """Inside the HTML editor modal, navigate to Link Management and apply UTM link template(s).

    Args:
        page: Playwright page (inside the email editor modal), on the Content tab.
        utm_templates: Which templates to select — "all" (default) selects every
            template offered in the dropdown; a list of substrings selects only
            templates whose name matches one of them (case-insensitive). Some
            brands (e.g. Burrow) have more than one link template that both need
            to be applied — this must not stop after the first match.
    """
    try:
        link_mgmt = page.get_by_text("Link Management", exact=True).first
        await link_mgmt.wait_for(state="visible", timeout=5000)
        await link_mgmt.click()
        await page.wait_for_timeout(2000)
        logger.info("Opened Link Management")
    except Exception as e:
        logger.warning(f"Could not open Link Management: {e}")
        return

    select_all = utm_templates is None or utm_templates == "all"
    specific_names = utm_templates if isinstance(utm_templates, list) else []

    # Open the "Select link templates" dropdown. When templates are already
    # applied (edit mode) the control shows "N item(s) selected" instead of the
    # placeholder text, so fall back to the last select control on the page.
    tmpl_ctrl = page.locator(".bcl-select__control").filter(has_text="Select link templates")
    if await tmpl_ctrl.count() == 0:
        ph = page.locator(".bcl-select__placeholder:has-text('Select link templates')")
        if await ph.count() > 0:
            tmpl_ctrl = ph.first.locator("xpath=ancestor::div[contains(@class,'bcl-select__control')]")
    if await tmpl_ctrl.count() == 0:
        tmpl_ctrl = page.locator(".bcl-select__control").last

    dropdown_opened = True
    try:
        await tmpl_ctrl.first.click(timeout=5000)
        await page.wait_for_timeout(1000)
    except Exception as e:
        logger.warning(f"Could not open link templates dropdown: {e}")
        dropdown_opened = False

    if dropdown_opened:
        options = page.locator(".bcl-select__option")
        opt_count = await options.count()
        if opt_count == 0:
            logger.info("No selectable link templates in dropdown — likely already applied")
            await page.keyboard.press("Escape")
        else:
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

                # An already-selected option would be de-selected by clicking it
                # again (and trigger a destructive "Remove link template?"
                # confirm) — skip it instead of toggling it off.
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

            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)
            await _dismiss_blocking_modal(page)

            if selected_count == 0 and already_count == 0:
                logger.warning("No link templates were selected")

    # Check any header "select all" checkboxes (covers static URLs).
    await page.wait_for_timeout(500)
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
            except Exception:
                pass
        logger.info(f"Checked {hc_count} select-all header checkbox(es)")

    # Final pass: check any remaining unchecked per-row checkboxes.
    # Liquid-variable URLs like {{ product_url }} are not covered by the
    # header "select all" and need their individual checkbox checked.
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
        logger.info(f"Checked {extra} additional unchecked link checkbox(es) (e.g. {{ product_url }})")


async def edit_existing_campaign(
    html: str,
    subject: str,
    preheader: str,
    campaign_url: str,
    brand_config: Dict,
    headless: bool = True,
    brand: str = BRAND,
) -> bool:
    """Navigate to an existing campaign draft and update its HTML content.

    Enters the campaign's Compose step, clicks 'Edit message' to open the
    HTML editor modal, injects the new HTML, re-applies the UTM template(s),
    verifies subject/preheader, then saves.
    """
    from playwright.async_api import async_playwright

    utm_templates = get_brand_entry(brand, brand_config).get("utm_templates", "all")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-save-password-bubble"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            await login(page)
            await save_session(context)

            # Navigate to the campaign (strip query params to get the base URL).
            # The campaign URL already lands directly in the Compose edit step —
            # no "Edit Campaign" button click is needed.
            base_url = campaign_url.split("?")[0]
            logger.info(f"Navigating to campaign: {base_url}")
            await page.goto(base_url, wait_until="load", timeout=20000)
            await page.wait_for_timeout(2000)

            # If on the overview page, click "Edit Draft" first
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

            # Navigate to the Compose step (wizard step 3)
            for compose_name in ["Compose Messages", "Compose"]:
                try:
                    btn = page.get_by_role("button", name=compose_name)
                    if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        logger.info(f"Navigated to '{compose_name}' step")
                        break
                except Exception:
                    continue

            # Click "Variant 1" tab to select it
            for var_sel in [
                page.get_by_role("tab", name="Variant 1"),
                page.get_by_role("button", name="Variant 1"),
                page.locator("[role='tab']:has-text('Variant 1')"),
                page.get_by_text("Variant 1", exact=True),
            ]:
                try:
                    if await var_sel.count() > 0 and await var_sel.first.is_visible(timeout=3000):
                        await var_sel.first.click()
                        await page.wait_for_timeout(1500)
                        logger.info("Clicked 'Variant 1'")
                        break
                except Exception:
                    continue

            # Reset subject/preheader via "Edit sending info" on the compose step
            # (not inside the HTML editor modal — that's a separate Monaco field
            # pair). This is a full select-all + retype, so it's safe to run on
            # every edit even if the fields were already correct.
            await set_subject_preheader(page, subject, preheader)

            # Scroll down far enough to expose the email preview / "Edit message" button
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(1000)

            # Click the "Edit message" button to open the HTML editor modal.
            # Try increasingly broad selectors; scroll a bit more between each attempt.
            opened_modal = False
            for msg_sel in [
                page.get_by_role("button", name="Edit message"),
                page.locator("button:has-text('Edit message')"),
                page.get_by_role("link", name="Edit message"),
                page.locator("a:has-text('Edit message')"),
                page.locator("button:has-text('Edit')").first,
            ]:
                try:
                    if await msg_sel.count() > 0 and await msg_sel.first.is_visible(timeout=5000):
                        await msg_sel.first.scroll_into_view_if_needed()
                        await msg_sel.first.click()
                        await page.wait_for_timeout(2000)
                        logger.info("Opened HTML editor modal")
                        opened_modal = True
                        break
                except Exception:
                    await page.evaluate("window.scrollBy(0, 500)")
                    await page.wait_for_timeout(500)
                    continue

            if not opened_modal:
                logger.warning("Could not find 'Edit message' button — attempting HTML inject directly into page")

            # The HTML editor modal opens on the Content tab by default for
            # existing HTML-code-editor campaigns.
            await page.wait_for_timeout(1000)

            # Ensure we're on the Content tab before injecting.
            # Try multiple selectors — the aria-label may vary between campaigns.
            # The Monaco editor must be visible before we attempt paste; if it's not,
            # clipboard paste will land in whatever field is focused (e.g. subject).
            content_tab_clicked = False
            for ct_sel in [
                page.locator("button[aria-label='Content']:not([data-route])"),
                page.get_by_role("tab", name="Content"),
                page.locator("button:has-text('Content')").first,
            ]:
                try:
                    if await ct_sel.count() > 0 and await ct_sel.first.is_visible(timeout=2000):
                        await ct_sel.first.click(timeout=3000)
                        await page.wait_for_timeout(500)
                        content_tab_clicked = True
                        logger.info("Clicked Content tab")
                        break
                except Exception:
                    continue
            if not content_tab_clicked:
                logger.info("Content tab not found — modal should already be on Content")

            await _inject_html(page, html)

            # Apply UTM template(s) (must be on Content tab — it is by default).
            # In edit mode templates are usually already applied; the function
            # detects this and skips re-selection without timing out.
            await _apply_utm_template(page, utm_templates)

            # NOTE: subject/preheader are handled above via set_subject_preheader()
            # (Edit sending info panel) — do NOT call fill_sending_settings here.
            # That function targets the modal's own Sending Settings tab via
            # .fill(), which does not properly update the Monaco/React state and
            # appends rather than replaces, producing doubled subject/preheader text.

            # Close modal
            await close_editor_modal(page)

            # Save draft
            await save_as_draft(page, dry_run=False)
            logger.info("Campaign updated and saved")
            return True

        except Exception as e:
            logger.error(f"Error editing campaign: {e}")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            err_path = PROJECT_ROOT / f"debug_cz_edit_error_{ts}.png"
            try:
                await page.screenshot(path=str(err_path), full_page=True)
                logger.info(f"Error screenshot: {err_path}")
            except Exception:
                pass
            return False
        finally:
            await browser.close()


async def build_campaign_playwright(
    html: str,
    subject: str,
    preheader: str,
    campaign_name: str,
    send_date: str,
    send_time_raw: str,
    segment_name: str,
    brand_config: Dict,
    task_name: str = "",
    dry_run: bool = False,
    headless: bool = True,
    brand: str = BRAND,
) -> Optional[str]:
    """Create the Braze campaign via Playwright. Returns the campaign URL or None."""
    from playwright.async_api import async_playwright

    brand_entry = get_brand_entry(brand, brand_config)
    conversions = brand_entry.get("conversion_events", {})

    # Map Asana segment name to brand config audience key
    _segment_map = {
        "Engaged File": "engaged",
        "Full File": "full_file",
        "Engaged Audience": "engaged",
        "Full file": "full_file",
    }
    segment_key = _segment_map.get(segment_name, "full_file")
    audience = (
        brand_entry.get("audiences", {}).get(segment_key)
        or brand_entry.get("audiences", {}).get("engaged", {})
    )

    # Use task_name (has spaces) for last-day keyword detection; fall back to campaign_name
    send_time_config = resolve_send_time_designed(task_name or campaign_name, send_date, send_time_raw, sto_threshold=4)

    logger.info(f"Campaign: {campaign_name}")
    logger.info(f"Audience: {audience.get('type')} / {audience.get('segment')}")
    logger.info(f"Send time: {send_time_config}")

    if dry_run:
        logger.info("DRY RUN — skipping Playwright campaign creation")
        return None

    campaign_url: Optional[str] = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-save-password-bubble"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            await login(page)
            await save_session(context)

            # Navigate to the brand's campaigns workspace
            await navigate_to_campaigns(page, brand=brand)

            # Create campaign
            await start_email_campaign(page)
            await set_campaign_name(page, campaign_name)

            # Open HTML editor modal (Content tab is active by default)
            await select_html_editor(page)

            # Inject HTML while still on the Content tab (avoids ambiguous locator)
            await page.wait_for_timeout(1000)
            await _inject_html(page, html)

            # Apply UTM template(s) via Link Management — must happen on Content tab
            # before switching tabs (Link Management sidebar is only visible there)
            await _apply_utm_template(page, brand_entry.get("utm_templates", "all"))

            # Switch to Sending Settings tab to fill subject + preheader + whitespace
            await fill_sending_settings(page, subject, preheader)

            # Close modal
            await close_editor_modal(page)

            # Target audience
            await configure_target_audience(page, audience, launch_date=send_date)

            # Delivery — skip TZ checkbox for IT (already implied by the fallback time label)
            skip_tz = send_time_config.get("type") == "intelligent_timing"
            await configure_delivery(page, send_time_config, launch_date=send_date, skip_tz_checkbox=skip_tz)

            # Conversion events (Assign step)
            await configure_conversions(page, conversions)

            # Save draft
            await save_as_draft(page, dry_run=False)

            campaign_url = get_campaign_url_from_page(page.url)
            logger.info(f"Campaign URL: {campaign_url}")

        except Exception as e:
            logger.error(f"Playwright error: {e}")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            err_path = PROJECT_ROOT / f"debug_cz_email_error_{ts}.png"
            try:
                await page.screenshot(path=str(err_path), full_page=True)
                logger.info(f"Error screenshot: {err_path}")
            except Exception:
                pass
        finally:
            await browser.close()

    return campaign_url


# ---------------------------------------------------------------------------
# Phase 6: Asana writeback
# ---------------------------------------------------------------------------

def write_back_to_asana(
    task_gid: str,
    campaign_url: str,
    template_id: Optional[str],
    oversize_errors: Optional[List["MediaFileTooLargeError"]] = None,
    brand: str = BRAND,
) -> None:
    """Update task with Braze link, advance status to Ready for QA, post comment."""
    # 1. Braze campaign link field
    updated = update_asana_with_braze_link(task_gid, campaign_url)
    if updated:
        logger.info("Asana FIELD_BRAZE_LINK updated")
    else:
        logger.warning("Failed to update FIELD_BRAZE_LINK")

    # 2. Status → Ready for QA
    _asana_request("PUT", f"tasks/{task_gid}", json_data={
        "data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}
    })
    logger.info("Status updated → Ready for QA")

    # 3. Fetch task for assignee GID (Asana auto-assigns Momina on Ready to Code)
    task = fetch_task_by_gid(task_gid)
    assignee = (task or {}).get("assignee") or {}
    assignee_gid = assignee.get("gid")

    # 4. Build comment body
    body_text = (
        f"this {brand} designed email has been automatically built in Braze. "
        "The campaign name, subject/preheader, audience, and send schedule are configured, "
        "and the email HTML has been assembled from the design assets in the Drive folder. "
        "Please QA the email body, subject line and preheader, audience, and send schedule "
        "before sending to the QA group.\n\n"
        f"Campaign link: {campaign_url}"
    )
    if oversize_errors:
        filenames = ", ".join(err.path.name for err in oversize_errors)
        body_text += (
            f"\n\nThe campaign has been built with an empty placeholder for {filenames}, "
            "which exceeds the Braze media library limit. Once the compressed file is available, "
            "please re-upload and update the HTML."
        )

    if assignee_gid:
        html_body = _html_module.escape(body_text, quote=False)
        url_escaped = _html_module.escape(campaign_url, quote=True)
        url_text = _html_module.escape(campaign_url, quote=False)
        html_body = html_body.replace(
            url_text,
            f'<a href="{url_escaped}">{url_text}</a>',
        )
        html_body = f'<a data-asana-gid="{assignee_gid}"/>, {html_body}'
        payload = {"data": {"html_text": f"<body>{html_body}</body>", "is_pinned": False}}
    else:
        body_text = body_text[0].upper() + body_text[1:]
        payload = {"data": {"text": body_text, "is_pinned": False}}

    ok = _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload)
    if ok:
        logger.info("Asana comment posted")
    else:
        logger.warning("Failed to post Asana comment")


def _post_oversize_comment(
    task_gid: str,
    oversize_errors: List["MediaFileTooLargeError"],
    brand: str = BRAND,
) -> None:
    """Post an Asana comment tagging the designer for each oversized image."""
    designer_gid = BRAND_DESIGNER_GID.get(brand.upper())
    lines = []
    for err in oversize_errors:
        mb = err.size_bytes / (1024 * 1024)
        lines.append(
            f"{err.path.name} is {mb:.1f} MB, which exceeds Braze's 5 MB media library limit. "
            "Can you compress and share a revised file?"
        )
    body = "\n".join(lines)

    if designer_gid:
        escaped = _html_module.escape(body, quote=False).replace("\n", "<br>")
        html_text = f"<body><a data-asana-gid=\"{designer_gid}\"/>, {escaped}</body>"
        payload = {"data": {"html_text": html_text, "is_pinned": False}}
    else:
        payload = {"data": {"text": body, "is_pinned": False}}

    ok = _asana_request("POST", f"tasks/{task_gid}/stories", json_data=payload)
    if ok:
        logger.info(f"Oversize image comment posted to Asana task {task_gid}")
    else:
        logger.warning("Failed to post oversize image comment to Asana")


# ---------------------------------------------------------------------------
# Main callable entry point (used by webhook and Claude-triggered builds)
# ---------------------------------------------------------------------------

async def build_cz_designed_email(
    task_gid: str,
    drive_url: Optional[str] = None,
    images_dir: Optional[str] = None,
    dry_run: bool = False,
    headless: bool = True,
    brand: str = BRAND,
) -> Dict:
    """Build an image-based designed email campaign in Braze from an Asana task.

    Despite the name (kept for backward compatibility), this builds designed emails
    for any brand on the from-scratch HTML/CSS pipeline — pass `brand` (e.g. "CZ",
    "STF"). Brand-specific behavior (footer, Braze workspace/API key, sale schedule)
    is resolved from `brand`.

    Args:
        task_gid: Asana task GID.
        drive_url: Google Drive folder URL containing the email slices.
        images_dir: Local directory path (alternative to drive_url for testing).
        dry_run: If True, build HTML and create template but skip Playwright + Asana writes.
        headless: Run Playwright browser headless.
        brand: Brand code (default "CZ"). Determines footer, API key, and sale lookup.

    Returns:
        {"success": bool, "braze_url": str|None, "errors": list[str]}
    """
    if not drive_url and not images_dir:
        return {"success": False, "braze_url": None, "errors": ["Must provide drive_url or images_dir"]}

    result: Dict = {"success": False, "braze_url": None, "errors": []}

    # ------------------------------------------------------------------
    # Fetch task and derive campaign parameters
    # ------------------------------------------------------------------
    logger.info(f"Fetching Asana task {task_gid}...")
    task = fetch_task_by_gid(task_gid)
    if not task:
        result["errors"].append(f"Could not fetch Asana task {task_gid}")
        return result

    task_name = (task.get("name") or "").strip()
    due_on = task.get("due_on") or ""
    subject = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""
    send_time_raw = _get_text_value(task, FIELD_SEND_TIME) or "7:15 AM"
    segment_name = _get_cf_enum_name(task, FIELD_SEGMENT) or "Full File"
    html_notes = task.get("html_notes") or ""

    if not subject:
        result["errors"].append("Subject Line field is empty on Asana task — fill it before running")
        return result
    if not due_on:
        result["errors"].append("Task has no due date — set before running")
        return result

    try:
        # Shared with the Braze DnD builder and the Klaviyo designed-email
        # builder (_derive_campaign_name() in build_designed_campaign.py) so
        # all three can't drift again — this used to call generate_campaign_name()
        # directly with the raw task name, skipping the prefix-stripping regex
        # the other two builders apply (a stray "SMS:" prefix, or the task's
        # own brand code, e.g. "CZ: Color Edit" — not just HAV's MP/DPS audience
        # tokens, which don't apply to CZ/STF/BUR anyway). Confirmed gap
        # 2026-09-05. No ref campaign exists for this from-scratch builder, so
        # ref_name is "" — same as the Klaviyo designed-email builder's call.
        campaign_name = _derive_campaign_name("", task_name, due_on, brand)
    except Exception as e:
        result["errors"].append(f"Could not generate campaign name: {e}")
        return result

    logger.info(f"Campaign: {campaign_name}")
    logger.info(f"Subject: {subject}")
    logger.info(f"Preheader: {preheader}")
    logger.info(f"Send date: {due_on} | Send time: {send_time_raw} | Segment: {segment_name}")

    links = _parse_slice_links(html_notes, brand=brand)
    alts = _parse_slice_alts(html_notes, brand=brand)
    kickers = _parse_kickers(html_notes)
    layouts = _parse_slice_layouts(html_notes)
    logger.info(
        f"Parsed {len(links)} slice links, {len(alts)} alt texts, "
        f"{len(kickers)} kickers, "
        f"{len(layouts) if layouts else 0} layout hints from task notes"
    )

    # ------------------------------------------------------------------
    # Acquire images
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="cz_email_") as tmpdir:
        tmp_path = Path(tmpdir)

        if images_dir:
            local_images = load_images_from_dir(Path(images_dir))
        else:
            logger.info("Downloading images from Google Drive...")
            try:
                local_images = await download_images_from_drive_with_retry(drive_url, tmp_path)
            except Exception as e:
                result["errors"].append(f"Drive download failed: {e}")
                return result

            if not local_images:
                result["errors"].append(
                    "No images found in Drive folder after retries — "
                    "aborting build instead of shipping a text-only email"
                )
                return result

        logger.info(f"Found {len(local_images)} images: {sorted(local_images.keys())}")

        image_specs = discover_image_configs(local_images, links, alts=alts, layouts=layouts, brand=brand)
        full_count = sum(1 for *_, layout in image_specs if layout == "full")
        half_count = sum(1 for *_, layout in image_specs if layout != "full")
        logger.info(f"Image layout: {full_count} full-width, {half_count} half-width ({half_count // 2} pairs)")

        has_category_blocks = any(
            "category blocks" in str(p.parent).lower() for p in local_images.values()
        )
        footer_override = _parse_footer_variant(html_notes)
        if footer_override is not None:
            logger.info(f"Footer override from task: {'without categories' if footer_override else 'with categories'}")
            has_category_blocks = footer_override
        else:
            logger.info(f"Category blocks subfolder: {'yes' if has_category_blocks else 'no'}")

        # ------------------------------------------------------------------
        # Upload + assemble HTML
        # ------------------------------------------------------------------
        cdn_urls, oversize_errors = upload_images(local_images, brand=brand)
        missing = [fn for fn, *_ in image_specs if fn not in cdn_urls]
        if missing:
            logger.warning(f"Missing CDN URLs for: {missing}")

        html = build_email_html(cdn_urls, image_specs, has_category_blocks=has_category_blocks, kickers=kickers, send_date=due_on, brand=brand)
        logger.info(f"HTML assembled: {len(html):,} chars")

        brand_config = load_brand_config()

        # ------------------------------------------------------------------
        # Create Braze template via API
        # ------------------------------------------------------------------
        template_id = create_braze_template(
            html,
            subject=subject,
            preheader=preheader,
            template_name=campaign_name,
            dry_run=dry_run,
            brand=brand,
        )

        # ------------------------------------------------------------------
        # Playwright campaign creation
        # ------------------------------------------------------------------
        campaign_url = await build_campaign_playwright(
            html=html,
            subject=subject,
            preheader=preheader,
            campaign_name=campaign_name,
            send_date=due_on,
            send_time_raw=send_time_raw,
            segment_name=segment_name,
            brand_config=brand_config,
            task_name=task_name,
            dry_run=dry_run,
            headless=headless,
            brand=brand,
        )

        # ------------------------------------------------------------------
        # Asana writeback
        # ------------------------------------------------------------------
        if campaign_url and not dry_run:
            write_back_to_asana(task_gid, campaign_url, template_id, oversize_errors=oversize_errors, brand=brand)
            if oversize_errors:
                _post_oversize_comment(task_gid, oversize_errors, brand=brand)
            result["braze_url"] = campaign_url
            result["success"] = True
        elif dry_run:
            logger.info("DRY RUN complete — no Braze or Asana changes made")
            result["success"] = True
            result["braze_url"] = None
        else:
            result["errors"].append("No campaign URL returned from Playwright")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Build CZ designed email campaign in Braze")
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--drive-url", help="Google Drive folder URL containing images")
    src_group.add_argument("--images-dir", help="Local directory containing images")
    parser.add_argument("--task-gid", required=True, help="Asana task GID")
    parser.add_argument("--brand", default=BRAND, help="Brand code (CZ, STF). Default: CZ")
    parser.add_argument("--dry-run", action="store_true", help="Build HTML and template only — no Playwright or Asana writes")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless (default: True)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Show browser window")
    parser.add_argument("--skip-upload", action="store_true", help="Skip media library upload (useful for --html-out inspection)")
    parser.add_argument("--html-out", help="Write assembled HTML to this file (for inspection)")
    parser.add_argument(
        "--edit-campaign-url",
        help="Edit an existing draft campaign instead of creating a new one. "
             "Pass the Braze campaign URL. Images are re-uploaded to get fresh CDN URLs.",
    )
    args = parser.parse_args()

    if args.edit_campaign_url:
        # ------------------------------------------------------------------
        # Edit mode: update HTML in an existing draft campaign
        # ------------------------------------------------------------------
        task = fetch_task_by_gid(args.task_gid)
        if not task:
            raise RuntimeError(f"Could not fetch Asana task {args.task_gid}")
        subject = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
        preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""
        due_on = task.get("due_on") or ""
        html_notes = task.get("html_notes") or ""
        links = _parse_slice_links(html_notes, brand=args.brand)
        alts = _parse_slice_alts(html_notes, brand=args.brand)
        kickers = _parse_kickers(html_notes)
        layouts = _parse_slice_layouts(html_notes)

        with tempfile.TemporaryDirectory(prefix="cz_email_") as tmpdir:
            tmp_path = Path(tmpdir)
            if args.images_dir:
                local_images = load_images_from_dir(Path(args.images_dir))
            else:
                logger.info("Downloading images from Google Drive...")
                local_images = download_images_from_drive(args.drive_url, tmp_path)

            image_specs = discover_image_configs(local_images, links, alts=alts, layouts=layouts, brand=args.brand)
            has_category_blocks = any(
                "category blocks" in str(p.parent).lower() for p in local_images.values()
            )
            footer_override = _parse_footer_variant(html_notes)
            if footer_override is not None:
                logger.info(f"Footer override from task: {'without categories' if footer_override else 'with categories'}")
                has_category_blocks = footer_override

            if args.skip_upload:
                cdn_urls: Dict[str, str] = {}
                oversize_errors: List[MediaFileTooLargeError] = []
            else:
                cdn_urls, oversize_errors = upload_images(local_images, brand=args.brand)

            html = build_email_html(cdn_urls, image_specs, has_category_blocks=has_category_blocks, kickers=kickers, send_date=due_on, brand=args.brand)

            if args.html_out:
                Path(args.html_out).write_text(html, encoding="utf-8")
                logger.info(f"HTML written to {args.html_out}")

            brand_config = load_brand_config()
            logger.info(f"Edit mode — updating existing campaign: {args.edit_campaign_url}")
            success = await edit_existing_campaign(
                html=html,
                subject=subject,
                preheader=preheader,
                campaign_url=args.edit_campaign_url,
                brand_config=brand_config,
                headless=args.headless,
                brand=args.brand,
            )
            if not success:
                logger.error("Campaign edit failed")
            if oversize_errors and args.task_gid and not args.dry_run:
                _post_oversize_comment(args.task_gid, oversize_errors, brand=args.brand)
    else:
        # ------------------------------------------------------------------
        # Normal build mode
        # ------------------------------------------------------------------
        result = await build_cz_designed_email(
            task_gid=args.task_gid,
            drive_url=args.drive_url,
            images_dir=args.images_dir,
            dry_run=args.dry_run,
            headless=args.headless,
            brand=args.brand,
        )

        if args.html_out and not result.get("success"):
            # For --html-out with --dry-run, do a separate pass to write HTML
            pass

        if result.get("errors"):
            for err in result["errors"]:
                logger.error(f"Build error: {err}")
        elif result.get("success"):
            logger.info(f"Build complete → {result.get('braze_url') or 'DRY RUN'}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
