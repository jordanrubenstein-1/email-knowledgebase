#!/usr/bin/env python3
"""
Build script: BUR Dining Table Rec T1 email template (Flow 1B).

Flow 1B (Touch 1) of the Burrow post-purchase series — the mirror of Flow 1A.
Targets customers who bought indoor dining CHAIRS (Alto/Haiku/Sonnet) but not a
dining table, and recommends the 4 Burrow dining tables (Serif, Harvest, Listo,
Gallery), all in the finish that matches the chair they bought (Walnut/Oak),
ordered by co-purchase.

All personalization comes from Braze custom attributes written to the user
profile by the daily GitLab sync job:
    scripts/braze_automation/sync_bur_post_purchase_attributes.py
For a Flow 1B enrollee the job writes:
    post_purchase_product_name  - the chair line, e.g. "Alto Dining Chairs"
    post_purchase_rec1-4_name   - e.g. "Serif Extendable Dining Table (Walnut)"
    post_purchase_rec1-4_img    - finish-matched table image URL
    post_purchase_rec1-4_url    - burrow.com PDP URL with ?Wood+Finish= selected
This template renders those attributes directly — same rec slots as 1A (a user is
in exactly one flow at a time, so the shared slots never collide).

  1. Downloads the 3 graphic slices from Google Drive (authenticated OAuth)
  2. Uploads them to the Burrow Braze media library via POST /media_library/create
  3. Builds the 600px HTML email (MSO Outlook wrapper, mobile-fluid images,
     abort-guard, message_extras, cream text block, 2x2 table-rec grid)
  4. Creates the Braze designed email template via POST /templates/email/create
     (only when --create is passed; otherwise just writes the HTML for QA)

Template name: TRG_EM_2026_07_BW_D_Dining_Table_Rec_T1_V1
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

TEMPLATE_NAME = "TRG_EM_2026_07_BW_D_Dining_Table_Rec_T1_V1"
SUBJECT       = "Your chairs are ready. Is your table?"
# Preheader lives in the Braze `preheader` field (Liquid supported); no hidden div.
PREHEADER     = "Here's what pairs well with your {{custom_attribute.${post_purchase_product_name}}}."

# Slices 1, 3, 5 all link to the dining tables collection (per brief).
DINING_TABLES_URL = "https://burrow.com/collections/dining-tables"

# Graphic slices (Google Drive) — slice 2 (text) and slice 4 (rec grid) are
# built inline below, not sourced from Drive.
SLICES = [
    {
        "key": "slice1",
        "drive": "https://drive.google.com/file/d/1OjukpgP9uNyWM-jTnE0uFxFH5Phid3VU/view",
        "media_name": "bur_dining_table_rec_t1_slice1.png",
        "alt": "Your Burrow dining chairs deserve the perfect table",
    },
    {
        "key": "slice3",
        "drive": "https://drive.google.com/file/d/1cIfHyZ1oUPLo0MIvD1VjPNc3ottR37dq/view",
        "media_name": "bur_dining_table_rec_t1_slice3.png",
        "alt": "Explore Burrow dining tables",
    },
    {
        "key": "slice5",
        "drive": "https://drive.google.com/file/d/1D7gpVkj8tPMcl5E0o8m7q49lw91MVwrg/view",
        "media_name": "bur_dining_table_rec_t1_slice5.png",
        "alt": "Explore all Burrow dining tables",
    },
]

SCRATCHPAD = Path(
    "/private/tmp/claude-501/"
    "-Users-jordan-rubenstein-Downloads-email-knowledgebase-email-knowledgebase/"
    "8d106062-1c61-4855-bb89-1d157220e71d/scratchpad"
)

# ── Liquid blocks (plain strings — real Liquid braces, never f-strings) ──────────

# Abort the send if any personalization attribute is missing. All 13 attributes
# are written atomically by the sync job; aborting is better than a broken email
# (e.g. a user who entered before the sync job first ran, or a bare chair record
# with no parseable finish).
ABORT_LIQUID = (
    "{% if custom_attribute.${post_purchase_product_name} == blank"
    " or custom_attribute.${post_purchase_rec1_name} == blank"
    " or custom_attribute.${post_purchase_rec1_img} == blank"
    " or custom_attribute.${post_purchase_rec1_url} == blank"
    " or custom_attribute.${post_purchase_rec2_name} == blank"
    " or custom_attribute.${post_purchase_rec2_img} == blank"
    " or custom_attribute.${post_purchase_rec2_url} == blank"
    " or custom_attribute.${post_purchase_rec3_name} == blank"
    " or custom_attribute.${post_purchase_rec3_img} == blank"
    " or custom_attribute.${post_purchase_rec3_url} == blank"
    " or custom_attribute.${post_purchase_rec4_name} == blank"
    " or custom_attribute.${post_purchase_rec4_img} == blank"
    " or custom_attribute.${post_purchase_rec4_url} == blank"
    " %}{% abort_message(\"post_purchase rec attributes not set\") %}{% endif %}"
)

# Logged on every send event (USERS_MESSAGES_EMAIL_SEND_SHARED.MESSAGE_EXTRAS).
# Join rec URLs to USERS_BEHAVIORS_PURCHASE_SHARED to measure which recommended
# tables were ultimately purchased.
MESSAGE_EXTRAS = (
    '{% message_extras :key "rec1_url" :value "{{custom_attribute.${post_purchase_rec1_url}}}" %}\n'
    '{% message_extras :key "rec2_url" :value "{{custom_attribute.${post_purchase_rec2_url}}}" %}\n'
    '{% message_extras :key "rec3_url" :value "{{custom_attribute.${post_purchase_rec3_url}}}" %}\n'
    '{% message_extras :key "rec4_url" :value "{{custom_attribute.${post_purchase_rec4_url}}}" %}'
)

# Slice 2: text block on cream (#F6EEE3). {{product_name}} = the chair line.
# Non-breaking space between "all" and "together" per brief.
SLICE2_TEXT = """  <!-- Slice 2: text block (cream) -->
  <tr>
    <td class="text-intro" style="background-color:#F6EEE3;padding:32px 40px;text-align:center;">
      <p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:21px;color:#1a1a1a;line-height:1.55;">
        Your {{custom_attribute.${post_purchase_product_name}}} arrived (or are on their way).
      </p>
      <p style="margin:12px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:21px;color:#1a1a1a;line-height:1.55;">
        Now all you need is a table to bring it all&nbsp;together.
      </p>
    </td>
  </tr>"""

# Slice 4: 2x2 table-rec grid (renders post_purchase_rec1-4_{img,url,name}).
GRID_HTML = """  <!-- Slice 4: 2x2 table recommendation grid -->
  <tr>
    <td style="padding:8px 20px 8px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <!-- Rec 1 -->
          <td width="50%" style="padding:0 8px 24px 0;vertical-align:top;text-align:center;">
            <a href="{{custom_attribute.${post_purchase_rec1_url}}}" target="_blank" style="text-decoration:none;">
              <img src="{{custom_attribute.${post_purchase_rec1_img}}}" width="270"
                   alt="{{custom_attribute.${post_purchase_rec1_name}}}"
                   style="display:block;width:100%;max-width:270px;height:auto;border:0;">
            </a>
            <a href="{{custom_attribute.${post_purchase_rec1_url}}}" target="_blank"
               style="display:block;margin-top:10px;font-family:Arial,Helvetica,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{custom_attribute.${post_purchase_rec1_name}}} &rarr;
            </a>
          </td>
          <!-- Rec 2 -->
          <td width="50%" style="padding:0 0 24px 8px;vertical-align:top;text-align:center;">
            <a href="{{custom_attribute.${post_purchase_rec2_url}}}" target="_blank" style="text-decoration:none;">
              <img src="{{custom_attribute.${post_purchase_rec2_img}}}" width="270"
                   alt="{{custom_attribute.${post_purchase_rec2_name}}}"
                   style="display:block;width:100%;max-width:270px;height:auto;border:0;">
            </a>
            <a href="{{custom_attribute.${post_purchase_rec2_url}}}" target="_blank"
               style="display:block;margin-top:10px;font-family:Arial,Helvetica,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{custom_attribute.${post_purchase_rec2_name}}} &rarr;
            </a>
          </td>
        </tr>
        <tr>
          <!-- Rec 3 -->
          <td width="50%" style="padding:0 8px 24px 0;vertical-align:top;text-align:center;">
            <a href="{{custom_attribute.${post_purchase_rec3_url}}}" target="_blank" style="text-decoration:none;">
              <img src="{{custom_attribute.${post_purchase_rec3_img}}}" width="270"
                   alt="{{custom_attribute.${post_purchase_rec3_name}}}"
                   style="display:block;width:100%;max-width:270px;height:auto;border:0;">
            </a>
            <a href="{{custom_attribute.${post_purchase_rec3_url}}}" target="_blank"
               style="display:block;margin-top:10px;font-family:Arial,Helvetica,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{custom_attribute.${post_purchase_rec3_name}}} &rarr;
            </a>
          </td>
          <!-- Rec 4 -->
          <td width="50%" style="padding:0 0 24px 8px;vertical-align:top;text-align:center;">
            <a href="{{custom_attribute.${post_purchase_rec4_url}}}" target="_blank" style="text-decoration:none;">
              <img src="{{custom_attribute.${post_purchase_rec4_img}}}" width="270"
                   alt="{{custom_attribute.${post_purchase_rec4_name}}}"
                   style="display:block;width:100%;max-width:270px;height:auto;border:0;">
            </a>
            <a href="{{custom_attribute.${post_purchase_rec4_url}}}" target="_blank"
               style="display:block;margin-top:10px;font-family:Arial,Helvetica,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{custom_attribute.${post_purchase_rec4_name}}} &rarr;
            </a>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""

