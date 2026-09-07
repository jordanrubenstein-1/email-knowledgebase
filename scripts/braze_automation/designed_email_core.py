#!/usr/bin/env python3
"""
Shared core for designed email auto-builders (all brands, all platforms).

This module contains everything brand-agnostic:
  - Brief parsing   — extract per-slice layout + links from Asana html_notes
  - Layout logic    — CLI override → brief → filename → image dimensions
  - Drive helpers   — list + download slice images from a Google Drive folder
  - Image cache     — local JSON cache (Drive file ID → CDN URL) to avoid re-uploads
  - HTML assembly   — Outlook-safe table layout, full-width + 50/50 rows, preheader div
  - Footer builder  — reads brand_config.yaml `designed_email.footer` section; all
                      footer elements are optional so new brands just add config
  - Sale check      — looks up sale_schedules.yaml for a brand on a given date

Platform-specific campaign creation (Klaviyo API, Braze Playwright) lives in
the entry-point scripts that import from here.

Adding a new brand:
  1. Add a `designed_email` section to data/brand_config.yaml.
  2. Run the appropriate entry-point script with --brand NEW_BRAND.
  3. No Python changes needed.
"""

from __future__ import annotations

import html as _html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FULL_WIDTH_THRESHOLD_PX = 450  # images narrower than this → 50/50 (dimension fallback)

SLICE_FILENAME_RE      = re.compile(r"^[Ss]lice\s*(\d+)\b", re.IGNORECASE)
_BARE_NUMERIC_SLICE_RE  = re.compile(r"^(\d{1,2})(?:[_\-\s]|\.[a-zA-Z]{2,4}$)")  # "1.png", "1_hero.png", "1-hero.png", "1 hero.png" — not "7.22 Summer Sale launch.png" (decimal-looking date stamps)
_HALF_WIDTH_FILENAME_RE = re.compile(r"\b(left|right|50.?50|half)\b", re.IGNORECASE)

# Default cache file path; entry-point scripts may override
DEFAULT_IMAGE_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "klaviyo_image_cache.json"


# ---------------------------------------------------------------------------
# Brief parser
# ---------------------------------------------------------------------------

