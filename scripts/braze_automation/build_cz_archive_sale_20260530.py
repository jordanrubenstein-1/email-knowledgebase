#!/usr/bin/env python3
"""
One-off build script: CZ Archive Sale email — 2026-05-30
Asana task GID: 1213928748054248

Workflow:
  1. Download 12 images from Google Drive (OAuth2)
  2. Detect actual pixel dimensions with PIL
  3. Upload each image to Braze media library (REST, BRAZE_API_KEY_MEDIA_CZ)
  4. Rebuild HTML with real Braze CDN URLs + correct image widths
  5. Save rebuilt HTML to campaigns/html/
  6. Create a Braze campaign draft via REST (campaigns/create)
  7. Update Asana task: Braze link, status → Ready for QA, comment

Usage:
    uv run python scripts/braze_automation/build_cz_archive_sale_20260530.py
    uv run python scripts/braze_automation/build_cz_archive_sale_20260530.py --dry-run
"""

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Path + env setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from utils.drive_client import download_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Campaign constants
# ---------------------------------------------------------------------------
BRAND          = "CZ"
ASANA_TASK_GID = "1213928748054248"
ASSIGNEE_GID   = "1209324586499326"
CAMPAIGN_NAME  = "P_EM_2026_05_30_CZ_D_Memorial_Day_Archive_Sale"
SUBJECT        = "Rare finds from the archive"
PREHEADER      = "Up to 70% off styles that won't be restocked."
FROM_NAME      = "The Citizenry"
FROM_EMAIL     = "info@mail.the-citizenry.com"
HTML_OUTPUT    = PROJECT_ROOT / "campaigns" / "html" / "p_em_2026_05_30_cz_d_memorial_day_archive_sale.html"

# ---------------------------------------------------------------------------
# Asana field GIDs
# ---------------------------------------------------------------------------
FIELD_TASK_STATUS = "1209982215610993"
FIELD_BRAZE_LINK  = "1210710306792280"
STATUS_READY_FOR_QA = "1213535128306988"
ASANA_BASE_URL    = "https://app.asana.com/api/1.0"

# ---------------------------------------------------------------------------
# Google Drive file IDs
# Order matters — dict keys are used as local temp-file names for clarity
# ---------------------------------------------------------------------------
DRIVE_FILES = {
    "1.png":           "1axIG7JqaaiS28JQJFn_3_doU9hQpuV-4",
    "2.gif":           "1hR1FGhQL1Y6TUZZgt03AxzutgLA82je8",
    "3.png":           "1vEjol9OBibTyGtP6wgZwd3iQYF415b37",
    "4.png":           "1tIHYXrgnGFKM2DS6rWUyCum3AV1EQPKq",
    "link-farm-01.png":"13rIGJKNWHYc1j3rndb0SheHcpEQe4gWQ",
    "link-farm-02.png":"105J0n8FnCuOScJ77i6q-1a6oy7bx-ycF",
    "link-farm-03.png":"154ePgshJjL-okiGEvh3v2TJ9BmSgheJS",
    "link-farm-04.png":"1MWKayrHHFgQGRx2J-JS69Jj2RzdSEnuG",
    "link-farm-05.png":"1mBh0Cafz-sKhp3CveN5aABQuYVJyg0-L",
    "link-farm-06.png":"1C8FhC9cWJg_ODTGM2PlCS1567cvmjOnj",
    "link-farm-07.png":"1s8LOHMxWLp9udcKeHlubji0voZ1fl3if",
    "link-farm-08.png":"16PKEfm55GZpIVBYjSiRL_1mWqArL2IzW",
}

