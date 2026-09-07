#!/usr/bin/env python3
"""
One-off script: Create BUR Post-Delivery Friendbuy email template in Braze.

Asana task: 1213933647865487
Campaign: OT_EM_BUR_PT_Post_Delivery_Friendbuy
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from braze_template_api import create_email_template
from import_braze import init_config

TEMPLATE_NAME = "TRG_EM_2026_04_BW_PT_Post_Delivery_Friendbuy_T1_V1"
BRAND = "BUR"

# Plain-text email body (two blank lines after greeting, same pattern as reference template)
BODY = """\
Hi {{${first_name} | default: 'there'}},


We hope you're loving your new Burrow piece. We also want to say a little thank you. If you refer a friend to Burrow, they'll get $75 off their first purchase. And when they place their order, we'll send you a $50 Amazon gift card as a token of appreciation.

Easy win for both of you.

You can grab your referral link here:
https://burrow.com/refer

Thanks again for choosing Burrow. We can't wait for you to get everything set up.

—The Burrow Team

{{content_blocks.${PT_sale_footer_unsubscribe} | id: 'cb3'}}\
"""

campaign_config = {
    "name": TEMPLATE_NAME,
    "email": {
        "subject": "A little thank you (and something for a friend)",
        "preheader": "",
        "body": BODY,
        "cta_links": [
            {"text": "https://burrow.com/refer", "url": "https://burrow.com/refer", "priority": 1},
        ],
    },
}

if __name__ == "__main__":
    print(f"Creating Braze email template: {TEMPLATE_NAME}")
    init_config(BRAND)

    template_id, error = create_email_template(campaign_config, BRAND)

    if error:
        print(f"✗ Failed to create template: {error}")
        sys.exit(1)

    print(f"✓ Template created successfully!")
    print(f"  Template ID: {template_id}")
    print(f"  Template name: {TEMPLATE_NAME}")
    print(f"  Subject: A little thank you (and something for a friend)")
    print(f"\nFind it in Braze: Templates > Email Templates > {TEMPLATE_NAME}")
    print(f"\nNote: delete old template 'OT_EM_BUR_PT_Post_Delivery_Friendbuy' (ID: 8f1c8324-4e9b-431f-8b58-8feb5e364c4f)")
