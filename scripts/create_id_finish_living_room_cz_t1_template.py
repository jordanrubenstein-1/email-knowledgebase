#!/usr/bin/env python3
"""
Build TRG_EM_2026_06_ID_D_Finish_Your_Living_Room_CZ_T1_V1 email template.

Downloads Slice 1–9 from Google Drive, uploads to Braze CDN (ID brand),
assembles HTML using the ID designed email structure, and creates the template
via Braze Templates API.

Usage:
    uv run python scripts/create_id_finish_living_room_cz_t1_template.py
    uv run python scripts/create_id_finish_living_room_cz_t1_template.py --dry-run
"""

import argparse
import logging
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from braze_campaign_api import braze_post_request, init_config, normalize_brand
from braze_automation.build_designed_campaign import upload_to_media_library_rest
from utils.drive_client import (
    list_folder_images,
    _get_drive_service,
    _download_authenticated,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BRAND = "ID"
TEMPLATE_NAME = "TRG_EM_2026_06_ID_D_Finish_Your_Living_Room_CZ_T1_V1"
SUBJECT = "Finishing touches for your new living room"
PREHEADER = "Pillows from St. Frank and The Inside, rugs and throws from The Citizenry — curated to complete your space."
DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/1WFzT7d9dKTiun6eOZ9uLsyIY2899VKfK"

SLICES = [
    {"name": "Slice 1.png", "link": "https://www.interiordefine.com/", "alt": "Shop Interior Define"},
    {"name": "Slice 2.png", "link": "https://www.the-citizenry.com/", "alt": "Shop The Citizenry"},
    {"name": "Slice 3.png", "link": "https://www.the-citizenry.com/", "alt": "Shop The Citizenry"},
    {"name": "Slice 4.png", "link": "https://www.the-citizenry.com/collections/shop-all-rugs-1?Type=Hand-Knotted", "alt": "Hand-Knotted Rugs"},
    {"name": "Slice 5.png", "link": "https://www.the-citizenry.com/collections/all-throws", "alt": "Organic Throw Blankets"},
    {"name": "Slice 6.png", "link": "https://www.the-citizenry.com/collections/shop-all-pillows?Type=Hand-Knotted", "alt": "Hand-Knotted Pillows"},
    {"name": "Slice 7.png", "link": "https://www.theinside.com/c/home-decor/throw-pillows", "alt": "The Inside Pillows"},
    {"name": "Slice 8.png", "link": "https://www.stfrank.com/collections/pillows", "alt": "St. Frank Pillows"},
    {"name": "Slice 9.png", "link": "https://havenly.com/ai-interior-design", "alt": "AI Interior Design"},
]

_FOOTER = """\
{{content_blocks.${b2c_footer} | id: 'cb4'}}
{{content_blocks.${All_Brands_Footer} | id: 'cb5'}}
{{content_blocks.${All_Brands_Footer2} | id: 'cb6'}}
{{content_blocks.${All_Brands_Footer3} | id: 'cb7'}}
{{content_blocks.${unsubscribe} | id: 'cb8'}}"""


def download_slices(dest_dir: Path) -> dict:
    """Download Slice 1–9 from Google Drive. Returns {filename: local_path}."""
    drive_files = list_folder_images(DRIVE_FOLDER_URL)
    logger.info(f"Found {len(drive_files)} images in Drive folder")

    service = _get_drive_service()
    if service is None:
        raise RuntimeError("Google Drive credentials not configured in .env")

    wanted = {s["name"] for s in SLICES}
    result = {}
    for f in drive_files:
        if f["name"] not in wanted:
            logger.info(f"Skipping: {f['name']}")
            continue
        dest_path = str(dest_dir / f["name"])
        _download_authenticated(service, f["id"], dest_path)
        result[f["name"]] = Path(dest_path)
        logger.info(f"Downloaded: {f['name']}")

    missing = wanted - set(result.keys())
    if missing:
        raise RuntimeError(f"Missing slices in Drive folder: {sorted(missing)}")

    return result


def upload_slices(local_files: dict) -> dict:
    """Upload each slice to Braze CDN. Returns {filename: cdn_url}."""
    cdn_urls = {}
    for fname, path in local_files.items():
        cdn_url = upload_to_media_library_rest(str(path), BRAND)
        if not cdn_url:
            raise RuntimeError(
                f"CDN upload failed for {fname}. "
                f"Check that BRAZE_API_KEY_MEDIA_{BRAND} is set in .env."
            )
        cdn_urls[fname] = cdn_url
        logger.info(f"Uploaded {fname} → {cdn_url}")
    return cdn_urls


def _image_row(row_num: int, slice_name: str, cdn_url: str, link: str, alt: str) -> str:
    safe_alt = alt.replace('"', '&quot;')
    return f"""\
<!-- ============================================================ -->
<!-- SLICE: {slice_name} — {alt}                -->
<!-- Alt:  {safe_alt}                    -->
<!-- Link: {link} -->
<!-- ============================================================ -->
<table class="row row-{row_num}" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content stack" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">
<table class="image_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad" style="width:100%" align="center">
<div style="max-width:600px">
<a href="{link}" target="_blank">
<img src="{cdn_url}" style="display:block;height:auto;border:0;width:100%" width="600" alt="{safe_alt}" title="{safe_alt}" height="auto">
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


def _footer_row(row_num: int) -> str:
    return f"""\
<!-- ============================================================ -->
<!-- FOOTER: ID content blocks (b2c_footer + All_Brands + unsubscribe) -->
<!-- ============================================================ -->
<table class="row row-{row_num}" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tbody><tr><td>
<table class="row-content stack" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff;border-radius:0;color:#000;width:600px;margin:0 auto" width="600">
<tbody><tr>
<td class="column column-1" width="100%" style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;padding-bottom:5px;padding-top:5px;vertical-align:top">
<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0">
<tr><td class="pad"><div style="font-family:'Open Sans',Arial,Sans-serif;text-align:center" align="center">
{_FOOTER}
</div></td></tr>
</table>
</td>
</tr></tbody>
</table>
</td></tr></tbody>
</table>
"""


def build_html(cdn_urls: dict) -> str:
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
</head>
<body class="body" style="margin:0;padding:0;-webkit-text-size-adjust:none;text-size-adjust:none;background-color:#fff">
<table class="nl-container" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff">
<tbody><tr><td>

"""

    rows = []
    for i, slice_cfg in enumerate(SLICES, start=1):
        cdn_url = cdn_urls[slice_cfg["name"]]
        rows.append(_image_row(i, slice_cfg["name"], cdn_url, slice_cfg["link"], slice_cfg["alt"]))

    footer = _footer_row(len(SLICES) + 1)
    tail = "\n</td></tr></tbody></table><!-- End -->\n</body>\n</html>"

    return head + "\n".join(rows) + footer + tail


def create_template(html: str, dry_run: bool = False) -> str:
    brand = normalize_brand(BRAND)
    init_config(brand)

    template_data = {
        "template_name": TEMPLATE_NAME,
        "subject": SUBJECT,
        "preheader": PREHEADER,
        "body": html,
    }

    if dry_run:
        logger.info("[DRY RUN] Would POST to templates/email/create:")
        logger.info(f"  template_name: {TEMPLATE_NAME}")
        logger.info(f"  subject:       {SUBJECT}")
        logger.info(f"  preheader:     {PREHEADER}")
        logger.info(f"  body length:   {len(html)} chars")
        return "dry-run-id"

    response_data, error = braze_post_request("templates/email/create", template_data, brand)
    if error:
        raise RuntimeError(f"Braze API error: {error}")

    template_id = response_data.get("email_template_id") or response_data.get("id")
    if not template_id:
        raise RuntimeError(f"Unexpected response: {response_data}")

    return template_id


def main():
    parser = argparse.ArgumentParser(
        description="Create ID Finish Your Living Room CZ T1 email template"
    )
    parser.add_argument("--dry-run", action="store_true", help="Build HTML, skip API calls")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)

        logger.info("Step 1: Downloading slices from Google Drive...")
        local_files = download_slices(dest)

        if args.dry_run:
            logger.info("[DRY RUN] Skipping CDN upload — using placeholder URLs")
            cdn_urls = {s["name"]: f"https://example.com/{s['name'].replace(' ', '_')}" for s in SLICES}
        else:
            logger.info("Step 2: Uploading slices to Braze CDN...")
            cdn_urls = upload_slices(local_files)

        logger.info("Step 3: Building HTML...")
        html = build_html(cdn_urls)
        logger.info(f"HTML built: {len(html):,} chars, {len(SLICES)} slices + footer")

        logger.info("Step 4: Creating template in Braze...")
        template_id = create_template(html, dry_run=args.dry_run)

    print(f"\n✓ Template created: {template_id}")
    print(f"  Name:      {TEMPLATE_NAME}")
    print(f"  Subject:   {SUBJECT}")
    print(f"  Preheader: {PREHEADER}")
    print(f"\nFind it in Braze → Templates & Media → Email Templates")


if __name__ == "__main__":
    main()
