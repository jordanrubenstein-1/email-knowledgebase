#!/usr/bin/env python3
"""
One-off script: Create ID Cart Abandon T2 plain-text email template in Braze.

Template name: TRG_EM_2026_05_ID_D_Cart_Abandon_T2_V1
Asana task:    1215025257765383
Send:          Canvas T2 touch — users with cart ≤ $3K
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, init_config

TEMPLATE_NAME = "TRG_EM_2026_05_ID_D_Cart_Abandon_T2_V1"
SUBJECT = "Your cart is saved. Flexible payments make it even easier"
BRAND = "ID"
CART_URL = "https://www.interiordefine.com/cart"

BODY_PARAGRAPHS = [
    "Just wanted to check in while you're thinking through that perfect piece for your space.",
    "Your cart is still saved, and we've made it easier than ever to get it home. With Afterpay, you can spread the cost into flexible payments — so you can focus on what actually matters: getting the piece you love.",
    "Custom furniture is worth it. We just want to make sure getting there feels that way too.",
    f'<a href="{CART_URL}" style="color:#1871D8;text-decoration:underline;">Complete your purchase now.</a>',
    "Any questions? There&#8217;s a real person on chat ready to help you through it.",
]

SIGNOFF = "Talk soon,<br>Lisa<br>Interior Define Team"


def build_html() -> str:
    template_path = Path(__file__).parent.parent / "components" / "id_pt_template.html"
    html = template_path.read_text()

    body_html = "\n".join(
        f'<p style="margin:0 0 14px 0;">{p}</p>' for p in BODY_PARAGRAPHS
    )
    html = html.replace("<!-- BODY_CONTENT -->", body_html)

    signoff_html = f'<p style="margin:0;">{SIGNOFF}</p>'
    html = html.replace("<!-- SIGNOFF -->", signoff_html)

    # Remove optional disclaimer row (not a sale send)
    begin = "<!-- BEGIN_DISCLAIMER_ROW -->"
    end = "<!-- END_DISCLAIMER_ROW -->"
    if begin in html and end in html:
        start_idx = html.index(begin)
        end_idx = html.index(end) + len(end)
        html = html[:start_idx] + html[end_idx:]

    return html


def main():
    init_config(BRAND)
    html = build_html()

    payload = {
        "template_name": TEMPLATE_NAME,
        "subject": SUBJECT,
        "preheader": "",
        "body": html,
    }

    print(f"Creating template: {TEMPLATE_NAME}")
    response, error = braze_post_request("templates/email/create", payload, BRAND)

    if error:
        print(f"ERROR: {error}")
        sys.exit(1)

    template_id = response.get("email_template_id") or response.get("id")
    print(f"Template created successfully.")
    print(f"Template ID: {template_id}")


if __name__ == "__main__":
    main()
