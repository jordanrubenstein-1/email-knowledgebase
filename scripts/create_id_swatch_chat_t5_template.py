#!/usr/bin/env python3
"""Update TRG_EM_2026_04_ID_PT_Swatch_Chat_T5_V1 Email Template in Braze (ID)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config

EXISTING_TEMPLATE_ID = "bb7a9658-77ff-4318-b591-3d4cdbac8bfe"
TEMPLATE_NAME = "TRG_EM_2026_04_ID_PT_Swatch_Chat_T5_V1"
SUBJECT = "Just ask. A designer is ready to chat right now."
PREHEADER = "Don't guess. Just ask us."

BODY = """<p>Hi {{${first_name} | default: 'there'}},</p>

<p>Choosing custom furniture means a lot of decisions. We&#8217;re here to make them easier.</p>

<ul style="margin: 0 0 14px 0; padding-left: 20px; line-height: 1.5;">
<li style="margin: 0 0 5px 0;">Not sure which cushion fill is right for you?</li>
<li style="margin: 0 0 5px 0;">Debating which leg finish will look best?</li>
<li style="margin: 0 0 5px 0;">Second-guessing a color after seeing the swatch in your space?</li>
<li style="margin: 0 0 5px 0;">Wondering if you should size up on the depth or height?</li>
<li style="margin: 0 0 5px 0;">Not sure which fabric will hold up best for your lifestyle?</li>
</ul>

<p>Chat with one of our designers &#8212; free, no appointment needed.<br>
<strong>Monday&#8211;Friday, 10am&#8211;6pm CT</strong></p>

<p><a href="https://www.interiordefine.com#hs-chat-open">Start a Chat</a></p>

<p>Rather meet in person or over a video call?<br>
<a href="https://www.interiordefine.com/design-services">Schedule a free appointment</a> or <a href="https://www.interiordefine.com/locations">Find your nearest store</a></p>

<p>Happy Shopping!<br>
The Interior Define Team</p>"""

FOOTER = """<p>Copyright &copy; {{ 'now' | date: '%Y' }}, Interior Define, All rights reserved.<br>
3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209</p>

<p>If you would rather not receive future emails from us, you may <a href="{{${set_user_to_unsubscribed_url}}}" style="color:#1871D8;text-decoration:underline;">unsubscribe</a>.</p>"""

formatted_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{margin:0;padding:0}}
p{{margin:0 0 14px 0;line-height:1.5}}
a{{color:#1871D8;text-decoration:underline}}
</style>
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="background-color:#ffffff;">
<tr><td align="center">
<table width="600" border="0" cellpadding="20" cellspacing="0">
<tr><td style="color:#101b24;font-family:Arial,sans-serif;font-size:14px;font-weight:400;line-height:150%;text-align:left;">

{BODY}

</td></tr>
<tr><td style="color:#101b24;font-family:Arial,sans-serif;font-size:9px;font-weight:400;line-height:normal;text-align:left;">

{FOOTER}

</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

brand = normalize_brand("ID")
init_config(brand)

response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": EXISTING_TEMPLATE_ID,
    "template_name": TEMPLATE_NAME,
    "subject": SUBJECT,
    "preheader": PREHEADER,
    "body": formatted_body,
}, brand)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

print("Template updated successfully!")
print(f"Template ID: {EXISTING_TEMPLATE_ID}")
print(f"Template name: {TEMPLATE_NAME}")
