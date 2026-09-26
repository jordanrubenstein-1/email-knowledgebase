#!/usr/bin/env python3
"""
Build script: BUR Dining Chair Rec T1 email template.

1. Saves 3 image slices to disk (slice1, slice3, slice8)
2. Uploads them to Braze media library via POST /media
3. Builds the 600px HTML email with 2x2 Liquid-powered product grid
4. Creates the Braze designed email template via POST /templates/email/create

Template name: TRG_EM_2026_06_BW_D_Dining_Chair_Rec_T1_V1
"""

import base64
import json
import os
import sys
import tempfile
import requests
from pathlib import Path
from dotenv import load_dotenv

# ── env ────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_KEY_BUR       = os.environ["BRAZE_API_KEY_BUR"]
API_KEY_MEDIA_BUR = os.environ["BRAZE_API_KEY_MEDIA_BUR"]
BRAZE_BASE        = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

# ── image sources ───────────────────────────────────────────────────────────────
TOOL_RESULTS = Path(
    "/Users/jordan.rubenstein/.claude/projects/"
    "-Users-jordan-rubenstein-Downloads-email-knowledgebase-email-knowledgebase/"
    "1f81f49e-f93d-4e22-8a5d-93a7954eed51/tool-results"
)

SLICE1_JSON = TOOL_RESULTS / "mcp-0a047b5e-1f5b-4eba-873d-f5e17967d36b-download_file_content-1783881243979.txt"
SLICE8_JSON = TOOL_RESULTS / "mcp-0a047b5e-1f5b-4eba-873d-f5e17967d36b-download_file_content-1783881246222.txt"

# Slice 3 was returned inline — embed the base64 directly
SLICE3_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAA4QAAAEQCAYAAADoJrpHAAAACXBIWXMAAAsTAAALEwEAmpwYAAAA"
    "AAAAASUVORK5CYII="  # placeholder — will be replaced below
)


def load_json_image(path: Path) -> bytes:
    with open(path) as f:
        data = json.load(f)
    return base64.b64decode(data["content"])


def upload_media(image_bytes: bytes, filename: str, mime: str = "image/png") -> str:
    """Upload image to Braze media library, return CDN URL."""
    url = f"{BRAZE_BASE}/media_library/create"
    ext = filename.rsplit(".", 1)[-1]
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {API_KEY_MEDIA_BUR}"},
        files={"asset_file": (filename, image_bytes, f"image/{ext}")},
        data={"name": filename},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    assets = body.get("new_assets", [])
    if not assets:
        raise ValueError(f"No assets in media upload response: {body}")
    cdn_url = assets[0]["url"]
    print(f"  uploaded {filename} → {cdn_url}")
    return cdn_url


