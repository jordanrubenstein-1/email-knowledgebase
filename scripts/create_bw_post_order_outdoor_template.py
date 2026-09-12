#!/usr/bin/env python3
"""Create BW PT Post-Order Finish Your Outdoor Space email template in Braze."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_template_api import create_email_template

campaign_config = {
    "name": "TRG_EM_2026_05_BW_PT_Post_Order_Finish_Your_Outdoor_Space",
    "email": {
        "subject": "The outdoor space is coming together. Here's the rest.",
        "preheader": "Outdoor pillows and rugs from St. Frank and The Inside — curated to complete your new space.",
        "body": (
            "Hi {{${first_name} | default: 'there'}},\n\n"
            "Your outdoor space is almost there. Now make it yours.\n\n"
            "You've got the seating sorted — now add the layer that makes it feel like a real outdoor room. "
            "We've teamed up with St. Frank and The Inside to bring you outdoor pillows and rugs worth lingering over.\n\n"
            "<b>St. Frank — Craft and texture, built for the outdoors</b>\n"
            "Free shipping on orders over $150.\n"
            "Explore outdoor pillows from St. Frank\n\n"
            "<b>The Inside — 100+ outdoor pillow fabrics (yes, really)</b>\n"
            "Find your outdoor vibe — from bold prints to laid-back neutrals, plus rugs to pull it all together.\n"
            "Explore The Inside outdoor collection\n\n"
            "Burrow Team\n\n"
            "{{content_blocks.${PT_sale_footer_unsubscribe}}}"
        ),
        "cta_links": [
            {
                "text": "Explore outdoor pillows from St. Frank",
                "url": "https://www.stfrank.com/collections/all-outdoor",
                "priority": 1,
            },
            {
                "text": "Explore The Inside outdoor collection",
                "url": "https://www.theinside.com/collections/outdoorliving",
                "priority": 2,
            },
        ],
    },
}

if __name__ == "__main__":
    print("Creating BW PT Post-Order Finish Your Outdoor Space template...")
    template_id, error = create_email_template(campaign_config, "BUR")
    if error:
        print(f"Error: {error}")
        sys.exit(1)
    print(f"Template created successfully! Template ID: {template_id}")