# ---------------------------------------------------------------------------
# Image layout metadata
# Links and alt text confirmed from Figma + reference email (5/16)
# ---------------------------------------------------------------------------
IMAGE_METADATA = {
    "1.png": {
        "alt":  "Memorial Day Sale — The Archive Sale",
        "link": "https://www.the-citizenry.com/",
        "layout": "full",
    },
    "2.gif": {
        "alt":  "New Styles Added: The Archive Sale — Shop Up to 70% Off",
        "link": "https://www.the-citizenry.com/collections/archive-sale",
        "layout": "full",
    },
    "3.png": {
        "alt":  "Shop The Archive Sale",
        "link": "https://www.the-citizenry.com/collections/archive-sale",
        "layout": "full",
    },
    "4.png": {
        "alt":  "Shop Archive Sale",
        "link": "https://www.the-citizenry.com/collections/archive-sale",
        "layout": "full",
    },
    "link-farm-01.png": {
        "alt":  "Memorial Day Sale — Up to 70% Off Archive Sale",
        "link": "https://www.the-citizenry.com/",
        "layout": "full",
    },
    "link-farm-02.png": {
        "alt":  "Bedding",
        "link": "https://www.the-citizenry.com/collections/shop-all-bedding-2",
        "layout": "half",
    },
    "link-farm-03.png": {
        "alt":  "Rugs",
        "link": "https://www.the-citizenry.com/collections/shop-all-rugs-1",
        "layout": "half",
    },
    "link-farm-04.png": {
        "alt":  "Pillows",
        "link": "https://www.the-citizenry.com/collections/shop-all-pillows",
        "layout": "half",
    },
    "link-farm-05.png": {
        "alt":  "Furniture",
        "link": "https://www.the-citizenry.com/collections/shop-all-furniture",
        "layout": "half",
    },
    "link-farm-06.png": {
        "alt":  "Best Sellers",
        "link": "https://www.the-citizenry.com/collections/all-best-sellers",
        "layout": "half",
    },
    "link-farm-07.png": {
        "alt":  "Shop All Sale",
        "link": "https://www.the-citizenry.com/",
        "layout": "half",
    },
    "link-farm-08.png": {
        "alt":  "Up to 70% Off Archive Sale",
        "link": "https://www.the-citizenry.com/collections/archive-sale",
        "layout": "full",
    },
}


# ---------------------------------------------------------------------------
# Step 1: Download images from Google Drive
# ---------------------------------------------------------------------------

def download_all_images(dry_run: bool = False) -> dict:
    """Download all 12 Drive images to temp files. Returns {name: local_path}."""
    paths = {}
    if dry_run:
        logger.info("[DRY RUN] Would download %d images from Google Drive", len(DRIVE_FILES))
        return {name: f"/tmp/{name}" for name in DRIVE_FILES}

    for name, file_id in DRIVE_FILES.items():
        ext = Path(name).suffix  # .png or .gif
        drive_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        logger.info("Downloading %s (Drive ID: %s)...", name, file_id)
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.close()
        local_path = download_image(drive_url, dest_path=tmp.name)
        paths[name] = local_path
        size_kb = Path(local_path).stat().st_size // 1024
        logger.info("  → saved to %s (%d KB)", local_path, size_kb)

    return paths


# ---------------------------------------------------------------------------
# Step 2: Detect image dimensions
# ---------------------------------------------------------------------------

def get_image_dimensions(local_paths: dict) -> dict:
    """Return {name: (width, height)} using PIL."""
    from PIL import Image
    dims = {}
    for name, path in local_paths.items():
        try:
            with Image.open(path) as img:
                dims[name] = img.size  # (width, height)
                logger.info("  %s → %dx%d px", name, img.size[0], img.size[1])
        except Exception as e:
            logger.warning("  Could not read dimensions for %s: %s — defaulting", name, e)
            dims[name] = (600, 100)  # safe fallback
    return dims


# ---------------------------------------------------------------------------
# Step 3: Upload to Braze media library
# ---------------------------------------------------------------------------

def upload_images_to_braze(local_paths: dict, dry_run: bool = False) -> dict:
    """Upload each image to Braze media library. Returns {name: cdn_url}."""
    media_key = os.environ.get("BRAZE_API_KEY_MEDIA_CZ")
    base_url   = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

    if not media_key:
        raise RuntimeError("BRAZE_API_KEY_MEDIA_CZ not set in .env")

    cdn_urls = {}
    for name, path in local_paths.items():
        if dry_run:
            cdn_urls[name] = f"https://braze-images.com/appboy/communication/assets/image_assets/images/dry-run/{name}"
            continue

        ext = Path(path).suffix.lstrip(".")
        logger.info("Uploading %s to Braze media library...", name)
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    f"{base_url}/media_library/create",
                    headers={"Authorization": f"Bearer {media_key}"},
                    files={"asset_file": (name, f, f"image/{ext}")},
                    data={"name": name},
                    timeout=120,
                )
            if resp.status_code in (200, 201):
                assets = resp.json().get("new_assets", [])
                if assets:
                    url = assets[0]["url"]
                    cdn_urls[name] = url
                    logger.info("  → %s", url)
                else:
                    raise RuntimeError(f"Upload OK but no new_assets in response: {resp.text[:200]}")
            else:
                raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:300]}")
        except Exception as e:
            logger.error("Failed to upload %s: %s", name, e)
            raise

    return cdn_urls