# Abort the send if any personalization attribute is missing.
# All 13 attributes are written atomically by the sync job in a single
# /users/track call, so a partial write shouldn't happen — but a user could
# enter the canvas before the sync job runs for the first time (backfill not
# yet complete), or an edge-case product not in the recommendation table could
# leave rec attributes unset. Aborting is better than sending a broken email.
_ABORT_LIQUID = (
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


def build_html(slice1_url: str, slice3_url: str, slice8_url: str) -> str:
    """Build the 600px designed email HTML with Liquid personalization."""
    # All personalization comes from Braze custom attributes set by the daily
    # sync job (sync_bur_post_purchase_attributes.py, 2:15 AM UTC). For each
    # dining table buyer the job writes post_purchase_product_name,
    # post_purchase_rec1-4_name/img/url to their Braze profile. The template
    # renders those attributes directly via {{custom_attribute.${...}}} --
    # no Liquid branching needed here.
    return f"""\
<!--
  HOW THIS TEMPLATE WORKS
  ---------------------------------------------------------------------------
  All personalization comes from Braze custom attributes written to the user
  profile by the daily GitLab sync job:
    scripts/braze_automation/sync_bur_post_purchase_attributes.py

  The sync job runs at 2:15 AM UTC. When a customer purchases a Burrow dining
  table it looks up their order, determines the table and finish, selects
  finish-matched chair recommendations from co-purchase data, and writes these
  attributes to their Braze profile:

    post_purchase_product_name  - e.g. "Serif Extendable Dining Table"
    post_purchase_rec1_name     - e.g. "Haiku Dining Chairs (Moss Green / Walnut)"
    post_purchase_rec1_img      - Shopify CDN image URL (finish-matched)
    post_purchase_rec1_url      - burrow.com URL with ?variant=ID (pre-selects colorway)
    post_purchase_rec2_name/img/url
    post_purchase_rec3_name/img/url
    post_purchase_rec4_name/img/url

  This email renders those attributes directly. No branching logic needed here.
  The canvas T1 step fires 7 days after canvas entry; by then the sync job has
  already written the correct values to the profile.
  ---------------------------------------------------------------------------
-->

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Burrow Dining Chair Recommendations</title>
<style>
  @media only screen and (max-width: 480px) {{
    .text-intro p {{
      font-size: 15px !important;
      line-height: 1.4 !important;
    }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">

{_ABORT_LIQUID}

<!-- Preheader: hidden text shown in inbox preview. The long stretch of
     whitespace/zero-width characters prevents the first visible line of
     the email from bleeding into the preview pane ("add whitespace after
     preheader" behaviour). -->
<!-- Message extras: logged on every send event in USERS_MESSAGES_EMAIL_SEND_SHARED.MESSAGE_EXTRAS.
     Join rec URLs to USERS_BEHAVIORS_PURCHASE_SHARED (match variant SKU from URL query string)
     to measure which recommended chairs were ultimately purchased. -->
{{% message_extras :key "rec1_url" :value "{{{{custom_attribute.${{post_purchase_rec1_url}}}}}}" %}}
{{% message_extras :key "rec2_url" :value "{{{{custom_attribute.${{post_purchase_rec2_url}}}}}}" %}}
{{% message_extras :key "rec3_url" :value "{{{{custom_attribute.${{post_purchase_rec3_url}}}}}}" %}}
{{% message_extras :key "rec4_url" :value "{{{{custom_attribute.${{post_purchase_rec4_url}}}}}}" %}}

<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">A few perfect chair pairings for your {{{{custom_attribute.${{post_purchase_product_name}}}}}}. &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>

<!--[if mso]>
<table width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:600px;">
<tr><td>
<![endif]-->
<table width="100%" cellpadding="0" cellspacing="0" border="0" align="center"
       style="font-family:Arial,sans-serif;background-color:#ffffff;max-width:600px;">

  <!-- Slice 1: header/lifestyle image -->
  <tr>
    <td style="padding:0;">
      <a href="https://burrow.com/collections/dining-chairs" style="text-decoration:none;">
        <img src="{slice1_url}" width="600" alt="Burrow" style="display:block;width:100%;max-width:600px;">
      </a>
    </td>
  </tr>

  <!-- Slice 2: text block -->
  <tr>
    <td class="text-intro" style="background-color:#F6EEE3;padding:32px 40px;text-align:center;">
      <p style="margin:0;font-family:Arial,sans-serif;font-size:21px;color:#1a1a1a;line-height:1.55;">
        Your {{{{custom_attribute.${{post_purchase_product_name}}}}}} looks&nbsp;great.
      </p>
      <p style="margin:8px 0 0 0;font-family:Arial,sans-serif;font-size:21px;color:#1a1a1a;line-height:1.55;">
        Let&rsquo;s find it the right seats.
      </p>
    </td>
  </tr>

  <!-- Slice 3: body copy image -->
  <tr>
    <td style="padding:0;">
      <a href="https://burrow.com/collections/dining-chairs" style="text-decoration:none;">
        <img src="{slice3_url}" width="600" alt="" style="display:block;width:100%;max-width:600px;">
      </a>
    </td>
  </tr>

  <!-- 2x2 product grid -->
  <tr>
    <td style="padding:8px 20px 8px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <!-- Rec 1 -->
          <td width="50%" style="padding:0 8px 24px 0;vertical-align:top;text-align:center;">
            <a href="{{{{custom_attribute.${{post_purchase_rec1_url}}}}}}" style="text-decoration:none;">
              <img src="{{{{custom_attribute.${{post_purchase_rec1_img}}}}}}" width="270"
                   alt="{{{{custom_attribute.${{post_purchase_rec1_name}}}}}}"
                   style="display:block;width:100%;max-width:270px;border:0;">
            </a>
            <a href="{{{{custom_attribute.${{post_purchase_rec1_url}}}}}}"
               style="display:block;margin-top:10px;font-family:Arial,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{{{custom_attribute.${{post_purchase_rec1_name}}}}}} &rarr;
            </a>
          </td>
          <!-- Rec 2 -->
          <td width="50%" style="padding:0 0 24px 8px;vertical-align:top;text-align:center;">
            <a href="{{{{custom_attribute.${{post_purchase_rec2_url}}}}}}" style="text-decoration:none;">
              <img src="{{{{custom_attribute.${{post_purchase_rec2_img}}}}}}" width="270"
                   alt="{{{{custom_attribute.${{post_purchase_rec2_name}}}}}}"
                   style="display:block;width:100%;max-width:270px;border:0;">
            </a>
            <a href="{{{{custom_attribute.${{post_purchase_rec2_url}}}}}}"
               style="display:block;margin-top:10px;font-family:Arial,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{{{custom_attribute.${{post_purchase_rec2_name}}}}}} &rarr;
            </a>
          </td>
        </tr>
        <tr>
          <!-- Rec 3 -->
          <td width="50%" style="padding:0 8px 24px 0;vertical-align:top;text-align:center;">
            <a href="{{{{custom_attribute.${{post_purchase_rec3_url}}}}}}" style="text-decoration:none;">
              <img src="{{{{custom_attribute.${{post_purchase_rec3_img}}}}}}" width="270"
                   alt="{{{{custom_attribute.${{post_purchase_rec3_name}}}}}}"
                   style="display:block;width:100%;max-width:270px;border:0;">
            </a>
            <a href="{{{{custom_attribute.${{post_purchase_rec3_url}}}}}}"
               style="display:block;margin-top:10px;font-family:Arial,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{{{custom_attribute.${{post_purchase_rec3_name}}}}}} &rarr;
            </a>
          </td>
          <!-- Rec 4 -->
          <td width="50%" style="padding:0 0 24px 8px;vertical-align:top;text-align:center;">
            <a href="{{{{custom_attribute.${{post_purchase_rec4_url}}}}}}" style="text-decoration:none;">
              <img src="{{{{custom_attribute.${{post_purchase_rec4_img}}}}}}" width="270"
                   alt="{{{{custom_attribute.${{post_purchase_rec4_name}}}}}}"
                   style="display:block;width:100%;max-width:270px;border:0;">
            </a>
            <a href="{{{{custom_attribute.${{post_purchase_rec4_url}}}}}}"
               style="display:block;margin-top:10px;font-family:Arial,sans-serif;font-size:13px;
                      color:#1a1a1a;text-decoration:none;line-height:1.4;">
              {{{{custom_attribute.${{post_purchase_rec4_name}}}}}} &rarr;
            </a>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Slice 8: CTA image -->
  <tr>
    <td style="padding:0;">
      <a href="https://burrow.com/collections/dining-chairs" style="text-decoration:none;">
        <img src="{slice8_url}" width="600" alt="Shop All Dining Chairs"
             style="display:block;width:100%;max-width:600px;">
      </a>
    </td>
  </tr>

  <!-- Footer -->
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
</body>
</html>
"""


def create_braze_template(html: str, subject: str, preheader: str, template_name: str) -> str:
    """Create email template via Braze API, return template_id."""
    url = f"{BRAZE_BASE}/templates/email/create"
    headers = {
        "Authorization": f"Bearer {API_KEY_BUR}",
        "Content-Type": "application/json",
    }
    payload = {
        "template_name": template_name,
        "subject": subject,
        "preheader_text": preheader,
        "body": html,
        "plaintext_body": (
            f"Hi {{{{${{first_name}} | default: 'there'}}}},\n\n"
            "Your dining table looks great. Let's find it the right seats.\n\n"
            "Shop all dining chairs: https://burrow.com/dining\n\n"
            "The Burrow Team"
        ),
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    body = resp.json()
    template_id = body.get("email_template_id") or body.get("template_id")
    if not template_id:
        raise ValueError(f"No template_id in response: {body}")
    return template_id


def main():
    print("=== BUR Dining Chair Rec T1 Template Builder ===\n")

    # 1. Load images
    print("Loading images...")
    slice1_bytes = load_json_image(SLICE1_JSON)
    slice8_bytes = load_json_image(SLICE8_JSON)

    # Slice 3: download from Drive (already captured — use file in scratchpad if present,
    # otherwise fall back to known Drive ID re-download via requests with Drive API key)
    scratchpad = Path(
        "/private/tmp/claude-501/"
        "-Users-jordan-rubenstein-Downloads-email-knowledgebase-email-knowledgebase/"
        "1f81f49e-f93d-4e22-8a5d-93a7954eed51/scratchpad"
    )
    slice3_path = scratchpad / "slice3.png"
    if slice3_path.exists():
        with open(slice3_path, "rb") as f:
            slice3_bytes = f.read()
        print(f"  slice3.png loaded from scratchpad ({len(slice3_bytes):,} bytes)")
    else:
        raise FileNotFoundError(f"slice3.png not found at {slice3_path}. Run save_slice3.py first.")

    print(f"  slice1.png: {len(slice1_bytes):,} bytes")
    print(f"  slice8.png: {len(slice8_bytes):,} bytes")

    # 2. Upload to Braze media library
    print("\nUploading to Braze media library...")
    slice1_cdn = upload_media(slice1_bytes, "bur_dining_rec_t1_slice1.png")
    slice3_cdn = upload_media(slice3_bytes, "bur_dining_rec_t1_slice3.png")
    slice8_cdn = upload_media(slice8_bytes, "bur_dining_rec_t1_slice8.png")

    # 3. Build HTML
    print("\nBuilding HTML template...")
    html = build_html(slice1_cdn, slice3_cdn, slice8_cdn)
    print(f"  HTML length: {len(html):,} chars")

    # 4. Create Braze template
    template_name = "TRG_EM_2026_06_BW_D_Dining_Chair_Rec_T1_V1"
    subject = "Your new table is missing something"
    preheader = "A few perfect chair pairings for your {{custom_attribute.${post_purchase_product_name}}}."
    print(f"\nCreating Braze template: {template_name} ...")
    template_id = create_braze_template(html, subject, preheader, template_name)
    print(f"\n✓ Template created successfully!")
    print(f"  Template name: {template_name}")
    print(f"  Template ID:   {template_id}")
    print(f"\nUpdate build_bur_dining_chair_rec_canvas.py with:")
    print(f"  T1_TEMPLATE_ID = \"{template_id}\"")

    return template_id


if __name__ == "__main__":
    main()