FOOTER_HTML = """  <!-- Footer (Burrow shared footer content block — matches 1A) -->
  <tr>
    <td style="padding:0;">
      {{content_blocks.${footer_us} | id: 'cb2'}}
    </td>
  </tr>"""


def _img_slice(src: str, alt: str) -> str:
    """A full-width graphic slice linking to the dining tables collection."""
    alt = alt.replace('"', "&quot;")
    return (
        "  <tr>\n"
        '    <td style="padding:0;font-size:0;line-height:0;">\n'
        f'      <a href="{DINING_TABLES_URL}" target="_blank" style="text-decoration:none;">\n'
        f'        <img src="{src}" width="600" alt="{alt}"\n'
        '             style="display:block;width:100%;max-width:600px;height:auto;border:0;">\n'
        "      </a>\n"
        "    </td>\n"
        "  </tr>"
    )


def build_html(slice_urls: dict) -> str:
    """Build the 600px designed-email HTML. slice_urls maps key -> src URL."""
    slice1 = _img_slice(slice_urls["slice1"], SLICES[0]["alt"])
    slice3 = _img_slice(slice_urls["slice3"], SLICES[1]["alt"])
    slice5 = _img_slice(slice_urls["slice5"], SLICES[2]["alt"])

    head = """\
<!--
  BUR Dining Table Rec — T1 (Flow 1B: chair buyers -> table recs)
  ---------------------------------------------------------------------------
  Touch 1 of the Flow 1B canvas. Personalization comes from Braze custom
  attributes written by sync_bur_post_purchase_attributes.py (2:15 AM UTC):
  post_purchase_product_name (chair line) + post_purchase_rec1-4_{name,img,url}
  (the 4 dining tables in the chair's finish, co-purchase ordered). Same rec
  slots as 1A; a user is in exactly one flow at a time.
  ---------------------------------------------------------------------------
-->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>Your chairs are ready. Is your table?</title>
<style>
  @media only screen and (max-width: 480px) {
    .text-intro { padding: 24px 24px !important; }
    .text-intro p { font-size: 17px !important; line-height: 1.45 !important; }
  }
</style>
<!--[if mso]>
<style type="text/css">
  table, td { border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }
  img { -ms-interpolation-mode:bicubic; }
</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#ffffff;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

"""

    # Preheader lives in the Braze `preheader` field, NOT the HTML. Whoever wires
    # the canvas step must check "add whitespace after preheader" in the composer.

    wrapper_open = """\
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

"""

    wrapper_close = """

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

    body = "\n".join([
        slice1,
        SLICE2_TEXT,
        slice3,
        GRID_HTML,
        slice5,
        FOOTER_HTML,
    ])

    return (
        head
        + ABORT_LIQUID + "\n\n"
        + MESSAGE_EXTRAS + "\n\n"
        + wrapper_open
        + body
        + wrapper_close
    )


def build_plaintext() -> str:
    return (
        "Hi {{${first_name} | default: 'there'}},\n\n"
        "Your {{custom_attribute.${post_purchase_product_name}}} arrived (or are on their way).\n"
        "Now all you need is a table to bring it all together.\n\n"
        "Explore our dining tables:\n"
        "1. {{custom_attribute.${post_purchase_rec1_name}}} - {{custom_attribute.${post_purchase_rec1_url}}}\n"
        "2. {{custom_attribute.${post_purchase_rec2_name}}} - {{custom_attribute.${post_purchase_rec2_url}}}\n"
        "3. {{custom_attribute.${post_purchase_rec3_name}}} - {{custom_attribute.${post_purchase_rec3_url}}}\n"
        "4. {{custom_attribute.${post_purchase_rec4_name}}} - {{custom_attribute.${post_purchase_rec4_url}}}\n\n"
        f"Shop all dining tables: {DINING_TABLES_URL}\n\n"
        "The Burrow Team"
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

    print("=== BUR Dining Table Rec T1 Template Builder (Flow 1B) ===\n")

    # 1. Ensure the 3 graphic slices are on disk (download if missing)
    print("Ensuring slice images are present...")
    SCRATCHPAD.mkdir(parents=True, exist_ok=True)
    local_paths = {}
    for cfg in SLICES:
        dest = SCRATCHPAD / f"{cfg['key']}.png"
        if not dest.exists():
            download_image(cfg["drive"], str(dest))
        print(f"  {cfg['key']}: {dest.stat().st_size:,} bytes")
        local_paths[cfg["key"]] = dest

    if not args.create:
        html = build_html({k: f"file://{p}" for k, p in local_paths.items()})
        preview = SCRATCHPAD / "table_rec_t1_preview.html"
        preview.write_text(html)
        print(f"\nQA preview written: {preview}")
        print("Render it, then re-run with --create to upload + create the template.")
        return

    # 2. Upload graphic slices to the Burrow media library
    print("\nUploading to Braze media library (Burrow)...")
    cdn_urls = {}
    for cfg in SLICES:
        cdn_urls[cfg["key"]] = upload_media(local_paths[cfg["key"]], cfg["media_name"])

    # 3. Build final HTML with CDN URLs
    print("\nBuilding HTML template...")
    html = build_html(cdn_urls)
    out = SCRATCHPAD / "table_rec_t1_final.html"
    out.write_text(html)
    print(f"  HTML length: {len(html):,} chars (written {out})")

    # 4. Create the Braze template
    print(f"\nCreating Braze template: {TEMPLATE_NAME} ...")
    template_id = create_braze_template(html)
    print("\n[OK] Template created!")
    print(f"  Template name: {TEMPLATE_NAME}")
    print(f"  Template ID:   {template_id}")
    print("\nWire into the Flow 1B canvas as Touch 1:")
    print(f"  Step name: {TEMPLATE_NAME}")
    print("  Designed sender: from_name 'Burrow', from_email friends@em.burrow.com, reply_to friends@burrow.com")


if __name__ == "__main__":
    main()