# ---------------------------------------------------------------------------
# Step 4: Build HTML
# ---------------------------------------------------------------------------

def _img_row(
    row_num: int,
    src: str,
    width: int,
    alt: str,
    link: str,
    name: str,
) -> str:
    """Generate a full-width image row (single column)."""
    return f"""
<!-- ============================================================ -->
<!-- SLICE: {name}                                               -->
<!-- Alt: {alt}                                                  -->
<!-- Link: {link}                                                -->
<!-- ============================================================ -->
<table class="row row-{row_num}" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content stack" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="image_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad" style="width:100%" align="center">
<div style="max-width:{width}px">
<a href="{link}" target="_blank">
<img src="{src}" style="display:block;height:auto;border:0;width:100%" width="{width}" alt="{alt}" title="{alt}" height="auto">
</a>
</div>
</td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>
"""


def _two_col_row(
    row_num: int,
    left_src: str, left_width: int, left_alt: str, left_link: str, left_name: str,
    right_src: str, right_width: int, right_alt: str, right_link: str, right_name: str,
) -> str:
    """Generate a two-column (50/50) image row."""
    return f"""
<!-- ============================================================ -->
<!-- SLICES: {left_name} + {right_name} (50/50)                  -->
<!-- Left: {left_alt} → {left_link}                              -->
<!-- Right: {right_alt} → {right_link}                           -->
<!-- ============================================================ -->
<table class="row row-{row_num}" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="50%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="image_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad" style="width:100%" align="center">
<div style="max-width:{left_width}px">
<a href="{left_link}" target="_blank">
<img src="{left_src}" style="display:block;height:auto;border:0;width:100%" width="{left_width}" alt="{left_alt}" title="{left_alt}" height="auto">
</a>
</div>
</td></tr>
</table>
</td>
<td class="column column-2" width="50%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="image_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad" style="width:100%" align="center">
<div style="max-width:{right_width}px">
<a href="{right_link}" target="_blank">
<img src="{right_src}" style="display:block;height:auto;border:0;width:100%" width="{right_width}" alt="{right_alt}" title="{right_alt}" height="auto">
</a>
</div>
</td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>
"""


