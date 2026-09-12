#!/usr/bin/env python3
"""Create the S6 Follow-Up Email template in Braze (HAV workspace).

This posts the HTML from components/hav_s6_followup_email.html directly to
the Braze templates/email/create endpoint. It bypasses create_email_template()
which is designed for plain-text-to-HTML conversion, not raw HTML templates.

Dynamic content uses {{canvas_entry_properties.*}} Liquid variables —
see the HTML file for the full list of variables to wire up in the canvas.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.braze_campaign_api import braze_post_request, init_config


TEMPLATE_NAME = "OT_EM_2026_06_HAV_CONV_H_Studio6"
SUBJECT = "Your room is ready, {{${first_name} | default: 'there'}}"
PREHEADER = "Shop every piece from your final design—or get help bringing it all together."
PLAINTEXT = (
    "Hi {{${first_name} | default: 'there'}},\n\n"
    "Your room design is ready. Shop every piece or work with a Havenly designer to bring it all together.\n\n"
    "View and shop your full room: {{canvas_entry_properties.${room_page_url}}}\n\n"
    "Purchase this room with 20% off: {{canvas_entry_properties.${room_page_url}}}\n\n"
    "Finalize with a designer for 50% off: {{canvas_entry_properties.${room_page_url}}}\n\n"
    "The Havenly Team"
)


def main():
    init_config("HAV")

    html_path = Path(__file__).parent.parent / "components" / "hav_s6_followup_email.html"
    if not html_path.exists():
        print(f"Error: HTML file not found at {html_path}")
        sys.exit(1)

    html = html_path.read_text(encoding="utf-8")
    print(f"Read HTML template ({len(html):,} bytes)")

    template_data = {
        "template_name": TEMPLATE_NAME,
        "subject": SUBJECT,
        "preheader": PREHEADER,
        "body": html,
        "plaintext_body": PLAINTEXT,
    }

    print(f"Creating Braze Email Template: '{TEMPLATE_NAME}' ...")
    response_data, error = braze_post_request("templates/email/create", template_data, "HAV")

    if error:
        print(f"Error: {error}")
        sys.exit(1)

    template_id = response_data.get("email_template_id") or response_data.get("id")
    if not template_id:
        print(f"Unexpected response (no template ID): {response_data}")
        sys.exit(1)

    print(f"\n✓ Template created successfully!")
    print(f"  Template ID : {template_id}")
    print(f"  Name        : {TEMPLATE_NAME}")
    print(f"  Find it at  : Braze > Engagement > Templates > Email Templates")


if __name__ == "__main__":
    main()
