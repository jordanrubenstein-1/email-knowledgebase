#!/usr/bin/env python3
"""Update TRG_EM_2026_04_ID_PT_Swatch_Personalized_T2_V1:
   - Fix event_properties → canvas_entry_properties
   - Fix subject line to use singular item names
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import get_api_key, get_base_url
import requests

BRAND = normalize_brand("ID")
TEMPLATE_ID = "61e381cd-d564-4b5e-a7c1-02dde71d0335"

init_config(BRAND)

# Fetch current body
headers = {"Authorization": f"Bearer {get_api_key()}"}
base_url = get_base_url().rstrip("/")
resp = requests.get(f"{base_url}/templates/email/info",
    headers=headers,
    params={"email_template_id": TEMPLATE_ID})
current_body = resp.json().get("body", "")

# Fix body: swap event_properties → canvas_entry_properties
new_body = current_body.replace("event_properties.", "canvas_entry_properties.")

# New subject line — singular item map, Sleeper Sofas before Sofas to avoid partial match
NEW_SUBJECT = (
    "{%- assign shopping = canvas_entry_properties.shopping_for | default: '' -%}"
    "{%- if shopping contains 'Sleeper Sofas' -%}{%- assign item = 'sleeper sofa' -%}"
    "{%- elsif shopping contains 'Sectionals' -%}{%- assign item = 'sectional' -%}"
    "{%- elsif shopping contains 'Sofas' -%}{%- assign item = 'sofa' -%}"
    "{%- elsif shopping contains 'Chairs/Chaises' -%}{%- assign item = 'chair or chaise' -%}"
    "{%- elsif shopping contains 'Ottomans' -%}{%- assign item = 'ottoman' -%}"
    "{%- elsif shopping contains 'Beds' -%}{%- assign item = 'bed' -%}"
    "{%- elsif shopping contains 'Dining' -%}{%- assign item = 'dining furniture' -%}"
    "{%- else -%}{%- assign item = '' -%}"
    "{%- endif -%}"
    "{%- if item != '' -%}Found \"the one\" for your {{ item }}?"
    "{%- else -%}Found \"the one\" for your space?{%- endif -%}"
)

response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": TEMPLATE_ID,
    "subject": NEW_SUBJECT,
    "body": new_body,
}, BRAND)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

print("Updated: TRG_EM_2026_04_ID_PT_Swatch_Personalized_T2_V1")
print(f"  Template ID: {TEMPLATE_ID}")
print()
print("Subject line examples:")
examples = [
    ("Sleeper Sofas", "sleeper sofa"),
    ("Sectionals",    "sectional"),
    ("Sofas",         "sofa"),
    ("Chairs/Chaises","chair or chaise"),
    ("Ottomans",      "ottoman"),
    ("Beds",          "bed"),
    ("Dining",        "dining furniture"),
    ("(blank)",       "(fallback) space"),
]
for raw, rendered in examples:
    print(f'  {raw:20s} → Found "the one" for your {rendered}?')