def _strip_tags(text: str) -> str:
    """Remove all HTML tags from a string.

    Replaces each tag with a space (not empty string) before collapsing
    whitespace, so that adjacent tag-separated content - e.g. sibling <li>
    items with no whitespace between them, which is intentional in the raw
    html_notes so Asana renders clean bullets - never gets glued into one
    word once tags are stripped. Confirmed bug 2026-09-03: a Link field
    immediately followed by the next <li>'s text (no separating whitespace)
    let the link-extraction regex's \\S+ swallow the next li's leading word
    into the URL (e.g. ".../beds" + "Kicker Slice 2..." -> ".../bedsKicker").
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


# Alt-text fields checked after CTA, in priority order — used verbatim, no
# length gate (matches the Braze CZ/STF/BUR builder: only CTA is length-gated
# there, per _parse_slice_alts() in build_cz_designed_email.py). Ported here
# since Klaviyo's download_and_upload_slices() previously had no brief-derived
# alt text at all, only ever the raw Drive filename stem (confirmed gap
# 2026-09-05).
_ALT_FALLBACK_FIELDS = ("hed", "name", "product tag", "eyebrow")
_ALT_MAX_WORDS = 6  # a CTA longer than this reads as body copy, not alt text — truncate it


def _parse_slice_fields(sub_ul_html: str) -> dict[str, str]:
    """Extract {field_label_lowercased: value} from a slice's <ul> sub-bullets.

    Each <li>Field: value</li> becomes one entry. Parsed per-<li> (not on the
    whole flattened block) so one field's value never bleeds into the next —
    the flattened text this module otherwise works with has no line
    boundaries between sub-bullets.
    """
    fields: dict[str, str] = {}
    for li_html in re.findall(r'<li>(.*?)</li>', sub_ul_html, re.IGNORECASE | re.DOTALL):
        li_text = _strip_tags(li_html).strip()
        m = re.match(r'([A-Za-z][A-Za-z0-9 /]{0,20}?)\s*:\s*(.+)$', li_text)
        if m:
            key = m.group(1).strip().lower()
            if key not in fields:  # first occurrence wins (e.g. "CTA" before "CTA 2")
                fields[key] = m.group(2).strip()
    return fields


def _derive_slice_alt(label: str, fields: dict[str, str]) -> str:
    """Pick alt text for a slice from its parsed fields, falling back to its label.

    Priority: CTA/Hero CTA (verbatim if short, else truncated) → HED → Name →
    Product tag → Eyebrow → the slice's own label (e.g. "Hero", "Product 1").
    Only CTA is length-gated — a long CTA reads as body copy, not alt text —
    HED/Name/etc. are used verbatim regardless of length, same as the Braze
    CZ/STF/BUR builder. Never returns empty: the caller's remaining fallback
    (a prettified Drive filename) only kicks in when there's no label either,
    which shouldn't happen in practice.
    """
    for key in ("cta", "hero cta"):
        value = fields.get(key)
        if value:
            words = value.split()
            return value if len(words) <= _ALT_MAX_WORDS else " ".join(words[:_ALT_MAX_WORDS])
    for key in _ALT_FALLBACK_FIELDS:
        value = fields.get(key)
        if value:
            return value
    return label.strip()


def parse_brief_slices(html_notes: str) -> dict[int, dict]:
    """
    Parse the Body Copy section of an Asana html_notes field.

    Returns a mapping of slice_num → {is_half_width: bool|None, link: str|None,
    alt: str|None}.

    Layout detection order:
      1. Slice name contains "50/50 left/right" or bare "left"/"right"
      2. "Layout: 50/50" sub-bullet under the slice

    Link is extracted from a "Link: https://..." sub-bullet. Alt text is
    derived from the slice's copy fields (CTA/HED/Name/etc., see
    _derive_slice_alt()), falling back to the slice's own label.
    Slices marked "[content block - no slice needed]" are skipped.
    Returns {} when no Body Copy section is found.
    """
    if not html_notes:
        return {}

    body_match = re.search(r'Body Copy', html_notes, re.IGNORECASE)
    if not body_match:
        return {}
    body_html = html_notes[body_match.start():]

    results: dict[int, dict] = {}
    slice_header_re = re.compile(
        r'<li>\s*(?:<[^>]+>)*\s*Slice\s+(\d+)\s*[—–-]?\s*([^<]*)',
        re.IGNORECASE,
    )
    for m in slice_header_re.finditer(body_html):
        num   = int(m.group(1))
        label = _strip_tags(m.group(2)).strip()

        if "content block" in label.lower() or "no slice" in label.lower():
            continue

        is_half: Optional[bool] = None
        if re.search(r'50.?50|(?:\b(?:left|right)\b)', label, re.IGNORECASE):
            is_half = True

        sub_start = m.end()
        sub_ul = re.search(r'<ul>(.*?)</ul>', body_html[sub_start:sub_start + 2000],
                           re.IGNORECASE | re.DOTALL)
        link: Optional[str] = None
        fields: dict[str, str] = {}
        if sub_ul:
            sub_text = _strip_tags(sub_ul.group(1))
            if is_half is None:
                layout_m = re.search(r'Layout\s*:\s*(.*)', sub_text, re.IGNORECASE)
                if layout_m and "50" in layout_m.group(1):
                    is_half = True
            link_m = re.search(r'Link\s*:\s*(https?://\S+)', sub_text, re.IGNORECASE)
            if link_m:
                link = link_m.group(1).rstrip('.,;)')
            fields = _parse_slice_fields(sub_ul.group(1))

        results[num] = {
            "is_half_width": is_half,
            "link": link,
            "alt": _derive_slice_alt(label, fields),
        }

    return results


# ---------------------------------------------------------------------------
# Layout classification
# ---------------------------------------------------------------------------

def _image_width(path: str) -> Optional[int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size[0]
    except Exception as e:
        logger.warning(f"Could not read image dimensions from {path}: {e}")
        return None


def _is_full_width_by_dims(path: str) -> bool:
    """Dimension fallback: True if image width ≥ FULL_WIDTH_THRESHOLD_PX."""
    w = _image_width(path)
    return (w is None) or (w >= FULL_WIDTH_THRESHOLD_PX)


def classify_slice_layout(
    slice_num: int,
    filename: str,
    brief_info: dict,
    half_width_from: Optional[int] = None,
) -> Optional[bool]:
    """
    Return True (full-width), False (50/50), or None (unknown → check image dims).

    Priority:
      1. --half-width-from N CLI flag: slices >= N are 50/50
      2. Brief html_notes: is_half_width True/False → definitive
      3. Filename keyword (left/right/50-50/half) → 50/50
      4. None → caller falls back to image dimensions
    """
    if half_width_from is not None:
        return slice_num < half_width_from
    info = brief_info.get(slice_num, {})
    brief_half = info.get("is_half_width")
    if brief_half is not None:
        return not brief_half
    if _HALF_WIDTH_FILENAME_RE.search(filename):
        return False
    return None


# ---------------------------------------------------------------------------
# Drive folder → sorted slice list
# ---------------------------------------------------------------------------

def _parse_slice_number(name: str) -> Optional[int]:
    m = SLICE_FILENAME_RE.match(name)
    if m:
        return int(m.group(1))
    m = _BARE_NUMERIC_SLICE_RE.match(name)
    return int(m.group(1)) if m else None


def list_drive_slices(folder_url: str) -> list[dict]:
    """
    List slice images in a Drive folder, sorted by slice number.
    Files must start with "Slice N" (e.g. "Slice 1 - hero.png") or a bare
    number (e.g. "1.png", "2.png") — anything else is silently skipped.

    Exception: a folder holding exactly ONE image is unambiguous, so that
    image is accepted whatever it is named (see below).

    Raises RuntimeError if Drive credentials are not configured.
    """
    from utils.drive_client import list_folder_images
    all_files = list_folder_images(folder_url)
    slices = []
    for f in all_files:
        num = _parse_slice_number(f["name"])
        if num is not None:
            slices.append({**f, "slice_num": num})

    # Single-image fallback.
    #
    # Designers routinely name a one-slice email after the send date rather
    # than "1.gif" — e.g. "8.19-EA-Last-Chance.gif". That is exactly the
    # decimal-date shape _BARE_NUMERIC_SLICE_RE deliberately rejects, so the
    # lone image was skipped and the whole build aborted over a filename.
    #
    # With exactly one image there is no slice ORDER to get wrong, so accept
    # it as slice 1. Deliberately NOT extended to 2+ unmatched files: there
    # the ordering is unknowable and guessing would silently ship slices in
    # the wrong sequence, which is worse than failing loudly.
    if not slices and len(all_files) == 1:
        lone = all_files[0]
        logger.warning(
            f"Single unrecognized image {lone['name']!r} in Drive folder — "
            f"treating it as slice 1"
        )
        slices.append({**lone, "slice_num": 1})

    slices.sort(key=lambda x: x["slice_num"])
    return slices


# ---------------------------------------------------------------------------
# Image cache (Drive file ID → CDN URL)
# ---------------------------------------------------------------------------

def load_image_cache(brand: str, cache_path: Path = DEFAULT_IMAGE_CACHE_PATH) -> dict:
    """Load the per-brand image cache dict from the JSON file."""
    try:
        if cache_path.exists():
            return json.loads(cache_path.read_text()).get(brand, {})
    except Exception:
        pass
    return {}


def save_image_cache(brand: str, file_id: str, cdn_url: str,
                     cache_path: Path = DEFAULT_IMAGE_CACHE_PATH) -> None:
    """Persist a single Drive file ID → CDN URL mapping to the JSON cache."""
    try:
        full = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        full.setdefault(brand, {})[file_id] = cdn_url
        cache_path.write_text(json.dumps(full, indent=2))
    except Exception as e:
        logger.warning(f"Could not save image cache: {e}")


# ---------------------------------------------------------------------------
# Download + upload loop (injectable uploader)
# ---------------------------------------------------------------------------

def _prettify_filename_alt(filename: str) -> str:
    """Turn a Drive filename stem into readable alt text: last-resort fallback.

    Matches the Braze CZ/STF/BUR builder's own filename fallback
    (discover_image_configs() in build_cz_designed_email.py) so both
    platforms degrade to the same thing when a slice has no brief-derived
    alt text at all (e.g. "Slice 3.png" -> "Slice 3").
    """
    stem = Path(filename).stem
    return stem.replace("-", " ").replace("_", " ").title()


def download_and_upload_slices(
    slice_files: list[dict],
    uploader: Callable[[str, str], Optional[str]],
    brand: str,
    default_link: str,
    img_cache: Optional[dict] = None,
    cache_path: Path = DEFAULT_IMAGE_CACHE_PATH,
) -> Optional[list[dict]]:
    """
    For each slice file in slice_files (pre-classified with _layout_preclass,
    _layout_source, _link_override, and optionally _alt_override keys set by
    the caller), download from Drive, upload via `uploader(local_path, name) →
    cdn_url`, and return assembled slice dicts ready for assemble_html().

    Alt text prefers `_alt_override` (brief-derived, via parse_brief_slices())
    and falls back to a prettified Drive filename — confirmed gap 2026-09-05:
    this previously always used the raw filename stem with no brief-derived
    fallback at all, unlike the Braze CZ/STF/BUR builder's rich CTA/HED/Name
    priority chain.

    Checks the local image cache before downloading; saves new uploads to cache.
    `uploader` is injected by the entry-point script — Klaviyo passes
    `client.upload_image_from_file`; a Braze/S3 uploader passes its own function.

    Returns None and logs errors if any upload fails.
    """
    from utils.drive_client import download_image

    if img_cache is None:
        img_cache = load_image_cache(brand, cache_path)

    assembled: list[dict] = []
    tmp_files: list[str] = []

    try:
        for sf in slice_files:
            # --- Cache hit ---
            cached_url = img_cache.get(sf["id"])
            if cached_url:
                logger.info(f"Slice {sf['slice_num']}: using cached CDN URL")
                pre = sf["_layout_preclass"]
                if pre is True:
                    is_half = False
                elif pre is False:
                    is_half = True
                else:
                    is_half = False  # no file to measure; default full-width
                assembled.append({
                    "slice_num":    sf["slice_num"],
                    "cdn_url":      cached_url,
                    "link":         sf.get("_link_override") or default_link,
                    "alt":          sf.get("_alt_override") or _prettify_filename_alt(sf["name"]),
                    "is_full_width": not is_half,
                })
                continue

            # --- Download from Drive ---
            drive_url  = f"https://drive.google.com/file/d/{sf['id']}/view"
            logger.info(f"Downloading Slice {sf['slice_num']}: {sf['name']}")
            local_path = download_image(drive_url)
            tmp_files.append(local_path)

            # --- Classify layout (dimension fallback if needed) ---
            pre    = sf["_layout_preclass"]
            source = sf["_layout_source"]
            if pre is True:
                is_half = False
            elif pre is False:
                is_half = True
            else:
                is_half = not _is_full_width_by_dims(local_path)
                source  = "dims"
            logger.info(f"  Layout: {'50/50' if is_half else 'full-width'} [{source}]")

            # --- Upload to CDN ---
            logger.info(f"  Uploading to CDN...")
            cdn_url = uploader(local_path, sf["name"])
            if not cdn_url:
                logger.error(f"Failed to upload Slice {sf['slice_num']} ({sf['name']!r})")
                return None
            logger.info(f"  CDN URL: {cdn_url[:80]}...")
            save_image_cache(brand, sf["id"], cdn_url, cache_path)

            assembled.append({
                "slice_num":    sf["slice_num"],
                "cdn_url":      cdn_url,
                "link":         sf.get("_link_override") or default_link,
                "alt":          sf.get("_alt_override") or _prettify_filename_alt(sf["name"]),
                "is_full_width": not is_half,
            })
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass

    return assembled


# ---------------------------------------------------------------------------
# Sale check
# ---------------------------------------------------------------------------

def check_on_sale(brand: str, send_date_str: str) -> bool:
    """Return True if brand has an active sale on send_date_str (YYYY-MM-DD)."""
    try:
        from utils.sale_matcher import load_sale_schedules
        from datetime import date
        d = date.fromisoformat(send_date_str)
        for s in load_sale_schedules():
            if s.get("brand") != brand:
                continue
            try:
                if date.fromisoformat(s["start_date"]) <= d <= date.fromisoformat(s["end_date"]):
                    return True
            except (KeyError, ValueError):
                pass
    except Exception as e:
        logger.warning(f"Sale check failed: {e}")
    return False


# ---------------------------------------------------------------------------
# Footer builder (reads brand_config.yaml → designed_email.footer)
# ---------------------------------------------------------------------------

def build_footer_html(footer_cfg: dict, year: int, on_sale: bool) -> str:
    """
    Build the complete email footer rows from brand config.

    footer_cfg is the `designed_email.footer` dict from brand_config.yaml.
    All keys are optional — omit any section and it's silently skipped:

      sms_signup:    image_url, link  (wrapped in Klaviyo phone_number conditional)
      follow_us:     image_url, link
      social_icons:  list of {link, image_url, width}
      address:       str
      company_name:  str  (used in copyright line)
      sale_disclaimer: str  (shown in italics when on_sale=True)

    All rows use colspan="2" so they span both columns of the email table.
    """
    rows: list[str] = []

    def _img_row(src: str, alt: str, link: str, comment: str = "") -> str:
        sl = _html.escape(link, quote=True)
        ss = _html.escape(src, quote=True)
        sa = _html.escape(alt, quote=True)
        cmt = f"\n        <!-- {comment} -->" if comment else ""
        return (
            f'{cmt}\n'
            f'        <tr>\n'
            f'          <td colspan="2" style="padding:0; font-size:0; line-height:0;">\n'
            f'            <a href="{sl}" style="display:block;">'
            f'<img src="{ss}" width="600" alt="{sa}" '
            f'style="width:100%; max-width:600px; height:auto; display:block; border:0;"></a>\n'
            f'          </td>\n'
            f'        </tr>\n'
        )

    # 1. SMS signup (conditional on phone_number not set)
    sms = footer_cfg.get("sms_signup")
    if sms and sms.get("image_url") and sms.get("link"):
        rows.append(
            '\n        <!-- SMS signup — shown only when subscriber has no phone number -->\n'
            '        {% if not person|lookup:"phone_number" %}'
            + _img_row(sms["image_url"], "Sign up for texts", sms["link"])
            + '        {% endif %}\n'
        )

    # 2. Follow us image
    follow = footer_cfg.get("follow_us")
    if follow and follow.get("image_url") and follow.get("link"):
        rows.append(_img_row(
            follow["image_url"], "Follow us!", follow["link"],
            comment="Follow us"
        ))

    # 3. Social icons
    icons = footer_cfg.get("social_icons", [])
    if icons:
        icon_cells = ""
        for icon in icons:
            sl = _html.escape(icon.get("link", ""), quote=True)
            ss = _html.escape(icon.get("image_url", ""), quote=True)
            w  = icon.get("width", 28)
            icon_cells += (
                f'            <a href="{sl}" target="_blank" style="display:inline-block; padding:0 10px 0 0;">'
                f'<img src="{ss}" width="{w}" alt="" '
                f'style="border:0; height:auto; outline:none; text-decoration:none; width:{w}px;"></a>\n'
            )
        rows.append(
            '\n        <!-- Social icons -->\n'
            '        <tr>\n'
            '          <td colspan="2" align="center" style="padding:1px 9px 15px 9px; font-size:0; line-height:0;">\n'
            + icon_cells
            + '          </td>\n'
              '        </tr>\n'
        )

    # 4. Text footer (address + copyright + unsubscribe)
    address      = footer_cfg.get("address", "")
    company_name = footer_cfg.get("company_name", "")
    disclaimer   = footer_cfg.get("sale_disclaimer", "")

    sale_line = ""
    if on_sale and disclaimer:
        sale_line = (
            f'<p style="margin:0 0 6px 0; font-size:10px; font-style:italic;">'
            f'{_html.escape(disclaimer)}'
            f'</p>'
        )

    address_line  = (f'<p style="margin:0 0 4px 0;">{_html.escape(address)}</p>' if address else "")
    copyright_line = (
        f'<p style="margin:0 0 4px 0;">&copy; {year} {_html.escape(company_name)}</p>'
        if company_name else
        f'<p style="margin:0 0 4px 0;">&copy; {year}</p>'
    )

    rows.append(
        '\n        <!-- Footer text -->\n'
        '        <tr>\n'
        '          <td colspan="2" align="center" valign="top"\n'
        '              style="padding:27px 9px; background-color:#F2F2F2;\n'
        '                     font-family:&quot;Helvetica Neue&quot;,Arial;\n'
        '                     font-size:11px; font-weight:400; letter-spacing:2px;\n'
        '                     line-height:1.5; text-align:center; color:#222222;">\n'
        f'            {sale_line}\n'
        f'            {address_line}\n'
        f'            {copyright_line}\n'
        '            <p style="margin:0;">If you no longer wish to receive emails from us, you can '
        '<a href="{% unsubscribe_link %}" style="color:#000; font-weight:400; text-decoration:underline;">UNSUBSCRIBE</a>'
        '</p>\n'
        '          </td>\n'
        '        </tr>\n'
    )

    return "".join(rows)


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

_HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml"
      xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:v="urn:schemas-microsoft-com:vml">
<head>
  <meta charset="utf-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title></title>
  <!--[if mso]>
  <noscript>
    <xml><o:OfficeDocumentSettings>
      <o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings></xml>
  </noscript>
  <![endif]-->
  <style type="text/css">
    /* ---- Reset ---- */
    body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
    table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; border-collapse: collapse; }
    img { -ms-interpolation-mode: bicubic; border: 0; display: block;
          height: auto; line-height: 100%; outline: none; text-decoration: none; }
    /* ---- Responsive ---- */
    @media only screen and (max-width: 620px) {
      .email-container { width: 100% !important; max-width: 100% !important; }
      .full-img { width: 100% !important; max-width: 100% !important; height: auto !important; }
      /* 50/50 cells (.half-cell, .half-img) intentionally excluded —
         50/50 blocks stay side-by-side on mobile */
    }
  </style>
</head>
<!--[if mso]><body class="mso"><![endif]-->
<!--[if !mso]><!--><body style="margin:0; padding:0; background-color:#ffffff; width:100%; -webkit-text-size-adjust:none;"><!--<![endif]-->

<!-- ======================================================
     OUTER WRAPPER — centers email in inbox pane
     ====================================================== -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:#ffffff; margin:0; padding:0;">
  <tr>
    <td align="center" valign="top" style="padding:0;">

      <!-- ================================================
           EMAIL CONTAINER — 600px fixed
           ================================================ -->
      <!--[if mso]><table role="presentation" align="center" border="0"
        cellpadding="0" cellspacing="0" width="600"><tr><td><![endif]-->
      <table role="presentation" class="email-container"
             width="600" cellpadding="0" cellspacing="0" border="0" align="center"
             style="background-color:#ffffff; width:600px; max-width:600px;">

"""

