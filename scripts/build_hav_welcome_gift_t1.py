#!/usr/bin/env python3
"""
Build HAV PT Welcome Gift Email — Test A, Day 1 template.
Creates an Email Template in the Havenly Braze workspace.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, init_config

TEMPLATE_NAME = "TRG_EM_2026_06_HAV_CONV_PT_Welcome_Gift_T1_V1_A"
SUBJECT = "Welcome — here's a little gift to get you started ✨"

BASE_DIR = Path(__file__).parent.parent
TEMPLATE_PATH = BASE_DIR / "components" / "hav_pt_template.html"

# ── Body content (goes after greeting, before signoff) ──────────────────────
BODY_HTML = """\
          <p style="margin:0;margin-bottom:0;">Welcome to Havenly, we&rsquo;re so excited to help you bring your space to life!</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">Your designer is ready to help you find pieces you&rsquo;ll love. {% if {{custom_attribute.${last_stage}}} != 'launch_room' and {{custom_attribute.${last_stage}}} != 'design_process_complete' %}We recommend <a href="https://havenly.com/rooms" style="color:#0000EE;text-decoration:underline;">completing your room profile</a> and scheduling time with them soon. {% endif %}They&rsquo;ll guide you through the process and help you pick the perfect items for your space.</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">And when you&rsquo;re ready to make your first purchase, we have a little something for you:</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">Use code GETSTARTED for <strong>10% off your first purchase</strong>.</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">Hold onto this &mdash; it&rsquo;ll be waiting for you when you&rsquo;re ready to shop. No rush!</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          <p style="margin:0;margin-bottom:0;">{% if {{custom_attribute.${last_stage}}} == 'design_process complete' %}<a href="https://havenly.com/shop-my-room" style="color:#0000EE;text-decoration:underline;">Start shopping &rarr;</a>{% else %}<a href="https://havenly.com/shop" style="color:#0000EE;text-decoration:underline;">Start shopping &rarr;</a>{% endif %}</p>
          <p style="margin:0;margin-bottom:0;">&nbsp;</p>
          {% assign future_ts = 'now' | date: '%s' | plus: 3369600 %}{% assign future_day = future_ts | date: '%-d' | plus: 0 %}{% assign future_month = future_ts | date: '%B' %}{% assign mod10 = future_day | modulo: 10 %}{% assign mod100 = future_day | modulo: 100 %}{% if mod100 >= 11 and mod100 <= 13 %}{% assign suffix = 'th' %}{% elsif mod10 == 1 %}{% assign suffix = 'st' %}{% elsif mod10 == 2 %}{% assign suffix = 'nd' %}{% elsif mod10 == 3 %}{% assign suffix = 'rd' %}{% else %}{% assign suffix = 'th' %}{% endif %}<p style="margin:0;margin-bottom:0;">Offer valid until {{ future_month }} {{ future_day }}{{ suffix }} for eligible customers only and cannot be combined with other promotions.</p>"""

# ── Signoff (as provided) ────────────────────────────────────────────────────
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

    payload = {
        "template_name": TEMPLATE_NAME,
        "subject": SUBJECT,
        "preheader": "",
        "body": html,
    }

    print(f"Creating template: {TEMPLATE_NAME}")
    response, error = braze_post_request("templates/email/create", payload, brand)

    if error:
        print(f"ERROR: {error}")
        sys.exit(1)

    template_id = (response or {}).get("email_template_id") or (response or {}).get("id")
    print(f"SUCCESS — template_id: {template_id}")
    print(f"Name: {TEMPLATE_NAME}")
    print(f"Subject: {SUBJECT}")


if __name__ == "__main__":
    main()
