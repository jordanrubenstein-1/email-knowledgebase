#!/usr/bin/env python3
"""Update TRG_EM_2026_04_ID_PT_Swatch_Personalized_T12_V1:
   - New subject line matching doc (with corrected Liquid)
   - Add "or chat online" to closing paragraph
   - Add all links from Possible alt email
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import get_api_key, get_base_url
import requests

BRAND = normalize_brand("ID")
TEMPLATE_ID = "2ee2b9de-6088-4db0-a698-8ff5aca9c892"

init_config(BRAND)
headers = {"Authorization": f"Bearer {get_api_key()}"}
base_url = get_base_url().rstrip("/")

resp = requests.get(f"{base_url}/templates/email/info", headers=headers,
    params={"email_template_id": TEMPLATE_ID})
body = resp.json().get("body", "")

# ── Subject line ─────────────────────────────────────────────────────────────
NEW_SUBJECT = (
    "{%- assign shopping = canvas_entry_properties.shopping_for | default: '' -%}"
    "{%- if shopping contains 'Sleeper Sofas' -%}{%- assign item = 'sleeper sofa' -%}"
    "{%- elsif shopping contains 'Sectionals' -%}{%- assign item = 'sectional' -%}"
    "{%- elsif shopping contains 'Sofas' -%}{%- assign item = 'sofa' -%}"
    "{%- elsif shopping contains 'Chairs/Chaises' -%}{%- assign item = 'chair or chaise' -%}"
    "{%- elsif shopping contains 'Ottomans' -%}{%- assign item = 'ottoman' -%}"
    "{%- elsif shopping contains 'Beds' -%}{%- assign item = 'bed' -%}"
    "{%- elsif shopping contains 'Dining' -%}{%- assign item = 'dining furniture' -%}"
    "{%- else -%}{%- assign item = '' -%}{%- endif -%}"
    "{%- if item != '' -%}It&#8217;s time to finalize your {{ item }}"
    "{%- else -%}It&#8217;s time to finalize your piece{%- endif -%}"
)

# ── Copy fix: add "or chat online" to closing paragraph ──────────────────────
body = body.replace(
    'Reply to this email to reconnect',
    'Reply to this email or <a href="https://www.interiordefine.com#hs-chat-open">chat online</a> to reconnect'
)

# ── Shopping conditional links ────────────────────────────────────────────────
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

# ── Style conditional links ───────────────────────────────────────────────────
body = body.replace(
    '<p>Clean silhouettes and simple forms often make',
    '<p><a href="https://www.interiordefine.com/lukas-collection?page=1">Clean silhouettes and simple forms</a> often make'
)
body = body.replace(
    '<p>Timeless shapes and fabrics tend to',
    '<p><a href="https://www.interiordefine.com/sloan-collection?page=1">Timeless shapes and fabrics</a> tend to'
)
body = body.replace(
    'can add personality to your space.',
    'can add <a href="https://www.interiordefine.com/skylar-collection?page=1">personality</a> to your space.'
)
body = body.replace(
    '<p>Simple, uncluttered forms',
    '<p><a href="https://www.interiordefine.com/winslow-collection?page=1">Simple</a>, uncluttered forms'
)
body = body.replace(
    '<p>Performance fabrics are designed to handle everyday life',
    '<p><a href="https://www.interiordefine.com/performance-fabrics-guide">Performance fabrics</a> are designed to handle everyday life'
)

response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": TEMPLATE_ID,
    "subject": NEW_SUBJECT,
    "body": body,
}, BRAND)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

print("Updated: TRG_EM_2026_04_ID_PT_Swatch_Personalized_T12_V1")
print(f"Template ID: {TEMPLATE_ID}")
print("\nSubject: It's time to finalize your {{ item }} (with fallback 'piece')")
print("\nCopy fix:")
print("  Added 'or chat online' (linked) to closing paragraph")
print("\nLinks added: 8 shopping + 5 style + 1 closing = 14 total")