_HTML_CLOSE = """\

      </table>
      <!--[if mso]></td></tr></table><![endif]-->
      <!-- END EMAIL CONTAINER -->

    </td>
  </tr>
</table>
<!-- END OUTER WRAPPER -->

</body>
</html>
"""


def _preheader_div(preheader: str) -> str:
    """
    Hidden preheader div for inbox preview text.

    For Klaviyo HTML/CSS code templates the preview_text API field is ignored —
    inbox clients read from the top of the email body instead. This hidden div
    sets it correctly; the &nbsp;&zwnj; padding prevents body copy from bleeding in.
    """
    text    = _html.escape(preheader, quote=False)
    padding = "&nbsp;&zwnj;" * 110
    return (
        '\n<!-- Preheader — hidden from view, read by inbox clients as preview text -->\n'
        f'<div style="display:none; max-height:0; overflow:hidden;">'
        f'{text}{padding}'
        f'</div>\n'
    )


def _full_width_row(cdn_url: str, link: str, alt: str, slice_num: int) -> str:
    """
    600px full-width image row.

    colspan="2" ensures this cell spans both columns when the same table also
    has 50/50 rows (which define 2 columns). Without it, table layout engines
    constrain the single cell to one column (300px).
    """
    sl = _html.escape(link, quote=True)
    ss = _html.escape(cdn_url, quote=True)
    sa = _html.escape(alt, quote=True)
    return (
        f'\n        <!-- Slice {slice_num} — full-width -->\n'
        f'        <tr>\n'
        f'          <td colspan="2" valign="top" style="padding:0; font-size:0; line-height:0;">\n'
        f'            <a href="{sl}" style="display:block;">'
        f'<img src="{ss}" class="full-img" width="600" alt="{sa}" '
        f'style="width:100%; max-width:600px; height:auto; display:block; border:0;"></a>\n'
        f'          </td>\n'
        f'        </tr>\n'
    )


