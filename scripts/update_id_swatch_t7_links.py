#!/usr/bin/env python3
"""Add Email 2 links to TRG_EM_2026_04_ID_PT_Swatch_Personalized_T7_V1."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import get_api_key, get_base_url
import requests

BRAND = normalize_brand("ID")
TEMPLATE_ID = "3df4899e-647d-4bdd-a10d-a8b43f2f5b1d"

init_config(BRAND)
headers = {"Authorization": f"Bearer {get_api_key()}"}
base_url = get_base_url().rstrip("/")

resp = requests.get(f"{base_url}/templates/email/info", headers=headers,
    params={"email_template_id": TEMPLATE_ID})
body = resp.json().get("body", "")

# Shopping conditionals — link the opening word of each sentence
body = body.replace(
    '<p>Sectionals can be especially tricky',
    '<p><a href="https://www.interiordefine.com/living/all-custom-sectionals?page=1">Sectionals</a> can be especially tricky'
)
body = body.replace(
    '<p>Sofas tend to set the tone',
    '<p><a href="https://www.interiordefine.com/living/all-custom-sofas?page=1">Sofas</a> tend to set the tone'
)
body = body.replace(
    '<p>Beds are such a focal point',
    '<p><a href="https://www.interiordefine.com/bedroom/all-beds?page=1">Beds</a> are such a focal point'
)

# Style conditionals — link the style word inline
body = body.replace(
    'With a modern style,',
    'With a <a href="https://www.interiordefine.com/lukas-collection?page=1">modern</a> style,'
)
body = body.replace(
    'With an eclectic style,',
    'With an <a href="https://www.interiordefine.com/skylar-collection?page=1">eclectic style</a>,'
)
body = body.replace(
    'With a minimalist approach,',
    'With a <a href="https://www.interiordefine.com/winslow-collection?page=1">minimalist</a> approach,'
)

# CTA — link "designers"
body = body.replace(
    'this is exactly where our designers can help.',
    'this is exactly where our <a href="https://www.interiordefine.com#hs-chat-open">designers</a> can help.'
)

response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": TEMPLATE_ID,
    "body": body,
}, BRAND)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

print("Updated: TRG_EM_2026_04_ID_PT_Swatch_Personalized_T7_V1")
print(f"Template ID: {TEMPLATE_ID}")
print("\nLinks added:")
links = [
    ("Sectionals",   "interiordefine.com/living/all-custom-sectionals"),
    ("Sofas",        "interiordefine.com/living/all-custom-sofas"),
    ("Beds",         "interiordefine.com/bedroom/all-beds"),
    ("modern",       "interiordefine.com/lukas-collection"),
    ("eclectic style","interiordefine.com/skylar-collection"),
    ("minimalist",   "interiordefine.com/winslow-collection"),
    ("designers",    "interiordefine.com#hs-chat-open"),
]
for text, url in links:
    print(f"  {text:20s} → {url}")
