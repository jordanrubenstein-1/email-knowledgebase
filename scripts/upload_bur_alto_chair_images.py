#!/usr/bin/env python3
"""
Download Alto dining chair images from Shopify CDN, resize to 540px wide (2x @270px
display size), convert webp → JPEG for Outlook compatibility, upload to Braze CDN,
and update the dining chair recommendation email template with the new URLs.

Template ID: 012c1de2-29be-4751-91be-28ff4324c94b
"""

import io
import os
import sys
import tempfile
from pathlib import Path

import requests
from PIL import Image
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from import_braze import init_config, get_base_url, get_api_key

load_dotenv(Path(__file__).parent.parent / ".env")

TEMPLATE_ID = "012c1de2-29be-4751-91be-28ff4324c94b"
BRAZE_BASE_URL = os.getenv("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
MEDIA_API_KEY = os.getenv("BRAZE_API_KEY_MEDIA_BUR")

SHOPIFY_BASE = "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/"

# (SKU, Shopify filename, version param) for every Alto image used in the template
ALTO_IMAGES = [
    ("DRST-DC-ALT-S2-MGOK", "DRST-DC-ALT-S2-MGOK.webp", "v=1747772306"),
    ("DRST-DC-ALT-S2-PYOK", "DRST-DC-ALT-S2-PYOK.webp", "v=1747772371"),
    ("DRST-DC-ALT-S2-MGWN", "DRST-DC-ALT-S2-MGWN.webp", "v=1747772332"),
    ("DRST-DC-ALT-S2-PYWN", "DRST-DC-ALT-S2-PYWN.webp", "v=1747772360"),
    ("DRST-DC-ALT-S2-SGWN", "DRST-DC-ALT-S2-SGWN.webp", "v=1747772278"),
]

TARGET_WIDTH = 540   # 2× the 270px display width
JPEG_QUALITY = 85    # good balance of quality and file size


def download_image(sku: str, filename: str, version: str) -> bytes:
    url = f"{SHOPIFY_BASE}{filename}?{version}"
    print(f"  Downloading {sku} ...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


def resize_and_convert(raw_bytes: bytes, sku: str) -> bytes:
    """Convert webp → JPEG and resize to TARGET_WIDTH, preserving aspect ratio."""
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    orig_w, orig_h = img.size
    new_h = round(orig_h * TARGET_WIDTH / orig_w)
    img = img.resize((TARGET_WIDTH, new_h), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    size_kb = out.tell() / 1024
    print(f"    {orig_w}×{orig_h} webp → {TARGET_WIDTH}×{new_h} JPEG ({size_kb:.0f} KB)")
    return out.getvalue()


def upload_to_braze(jpeg_bytes: bytes, sku: str) -> str | None:
    """Upload JPEG to Braze media library. Returns CDN URL or None."""
    if not MEDIA_API_KEY:
        raise RuntimeError("BRAZE_API_KEY_MEDIA_BUR not set in .env")

    filename = f"{sku}.jpg"
    resp = requests.post(
        f"{BRAZE_BASE_URL}/media_library/create",
        headers={"Authorization": f"Bearer {MEDIA_API_KEY}"},
        files={"asset_file": (filename, jpeg_bytes, "image/jpeg")},
        data={"name": filename},
        timeout=60,
    )
    if not resp.ok:
        print(f"    [error] upload failed ({resp.status_code}): {resp.text[:300]}")
        return None
    assets = resp.json().get("new_assets", [])
    url = assets[0]["url"] if assets else None
    print(f"    → {url}")
    return url


def fetch_template():
    r = requests.get(
        f"{get_base_url()}/templates/email/info",
        params={"email_template_id": TEMPLATE_ID},
        headers={"Authorization": f"Bearer {get_api_key()}"},
    )
    r.raise_for_status()
    return r.json()


def update_template(new_html: str, new_pt: str, subject: str) -> bool:
    resp = requests.post(
        f"{get_base_url()}/templates/email/update",
        headers={"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"},
        json={
            "email_template_id": TEMPLATE_ID,
            "subject": subject,
            "body": new_html,
            "plaintext_body": new_pt,
        },
        timeout=60,
    )
    if not resp.ok:
        print(f"  [error] template update failed ({resp.status_code}): {resp.text[:300]}")
        return False
    return True


def main(dry_run: bool = False):
    init_config("BUR")

    # Step 1: Download, resize, upload each Alto image
    cdn_map: dict[str, str] = {}   # SKU → Braze CDN URL

    for sku, filename, version in ALTO_IMAGES:
        print(f"\n{sku}")
        raw = download_image(sku, filename, version)
        jpeg = resize_and_convert(raw, sku)

        if dry_run:
            print(f"    [dry-run] would upload {sku}.jpg ({len(jpeg)//1024} KB)")
            cdn_map[sku] = f"https://braze-images.com/DRY_RUN/{sku}.jpg"
        else:
            url = upload_to_braze(jpeg, sku)
            if not url:
                print(f"    [skip] upload failed for {sku}")
                continue
            cdn_map[sku] = url

    if not cdn_map:
        print("\nNo images uploaded — nothing to patch.")
        return

    print(f"\n\nFetching template to patch...")
    tpl = fetch_template()
    html = tpl.get("body", "")
    pt = tpl.get("plaintext_body", "")
    subject = tpl.get("subject", "")

    # Step 2: Replace Shopify CDN URLs with Braze CDN URLs in the template
    old_base = "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/"
    patched = 0
    for sku, braze_url in cdn_map.items():
        # Match any version of the Alto webp URL (with or without ?v=...)
        for suffix in [".webp", ".webp?"]:
            old_url = old_base + sku + suffix
            if old_url in html or old_url in pt:
                # Replace the full URL including any trailing query string
                import re
                pattern = re.escape(old_base + sku + ".webp") + r"(?:\?[^'\">\s]*)?"
                new_html_candidate = re.sub(pattern, braze_url, html)
                new_pt_candidate = re.sub(pattern, braze_url, pt)
                if new_html_candidate != html or new_pt_candidate != pt:
                    html = new_html_candidate
                    pt = new_pt_candidate
                    patched += 1
                    print(f"  Patched {sku}: → {braze_url}")
                break

    if patched == 0:
        # Try direct replacement with the full original URL
        for sku, braze_url in cdn_map.items():
            for sku_data in ALTO_IMAGES:
                if sku_data[0] == sku:
                    old = f"{old_base}{sku_data[1]}?{sku_data[2]}"
                    if old in html:
                        html = html.replace(old, braze_url)
                        pt = pt.replace(old, braze_url)
                        patched += 1
                        print(f"  Patched {sku}: → {braze_url}")

    print(f"\n{patched} image URL(s) replaced in template.")

    if dry_run:
        print("[dry-run] would update template — skipping POST")
        return

    print("Updating template in Braze...")
    ok = update_template(html, pt, subject)
    if ok:
        print("✓ Template updated with Braze CDN image URLs.")
    else:
        print("✗ Template update failed.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
