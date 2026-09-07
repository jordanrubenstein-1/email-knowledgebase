#!/usr/bin/env python3
"""
Build script: BUR Dining Chair Rec T3 email template (Interior Define cross-brand).

Touch 3 (Day 35) of the Dining Chair Rec canvas (TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A).
Sent from the Burrow workspace to dining-table buyers who still haven't bought
chairs. Where T1/T2 recommend Burrow chairs, T3 cross-promotes Interior Define's
made-to-order dining chairs — a Havenly Brands cross-brand play.

Unlike T1, T3 is fully static: 4 designer image slices, no per-user
personalization (no rec attributes / abort Liquid / message_extras). Every slice
links to the same ID custom dining chairs collection.

  1. Downloads the 4 image slices from Google Drive (authenticated OAuth)
  2. Uploads them to the Burrow Braze media library via POST /media_library/create
  3. Builds the 600px HTML email (MSO Outlook wrapper, mobile-fluid images)
  4. Creates the Braze designed email template via POST /templates/email/create
     (only when --create is passed; otherwise just writes the HTML for QA)

Template name: TRG_EM_2026_06_BW_D_Dining_Chair_Rec_T3_V1
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── env ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))
from utils.drive_client import download_image  # noqa: E402

API_KEY_BUR       = os.environ["BRAZE_API_KEY_BUR"]
API_KEY_MEDIA_BUR = os.environ["BRAZE_API_KEY_MEDIA_BUR"]
BRAZE_BASE        = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

TEMPLATE_NAME = "TRG_EM_2026_06_BW_D_Dining_Chair_Rec_T3_V1"
SUBJECT       = "Sometimes you need more options"
PREHEADER     = "Meet Interior Define. Custom dining chairs made to order."

# Every slice links to the ID custom dining chairs collection (verified 200).
ID_URL = "https://www.interiordefine.com/dining/all-custom-dining-seating/custom-dining-chairs-and-dining-stools?page=1"

# Slice source images (Google Drive) + alt text pulled from the baked-in copy.
SLICES = [
    {
        "file": "t3_slice1.png",
        "drive": "https://drive.google.com/file/d/1gQxUTMt8baDxwoq2DNKQhLDpDT_Wyx6_/view",
        "media_name": "bur_dining_rec_t3_slice1.png",
        "alt": "Sometimes you need more options",
    },
    {
        "file": "t3_slice2.png",
        "drive": "https://drive.google.com/file/d/1acXb6tOKVl_zSywhQ6gXdWF2J-34XVGj/view",
        "media_name": "bur_dining_rec_t3_slice2.png",
        "alt": "Not every chair is a Burrow chair. And that's okay. Our sister brands have options worth exploring.",
    },
    {
        "file": "t3_slice3.png",
        "drive": "https://drive.google.com/file/d/1SOwoL4LP7u4uaScEvnM1C2zXNa2f9GXL/view",
        "media_name": "bur_dining_rec_t3_slice3.png",
        "alt": "Interior Define specializes in made-to-order dining chairs in a wide range of fabrics and finishes. They're worth a look if you want something more custom.",
    },
    {
        "file": "t3_slice4.png",
        "drive": "https://drive.google.com/file/d/1nKhctNqdL0pB1ENCH2qyNqcGgZCLq4eb/view",
        "media_name": "bur_dining_rec_t3_slice4.png",
        "alt": "Shop Interior Define for custom dining chairs built to order",
    },
]

SCRATCHPAD = Path(
    "/private/tmp/claude-501/"
    "-Users-jordan-rubenstein-Downloads-email-knowledgebase-email-knowledgebase/"
    "fdc5aa56-43ea-4feb-8e04-73236a939f4e/scratchpad"
)


def upload_media(image_path: Path, media_name: str) -> str:
    """Upload an image to the Burrow Braze media library, return the CDN URL."""
    url = f"{BRAZE_BASE}/media_library/create"
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {API_KEY_MEDIA_BUR}"},
        files={"asset_file": (media_name, image_bytes, "image/png")},
        data={"name": media_name},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    assets = body.get("new_assets", [])
    if not assets:
        raise ValueError(f"No assets in media upload response: {body}")
    cdn_url = assets[0]["url"]
    print(f"  uploaded {media_name} -> {cdn_url}")
    return cdn_url


def build_html(slice_urls: list[str]) -> str:
    """Build the 600px static designed-email HTML.

    slice_urls: [slice1_url, slice2_url, slice3_url, slice4_url] — either Braze
    CDN URLs (real build) or local file:// paths (QA preview).
    """
    rows = []
    for cfg, src in zip(SLICES, slice_urls):
        alt = cfg["alt"].replace('"', "&quot;")
        rows.append(f"""  <!-- {cfg['media_name']} -->
  <tr>
    <td style="padding:0;font-size:0;line-height:0;">
      <a href="{ID_URL}" target="_blank" style="text-decoration:none;">
        <img src="{src}" width="600" alt="{alt}"
             style="display:block;width:100%;max-width:600px;height:auto;border:0;">
      </a>
    </td>
  </tr>""")
    grid = "\n".join(rows)

    return f"""\
