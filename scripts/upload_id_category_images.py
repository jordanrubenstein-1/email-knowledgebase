#!/usr/bin/env python3
"""
Upload ID category browse-abandon images to Braze Media Library and patch
the URL placeholders in id_top_categories_template.html.

Usage:
  # Upload all 26 images and patch the template
  uv run python scripts/upload_id_category_images.py

  # Verify all placeholders have been filled in
  uv run python scripts/upload_id_category_images.py --verify

  # Print the manual upload checklist
  uv run python scripts/upload_id_category_images.py --guide
"""

import json
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import os

IMAGE_DIR = Path.home() / "Downloads" / "drive-download-20260516T050546Z-3-001"
OUTPUT_JSON = Path(__file__).parent / "id_category_image_urls.json"
TEMPLATE_FILE = Path(__file__).parent / "id_top_categories_template.html"

API_KEY = os.environ["BRAZE_API_KEY_MEDIA_ID"]
BASE_URL = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

# Map from category_name attribute value -> image filename
CATEGORY_MAP = {
    "accent chairs": "Accent Chairs.png",
    "artwork": "Artwork.png",
    "bedroom": "Bedroom.png",
    "beds": "Beds.png",
    "benches": "Benches.png",
    "best sellers": "Best Sellers.png",
    "bumper sectionals": "Bumper Sectionals.png",
    "chairs": "Chairs.png",
    "chaise sectionals": "Chaise Sectionals.png",
    "coffee tables": "Coffee Tables.png",
    "corner sectionals": "Corner Sectionals.png",
    "dining": "Dining.png",
    "dining benches": "Dining Benches.png",
    "dining chairs": "Dining Chairs + Stools.png",
    "dining tables": "Dining Tables.png",
    "in stock": "In Stock.png",
    "loveseats": "Loveseats.png",
    "made to order pillows": "MTO Pillows.png",
    "modular": "Modular Seating.png",
    "ottomans": "Ottomans.png",
    "rugs": "Rugs.png",
    "sectionals": "Sectionals.png",
    "sleeper sofas": "Sleeper Sofa.png",
    "sofas": "Sofas.png",
    "swivel chairs": "Swivel Chairs.png",
    "tables": "Tables.png",
}


TEMPLATE_FILE = Path(__file__).parent / "id_top_categories_template.html"

# Placeholder token format used in the template
PLACEHOLDER_PREFIX = "BRAZE_URL_"

# Maps category_name → placeholder token suffix (used for verification)
PLACEHOLDER_MAP = {
    "accent chairs": "ACCENT_CHAIRS",
    "artwork": "ARTWORK",
    "bedroom": "BEDROOM",
    "beds": "BEDS",
    "benches": "BENCHES",
    "best sellers": "BEST_SELLERS",
    "bumper sectionals": "BUMPER_SECTIONALS",
    "chairs": "CHAIRS",
    "chaise sectionals": "CHAISE_SECTIONALS",
    "coffee tables": "COFFEE_TABLES",
    "corner sectionals": "CORNER_SECTIONALS",
    "dining": "DINING",
    "dining benches": "DINING_BENCHES",
    "dining chairs": "DINING_CHAIRS",
    "dining tables": "DINING_TABLES",
    "in stock": "IN_STOCK",
    "loveseats": "LOVESEATS",
    "made to order pillows": "MADE_TO_ORDER_PILLOWS",
    "modular": "MODULAR",
    "ottomans": "OTTOMANS",
    "rugs": "RUGS",
    "sectionals": "SECTIONALS",
    "sleeper sofas": "SLEEPER_SOFAS",
    "sofas": "SOFAS",
    "swivel chairs": "SWIVEL_CHAIRS",
    "tables": "TABLES",
}


def upload_image(filename: str) -> str:
    """Upload a PNG to the Braze media library and return its CDN URL."""
    filepath = IMAGE_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Image not found: {filepath}")
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/media_library/create",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"asset_file": (filename, f, "image/png")},
            data={"name": filename},
            timeout=60,
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:300]}")
    assets = resp.json().get("new_assets", [])
    if not assets:
        raise RuntimeError(f"No assets in response: {resp.json()}")
    return assets[0]["url"]


