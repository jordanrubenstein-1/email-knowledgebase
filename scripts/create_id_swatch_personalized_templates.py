#!/usr/bin/env python3
"""
Create two ID plain-text email templates in Braze:
  - TRG_EM_2026_04_ID_PT_Swatch_Personalized_T7_V1
  - TRG_EM_2026_04_ID_PT_Swatch_Personalized_T10_V1
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config

BRAND = normalize_brand("ID")

FOOTER = """<p>Copyright &copy; {{ 'now' | date: '%Y' }}, Interior Define, All rights reserved.<br>
3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209</p>

<p>If you would rather not receive future emails from us, you may <a href="{{${set_user_to_unsubscribed_url}}}" style="color:#1871D8;text-decoration:underline;">unsubscribe</a>.</p>"""


def wrap_html(body_content: str, footer_content: str) -> str:
    return f"""<!DOCTYPE html>
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

{body_content}

</td></tr>
<tr><td style="color:#101b24;font-family:Arial,sans-serif;font-size:9px;font-weight:400;line-height:normal;text-align:left;">

{footer_content}

</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def create_or_update(name: str, subject: str, preheader: str, body_html: str,
                     existing_id: str = None) -> None:
    init_config(BRAND)
    payload = {
        "template_name": name,
        "subject": subject,
        "preheader": preheader,
        "body": body_html,
    }
    if existing_id:
        payload["email_template_id"] = existing_id
        endpoint = "templates/email/update"
        verb = "Updated"
    else:
        endpoint = "templates/email/create"
        verb = "Created"

    response_data, error = braze_post_request(endpoint, payload, BRAND)
    if error:
        print(f"ERROR ({name}): {error}")
        sys.exit(1)

    template_id = (
        existing_id
        or response_data.get("email_template_id")
        or response_data.get("id")
    )
    print(f"{verb}: {name}")
    print(f"  Template ID: {template_id}\n")


# ---------------------------------------------------------------------------
# T7 — TRG_EM_2026_04_ID_PT_Swatch_Personalized_T7_V1
# ---------------------------------------------------------------------------
T7_SUBJECT = (
    "{%- assign style = canvas_entry_properties.design_style | default: '' -%}"
    "{%- if style != '' -%}Your {{style | downcase}} space is coming together"
    "{%- else -%}Your space is coming together{%- endif -%}"
)

T7_BODY = """\
{%- assign shopping = canvas_entry_properties.shopping_for | default: "" -%}
{%- assign style = canvas_entry_properties.design_style | default: "" -%}

<p>Hi {{${first_name} | default: 'there'}},</p>

<p>Now that you&#8217;ve had a chance to see your swatches at home, you&#8217;re probably starting to get a feel for what works (and what doesn&#8217;t).</p>

{% if shopping contains "Sectionals" %}
<p>Sectionals can be especially tricky since they anchor the whole room.</p>
{% elsif shopping contains "Sofas" %}
<p>Sofas tend to set the tone for the entire space, so it&#8217;s worth getting the fabric just right.</p>
{% elsif shopping contains "Beds" %}
<p>Beds are such a focal point &#8212; the fabric you choose really shapes the overall feel of the room.</p>
{% endif %}

{% if style contains "Modern" %}
<p>With a modern style, small differences in texture or tone can completely change the look.</p>
{% elsif style contains "Eclectic" %}
<p>With an eclectic style, it&#8217;s all about finding the right balance between statement and cohesion.</p>
{% elsif style contains "Minimalist" %}
<p>With a minimalist approach, the right fabric can make the entire space feel more intentional.</p>
{% endif %}

<p>If you&#8217;re unsure between a few options, this is exactly where our designers can help.</p>

<p>We offer free design support &#8212; they can:</p>
<ul style="margin: 0 0 14px 0; padding-left: 20px; line-height: 1.5;">
<li style="margin: 0 0 5px 0;">Review your swatches with you</li>
<li style="margin: 0 0 5px 0;">Recommend the best fabric for your lifestyle</li>
<li style="margin: 0 0 5px 0;">Help you visualize the full piece in your space</li>
</ul>

<p>You can connect with them online or visit one of our studios, whichever is easier.</p>

<p>Want me to set that up for you?</p>

<p>Best,<br>The Interior Define Team</p>"""

# ---------------------------------------------------------------------------
# T10 — TRG_EM_2026_04_ID_PT_Swatch_Personalized_T10_V1
# ---------------------------------------------------------------------------
T10_SUBJECT = (
    "{%- assign shopping = canvas_entry_properties.shopping_for | default: '' -%}"
    "{%- if shopping != '' -%}Want help choosing the right {{shopping | downcase}}?"
    "{%- else -%}Want help choosing the right piece?{%- endif -%}"
)

T10_BODY = """\
{%- assign shopping = canvas_entry_properties.shopping_for | default: "" -%}
{%- assign style = canvas_entry_properties.design_style | default: "" -%}

<p>Hi {{${first_name} | default: 'there'}},</p>

<p>Just checking in &#8212; have you had a chance to look through your swatches in your space yet?</p>

<p>A quick tip:<br>
Try narrowing it down to your top 2&#8211;3 favorites and look at them at different times of day. Lighting can completely change how a fabric feels.</p>

{% if style contains "Family-Friendly" %}
<p>If durability is important, this is also a great time to think about performance fabrics &#8212; they&#8217;re designed to handle everyday life.</p>
{% endif %}

{% if shopping contains "Sofas" or shopping contains "Sectionals" %}
<p>Since this is a larger piece, getting the fabric right now makes a huge difference long-term.</p>
{% endif %}

<p>If you&#8217;re close to deciding, I&#8217;m happy to help you finalize everything &#8212; or answer any last questions.</p>

<p>And if you want a bit more guidance, our design team is always available (online or in-store) at no cost.</p>

<p>Just reply here &#8212; I&#8217;d love to help you find the right fit.</p>

<p>Best,<br>The Interior Define Team</p>"""

# ---------------------------------------------------------------------------
# Create both templates
# ---------------------------------------------------------------------------
create_or_update(
    name="TRG_EM_2026_04_ID_PT_Swatch_Personalized_T7_V1",
    subject=T7_SUBJECT,
    preheader="",
    body_html=wrap_html(T7_BODY, FOOTER),
    existing_id="3df4899e-647d-4bdd-a10d-a8b43f2f5b1d",
)

create_or_update(
    name="TRG_EM_2026_04_ID_PT_Swatch_Personalized_T10_V1",
    subject=T10_SUBJECT,
    preheader="",
    body_html=wrap_html(T10_BODY, FOOTER),
    existing_id="a4784a01-8967-4f5f-9048-ea9e7dfe1983",
)

print("Done.")