def build_html(cdn_urls: dict, dims: dict) -> str:
    """Assemble the complete email HTML from CDN URLs and measured dimensions."""

    def url(name):
        return cdn_urls[name]

    def w(name):
        return dims[name][0]

    head = """\
<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="en">
<head>
  <title></title>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <!--[if mso]>
  <xml>
    <w:WordDocument xmlns:w="urn:schemas-microsoft-com:office:word"><w:DontUseAdvancedTypographyReadingMail/></w:WordDocument>
    <o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch><o:AllowPNG/></o:OfficeDocumentSettings>
  </xml>
  <![endif]-->
  <!--[if !mso]><!-->
  <link href="https://fonts.googleapis.com/css?family=Open+Sans" rel="stylesheet" type="text/css">
  <!--<![endif]-->
  <style>
    *{box-sizing:border-box}
    body{margin:0;padding:0}
    a[x-apple-data-detectors]{color:inherit!important;text-decoration:inherit!important}
    #MessageViewBody a{color:inherit;text-decoration:none}
    p{line-height:inherit}
    .desktop_hide,.desktop_hide table{mso-hide:all;display:none;max-height:0;overflow:hidden}
    .image_block img+div{display:none}
    sub,sup{font-size:75%;line-height:0}
    @media (max-width:620px){
      .row-content{width:100%!important}
      .stack .column{width:100%;display:block}
      .mobile_hide{min-height:0;max-height:0;max-width:0;display:none;overflow:hidden;font-size:0}
      .desktop_hide,.desktop_hide table{display:table!important;max-height:none!important}
    }
  </style>
  <!--[if mso ]><style>sup, sub { font-size: 100% !important; } sup { mso-text-raise:10% } sub { mso-text-raise:-10% }</style><![endif]-->
</head>
<body class="body" style="margin:0;padding:0;-webkit-text-size-adjust:none;text-size-adjust:none;background-color:#fff">
<table class="nl-container" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff">
<tbody><tr><td>
"""

    # ---- Main content rows ------------------------------------------------
    rows = ""

    # Row 1: 1.png — sale banner (full width)
    rows += _img_row(1, url("1.png"), w("1.png"),
                     IMAGE_METADATA["1.png"]["alt"],
                     IMAGE_METADATA["1.png"]["link"],
                     "1.png — Sale banner")

    # Row 2: 2.gif — animated hero (full width)
    rows += _img_row(2, url("2.gif"), w("2.gif"),
                     IMAGE_METADATA["2.gif"]["alt"],
                     IMAGE_METADATA["2.gif"]["link"],
                     "2.gif — Animated hero")

    # Row 3: 3.png — photo grid (full width)
    rows += _img_row(3, url("3.png"), w("3.png"),
                     IMAGE_METADATA["3.png"]["alt"],
                     IMAGE_METADATA["3.png"]["link"],
                     "3.png — Photo grid")

    # Row 4: 4.png — CTA button (full width)
    rows += _img_row(4, url("4.png"), w("4.png"),
                     IMAGE_METADATA["4.png"]["alt"],
                     IMAGE_METADATA["4.png"]["link"],
                     "4.png — CTA button")

    # Row 5: link-farm-01 — sale link farm header (full width)
    rows += _img_row(5, url("link-farm-01.png"), w("link-farm-01.png"),
                     IMAGE_METADATA["link-farm-01.png"]["alt"],
                     IMAGE_METADATA["link-farm-01.png"]["link"],
                     "link-farm-01.png — Sale link farm header")

    # Row 6: link-farm-02 + link-farm-03 (Bedding | Rugs)
    rows += _two_col_row(
        6,
        url("link-farm-02.png"), w("link-farm-02.png"),
        IMAGE_METADATA["link-farm-02.png"]["alt"], IMAGE_METADATA["link-farm-02.png"]["link"],
        "link-farm-02.png",
        url("link-farm-03.png"), w("link-farm-03.png"),
        IMAGE_METADATA["link-farm-03.png"]["alt"], IMAGE_METADATA["link-farm-03.png"]["link"],
        "link-farm-03.png",
    )

    # Row 7: link-farm-04 + link-farm-05 (Pillows | Furniture)
    rows += _two_col_row(
        7,
        url("link-farm-04.png"), w("link-farm-04.png"),
        IMAGE_METADATA["link-farm-04.png"]["alt"], IMAGE_METADATA["link-farm-04.png"]["link"],
        "link-farm-04.png",
        url("link-farm-05.png"), w("link-farm-05.png"),
        IMAGE_METADATA["link-farm-05.png"]["alt"], IMAGE_METADATA["link-farm-05.png"]["link"],
        "link-farm-05.png",
    )

    # Row 8: link-farm-06 + link-farm-07 (Best Sellers | Shop All Sale)
    rows += _two_col_row(
        8,
        url("link-farm-06.png"), w("link-farm-06.png"),
        IMAGE_METADATA["link-farm-06.png"]["alt"], IMAGE_METADATA["link-farm-06.png"]["link"],
        "link-farm-06.png",
        url("link-farm-07.png"), w("link-farm-07.png"),
        IMAGE_METADATA["link-farm-07.png"]["alt"], IMAGE_METADATA["link-farm-07.png"]["link"],
        "link-farm-07.png",
    )

    # Row 9: link-farm-08 — bottom strip / "Up to 70% Off Archive Sale" (full width)
    rows += _img_row(9, url("link-farm-08.png"), w("link-farm-08.png"),
                     IMAGE_METADATA["link-farm-08.png"]["alt"],
                     IMAGE_METADATA["link-farm-08.png"]["link"],
                     "link-farm-08.png — Up to 70% Off Archive Sale")

    # ---- Footer content blocks --------------------------------------------
    footer = """
<!-- ============================================================ -->
<!-- FOOTER                                                       -->
<!-- ============================================================ -->
<table class="row row-10" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad"><div style="font-family:Open Sans,Arial,Sans-serif;text-align:center" align="center">{{content_blocks.${CZ_Main_Footer_Without_Categories} | id: 'cb17'}}</div></td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>

<table class="row row-11" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad"><div style="font-family:Open Sans,Arial,Sans-serif;text-align:center" align="center">{{content_blocks.${Havenly_Footer_1} | id: 'cb2'}}</div></td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>

<table class="row row-12" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad"><div style="font-family:Open Sans,Arial,Sans-serif;text-align:center" align="center">{{content_blocks.${Havenly_Footer_2} | id: 'cb3'}}</div></td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>

<table class="row row-13" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad"><div style="font-family:Open Sans,Arial,Sans-serif;text-align:center" align="center">{{content_blocks.${Havenly_Footer_3} | id: 'cb11'}}</div></td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>

<table class="row row-14" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad"><div style="font-family:Open Sans,Arial,Sans-serif;text-align:center" align="center">{{content_blocks.${unsub_block} | id: 'cb5'}}</div></td></tr>
</table>
<table class="paragraph_block block-2" width="100%" border="0" cellpadding="10" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;word-break:break-word">
<tr><td class="pad"><div style="color:#959596;direction:ltr;font-family:Open Sans,Arial,Sans-serif;font-size:11px;font-weight:400;letter-spacing:0;line-height:1.1;text-align:center">
<p style="margin:0"><em>For a limited time, receive up to 70% off select styles. Sale ends May 30, 2026 at midnight EST. These products are not eligible for additional discounts. Not valid on previous purchases or gift cards. Please refer to individual product details for returns and exchange information. Select styles are final sale.</em></p>
</div></td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>
"""

    tail = """

</td></tr></tbody>
</table>
<!-- End -->
</body>
</html>
"""

    return head + rows + footer + tail