<!--
  BUR Dining Chair Rec — T3 (Interior Define cross-brand)
  ---------------------------------------------------------------------------
  Touch 3 (Day 35) of TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A.
  Static designed email — no personalization. All 4 slices link to the ID
  custom dining chairs collection. Sent from the Burrow workspace; footer is
  Burrow's shared footer content block (matches T1).
  ---------------------------------------------------------------------------
-->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>Sometimes you need more options</title>
<!--[if mso]>
<style type="text/css">
  table, td {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }}
  img {{ -ms-interpolation-mode:bicubic; }}
</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#ffffff;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

<!-- Preheader lives in the Braze template `preheader` field, NOT in the HTML.
     Do not add a hidden preheader div here -- it would double up with the field.
     Whoever wires the canvas step must check "add whitespace after preheader"
     in the composer so the body copy doesn't bleed into the preview pane. -->

<!-- Full-width background wrapper -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:#ffffff;">
  <tr>
    <td align="center" style="padding:0;">

<!--[if mso]>
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:600px;">
<tr><td>
<![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" align="center"
       style="font-family:Arial,Helvetica,sans-serif;background-color:#ffffff;max-width:600px;margin:0 auto;">

{grid}

  <!-- Footer (Burrow shared footer content block — matches T1) -->
  <tr>
    <td style="padding:0;">
      {{{{content_blocks.${{footer_us}} | id: 'cb2'}}}}
    </td>
  </tr>

</table>
<!--[if mso]>
</td></tr>
</table>
<![endif]-->

    </td>
  </tr>
</table>
</body>
</html>
"""


def build_plaintext() -> str:
    return (
        "Hi {{${first_name} | default: 'there'}},\n\n"
        "Sometimes you need more options.\n\n"
        "Not every chair is a Burrow chair. And that's okay. Our sister brands "
        "have options worth exploring.\n\n"
        "Interior Define specializes in made-to-order dining chairs in a wide "
        "range of fabrics and finishes. They're worth a look if you want "
        "something more custom.\n\n"
        f"Shop Interior Define for custom dining chairs built to order: {ID_URL}\n\n"
        "The Burrow Team"
    )


def create_braze_template(html: str) -> str:
    url = f"{BRAZE_BASE}/templates/email/create"
    headers = {
        "Authorization": f"Bearer {API_KEY_BUR}",
        "Content-Type": "application/json",
    }
    payload = {
        "template_name": TEMPLATE_NAME,
        "subject": SUBJECT,
        "preheader": PREHEADER,  # Braze's field is `preheader`, not `preheader_text`
        "body": html,
        "plaintext_body": build_plaintext(),
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    body = resp.json()
    template_id = body.get("email_template_id") or body.get("template_id")
    if not template_id:
        raise ValueError(f"No template_id in response: {body}")
    return template_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true",
                    help="Upload images to Braze + create the template. "
                         "Without it, builds a local-image HTML preview only.")
    args = ap.parse_args()

    print("=== BUR Dining Chair Rec T3 Template Builder ===\n")

    # 1. Ensure the 4 slices are on disk (download if missing)
    print("Ensuring slice images are present...")
    local_paths = []
    for cfg in SLICES:
        dest = SCRATCHPAD / cfg["file"]
        if not dest.exists():
            download_image(cfg["drive"], str(dest))
        print(f"  {cfg['file']}: {dest.stat().st_size:,} bytes")
        local_paths.append(dest)

    if not args.create:
        # QA preview: build HTML pointing at local files.
        html = build_html([f"file://{p}" for p in local_paths])
        preview = SCRATCHPAD / "t3_preview.html"
        preview.write_text(html)
        print(f"\nQA preview written: {preview}")
        print("Render it, then re-run with --create to upload + create the template.")
        return

    # 2. Upload slices to the Burrow media library
    print("\nUploading to Braze media library (Burrow)...")
    cdn_urls = [upload_media(p, cfg["media_name"]) for p, cfg in zip(local_paths, SLICES)]

    # 3. Build final HTML with CDN URLs
    print("\nBuilding HTML template...")
    html = build_html(cdn_urls)
    out = SCRATCHPAD / "t3_final.html"
    out.write_text(html)
    print(f"  HTML length: {len(html):,} chars (written {out})")

    # 4. Create the Braze template
    print(f"\nCreating Braze template: {TEMPLATE_NAME} ...")
    template_id = create_braze_template(html)
    print("\n[OK] Template created!")
    print(f"  Template name: {TEMPLATE_NAME}")
    print(f"  Template ID:   {template_id}")
    print("\nWire into the canvas as Touch 3 (Step F):")
    print(f"  Step name: TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A_T3_V1")


if __name__ == "__main__":
    main()
