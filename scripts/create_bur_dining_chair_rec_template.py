#!/usr/bin/env python3
"""
Create the Burrow "Dining Chair Recommendation" email template in the BUR Braze workspace.

Design: Figma node 510:2 in file 1LyssxH7GsjnRp6bwxxsYl
  - Hero lifestyle image (static — user supplies Braze-hosted URL)
  - Live-text product_name section
  - 2×2 product grid via canvas_entry_properties (50/50, no mobile stacking)
  - CTA banner (static — user supplies Braze-hosted URL)

After creation, update the two placeholder image URLs in the template:
  HERO_IMAGE_URL   — dining room lifestyle image with "The Table Is Set. Almost." headline
  CTA_BANNER_URL   — dark espresso chairs image with "Shop All Dining Chairs" CTA text

Liquid variables expected in canvas_entry_properties:
  product_name        — purchased table name (e.g. "Serif Dining Table")
  rec_1_image_url … rec_4_image_url  — product image URLs
  rec_1_name      … rec_4_name       — product names
  rec_1_url       … rec_4_url        — product page URLs
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, init_config

TEMPLATE_NAME = "TRG_EM_BUR_PT_Dining_Chair_Recommendation_V1"

HTML = """\
<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="en">
<head>
<title></title>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<!--[if mso]><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch><o:AllowPNG/></o:OfficeDocumentSettings></xml><![endif]-->
<!--[if !mso]><!-->
<link href="https://d1qnmprc5tnkc9.cloudfront.net/fonts/c506d6b24ddd6d6a415b040bedcc2c5d.woff" rel="stylesheet" type="text/css">
<!--<![endif]-->
<style>
*{box-sizing:border-box}
body{margin:0;padding:0;background-color:#f7eee3}
a[x-apple-data-detectors]{color:inherit!important;text-decoration:inherit!important}
#MessageViewBody a{color:inherit;text-decoration:none}
p{line-height:inherit;margin:0}
img{-ms-interpolation-mode:bicubic}
</style>
<!--[if mso]><style>
td{font-family:Arial,sans-serif}
</style><![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#f7eee3;-webkit-text-size-adjust:none;text-size-adjust:none;">

<!-- ============================================================
     OUTER WRAPPER
     ============================================================ -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"
  style="mso-table-lspace:0;mso-table-rspace:0;background-color:#f7eee3;">
<tr><td align="center" style="padding:0;">

  <!-- ============================================================
       ROW 1 — MASTER HEADER (Burrow logo bar, content block)
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;">
  <tr><td align="center"
    style="mso-table-lspace:0;mso-table-rspace:0;padding:0;font-family:Neuzeit,Arial,sans-serif;text-align:center;">
    {{content_blocks.${MASTER_HEADER} | id: 'cb1'}}
  </td></tr>
  </table>

  <!-- ============================================================
       ROW 2 — HERO IMAGE
       Replace HERO_IMAGE_URL with Braze-hosted asset.
       Image should contain: dining room lifestyle photo + headline
       "The Table Is Set. Almost." baked in at 600×430px (or similar).
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;">
  <tr><td style="mso-table-lspace:0;mso-table-rspace:0;padding:0;line-height:0;font-size:0;">
    <a href="https://burrow.com/dining" target="_blank"
      style="display:block;text-decoration:none;line-height:0;">
      <img src="HERO_IMAGE_URL"
        alt="The Table Is Set. Almost."
        width="600"
        style="display:block;width:100%;height:auto;border:0;max-width:600px;">
    </a>
  </td></tr>
  </table>

  <!-- ============================================================
       ROW 3 — PRODUCT NAME (live text, cream background)
       {{canvas_entry_properties.${product_name}}} renders the
       purchased table name dynamically at send time.
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;background-color:#f7eee3;">
  <tr><td align="center"
    style="mso-table-lspace:0;mso-table-rspace:0;padding:40px 48px 36px;background-color:#f7eee3;text-align:center;">
    <!--[if mso]><table width="504" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation"><tr><td align="center"><![endif]-->
    <p style="font-family:Neuzeit,Arial,sans-serif;font-size:21px;font-weight:400;color:#3c2b1f;
      line-height:1.55;text-align:center;margin:0 0 5px;">
      Your {{canvas_entry_properties.${product_name}}} looks great.
    </p>
    <p style="font-family:Neuzeit,Arial,sans-serif;font-size:21px;font-weight:400;color:#3c2b1f;
      line-height:1.55;text-align:center;margin:0;">
      Let&rsquo;s find it the right seats.
    </p>
    <!--[if mso]></td></tr></table><![endif]-->
  </td></tr>
  </table>

  <!-- ============================================================
       ROW 4 — BODY COPY (white background)
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;background-color:#ffffff;">
  <tr><td align="center"
    style="mso-table-lspace:0;mso-table-rspace:0;padding:40px 64px;background-color:#ffffff;text-align:center;">
    <!--[if mso]><table width="472" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation"><tr><td align="center"><![endif]-->
    <p style="font-family:Neuzeit,Arial,sans-serif;font-size:16px;font-weight:400;color:#3c2b1f;
      line-height:1.7;text-align:center;margin:0;">
      We picked a few dining chairs that pair well with your table. Different styles, same Burrow quality. Browse below and see what feels right.
    </p>
    <!--[if mso]></td></tr></table><![endif]-->
  </td></tr>
  </table>

  <!-- ============================================================
       ROW 5 — 2×2 PRODUCT GRID
       50/50 layout — stays two-column on mobile (no stacking).
       Product images and names come from canvas_entry_properties.
       table-layout:fixed forces equal-width columns on all clients.
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;background-color:#ffffff;">
  <tr><td style="mso-table-lspace:0;mso-table-rspace:0;padding:0 20px 4px;background-color:#ffffff;">

    <!-- Top row of products -->
    <table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"
      style="mso-table-lspace:0;mso-table-rspace:0;table-layout:fixed;width:100%;">
    <tr>
      <!-- Product 1 -->
      <td width="50%" valign="top"
        style="mso-table-lspace:0;mso-table-rspace:0;width:50%;padding:0 6px 0 0;">
        <a href="{{canvas_entry_properties.${rec_1_url}}}" target="_blank"
          style="display:block;text-decoration:none;color:inherit;">
          <img src="{{canvas_entry_properties.${rec_1_image_url}}}"
            alt="{{canvas_entry_properties.${rec_1_name}}}"
            style="display:block;width:100%;height:auto;border:0;" width="270">
        </a>
        <p style="font-family:Neuzeit,Arial,sans-serif;font-size:13px;font-weight:400;
          color:#3c2b1f;line-height:1.4;margin:9px 0 22px;text-align:left;">
          <a href="{{canvas_entry_properties.${rec_1_url}}}" target="_blank"
            style="color:#3c2b1f;text-decoration:none;">
            {{canvas_entry_properties.${rec_1_name}}}&nbsp;&nbsp;&rarr;
          </a>
        </p>
      </td>
      <!-- Product 2 -->
      <td width="50%" valign="top"
        style="mso-table-lspace:0;mso-table-rspace:0;width:50%;padding:0 0 0 6px;">
        <a href="{{canvas_entry_properties.${rec_2_url}}}" target="_blank"
          style="display:block;text-decoration:none;color:inherit;">
          <img src="{{canvas_entry_properties.${rec_2_image_url}}}"
            alt="{{canvas_entry_properties.${rec_2_name}}}"
            style="display:block;width:100%;height:auto;border:0;" width="270">
        </a>
        <p style="font-family:Neuzeit,Arial,sans-serif;font-size:13px;font-weight:400;
          color:#3c2b1f;line-height:1.4;margin:9px 0 22px;text-align:left;">
          <a href="{{canvas_entry_properties.${rec_2_url}}}" target="_blank"
            style="color:#3c2b1f;text-decoration:none;">
            {{canvas_entry_properties.${rec_2_name}}}&nbsp;&nbsp;&rarr;
          </a>
        </p>
      </td>
    </tr>
    </table>

    <!-- Bottom row of products -->
    <table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"
      style="mso-table-lspace:0;mso-table-rspace:0;table-layout:fixed;width:100%;">
    <tr>
      <!-- Product 3 -->
      <td width="50%" valign="top"
        style="mso-table-lspace:0;mso-table-rspace:0;width:50%;padding:0 6px 0 0;">
        <a href="{{canvas_entry_properties.${rec_3_url}}}" target="_blank"
          style="display:block;text-decoration:none;color:inherit;">
          <img src="{{canvas_entry_properties.${rec_3_image_url}}}"
            alt="{{canvas_entry_properties.${rec_3_name}}}"
            style="display:block;width:100%;height:auto;border:0;" width="270">
        </a>
        <p style="font-family:Neuzeit,Arial,sans-serif;font-size:13px;font-weight:400;
          color:#3c2b1f;line-height:1.4;margin:9px 0 22px;text-align:left;">
          <a href="{{canvas_entry_properties.${rec_3_url}}}" target="_blank"
            style="color:#3c2b1f;text-decoration:none;">
            {{canvas_entry_properties.${rec_3_name}}}&nbsp;&nbsp;&rarr;
          </a>
        </p>
      </td>
      <!-- Product 4 -->
      <td width="50%" valign="top"
        style="mso-table-lspace:0;mso-table-rspace:0;width:50%;padding:0 0 0 6px;">
        <a href="{{canvas_entry_properties.${rec_4_url}}}" target="_blank"
          style="display:block;text-decoration:none;color:inherit;">
          <img src="{{canvas_entry_properties.${rec_4_image_url}}}"
            alt="{{canvas_entry_properties.${rec_4_name}}}"
            style="display:block;width:100%;height:auto;border:0;" width="270">
        </a>
        <p style="font-family:Neuzeit,Arial,sans-serif;font-size:13px;font-weight:400;
          color:#3c2b1f;line-height:1.4;margin:9px 0 22px;text-align:left;">
          <a href="{{canvas_entry_properties.${rec_4_url}}}" target="_blank"
            style="color:#3c2b1f;text-decoration:none;">
            {{canvas_entry_properties.${rec_4_name}}}&nbsp;&nbsp;&rarr;
          </a>
        </p>
      </td>
    </tr>
    </table>

  </td></tr>
  </table>

  <!-- Spacer between grid and CTA (white bg) -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;background-color:#ffffff;">
  <tr><td style="mso-table-lspace:0;mso-table-rspace:0;height:8px;background-color:#ffffff;line-height:8px;font-size:8px;">
    &nbsp;
  </td></tr>
  </table>

  <!-- ============================================================
       ROW 6 — CTA BANNER
       Replace CTA_BANNER_URL with Braze-hosted asset.
       Image should contain: dark espresso bg + 3 chairs lifestyle
       photo + "Shop All Dining Chairs" text baked in.
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;">
  <tr><td style="mso-table-lspace:0;mso-table-rspace:0;padding:0;line-height:0;font-size:0;">
    <a href="https://burrow.com/dining" target="_blank"
      style="display:block;text-decoration:none;line-height:0;">
      <img src="CTA_BANNER_URL"
        alt="Shop All Dining Chairs"
        width="600"
        style="display:block;width:100%;height:auto;border:0;max-width:600px;">
    </a>
  </td></tr>
  </table>

  <!-- ============================================================
       ROW 7 — FOOTER (content block)
       ============================================================ -->
  <table align="center" width="600" border="0" cellpadding="0" cellspacing="0" role="presentation"
    style="mso-table-lspace:0;mso-table-rspace:0;width:600px;max-width:600px;background-color:#f7eee3;">
  <tr><td align="center"
    style="mso-table-lspace:0;mso-table-rspace:0;padding:0;font-family:Neuzeit,Arial,sans-serif;text-align:center;">
    {{content_blocks.${footer_us} | id: 'cb2'}}
  </td></tr>
  </table>

</td></tr>
</table>

</body>
</html>
"""

PLAINTEXT = """\
Hi {{${first_name} | default: 'there'}},

Your {{canvas_entry_properties.${product_name}}} looks great. Let's find it the right seats.

We picked a few dining chairs that pair well with your table. Different styles, same Burrow quality. Browse below and see what feels right.

{{canvas_entry_properties.${rec_1_name}}}
{{canvas_entry_properties.${rec_1_url}}}

{{canvas_entry_properties.${rec_2_name}}}
{{canvas_entry_properties.${rec_2_url}}}

{{canvas_entry_properties.${rec_3_name}}}
{{canvas_entry_properties.${rec_3_url}}}

{{canvas_entry_properties.${rec_4_name}}}
{{canvas_entry_properties.${rec_4_url}}}

Shop All Dining Chairs:
https://burrow.com/dining

{{content_blocks.${PT_sale_footer_unsubscribe}}}
"""


def main():
    init_config("BUR")

    payload = {
        "template_name": TEMPLATE_NAME,
        "subject": "The right seats for your {{canvas_entry_properties.${product_name}}}",
        "body": HTML,
        "plaintext_body": PLAINTEXT,
        "tags": [],
    }

    print(f"Creating template: {TEMPLATE_NAME}")
    data, err = braze_post_request("templates/email/create", payload, brand="BUR")

    if err:
        print(f"ERROR: {err}")
        return

    template_id = data.get("email_template_id") or data.get("template_id")
    print(f"✓ Template created successfully")
    print(f"  Template ID: {template_id}")
    print()
    print("Next steps:")
    print("  1. Upload hero image to Braze CDN → replace HERO_IMAGE_URL in template")
    print("  2. Upload CTA banner image → replace CTA_BANNER_URL in template")
    print("  3. Confirm canvas_entry_properties variable names match your canvas config:")
    print("     product_name, rec_1_image_url … rec_4_image_url,")
    print("     rec_1_name … rec_4_name, rec_1_url … rec_4_url")


if __name__ == "__main__":
    main()