# ---------------------------------------------------------------------------
# Step 5: Create Braze campaign via REST
# ---------------------------------------------------------------------------

def create_braze_campaign(html_body: str, dry_run: bool = False) -> Optional[str]:
    """POST campaigns/create and return the campaign_id (Braze internal ID)."""
    if dry_run:
        logger.info("[DRY RUN] Would create Braze campaign: %s", CAMPAIGN_NAME)
        return "dry-run-campaign-id"

    api_key  = os.environ.get("BRAZE_API_KEY_CZ")
    base_url = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

    if not api_key:
        raise RuntimeError("BRAZE_API_KEY_CZ not set in .env")

    payload = {
        "name": CAMPAIGN_NAME,
        "description": f"Auto-built from Asana task {ASANA_TASK_GID}",
        "messages": {
            "email": {
                "subject": SUBJECT,
                "preheader": PREHEADER,
                "from": f"{FROM_NAME} <{FROM_EMAIL}>",
                "body": html_body,
            }
        },
    }

    logger.info("Creating Braze campaign: %s", CAMPAIGN_NAME)
    resp = requests.post(
        f"{base_url}/campaigns/create",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"campaigns/create failed ({resp.status_code}): {resp.text[:400]}")

    data = resp.json()
    campaign_id = data.get("campaign_id") or data.get("id")
    if not campaign_id:
        raise RuntimeError(f"No campaign_id in response: {data}")

    logger.info("Campaign created — ID: %s", campaign_id)
    return campaign_id


def campaign_dashboard_url(campaign_id: str) -> str:
    dashboard_base = os.environ.get("BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com").rstrip("/")
    return f"{dashboard_base}/campaigns/{campaign_id}"


# ---------------------------------------------------------------------------
# Step 6: Asana writeback
# ---------------------------------------------------------------------------

