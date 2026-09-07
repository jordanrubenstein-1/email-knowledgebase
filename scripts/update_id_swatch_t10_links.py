#!/usr/bin/env python3
"""Update TRG_EM_2026_04_ID_PT_Swatch_Personalized_T10_V1:
   - Fix 3 copy lines to match Email 3 in doc
   - Add links: larger piece, online, in-store
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from braze_campaign_api import braze_post_request, normalize_brand, init_config
from import_braze import get_api_key, get_base_url
import requests

BRAND = normalize_brand("ID")
TEMPLATE_ID = "a4784a01-8967-4f5f-9048-ea9e7dfe1983"

init_config(BRAND)
headers = {"Authorization": f"Bearer {get_api_key()}"}
base_url = get_base_url().rstrip("/")

resp = requests.get(f"{base_url}/templates/email/info", headers=headers,
    params={"email_template_id": TEMPLATE_ID})
body = resp.json().get("body", "")

# ── Copy fixes ──────────────────────────────────────────────────────────────

body = body.replace(
    "I&#8217;m happy to help you finalize everything",
    "we&#8217;re happy to help you finalize everything"
)
body = body.replace(
    "our design team is always available (online or in-store) at no cost.",
    "our design experts have been in touch and we are always available "
    "(<a href=\"https://www.interiordefine.com#hs-chat-open\">online</a> or "
    "<a href=\"https://www.interiordefine.com/locations\">in-store</a>) at no cost."
)
body = body.replace(
    "I&#8217;d love to help you find the right fit.",
    "we&#8217;d love to connect you with your design expert and help you find the right fit."
)

# ── Link: "larger piece" ─────────────────────────────────────────────────────
body = body.replace(
    "Since this is a larger piece,",
    'Since this is a <a href="https://www.interiordefine.com/living/all">larger piece</a>,'
)

response_data, error = braze_post_request("templates/email/update", {
    "email_template_id": TEMPLATE_ID,
    "body": body,
}, BRAND)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

print("Updated: TRG_EM_2026_04_ID_PT_Swatch_Personalized_T10_V1")
print(f"Template ID: {TEMPLATE_ID}")
print("\nCopy fixes:")
print("  'I'm happy'        → 'we're happy'")
print("  'design team'      → 'design experts have been in touch and we are always available'")
print("  'I'd love to help' → 'we'd love to connect you with your design expert...'")
print("\nLinks added:")
print("  larger piece → interiordefine.com/living/all")
print("  online       → interiordefine.com#hs-chat-open")
print("  in-store     → interiordefine.com/locations")
