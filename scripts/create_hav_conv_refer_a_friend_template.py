#!/usr/bin/env python3
"""
One-off script: create P_2026_04_30_HAV_CONV_PT_MDS_Refer_A_Friend in Braze Email Templates.

Uses the HAV color block plain-text template layout.
Run: uv run python scripts/create_hav_conv_refer_a_friend_template.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, init_config

TEMPLATE_NAME = "P_2026_04_30_HAV_CONV_PT_MDS_Refer_A_Friend"
SUBJECT = "Your friends deserve this, too"

BODY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Havenly</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
</head>

<body style="margin: 0; padding: 0; background-color: #f4f4f4;">

  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
         style="max-width: 600px; width: 100%; margin: 0 auto;">

    <!-- Header row: left color bar | olive-gold logo header | right color bar -->
    <tr>
      <td bgcolor="#ed6b4d" width="35" rowspan="3" style="background-color: #ed6b4d;">
        <div style="font-size: 1px; line-height: 1px;">&nbsp;</div>
      </td>

      <td bgcolor="#c2b04a" style="background-color: #c2b04a; padding: 16px 20px;">
        <a href="https://havenly.com/" style="display: block; text-decoration: none;">
          <img src="https://braze-images.com/appboy/communication/assets/image_assets/images/697a85e045042100652b5d66/original.png?1769637344"
               width="120" alt="Havenly"
               style="display: block; max-width: 100%; height: auto;" />
        </a>
      </td>

      <td bgcolor="#e59400" width="35" rowspan="3" style="background-color: #e59400;">
        <div style="font-size: 1px; line-height: 1px;">&nbsp;</div>
      </td>
    </tr>

    <!-- Body row -->
    <tr>
      <td bgcolor="#FFFFFF" width="530"
          style="background-color: #FFFFFF; vertical-align: top;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="padding: 24px 20px 36px 20px; font-family: Helvetica, Arial, sans-serif;
                        font-size: 14px; line-height: 1.5; color: #101b24;">

              <!-- Greeting + Body Copy -->
              <div style="line-height: 1.5; color: #101b24; font-family: Helvetica, Arial, sans-serif; font-size: 14px;">
                <p style="margin: 0 0 16px 0;">Hi {{${first_name} | default: 'there'}},</p>
                <p style="margin: 0 0 16px 0;">Know a friend who loves good design? Share your referral link before Memorial Day and they&#8217;ll get to work with a Havenly designer for $50 off. Once they book, you&#8217;ll get $100 in marketplace credit&#8212;just in time to stack on top of our Memorial Day sale prices.</p>
                <p style="margin: 0 0 8px 0;"><strong>Here&#8217;s how it works:</strong></p>
                <ol style="margin: 0 0 16px 0; padding-left: 20px;">
                  <li style="margin-bottom: 6px;">Share your unique link with a friend</li>
                  <li style="margin-bottom: 6px;">They book with a Havenly designer (at a discounted rate)</li>
                  <li style="margin-bottom: 6px;">You get $100 in marketplace credit once their booking is complete</li>
                </ol>
              </div>

              <!-- CTA Button -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
                     style="margin: 8px 0 24px 0;">
                <tr>
                  <td style="text-align: center;">
                    <a href="https://havenly.com/referral/{{custom_attribute.${referralCode}}}"
                       style="display: inline-block; font-family: Helvetica, Arial, sans-serif;
                              font-size: 18px; line-height: 22px; font-weight: 600;
                              letter-spacing: 0.79px; text-transform: uppercase;
                              color: #FFFFFF; text-decoration: none;
                              border: 2px solid #CD8F52; padding: 14px 32px;
                              background-color: #CD8F52; border-radius: 50px;
                              white-space: nowrap;">
                      SHARE YOUR LINK
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Signoff -->
              <div style="line-height: 1.5; color: #101b24; font-family: Helvetica, Arial, sans-serif; font-size: 14px;">
                <p style="margin: 0;">Happy decorating,<br>
                <strong>The Havenly Team</strong></p>
              </div>

            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- Footer bar: navy with H icon -->
    <tr>
      <td bgcolor="#304561"
          style="background-color: #304561; padding: 28px 20px; text-align: right;">
        <a href="https://havenly.com/" style="display: inline-block; text-decoration: none;">
          <img src="https://braze-images.com/appboy/communication/assets/image_assets/images/697a85e4b446f100635ef81c/original.png?1769637348"
               alt="H" width="40"
               style="display: block; max-width: 100%; height: auto;" />
        </a>
      </td>
    </tr>

  </table>

  <!-- Unsubscribe -->
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
         style="max-width: 600px; width: 100%; margin: 0 auto; background-color: #f4f4f4;">
    <tr>
      <td align="center" style="padding: 8px 20px 4px 20px;
                                  font-family: Helvetica, Arial, sans-serif;
                                  font-size: 12px; color: #666666;">
        {{content_blocks.${unsubscribe} | id: 'cb1'}}
      </td>
    </tr>
  </table>

</body>
</html>"""


def main():
    init_config("HAV")

    template_data = {
        "template_name": TEMPLATE_NAME,
        "subject": SUBJECT,
        "preheader": "",
        "body": BODY_HTML,
        "plaintext_body": (
            "Hi {{${first_name} | default: 'there'}},\n\n"
            "Know a friend who loves good design? Share your referral link before Memorial Day "
            "and they'll get to work with a Havenly designer for $50 off. Once they book, "
            "you'll get $100 in marketplace credit—just in time to stack on top of our "
            "Memorial Day sale prices.\n\n"
            "Here's how it works:\n"
            "1. Share your unique link with a friend\n"
            "2. They book with a Havenly designer (at a discounted rate)\n"
            "3. You get $100 in marketplace credit once their booking is complete\n\n"
            "SHARE YOUR LINK: https://havenly.com/referral/{{custom_attribute.${referralCode}}}\n\n"
            "Happy decorating,\n"
            "The Havenly Team"
        ),
    }

    response, error = braze_post_request("templates/email/create", template_data, "HAV")

    if error:
        print(f"Error: {error}")
        sys.exit(1)

    template_id = response.get("email_template_id") or response.get("id")
    print(f"Created template: {TEMPLATE_NAME}")
    print(f"Template ID: {template_id}")


if __name__ == "__main__":
    main()
