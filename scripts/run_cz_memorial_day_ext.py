#!/usr/bin/env python3
"""Build CZ Memorial Day Sale Extension Last Day email."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "braze_automation"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import build_cz_designed_email as _mod

# Slice links in order (root images first, then category blocks)
_LINKS = [
    "https://www.the-citizenry.com/",                              # 1 Memorial Day Sale
    "https://www.the-citizenry.com/collections/shop-all-rugs-1",  # 2 Shop Rugs
    "https://www.the-citizenry.com/collections/shop-all-bedding-2", # 3 Shop Bedding
    "https://www.the-citizenry.com/collections/shop-all-pillows",  # 4 Shop Pillows
    "https://www.the-citizenry.com/collections/shop-all-furniture", # 5 Shop Furniture
    "https://www.the-citizenry.com/collections/all-accents",       # 6 Shop Accents
    "https://www.the-citizenry.com/collections/archive-sale",      # 7 Shop The Archive Sale
    "https://www.the-citizenry.com/",                              # 8 Shop Now (sale link farm)
]

# Patch link parsing to use the provided URLs instead of reading from task notes
_mod._parse_slice_links = lambda html_notes: _LINKS

result = asyncio.run(_mod.build_cz_designed_email(
    task_gid="1214106541678772",
    drive_url="https://drive.google.com/drive/folders/1T8-_0eLQatLaNPbQ2nHwbYZrZ5nL_y_D?usp=drive_link",
    dry_run=False,
    headless=True,
))

if result.get("success"):
    print(f"\n✅ Build complete: {result['braze_url']}")
else:
    print(f"\n❌ Build failed:")
    for err in result.get("errors", []):
        print(f"  - {err}")
