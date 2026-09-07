#!/usr/bin/env python3
"""
Patch the existing BUR Dining Chair Rec T1 template in Braze:
  1. Add Braze message_extras tags (rec1-4 URLs) for purchase attribution
  2. Add MSO conditional comment wrapper so Outlook 2007-2019 sees a fixed
     600px table instead of the fluid width="100%" one (Outlook ignores
     CSS max-width and would otherwise stretch to full reading-pane width)

Fetches the current HTML from Braze, applies both patches, then updates
the template via POST /templates/email/update.
"""

import os
import re
import sys

import requests
from dotenv import load_dotenv



load_dotenv()

BRAZE_BASE = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
API_KEY_BUR = os.environ["BRAZE_API_KEY_BUR"]
TEMPLATE_ID = "57fb19b9-8900-4a13-a292-35c4b1bb2a6f"

HEADERS = {
    "Authorization": f"Bearer {API_KEY_BUR}",
    "Content-Type": "application/json",
}

MESSAGE_EXTRAS = """\
<!-- Message extras: logged on every send event in USERS_MESSAGES_EMAIL_SEND_SHARED.MESSAGE_EXTRAS.
     Join rec URLs to USERS_BEHAVIORS_PURCHASE_SHARED (match variant SKU from URL query string)
     to measure which recommended chairs were ultimately purchased. -->
{% message_extras :key "rec1_url" :value "{{custom_attribute.${post_purchase_rec1_url}}}" %}
{% message_extras :key "rec2_url" :value "{{custom_attribute.${post_purchase_rec2_url}}}" %}
{% message_extras :key "rec3_url" :value "{{custom_attribute.${post_purchase_rec3_url}}}" %}
{% message_extras :key "rec4_url" :value "{{custom_attribute.${post_purchase_rec4_url}}}" %}

"""

MSO_OPEN = """\
<!--[if mso]>
<table width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:600px;">
<tr><td>
<![endif]-->
"""

MSO_CLOSE = """\
<!--[if mso]>
</td></tr>
</table>
<![endif]-->
"""

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
    " %}{% abort_message(\"post_purchase rec attributes not set\") %}{% endif %}\n"
)


def get_template(template_id: str) -> dict:
    url = f"{BRAZE_BASE}/templates/email/info"
    resp = requests.get(url, headers=HEADERS, params={"email_template_id": template_id})
    resp.raise_for_status()
    return resp.json()


def patch_html(html: str) -> str:
    # -- Patch 1: message_extras --
    # Insert right before the preheader comment (or the preheader div itself)
    marker = "<!-- Preheader:"
    if marker in html:
        html = html.replace(marker, MESSAGE_EXTRAS + marker, 1)
    else:
        # Fallback: insert before the first <div style="display:none
        html = html.replace('<div style="display:none', MESSAGE_EXTRAS + '<div style="display:none', 1)

    # -- Patch 2: MSO conditional wrapper --
    # Open: insert the MSO wrapper just before the outer fluid table
    outer_table_re = re.compile(
        r'(<table width="100%" cellpadding="0" cellspacing="0" border="0" align="center"\s*'
        r'style="[^"]*max-width:600px[^"]*">)',
        re.DOTALL,
    )
    if outer_table_re.search(html):
        html = outer_table_re.sub(MSO_OPEN + r"\1", html, count=1)
    else:
        print("WARNING: outer fluid table not found — MSO patch skipped", file=sys.stderr)

    # Close: insert the MSO closing comment after the matching </table> + before </body>
    html = html.replace("</table>\n</body>", f"</table>\n{MSO_CLOSE}</body>", 1)
    if "</body>" in html and MSO_CLOSE not in html:
        # Last </table> before </body> — broader fallback
        idx = html.rfind("</table>")
        if idx != -1:
            html = html[:idx + len("</table>")] + "\n" + MSO_CLOSE + html[idx + len("</table>"):]

    return html


def update_template(template_id: str, template_name: str, subject: str,
                    preheader: str, html: str) -> None:
    url = f"{BRAZE_BASE}/templates/email/update"
    payload = {
        "email_template_id": template_id,
        "template_name": template_name,
        "subject": subject,
        "preheader_text": preheader,  # create uses preheader_text; update accepts both
        "body": html,
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    resp.raise_for_status()
    body = resp.json()
    if body.get("message") not in ("success", None):
        print(f"Braze response: {body}", file=sys.stderr)


def main():
    print(f"Fetching template {TEMPLATE_ID} ...")
    data = get_template(TEMPLATE_ID)
    html = data["body"]
    template_name = data["template_name"]
    subject = data["subject"]
    preheader = data.get("preheader", data.get("preheader_text", ""))

    print(f"  Template name:  {template_name}")
    print(f"  HTML length:    {len(html):,} chars")

    # Guard: don't double-patch
    skip_extras = "message_extras" in html
    skip_mso    = "<!--[if mso]>" in html
    skip_abort  = "abort_message" in html

    if skip_extras:
        print("  already has message_extras — skipping patch 1")
    if skip_mso:
        print("  already has MSO wrapper — skipping patch 2")
    if skip_abort:
        print("  already has abort_message — skipping patch 3")

    if skip_extras and skip_mso and skip_abort:
        print("\nNo changes needed. Exiting.")
        return

    print("\nApplying patches...")
    if not skip_extras:
        html = _apply_extras(html)
        print("  ✓ message_extras added")
    if not skip_mso:
        html = _apply_mso(html)
        print("  ✓ MSO conditional wrapper added")
    if not skip_abort:
        html = _apply_abort(html)
        print("  ✓ abort_message check added")

    print(f"\nUpdating template in Braze...")
    update_template(TEMPLATE_ID, template_name, subject, preheader, html)
    print(f"✓ Template updated successfully: {template_name}")


def _apply_abort(html: str) -> str:
    # Insert right after <body ...> opening tag
    marker = "<body"
    idx = html.find(marker)
    if idx == -1:
        print("WARNING: <body> tag not found — abort patch skipped", file=sys.stderr)
        return html
    end = html.index(">", idx) + 1  # end of the opening <body ...> tag
    return html[:end] + "\n\n" + ABORT_LIQUID + "\n" + html[end:]


def _apply_extras(html: str) -> str:
    marker = "<!-- Preheader:"
    if marker in html:
        return html.replace(marker, MESSAGE_EXTRAS + marker, 1)
    return html.replace('<div style="display:none', MESSAGE_EXTRAS + '<div style="display:none', 1)


def _apply_mso(html: str) -> str:
    outer_table_re = re.compile(
        r'(<table width="100%" cellpadding="0" cellspacing="0" border="0" align="center"\s*'
        r'style="[^"]*max-width:600px[^"]*">)',
        re.DOTALL,
    )
    if outer_table_re.search(html):
        html = outer_table_re.sub(MSO_OPEN + r"\1", html, count=1)
    else:
        print("WARNING: outer fluid table not found — MSO patch skipped", file=sys.stderr)

    if "</table>\n</body>" in html:
        html = html.replace("</table>\n</body>", f"</table>\n{MSO_CLOSE}</body>", 1)
    else:
        idx = html.rfind("</table>")
        if idx != -1:
            html = html[:idx + len("</table>")] + "\n" + MSO_CLOSE + html[idx + len("</table>"):]
    return html


if __name__ == "__main__":
    main()
