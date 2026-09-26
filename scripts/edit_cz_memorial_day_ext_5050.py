#!/usr/bin/env python3
"""Edit the Memorial Day Sale Extension Last Day campaign: slices 2–7 → 50/50 modules."""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import build_cz_designed_email as _mod
from braze_automation.build_pt_campaign import (
    fetch_task_by_gid,
    _get_text_value,
    FIELD_SUBJECT_LINE,
    FIELD_PRE_HEADER,
    load_brand_config,
)

CAMPAIGN_URL = "https://dashboard-07.braze.com/engagement/campaigns/6a10b0bd3fdc6d00862f87f3/666672a4d8965b005ac6c1bd"
DRIVE_URL = "https://drive.google.com/drive/folders/1T8-_0eLQatLaNPbQ2nHwbYZrZ5nL_y_D?usp=drive_link"
TASK_GID = "1214106541678772"

# Layout: slice 1 full-width, slices 2–7 as 50/50 pairs, slice 8 full-width
_LINKS = [
    "https://www.the-citizenry.com/",                                # 1 full
    "https://www.the-citizenry.com/collections/shop-all-rugs-1",    # 2 left
    "https://www.the-citizenry.com/collections/shop-all-bedding-2", # 3 right
    "https://www.the-citizenry.com/collections/shop-all-pillows",   # 4 left
    "https://www.the-citizenry.com/collections/shop-all-furniture",  # 5 right
    "https://www.the-citizenry.com/collections/all-accents",         # 6 left
    "https://www.the-citizenry.com/collections/archive-sale",        # 7 right
    "https://www.the-citizenry.com/",                                # 8 full
]

_ALTS = [
    "Memorial Day Sale",
    "Shop Rugs",
    "Shop Bedding",
    "Shop Pillows",
    "Shop Furniture",
    "Shop Accents",
    "Shop The Archive Sale",
    "Shop Now",
]


async def main():
    task = fetch_task_by_gid(TASK_GID)
    subject = _get_text_value(task, FIELD_SUBJECT_LINE) or ""
    preheader = _get_text_value(task, FIELD_PRE_HEADER) or ""

    with tempfile.TemporaryDirectory(prefix="cz_email_edit_") as tmpdir:
        tmp_path = Path(tmpdir)

        print("Downloading images from Drive...")
        local_images = _mod.download_images_from_drive(DRIVE_URL, tmp_path)

        print("Uploading images to Braze media library...")
        cdn_urls = _mod.upload_images(local_images)

        # Sort root images numerically: 1.gif, 2.png … 8.png
        import re
        ordered = sorted(
            [n for n in cdn_urls],
            key=lambda f: int(re.match(r"^(\d+)", f).group(1)) if re.match(r"^(\d+)", f) else 999,
        )
        if len(ordered) < 8:
            print(f"❌ Expected 8 images, got {len(ordered)}: {ordered}")
            return

        # Build configs:
        # - root_image_config: only slice 1 (full-width)
        # - category_config: slices 2–7 as left/right pairs, slice 8 as full
        root_image_config = [
            (ordered[0], _LINKS[0], _ALTS[0]),
        ]
        category_config = [
            (ordered[1], _LINKS[1], _ALTS[1], "left"),
            (ordered[2], _LINKS[2], _ALTS[2], "right"),
            (ordered[3], _LINKS[3], _ALTS[3], "left"),
            (ordered[4], _LINKS[4], _ALTS[4], "right"),
            (ordered[5], _LINKS[5], _ALTS[5], "left"),
            (ordered[6], _LINKS[6], _ALTS[6], "right"),
            (ordered[7], _LINKS[7], _ALTS[7], "full"),
        ]

        html = _mod.build_email_html(cdn_urls, root_image_config, category_config)
        print(f"HTML assembled: {len(html):,} chars")

        brand_config = load_brand_config()
        print("Editing campaign in Braze...")
        success = await _mod.edit_existing_campaign(
            html=html,
            subject=subject,
            preheader=preheader,
            campaign_url=CAMPAIGN_URL,
            brand_config=brand_config,
            headless=True,
        )

        if success:
            print(f"\n✅ Campaign updated — slices 2–7 are now 50/50 modules")
        else:
            print(f"\n❌ Campaign edit failed")


asyncio.run(main())
