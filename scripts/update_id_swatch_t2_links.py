#!/usr/bin/env python3
"""Add Email 1 links to TRG_EM_2026_04_ID_PT_Swatch_Personalized_T2_V1."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import get_api_key, get_base_url
import requests

BRAND = normalize_brand("ID")
TEMPLATE_ID = "61e381cd-d564-4b5e-a7c1-02dde71d0335"

init_config(BRAND)
headers = {"Authorization": f"Bearer {get_api_key()}"}
base_url = get_base_url().rstrip("/")

# Fetch current body
resp = requests.get(f"{base_url}/templates/email/info", headers=headers,
    params={"email_template_id": TEMPLATE_ID})
body = resp.json().get("body", "")

# ---------------------------------------------------------------------------
# Apply links — exact string replacements, everything else unchanged
# ---------------------------------------------------------------------------

# Shopping conditionals
body = body.replace(
    'shopping for a sleeper sofa,',
    'shopping for a <a href="https://www.interiordefine.com/living/all-custom-sofas/custom-sleeper-sofas?page=1">sleeper sofa</a>,'
)
body = body.replace(
    'shopping for a sectional,',
    'shopping for a <a href="https://www.interiordefine.com/living/all-custom-sectionals?page=1">sectional</a>,'
)
body = body.replace(
    'shopping for a sofa,',
    'shopping for a <a href="https://www.interiordefine.com/living/all-custom-sofas?page=1">sofa</a>,'
)
body = body.replace(
    'shopping for a chair or chaise,',
    'shopping for a <a href="https://www.interiordefine.com/living/all-custom-chairs?page=1">chair</a> or <a href="https://www.interiordefine.com/living/all-custom-chairs/custom-chaise-lounges?page=1">chaise</a>,'
)
body = body.replace(
    'shopping for an ottoman,',
    'shopping for an <a href="https://www.interiordefine.com/living/all-custom-ottomans?page=1">ottoman</a>,'
)
body = body.replace(
    'shopping for a bed,',
    'shopping for a <a href="https://www.interiordefine.com/bedroom/all-beds?page=1">bed</a>,'
)
body = body.replace(
    'shopping for dining furniture,',
    'shopping for <a href="https://www.interiordefine.com/dining?page=1">dining furniture</a>,'
)

# Style conditionals
body = body.replace(
    'leaning modern,',
    'leaning <a href="https://www.interiordefine.com/lukas-collection?page=1">modern</a>,'
)
body = body.replace(
    'more classic,',
    'more <a href="https://www.interiordefine.com/sloan-collection?page=1">classic</a>,'
)
body = body.replace(
    'an eclectic look,',
    'an <a href="https://www.interiordefine.com/skylar-collection?page=1">eclectic</a> look,'
)
body = body.replace(
    'a minimalist feel,',
    'a <a href="https://www.interiordefine.com/winslow-collection?page=1">minimalist</a> feel,'
)
body = body.replace(
    'performance fabrics are a great option',
    '<a href="https://www.interiordefine.com/performance-fabrics-guide">performance fabrics</a> are a great option'
)

# Final CTA
body = body.replace(
    'Reach back out anytime',
    '<a href="https://www.interiordefine.com#hs-chat-open">Reach back out</a> anytime'
)

# Push update
response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": TEMPLATE_ID,
    "body": body,
}, BRAND)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

print("Updated: TRG_EM_2026_04_ID_PT_Swatch_Personalized_T2_V1")
print(f"Template ID: {TEMPLATE_ID}")
print("\nLinks added:")
links = [
    ("sleeper sofa", "interiordefine.com/living/all-custom-sofas/custom-sleeper-sofas"),
    ("sectional", "interiordefine.com/living/all-custom-sectionals"),
    ("sofa", "interiordefine.com/living/all-custom-sofas"),
    ("chair / chaise (2 links)", "interiordefine.com/living/all-custom-chairs[/...]"),
    ("ottoman", "interiordefine.com/living/all-custom-ottomans"),
    ("bed", "interiordefine.com/bedroom/all-beds"),
    ("dining furniture", "interiordefine.com/dining"),
    ("modern", "interiordefine.com/lukas-collection"),
    ("classic", "interiordefine.com/sloan-collection"),
    ("eclectic", "interiordefine.com/skylar-collection"),
    ("minimalist", "interiordefine.com/winslow-collection"),
    ("performance fabrics", "interiordefine.com/performance-fabrics-guide"),
    ("Reach back out", "interiordefine.com#hs-chat-open"),
]
for text, url in links:
    print(f"  {text:35s} → {url}")