def patch_template(url_map: dict) -> None:
    """Replace BRAZE_URL_* placeholders in the template with real CDN URLs.

    Sorts by token length descending so longer tokens (e.g. BRAZE_URL_DINING_BENCHES)
    are replaced before shorter prefixes (e.g. BRAZE_URL_DINING).
    """
    content = TEMPLATE_FILE.read_text()
    replacements = [
        (f"{PLACEHOLDER_PREFIX}{PLACEHOLDER_MAP[cat]}", url)
        for cat, url in url_map.items()
        if cat in PLACEHOLDER_MAP
    ]
    # Longest token first to avoid prefix-clobbering (e.g. DINING before DINING_BENCHES)
    for token, url in sorted(replacements, key=lambda x: len(x[0]), reverse=True):
        content = content.replace(token, url)
    TEMPLATE_FILE.write_text(content)


def verify_template():
    """Check which BRAZE_URL_* placeholders are still unfilled in the template."""
    if not TEMPLATE_FILE.exists():
        print(f"Template not found: {TEMPLATE_FILE}")
        sys.exit(1)

    content = TEMPLATE_FILE.read_text()
    unfilled = []
    filled = []

    for category_name, suffix in sorted(PLACEHOLDER_MAP.items()):
        token = f"{PLACEHOLDER_PREFIX}{suffix}"
        if token in content:
            unfilled.append((category_name, token, CATEGORY_MAP[category_name]))
        else:
            filled.append(category_name)

    if filled:
        print(f"✓ {len(filled)} URLs filled in")

    if unfilled:
        print(f"\n✗ {len(unfilled)} placeholders still need real URLs:")
        print(f"{'Category':<30} {'Placeholder':<35} {'Image file'}")
        print("-" * 85)
        for cat, token, filename in unfilled:
            print(f"  {cat:<28} {token:<33} {filename}")
        print(f"\nUpload these images in Braze Dashboard > Templates > Media Library")
        print(f"Image folder: {IMAGE_DIR}")
        sys.exit(1)
    else:
        print("✓ All 26 image URL placeholders have been filled. Template is ready.")


def print_upload_guide():
    """Print the manual upload checklist."""
    print("Manual upload checklist — Braze Dashboard > Templates > Media Library")
    print(f"Image folder: {IMAGE_DIR}\n")
    print(f"{'Image file':<35} {'category_name':<30} {'Placeholder to replace'}")
    print("-" * 90)
    for category_name, filename in sorted(CATEGORY_MAP.items(), key=lambda x: x[1]):
        suffix = PLACEHOLDER_MAP[category_name]
        token = f"{PLACEHOLDER_PREFIX}{suffix}"
        print(f"  {filename:<33} {category_name:<28} {token}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ID category image upload helper")
    parser.add_argument("--verify", action="store_true",
                        help="Check template for unfilled URL placeholders")
    parser.add_argument("--guide", action="store_true",
                        help="Print manual upload checklist without uploading")
    args = parser.parse_args()

    if args.verify:
        verify_template()
        return
    if args.guide:
        print_upload_guide()
        return

    # Load any already-uploaded URLs so we can skip re-uploads
    existing = {}
    if OUTPUT_JSON.exists():
        existing = json.loads(OUTPUT_JSON.read_text())

    results = dict(existing)
    errors = []

    for category_name, filename in sorted(CATEGORY_MAP.items()):
        if category_name in existing:
            print(f"SKIP (already uploaded) '{filename}' → {existing[category_name]}")
            continue
        print(f"Uploading '{filename}' ...", end=" ", flush=True)
        try:
            url = upload_image(filename)
            results[category_name] = url
            print(f"OK  {url}")
        except Exception as e:
            print(f"FAILED: {e}")
            errors.append((category_name, str(e)))
        time.sleep(0.3)

    OUTPUT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nSaved {len(results)} URLs to {OUTPUT_JSON}")

    if results:
        patch_template(results)
        print(f"Patched placeholders in {TEMPLATE_FILE.name}")

    if errors:
        print(f"\n{len(errors)} error(s):")
        for cat, msg in errors:
            print(f"  {cat}: {msg}")
        sys.exit(1)

    verify_template()


if __name__ == "__main__":
    main()