def _asana_request(method: str, endpoint: str, json_data=None):
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("ASANA_ACCESS_TOKEN not set in .env")
    url  = f"{ASANA_BASE_URL}/{endpoint}"
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.request(method, url, headers=hdrs, json=json_data, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error("Asana %s %s → %d: %s", method, endpoint, resp.status_code, resp.text[:200])
        return None
    return resp.json()


def update_asana(braze_url: str, dry_run: bool = False):
    """Write Braze link, set status → Ready for QA, post comment."""
    if dry_run:
        logger.info("[DRY RUN] Would update Asana task %s with %s", ASANA_TASK_GID, braze_url)
        return

    # 1. Write Braze link
    link_ok = _asana_request("PUT", f"tasks/{ASANA_TASK_GID}", json_data={
        "data": {"custom_fields": {FIELD_BRAZE_LINK: braze_url}}
    })
    if link_ok:
        logger.info("Asana: Braze link written")
    else:
        logger.warning("Asana: failed to write Braze link")

    # 2. Set status → Ready for QA
    status_ok = _asana_request("PUT", f"tasks/{ASANA_TASK_GID}", json_data={
        "data": {"custom_fields": {FIELD_TASK_STATUS: STATUS_READY_FOR_QA}}
    })
    if status_ok:
        logger.info("Asana: status set to Ready for QA")
    else:
        logger.warning("Asana: failed to set status")

    # 3. Post comment tagging assignee
    import html as _html
    body_text = (
        "this designed email campaign has been automatically built in Braze. "
        "The HTML email has been coded and uploaded — please QA the subject line, "
        "preheader, audience, send schedule, image links, and alt text before sending "
        "to the QA group.\n\n"
        f"Campaign link: {braze_url}"
    )
    escaped   = _html.escape(body_text, quote=False)
    url_text  = _html.escape(braze_url, quote=False)
    url_attr  = _html.escape(braze_url, quote=True)
    escaped   = escaped.replace(url_text, f'<a href="{url_attr}">{url_text}</a>')
    html_body = f'<a data-asana-gid="{ASSIGNEE_GID}"/>, {escaped}'
    comment_ok = _asana_request("POST", f"tasks/{ASANA_TASK_GID}/stories", json_data={
        "data": {"html_text": f"<body>{html_body}</body>", "is_pinned": False}
    })
    if comment_ok:
        logger.info("Asana: comment posted")
    else:
        logger.warning("Asana: failed to post comment")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build CZ Archive Sale email (2026-05-30)")
    parser.add_argument("--dry-run", action="store_true", help="Skip Braze + Asana writes")
    args = parser.parse_args()
    dry_run = args.dry_run

    if dry_run:
        logger.info("=== DRY RUN MODE — no Braze or Asana changes ===")

    # 1. Download images
    logger.info("--- Step 1: Downloading images from Google Drive ---")
    local_paths = download_all_images(dry_run=dry_run)

    # 2. Detect dimensions
    logger.info("--- Step 2: Detecting image dimensions ---")
    if dry_run:
        dims = {name: (600, 400) for name in DRIVE_FILES}
        # Simulate half-width dims for link farm pairs
        for name in ["link-farm-02.png", "link-farm-03.png", "link-farm-04.png",
                     "link-farm-05.png", "link-farm-06.png", "link-farm-07.png"]:
            dims[name] = (300, 200)
    else:
        dims = get_image_dimensions(local_paths)

    logger.info("Image dimensions:")
    for name, (w, h) in dims.items():
        logger.info("  %-22s %d x %d", name, w, h)

    # 3. Upload to Braze media library
    logger.info("--- Step 3: Uploading to Braze media library ---")
    cdn_urls = upload_images_to_braze(local_paths, dry_run=dry_run)
    logger.info("CDN URLs:")
    for name, url in cdn_urls.items():
        logger.info("  %-22s %s", name, url)

    # 4. Build HTML
    logger.info("--- Step 4: Building HTML ---")
    html_body = build_html(cdn_urls, dims)
    HTML_OUTPUT.write_text(html_body, encoding="utf-8")
    logger.info("HTML saved to %s (%d bytes)", HTML_OUTPUT, len(html_body))

    # 5. Create Braze campaign
    logger.info("--- Step 5: Creating Braze campaign ---")
    campaign_id = create_braze_campaign(html_body, dry_run=dry_run)
    braze_url   = campaign_dashboard_url(campaign_id)
    logger.info("Braze campaign URL: %s", braze_url)

    # 6. Update Asana
    logger.info("--- Step 6: Updating Asana task ---")
    update_asana(braze_url, dry_run=dry_run)

    # Clean up temp files
    if not dry_run:
        for path in local_paths.values():
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
        logger.info("Temp files cleaned up")

    logger.info("=== Done! ===")
    logger.info("Campaign: %s", CAMPAIGN_NAME)
    logger.info("Braze URL: %s", braze_url)


if __name__ == "__main__":
    main()
