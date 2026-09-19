#!/usr/bin/env python3
"""
Update the Burrow "Dining Chair Recommendation" email template in BUR Braze.

Replaces canvas_entry_properties.${rec_*} and canvas_entry_properties.${product_name}
references (which cannot be populated from a purchase event trigger) with Liquid assign
blocks keyed on canvas_entry_properties.${product_id}.

Branches on 8 table variants (4 tables × 2 finishes). Chair recs are data-driven from
co-purchase analysis — top 4 chair/colorway combos by order count, always matching the
table's wood finish.

Template ID: 012c1de2-29be-4751-91be-28ff4324c94b
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, init_config
from import_braze import get_base_url, get_api_key, init_config as _init
import requests

TEMPLATE_ID = "012c1de2-29be-4751-91be-28ff4324c94b"
TEMPLATE_NAME = "TRG_EM_2026_06_BW_D_Dining_Chair_Recommendation_T1_V1"

IMG_BASE = "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/"

HAIKU_URL = "https://burrow.com/dining/haiku-dining-chairs?sku="
ALTO_URL = "https://burrow.com/dining/alto-dining-chairs?sku="

# Shopify CDN image filenames per SKU.
# Haiku images are .jpg; Alto images are .webp.
# Note: .webp may not render in Outlook desktop — upload to Braze CDN if Outlook support is needed.
IMGS = {
    "DRST-DC-HKU-S2-PYOK": IMG_BASE + "DRST-DC-HKU-S2-PYOK.jpg?v=1744521831",
    "DRST-DC-HKU-S2-MGOK": IMG_BASE + "DRST-DC-HKU-S2-MGOK.jpg?v=1744521806",
    "DRST-DC-HKU-S2-TNOK": IMG_BASE + "DRST-DC-HKU-S2-TNOK.jpg?v=1744521868",
    "DRST-DC-HKU-S2-MGWN": IMG_BASE + "DRST-DC-HKU-S2-MGWN.jpg?v=1744521819",
    "DRST-DC-HKU-S2-SGWN": IMG_BASE + "DRST-DC-HKU-S2-SGWN.jpg?v=1744521855",
    "DRST-DC-HKU-S2-PYWN": IMG_BASE + "DRST-DC-HKU-S2-PYWN.jpg?v=1744521844",
    "DRST-DC-ALT-S2-MGOK": IMG_BASE + "DRST-DC-ALT-S2-MGOK.webp?v=1747772306",
    "DRST-DC-ALT-S2-PYOK": IMG_BASE + "DRST-DC-ALT-S2-PYOK.webp?v=1747772371",
    "DRST-DC-ALT-S2-MGWN": IMG_BASE + "DRST-DC-ALT-S2-MGWN.webp?v=1747772332",
    "DRST-DC-ALT-S2-PYWN": IMG_BASE + "DRST-DC-ALT-S2-PYWN.webp?v=1747772360",
    "DRST-DC-ALT-S2-SGWN": IMG_BASE + "DRST-DC-ALT-S2-SGWN.webp?v=1747772278",
}


def rec(slot_num, label, sku, chair="haiku"):
    """Build Liquid assign lines for one rec slot."""
    url_base = HAIKU_URL if chair == "haiku" else ALTO_URL
    lines = [
        f"  {{%- assign rec_{slot_num}_name = '{label}' -%}}",
        f"  {{%- assign rec_{slot_num}_img = '{IMGS[sku]}' -%}}",
        f"  {{%- assign rec_{slot_num}_url = '{url_base}{sku}' -%}}",
    ]
    return "\n".join(lines)


# Data-driven recs per table variant (from co-purchase analysis, Jul 2024–present)
BRANCHES = [
    # Serif + Walnut (most data: 386 co-orders in top 4)
    ("Serif", "Walnut", "Serif Extendable Dining Table", [
        rec(1, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGWN"),
        rec(2, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGWN", "alto"),
        rec(3, "Haiku Dining Chairs (Stone Grey)", "DRST-DC-HKU-S2-SGWN"),
        rec(4, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYWN"),
    ]),
    # Serif + Oak (163 co-orders in top 4)
    ("Serif", "Oak", "Serif Extendable Dining Table", [
        rec(1, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYOK"),
        rec(2, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGOK"),
        rec(3, "Haiku Dining Chairs (Camel Leather)", "DRST-DC-HKU-S2-TNOK"),
        rec(4, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGOK", "alto"),
    ]),
    # Listo + Walnut (83 co-orders)
    ("Listo", "Walnut", "Listo Extendable Dining Table", [
        rec(1, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGWN"),
        rec(2, "Alto Dining Chairs (Papyrus)", "DRST-DC-ALT-S2-PYWN", "alto"),
        rec(3, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGWN", "alto"),
        rec(4, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYWN"),
    ]),
    # Listo + Oak (71 co-orders)
    ("Listo", "Oak", "Listo Extendable Dining Table", [
        rec(1, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGOK", "alto"),
        rec(2, "Haiku Dining Chairs (Camel Leather)", "DRST-DC-HKU-S2-TNOK"),
        rec(3, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGOK"),
        rec(4, "Alto Dining Chairs (Papyrus)", "DRST-DC-ALT-S2-PYOK", "alto"),
    ]),
    # Harvest + Walnut (86 co-orders)
    ("Harvest", "Walnut", "Harvest Extendable Dining Table", [
        rec(1, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGWN"),
        rec(2, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYWN"),
        rec(3, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGWN", "alto"),
        rec(4, "Alto Dining Chairs (Papyrus)", "DRST-DC-ALT-S2-PYWN", "alto"),
    ]),
    # Harvest + Oak (71 co-orders)
    ("Harvest", "Oak", "Harvest Extendable Dining Table", [
        rec(1, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGOK"),
        rec(2, "Haiku Dining Chairs (Camel Leather)", "DRST-DC-HKU-S2-TNOK"),
        rec(3, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYOK"),
        rec(4, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGOK", "alto"),
    ]),
    # Gallery + Walnut (limited data; substituting Alto for Sonnet)
    ("Gallery", "Walnut", "Gallery Dining Table", [
        rec(1, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYWN"),
        rec(2, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGWN"),
        rec(3, "Alto Dining Chairs (Stone Grey)", "DRST-DC-ALT-S2-SGWN", "alto"),
        rec(4, "Alto Dining Chairs (Papyrus)", "DRST-DC-ALT-S2-PYWN", "alto"),
    ]),
    # Gallery + Oak (limited data; substituting Alto for Sonnet)
    ("Gallery", "Oak", "Gallery Dining Table", [
        rec(1, "Haiku Dining Chairs (Camel Leather)", "DRST-DC-HKU-S2-TNOK"),
        rec(2, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGOK"),
        rec(3, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGOK", "alto"),
        rec(4, "Alto Dining Chairs (Papyrus)", "DRST-DC-ALT-S2-PYOK", "alto"),
    ]),
]


def build_liquid_block():
    """Build the full Liquid assign block for all 8 table variants."""
    lines = []
    for i, (table, finish, display_name, recs) in enumerate(BRANCHES):
        # Walnut check comes before Oak (Oak is the else/fallback per table)
        if finish == "Walnut":
            cond = (
                f"{{% if canvas_entry_properties.${{product_id}} contains '{table}'"
                f" and canvas_entry_properties.${{product_id}} contains 'Walnut' %}}"
            )
        else:
            # Oak: any remaining match for this table (includes Oak and bare names)
            if i == 0:
                cond = f"{{% if canvas_entry_properties.${{product_id}} contains '{table}' %}}"
            else:
                # Find if there's a Walnut branch for the same table already emitted
                cond = f"{{% elsif canvas_entry_properties.${{product_id}} contains '{table}' %}}"

        lines.append(cond)
        lines.append(f"  {{%- assign table_name = '{display_name}' -%}}")
        for r in recs:
            lines.append(r)

    lines.append("{% else %}")
    lines.append("  {%- assign table_name = 'dining table' -%}")
    # Fallback: Serif Walnut recs (most popular overall)
    lines.append(rec(1, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGWN"))
    lines.append(rec(2, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGWN", "alto"))
    lines.append(rec(3, "Haiku Dining Chairs (Stone Grey)", "DRST-DC-HKU-S2-SGWN"))
    lines.append(rec(4, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYWN"))
    lines.append("{% endif %}")

    return "\n".join(lines)


def build_if_elif_block():
    """Build a clean if/elsif chain (Walnut check before Oak per table)."""
    lines = []
    first = True
    for table, finish, display_name, recs in BRANCHES:
        if finish == "Walnut":
            cond = (
                f"  canvas_entry_properties.${{product_id}} contains '{table}'"
                f" and canvas_entry_properties.${{product_id}} contains 'Walnut'"
            )
        else:
            cond = f"  canvas_entry_properties.${{product_id}} contains '{table}'"

        if first:
            lines.append(f"{{% if {cond.strip()} %}}")
            first = False
        else:
            lines.append(f"{{% elsif {cond.strip()} %}}")

        lines.append(f"  {{%- assign table_name = '{display_name}' -%}}")
        for r in recs:
            lines.append(r)

    lines.append("{% else %}")
    lines.append("  {%- assign table_name = 'dining table' -%}")
    lines.append(rec(1, "Haiku Dining Chairs (Moss Green)", "DRST-DC-HKU-S2-MGWN"))
    lines.append(rec(2, "Alto Dining Chairs (Moss Green)", "DRST-DC-ALT-S2-MGWN", "alto"))
    lines.append(rec(3, "Haiku Dining Chairs (Stone Grey)", "DRST-DC-HKU-S2-SGWN"))
    lines.append(rec(4, "Haiku Dining Chairs (Papyrus)", "DRST-DC-HKU-S2-PYWN"))
    lines.append("{% endif %}")

    return "\n".join(lines)


LIQUID_BLOCK = build_if_elif_block()

# Substitution map: old canvas_entry_properties ref → new Liquid variable
BODY_SUBS = {
    "{{canvas_entry_properties.${product_name}}}": "{{table_name}}",
    "{{canvas_entry_properties.${rec_1_image_url}}}": "{{rec_1_img}}",
    "{{canvas_entry_properties.${rec_1_name}}}": "{{rec_1_name}}",
    "{{canvas_entry_properties.${rec_1_url}}}": "{{rec_1_url}}",
    "{{canvas_entry_properties.${rec_2_image_url}}}": "{{rec_2_img}}",
    "{{canvas_entry_properties.${rec_2_name}}}": "{{rec_2_name}}",
    "{{canvas_entry_properties.${rec_2_url}}}": "{{rec_2_url}}",
    "{{canvas_entry_properties.${rec_3_image_url}}}": "{{rec_3_img}}",
    "{{canvas_entry_properties.${rec_3_name}}}": "{{rec_3_name}}",
    "{{canvas_entry_properties.${rec_3_url}}}": "{{rec_3_url}}",
    "{{canvas_entry_properties.${rec_4_image_url}}}": "{{rec_4_img}}",
    "{{canvas_entry_properties.${rec_4_name}}}": "{{rec_4_name}}",
    "{{canvas_entry_properties.${rec_4_url}}}": "{{rec_4_url}}",
}

NEW_SUBJECT = "The right seats for your {{table_name}}"


def fetch_template():
    """Fetch the current template from Braze."""
    r = requests.get(
        f"{get_base_url()}/templates/email/info",
        params={"email_template_id": TEMPLATE_ID},
        headers={"Authorization": f"Bearer {get_api_key()}"},
    )
    r.raise_for_status()
    return r.json()


def patch_html(html):
    """Inject Liquid block and replace canvas_entry_properties refs in HTML body."""
    # Inject after <body ...> opening tag
    body_tag_end = html.find(">", html.find("<body"))
    if body_tag_end == -1:
        raise ValueError("Could not find <body> tag in template HTML")

    inject_point = body_tag_end + 1
    html = html[:inject_point] + "\n\n" + LIQUID_BLOCK + "\n\n" + html[inject_point:]

    for old, new in BODY_SUBS.items():
        html = html.replace(old, new)

    return html


def patch_plaintext(pt):
    """Replace canvas_entry_properties refs in plaintext body."""
    for old, new in BODY_SUBS.items():
        # Plaintext uses same variable names; img isn't in plaintext so it's a no-op
        pt = pt.replace(old, new)
    return pt


def main(dry_run=False):
    init_config("BUR")

    print("Fetching current template...")
    tpl = fetch_template()
    current_subject = tpl.get("subject", "")
    current_html = tpl.get("body", "")
    current_pt = tpl.get("plaintext_body", "")

    print(f"  Current subject: {current_subject}")

    new_html = patch_html(current_html)
    new_pt = patch_plaintext(current_pt)

    # Verify subs applied
    remaining = [old for old in BODY_SUBS if old in new_html or old in new_pt]
    if remaining:
        print(f"WARNING: Some refs not replaced: {remaining}")

    if dry_run:
        print("\n--- DRY RUN ---")
        print("Subject:", NEW_SUBJECT)
        print("Liquid block injected:")
        print(LIQUID_BLOCK[:500], "...")
        print("Substitutions applied:", list(BODY_SUBS.keys()))
        print("Remaining refs:", remaining)
        return

    payload = {
        "email_template_id": TEMPLATE_ID,
        "template_name": TEMPLATE_NAME,
        "subject": NEW_SUBJECT,
        "body": new_html,
        "plaintext_body": new_pt,
    }

    print("\nUpdating template in Braze...")
    data, err = braze_post_request("templates/email/update", payload, brand="BUR")
    if err:
        print(f"ERROR: {err}")
        return

    print(f"✓ Template updated successfully")
    print(f"  Template ID: {TEMPLATE_ID}")
    print(f"  New subject: {NEW_SUBJECT}")
    print()
    print("Next steps:")
    print("  1. Preview template in Braze UI with a test user who purchased a Serif/Walnut table")
    print("  2. Verify {{table_name}} renders as 'Serif Extendable Dining Table'")
    print("  3. Verify rec_1–rec_4 images and names render for that variant")
    print("  4. Check all 8 branches by adjusting the test purchase event property")
    print("  5. Note: Alto images are .webp — may not render in Outlook desktop.")
    print("     Upload to Braze CDN if Outlook support is required.")


if __name__ == "__main__":
    import sys
    main(dry_run="--dry-run" in sys.argv)