def _half_width_pair_row(
    left_cdn: str, left_link: str, left_alt: str, left_num: int,
    right_cdn: str, right_link: str, right_alt: str, right_num: int,
) -> str:
    """Two 50/50 half-width (300px each) cells in one row."""
    def cell(cdn: str, link: str, alt: str) -> str:
        sl = _html.escape(link, quote=True)
        ss = _html.escape(cdn, quote=True)
        sa = _html.escape(alt, quote=True)
        return (
            f'          <td class="half-cell" width="300" valign="top"\n'
            f'              style="padding:0; font-size:0; line-height:0; width:300px;">\n'
            f'            <a href="{sl}" style="display:block;">'
            f'<img src="{ss}" class="half-img" width="300" alt="{sa}" '
            f'style="width:100%; max-width:300px; height:auto; display:block; border:0;"></a>\n'
            f'          </td>\n'
        )
    return (
        f'\n        <!-- Slice {left_num} + {right_num} — 50/50 -->\n'
        f'        <tr>\n'
        + cell(left_cdn, left_link, left_alt)
        + cell(right_cdn, right_link, right_alt)
        + f'        </tr>\n'
    )


def assemble_html(slices: list[dict], preheader: str = "", footer_html: str = "") -> str:
    """
    Assemble complete email HTML from slice dicts + pre-built footer HTML.

    Each slice dict: cdn_url, link, alt, is_full_width, slice_num.
    Adjacent 50/50 (is_full_width=False) slices are paired into one row.
    An unpaired trailing 50/50 slice is rendered full-width with a warning.

    footer_html is the output of build_footer_html() — already brand-specific.
    """
    rows: list[str] = []
    i = 0
    while i < len(slices):
        s = slices[i]
        if s["is_full_width"]:
            rows.append(_full_width_row(s["cdn_url"], s["link"], s["alt"], s["slice_num"]))
            i += 1
        else:
            if i + 1 < len(slices) and not slices[i + 1]["is_full_width"]:
                r = slices[i + 1]
                rows.append(_half_width_pair_row(
                    s["cdn_url"], s["link"], s["alt"], s["slice_num"],
                    r["cdn_url"], r["link"], r["alt"], r["slice_num"],
                ))
                i += 2
            else:
                logger.warning(
                    f"Slice {s['slice_num']} is 50/50 but has no pair — rendering full-width"
                )
                rows.append(_full_width_row(s["cdn_url"], s["link"], s["alt"], s["slice_num"]))
                i += 1

    head = _HTML_HEAD
    if preheader:
        anchor = "\n<!-- ======================================================"
        head = head.replace(anchor, _preheader_div(preheader) + anchor, 1)

    return head + "".join(rows) + footer_html + _HTML_CLOSE
