#!/usr/bin/env python3
"""Find TRG_EM_2026_04_ID_PT_Swatch_Personalized_T2_V1 and update its subject line."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import requests
from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import init_config as _init, get_api_key, get_base_url

BRAND = normalize_brand("ID")
TARGET_NAME = "TRG_EM_2026_04_ID_PT_Swatch_Personalized_T2_V1"

init_config(BRAND)
api_key = get_api_key()
base_url = get_base_url().rstrip("/")
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

# List templates and find by name (GET endpoint)
resp = requests.get(f"{base_url}/templates/email/list", headers=headers, params={"count": 100})
resp.raise_for_status()
templates = resp.json().get("templates", [])

match = next((t for t in templates if t.get("template_name") == TARGET_NAME), None)

if not match:
    print(f"Template not found: {TARGET_NAME}")
    print("Swatch/T2 templates found:")
    for t in templates:
        if "Swatch" in t.get("template_name", "") or "T2" in t.get("template_name", ""):
            print(f"  {t['template_name']} — {t.get('email_template_id') or t.get('id')}")
    sys.exit(1)

template_id = match.get("email_template_id") or match.get("id")
print(f"Found: {TARGET_NAME}")
print(f"  Template ID: {template_id}")

# New subject line with fallback
new_subject = (
    "{%- assign shopping = event_properties.shopping_for | default: '' -%}"
    "{%- if shopping != '' -%}Found \"the one\" for your {{shopping | downcase}}?"
    "{%- else -%}Found \"the one\" for your space?{%- endif -%}"
)

response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": template_id,
    "subject": new_subject,
}, BRAND)

if error:
    print(f"ERROR updating: {error}")
    sys.exit(1)

print("Subject line updated successfully!")
print(f"  With value:    Found \"the one\" for your {{shopping | downcase}}?")
print(f"  Without value: Found \"the one\" for your space?")
