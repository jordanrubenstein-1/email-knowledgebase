"""
Example: Interior Define Cart Abandonment T1

Demonstrates how to assemble a trigger email from component blocks.
Run with: uv run python scripts/email_previews/build_example_cart_abandon_t1.py
Then open: scripts/email_previews/cart_abandon_t1.html
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.build_id_email import build_email

html = build_email(
    preheader="Your sofa is still waiting — plus, order free swatches to find your perfect fabric.",
    blocks=[
        # ── Logo bar ──────────────────────────────────────────────────────────
        {"block": "logo_bar"},

        # ── Hero: full-bleed background image with headline + CTA ─────────────
        {
            "block": "hero_full",
            "preset": "default_dark",   # btn = off-white on dark bg
            "image_url": "https://e.hypermatic.com/149a5ae68d7d60926a53a41277069463.gif",
            "headline": "You left something behind.",
            "subheadline": "Your custom sofa is still waiting. Complete your order before it sells out.",
            "cta_text": "Return to cart",
            "cta_url": "https://www.interiordefine.com/cart",
            "hero_height": 600,
        },

        # ── Category nav: shop by room ────────────────────────────────────────
        {
            "block": "category_nav",
            "preset": "default_light",
            "section_header": "Shop by Room",
            "section_subheader": "Find the perfect piece for every space.",
            "categories": [
                {"label": "NEW",      "url": "https://www.interiordefine.com/new-arrivals"},
                {"label": "LIVING",   "url": "https://www.interiordefine.com/sofas"},
                {"label": "BEDROOM",  "url": "https://www.interiordefine.com/beds"},
                {"label": "DINING",   "url": "https://www.interiordefine.com/dining"},
                {"label": "OUTDOOR",  "url": "https://www.interiordefine.com/outdoor"},
                {"label": "LIGHTING", "url": "https://www.interiordefine.com/lighting"},
            ],
        },

        # ── Feature block: performance fabrics (white bg) ─────────────────────
        {
            "block": "feature_text_image",
            "preset": "white",
            "title": "Made for Everyday Moments",
            "body": (
                "Raise your hand if your couch has ever been personally victimized by red wine. "
                "Our performance fabrics are designed to handle the mess — so you can live "
                "beautifully (and boldly)."
            ),
            "image_url": "https://e.hypermatic.com/7e4ef2e5cc981f6ca56bb55b998be12e.gif",
            "link_text": "Order free swatches",
            "link_url": "https://swatches.interiordefine.com/",
        },

        # ── Feature block: comfort story (tan bg for visual rhythm) ───────────
        {
            "block": "feature_text_image",
            "preset": "tan",
            "title": "Sink In, Stay Cozy",
            "body": (
                "Deep seats, generous cushions, and fabrics that only get better with time. "
                "Every piece is built to be lived in."
            ),
            "image_url": "https://e.hypermatic.com/51659d77d781ef4dddb736ef2a7f130a.jpg",
            "link_text": "Customize yours",
            "link_url": "https://www.interiordefine.com/sofas",
        },

        # ── Dark feature: pet-friendly fabrics ───────────────────────────────
        {
            "block": "feature_text_image_dark",
            "image_url": "https://e.hypermatic.com/27ad65de897ddf075db413e0fd410629.jpg",
            "title": "Pet-tested and approved",
            "body": (
                "Tightly woven fabrics for next-level durability — designed with furry friends in mind."
            ),
            "link_text": "Order free swatches",
            "link_url": "https://swatches.interiordefine.com/",
            "height": 420,
            "bottom_padding": 180,
        },

        # ── Final CTA banner ─────────────────────────────────────────────────
        {
            "block": "header_with_cta",
            "preset": "default_dark",
            "header": "Find your perfect fabric.",
            "cta_text": "Order free swatches",
            "cta_url": "https://swatches.interiordefine.com/",
        },

        # ── Footer chrome ─────────────────────────────────────────────────────
        {"block": "divider"},
        {"block": "icon_cta_bar", "preset": "white"},
        {"block": "divider"},
        {"block": "footer", "year": "2025"},
    ],
)

out_path = os.path.join(os.path.dirname(__file__), "cart_abandon_t1.html")
with open(out_path, "w") as f:
    f.write(html)

print(f"Preview written to: {out_path}")
print("Open with: open scripts/email_previews/cart_abandon_t1.html")
