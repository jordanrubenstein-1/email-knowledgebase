#!/usr/bin/env python3
"""Build HAV PT Welcome Gift — Test B, Day 40 template."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, init_config

TEMPLATE_NAME = "TRG_EM_2026_06_HAV_CONV_PT_Welcome_Gift_T4_V1_B"
SUBJECT = "Last chance: your Havenly offer expires today"

BASE_DIR = Path(__file__).parent.parent
TEMPLATE_PATH = BASE_DIR / "components" / "hav_pt_template.html"

# Day 40 — offer expires today, no offset
BODY_HTML = """\
          <p style="margin:0;margin-bottom:0;">Today is the last day to use your shopping offer &mdash; don&rsquo;t let it slip away!</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;"><strong>Use code 100OFF for $100 off your first purchase of $1,000 or more.</strong></p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">Your dream space is within reach. Now&rsquo;s the perfect time to complete your room and make it yours.</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">{% if {{custom_attribute.${last_stage}}} == 'design_process complete' %}<a href="https://havenly.com/shop-my-room" style="color:#0000EE;text-decoration:underline;">Start shopping &rarr;</a>{% else %}<a href="https://havenly.com/shop" style="color:#0000EE;text-decoration:underline;">Start shopping &rarr;</a>{% endif %}</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          {% assign today_ts = 'now' | date: '%s' %}{% assign today_day = today_ts | date: '%-d' | plus: 0 %}{% assign today_month = today_ts | date: '%B' %}{% assign mod10 = today_day | modulo: 10 %}{% assign mod100 = today_day | modulo: 100 %}{% if mod100 >= 11 and mod100 <= 13 %}{% assign suffix = 'th' %}{% elsif mod10 == 1 %}{% assign suffix = 'st' %}{% elsif mod10 == 2 %}{% assign suffix = 'nd' %}{% elsif mod10 == 3 %}{% assign suffix = 'rd' %}{% else %}{% assign suffix = 'th' %}{% endif %}<p style="margin:0;margin-bottom:0;">Offer valid until {{ today_month }} {{ today_day }}{{ suffix }} for eligible customers only and cannot be combined with other promotions.</p>"""

SIGNOFF_HTML = """\
          <p style="margin:0;margin-bottom:0;">Thanks,</p>
          <p style="margin:0;margin-bottom:0;">Lisa</p>
          <p style="margin:0;margin-bottom:0;">Head of Customer Experience</p>"""


def build_html() -> str:
    base = TEMPLATE_PATH.read_text()
    base = base.replace("<!-- BODY_CONTENT -->", BODY_HTML)
    base = base.replace("<!-- SIGNOFF -->", SIGNOFF_HTML)
    # Not a sale send -- strip the optional disclaimer row entirely
    start = base.find("<!-- BEGIN_DISCLAIMER_ROW -->")
    end = base.find("<!-- END_DISCLAIMER_ROW -->")
    if start >= 0 and end >= 0:
        end += len("<!-- END_DISCLAIMER_ROW -->")
        base = base[:start] + base[end:]
    return base


def main():
    brand = "HAV"
    init_config(brand)
    html = build_html()
    payload = {"template_name": TEMPLATE_NAME, "subject": SUBJECT, "preheader": "", "body": html}
    print(f"Creating template: {TEMPLATE_NAME}")
    response, error = braze_post_request("templates/email/create", payload, brand)
    if error:
        print(f"ERROR: {error}")
        sys.exit(1)
    template_id = (response or {}).get("email_template_id") or (response or {}).get("id")
    print(f"SUCCESS — template_id: {template_id}")


if __name__ == "__main__":
    main()
